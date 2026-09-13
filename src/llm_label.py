"""Collect the earlier full-stratum model classifications.

This script supports provider-specific requests and saved checkpoints. Running
it can make paid API calls. The submission notebook uses the selected production
samples in data/processed/alignment, with earlier checkpoints retained only for
development history."""
from __future__ import annotations
import argparse, csv, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import codebook as cb

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/processed/corpus.csv"
SHEET = ROOT / "data/processed/validation_sheet.csv"
OUT = ROOT / "data/processed/llm_labels.csv"
STATE = ROOT / "data/processed/llm_batches.json"

FAMILIES = list(cb.GENRE_RULES)   # the same 23 families the report uses
PLAY = {'Health and fitness': 'Health and Fitness / Medical', 'Money and admin': 'Finance', 'Shop and commerce': 'Shopping', 'Business and clients': '(no Play equivalent; native to this corpus)', 'Travel and hospitality': 'Travel and Local', 'Property and home': 'House and Home', 'Logistics and transport': 'Auto and Vehicles / Maps and Navigation', 'Food and drink': 'Food and Drink', 'Beauty and fashion': 'Beauty', 'Jobs and careers': 'Business (careers)', 'Pets and animals': 'Lifestyle (pets)', 'Faith and culture': 'Lifestyle (faith, astrology)', 'News and information': 'News and Magazines / Weather', 'Sport and outdoors': 'Sports', 'Trackers and dashboards': '(no Play equivalent; native to this corpus)', 'Planning and productivity': 'Productivity', 'Games and toys': 'Games (any Play game category)', 'Learning and study': 'Education', 'Creative and media': 'Art and Design / Photography / Music and Audio / Video', 'Community and events': 'Social / Events / Communications', 'AI and chatbots': '(no Play equivalent; native to this corpus)', 'Site and portfolio': '(no Play equivalent; native to this corpus)', 'Utilities and converters': 'Tools'}
# Families are adapted from Google Play's 32 app categories (support.google.com/googleplay/android-developer/answer/9859673);
# four have no Play equivalent and are declared as native to this corpus.
EXTRA = [
    "Generic or brand-style name",     # all product words, says nothing about purpose
    "Unreadable: invented or brand name",
    "Unreadable: not English",
    "Cannot tell",
]
LABELS = FAMILIES + EXTRA

SYSTEM = f"""You classify the NAME of a small software project into exactly one family.
You see only the name the maker gave the project, sometimes with the title of its web page.
Do not guess beyond what the words support. Rules, in order:
1. If the name is in a language other than English and you can read it, translate silently and classify.
2. If the words state a purpose or domain, pick the matching family from this list. Each family is
   adapted from Google Play's published app categories, shown in brackets, so use the Play meaning when unsure:
{chr(10).join('   - ' + f + '   [Google Play: ' + PLAY.get(f, 'n/a') + ']' for f in FAMILIES)}
3. If every word is product vocabulary (hub, flow, connect, pro, app, studio, lab) and none says what it does, answer "Generic or brand-style name".
4. If the name is an invented word or a brand with no readable meaning, answer "Unreadable: invented or brand name".
5. If it is in a language you cannot read, answer "Unreadable: not English" and give the language if you can.
6. Otherwise answer "Cannot tell".
Confidence is your own estimate that a careful human would choose the same family: 0.5 means a coin flip."""

SCHEMA = {
    "type": "object",
    "properties": {
        "family": {"type": "string", "enum": LABELS},
        "language": {"type": "string", "description": "ISO 639-1 code of the name's language, or 'unknown'"},
        "confidence": {"type": "number", "description": "between 0 and 1"},   # min/max keywords are rejected by Anthropic structured outputs
    },
    "required": ["family", "language", "confidence"],
    "additionalProperties": False,
}


def load_rows(scope: str) -> list[dict]:
    import pandas as pd
    d = pd.read_csv(CORPUS, low_memory=False, dtype=str, keep_default_na=False)
    d = d[d.stratum == "lovable"]
    d = d[~d.repo_slug.map(cb.is_auto_slug)]
    if scope == "sample":
        ids = set(pd.read_csv(SHEET, dtype=str)["project_name"])
        d = d[d.repo_slug.isin(ids)].drop_duplicates("repo_slug")
    elif scope == "unclassified":
        d = d[d.repo_slug.map(cb.genre).isin(["Unclassified", "Generic or brand-style name"])]
    elif scope != "all":
        raise SystemExit(f"unknown scope {scope}")
    return d[["repo_id", "repo_slug", "page_title"]].to_dict("records")


def user_text(r: dict) -> str:
    t = f"Project name: {r['repo_slug']}"
    if r.get("page_title"):
        t += f"\nPage title: {r['page_title']}"
    return t


def estimate(rows: list[dict], model: str) -> None:
    # Rough: system prompt cached after the first request. Per-item ~40 in, ~30 out.
    price = {"claude-opus-5": (5.0, 25.0), "claude-haiku-4-5": (1.0, 5.0),
             "claude-sonnet-5": (2.0, 10.0)}.get(model, (5.0, 25.0))
    n = len(rows); inp = n * 40; out = n * 30
    usd = (inp * price[0] + out * price[1]) / 1e6 * 0.5   # Batches are half price
    print(f"{n:,} names on {model}: about {inp:,} input and {out:,} output tokens, "
          f"roughly ${usd:.2f} at Batches pricing. Nothing has been sent.")


def run(rows: list[dict], model: str) -> str:
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    client = anthropic.Anthropic()
    requests = [
        Request(
            custom_id=r["repo_id"],
            params=MessageCreateParamsNonStreaming(
                model=model,
                max_tokens=256,
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_text(r)}],
                output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            ),
        )
        for r in rows
    ]
    # One 42,000-request POST dropped the connection, and so did 4,000-request
    # chunks intermittently. Submit 1,000 at a time, retry on connection errors,
    # and resume past chunks already recorded for this model.
    CHUNK = 1000
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    already = sum(v["n"] for v in state.values() if v.get("model") == model)
    if already:
        print(f"resuming: {already:,} requests already submitted for {model}; skipping them")
    ids = []
    for i in range(already, len(requests), CHUNK):
        part = requests[i:i + CHUNK]
        for attempt in range(4):
            try:
                batch = client.messages.batches.create(requests=part); break
            except anthropic.APIConnectionError:
                if attempt == 3: raise
                time.sleep(3 * (attempt + 1)); print("  connection dropped, retrying")
        state[batch.id] = {"model": model, "n": len(part), "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        STATE.write_text(json.dumps(state, indent=1)); ids.append(batch.id)
        print(f"batch {batch.id}: {len(part):,} requests, status {batch.processing_status}")
    print(f"{len(ids)} batches submitted; collect all with: .venv/bin/python3 src/llm_label.py --collect-all --wait")
    return ids[-1]


def run_openai(rows: list[dict], model: str, workers: int = 8) -> None:
    """Second provider. Same prompt, same schema, same blind design. Synchronous with a
    thread pool: 42,000 names take about half an hour at eight workers."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from openai import OpenAI
    client = OpenAI()
    fmt = {"type": "json_schema", "json_schema": {"name": "family", "strict": True, "schema": SCHEMA}}
    done = set()
    if OUT.exists():
        with OUT.open() as fh:
            done = {r["repo_id"] for r in csv.DictReader(fh) if r.get("model") == model}
    todo = [r for r in rows if r["repo_id"] not in done]
    print(f"{len(todo):,} to label on {model} ({len(done):,} already done)")
    def one(r):
        resp = client.chat.completions.create(
            model=model, temperature=0, max_tokens=120,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_text(r)}],
            response_format=fmt)
        return r["repo_id"], json.loads(resp.choices[0].message.content)
    new = not OUT.exists()
    ok = err = 0
    with OUT.open("a", newline="") as fh, ThreadPoolExecutor(workers) as ex:
        w = csv.writer(fh)
        if new: w.writerow(["repo_id", "model", "llm_genre", "language", "confidence", "batch_id"])
        futs = [ex.submit(one, r) for r in todo]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                rid, d = f.result()
                w.writerow([rid, model, d["family"], d.get("language", ""), d.get("confidence", ""), "sync"]); ok += 1
            except Exception as e:
                err += 1
                if err <= 3: print("error:", type(e).__name__, str(e)[:120])
            if i % 500 == 0: fh.flush(); print(f"  {i:,}/{len(todo):,}")
    print(f"labelled {ok:,}, failed {err}, written to {OUT.relative_to(ROOT)}")


def collect(batch_id: str, wait: bool) -> None:
    import anthropic
    client = anthropic.Anthropic()
    while True:
        b = client.messages.batches.retrieve(batch_id)
        if b.processing_status == "ended":
            break
        if not wait:
            print(f"status {b.processing_status}: {b.request_counts.processing} still processing"); return
        print(f"waiting: {b.request_counts.processing} processing, {b.request_counts.succeeded} done"); time.sleep(60)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    model = state.get(batch_id, {}).get("model", "unknown")
    new = OUT.exists() is False
    with OUT.open("a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["repo_id", "model", "llm_genre", "language", "confidence", "batch_id"])
        ok = err = 0
        for res in client.messages.batches.results(batch_id):
            if res.result.type != "succeeded":
                err += 1; continue
            text = next((blk.text for blk in res.result.message.content if blk.type == "text"), "{}")
            try:
                d = json.loads(text)
                w.writerow([res.custom_id, model, d["family"], d.get("language", ""), d.get("confidence", ""), batch_id]); ok += 1
            except (json.JSONDecodeError, KeyError):
                err += 1
    print(f"collected {ok:,} labels, {err} failed, appended to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "openai"])
    ap.add_argument("--scope", default="unclassified", choices=["sample", "unclassified", "all"])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--estimate", action="store_true")
    g.add_argument("--run", action="store_true")
    g.add_argument("--collect", metavar="BATCH_ID")
    g.add_argument("--collect-all", action="store_true", help="collect every batch recorded in llm_batches.json")
    ap.add_argument("--wait", action="store_true", help="with --collect, poll until the batch ends")
    a = ap.parse_args()
    if a.collect_all:
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        done_ids = set()
        if OUT.exists():
            with OUT.open() as fh: done_ids = {r["batch_id"] for r in csv.DictReader(fh)}
        for bid in state:
            if bid in done_ids: continue
            print(f"--- {bid} ({state[bid]['model']}, {state[bid]['n']:,} requests)"); collect(bid, a.wait)
    elif a.collect:
        collect(a.collect, a.wait)
    else:
        rows = load_rows(a.scope)
        if a.estimate:
            estimate(rows, a.model)
        elif a.provider == "openai":
            run_openai(rows, a.model)
        else:
            run(rows, a.model)
