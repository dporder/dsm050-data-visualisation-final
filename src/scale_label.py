"""Apply a selected prompt version to a saved sample of project names.

The script checks the recorded model choice, keeps a fixed sampling seed and
saves predictions as they arrive. Running it can make paid API calls. Partial
checkpoints retain their actual completed row count."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import build_tasks as bt                      # noqa: E402  the same pool as the human tasks
from align_judge import (Judge, load_prompt, load_task, prices_for, schema_for,   # noqa: E402
                         estimate_input_tokens, usd, OUTPUT_TOKENS_PER_CALL, ALIGN_DIR)
from score_validation import wilson           # noqa: E402

FIELDS = ["repo_id", "repo_slug", "cell", "task", "model", "prompt_version", "label", "reason",
          "input_tokens", "output_tokens", "usd", "called_utc"]


def draw(n: int, seed: int) -> pd.DataFrame:
    pool, counts = bt.load_pool("genre")
    s = pool.sample(n=min(n, len(pool)), random_state=seed).reset_index(drop=True)
    print("pool %s names (builder-tool stratum, readable, %s auto-named excluded); drew %d with seed %d"
          % (format(counts["pool"], ","), format(counts["auto_named_excluded"], ","), len(s), seed))
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--prompt-version", type=int, required=True)
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--budget-usd", type=float, default=5.0)
    ap.add_argument("--price-in", type=float, default=None)
    ap.add_argument("--price-out", type=float, default=None)
    ap.add_argument("--max-output-tokens", type=int, default=300)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--estimate", action="store_true")
    g.add_argument("--run", action="store_true")
    a = ap.parse_args()

    task = load_task(a.task)
    options = task["options"]
    system, prompt_path = load_prompt(a.task, a.prompt_version, task["question"], options)
    price = prices_for(a.model, a.price_in, a.price_out)
    sample = draw(a.n, a.seed)
    items = [{"id": str(r.repo_id), "primary": str(r.repo_slug), "cell": str(r.cell),
              "fields": ({"page title": bt.text(r.page_title)} if bt.text(r.page_title) else {})}
             for r in sample.itertuples()]

    stem = "scale_%s_%s_v%d_n%d_seed%d" % (a.task, a.model, a.prompt_version, a.n, a.seed)
    ck = ALIGN_DIR / (stem + ".csv")
    done = {}
    if ck.exists():
        with ck.open(newline="") as fh:
            done = {r["repo_id"]: r for r in csv.DictReader(fh)}
    todo = [it for it in items if it["id"] not in done]
    print("task %s, model %s, prompt %s: %d names, %d already in %s, %d to label"
          % (a.task, a.model, prompt_path.relative_to(ROOT), len(items), len(done), ck.relative_to(ROOT), len(todo)))

    judge = Judge(a.model, system, options, a.max_output_tokens, cache_system=True) if todo else None
    per_in = judge.input_tokens(todo[0]) if judge else 0
    if not per_in:
        per_in = estimate_input_tokens(system, schema_for(options))
    est = usd(per_in * len(todo), OUTPUT_TOKENS_PER_CALL * len(todo), price)
    print("estimate without caching: %s input tokens per call, about $%.2f for %d calls at $%.2f and $%.2f per "
          "million (cache reads of the system prompt bill at a tenth, so the real bill is lower). Budget $%.2f."
          % (format(per_in, ","), est, len(todo), price[0], price[1], a.budget_usd))
    if est > a.budget_usd:
        raise SystemExit("refusing to run: the estimate is over the budget. Lower --n or raise --budget-usd deliberately.")
    if a.estimate:
        print("estimate only, nothing was sent")
        return

    lock = threading.Lock()
    spent = 0.0
    stop = False
    new = not ck.exists()
    fh = ck.open("a", newline="")
    w = csv.DictWriter(fh, fieldnames=FIELDS)
    if new:
        w.writeheader(); fh.flush()

    def one(item):
        nonlocal spent, stop
        if stop:
            return None
        try:
            answer, tin, tout = judge(item)
        except Exception as exc:                          # noqa: BLE001
            return ("fail", item["primary"], "%s: %s" % (type(exc).__name__, str(exc)[:120]))
        cost = usd(tin, tout, price)
        row = {"repo_id": item["id"], "repo_slug": item["primary"], "cell": item["cell"], "task": a.task,
               "model": a.model, "prompt_version": a.prompt_version, "label": answer.get("label", ""),
               "reason": answer.get("reason", ""), "input_tokens": tin, "output_tokens": tout,
               "usd": "%.6f" % cost, "called_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        with lock:
            w.writerow(row); fh.flush()
            spent += cost
            if spent > a.budget_usd:
                stop = True
        return ("ok", item["primary"], cost)

    n_ok = n_fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(one, it) for it in todo]
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r is None:
                continue
            if r[0] == "ok":
                n_ok += 1
            else:
                n_fail += 1
                if n_fail <= 5:
                    print("  failed: %s (%s)" % (r[1], r[2]))
            if i % 100 == 0:
                print("  %d/%d done, $%.3f, %.0f s" % (i, len(todo), spent, time.time() - t0))
    fh.close()
    print("labelled %d, failed %d, spent $%.4f%s" % (n_ok, n_fail, spent,
          " (stopped at the budget; rerun to resume)" if stop else ""))

    # Shares with Wilson intervals, the numbers the report quotes.
    d = pd.read_csv(ck, dtype=str, keep_default_na=False)
    n = len(d)
    rows = []
    for label, k in d["label"].value_counts().items():
        p, lo, hi = wilson(int(k), n)
        rows.append({"label": label, "count": int(k), "share": round(100 * p, 1),
                     "wilson_lo": round(100 * lo, 1), "wilson_hi": round(100 * hi, 1)})
    shares = pd.DataFrame(rows)
    out = ALIGN_DIR / (stem + "_shares.csv")
    shares.to_csv(out, index=False)
    print("\nshares over %d labelled names (per cent, Wilson 95 per cent):" % n)
    print(shares.to_string(index=False))
    print("wrote %s" % out.relative_to(ROOT))


if __name__ == "__main__":
    main()
