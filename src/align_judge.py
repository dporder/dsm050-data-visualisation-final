"""Run and save model predictions for a fixed evaluation task.

The first 40 items support prompt development. The final ten are scored for the
selected version. The four development blocks summarize one prompt version and
do not represent independent cross-validation fits. Running this command can
make paid API calls. The notebook reproduces results from saved checkpoints."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from score_validation import kappa, wilson  # one definition of the interval and kappa

TASK_DIR = ROOT / "tools/evaluator/tasks"
LABEL_DIR = ROOT / "data/processed/human_labels"
ALIGN_DIR = ROOT / "data/processed/alignment"
PROMPT_DIR = ROOT / "prompts"

TUNING_SIZE = 40
FINAL_VERDICTS = ("label", "reject")

# United States dollars per million tokens, (input, output).
# The Anthropic rates are the published list prices for these models. The OpenAI
# rate for gpt-4.1 is from memory and carries a verification flag: check it at
# platform.openai.com before quoting it anywhere. A model with no rate here
# refuses to run until --price-in and --price-out are given, because guessing a
# price would make the budget rule meaningless.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-4.1": (2.0, 8.0),          # verification flag, see above
    "gpt-5.2": None,                  # not known here, pass --price-in and --price-out
}

# What one call costs, roughly, before it is made. Four characters to the token is
# the usual English rule of thumb, and the answers are one option plus a short
# reason, so sixty output tokens is a fair allowance.
CHARS_PER_TOKEN = 4
OUTPUT_TOKENS_PER_CALL = 60
SAFETY = 1.3      # the fallback estimate runs low, so it is padded before the budget check

CHECKPOINT_FIELDS = [
    "item_id", "repo_slug", "task", "model", "prompt_version",
    "label", "reason", "input_tokens", "output_tokens", "usd", "called_utc",
]


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def provider_of(model: str) -> str:
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
        return "openai"
    raise SystemExit("cannot tell which provider serves %r: name it claude... or gpt..." % model)


def load_task(task: str) -> dict:
    path = TASK_DIR / ("%s.json" % task)
    if not path.exists():
        raise SystemExit("no task file at %s. Build it with src/build_tasks.py" % path)
    d = json.loads(path.read_text())
    if not d.get("items"):
        raise SystemExit("%s holds no items" % path)
    return d


def load_prompt(task: str, version: int, question: str, options: list) -> "tuple[str, Path]":
    path = PROMPT_DIR / ("%s_v%d.txt" % (task, version))
    if not path.exists():
        raise SystemExit(
            "no prompt at %s. A new prompt version is a new file, so copy the last one and edit it."
            % path
        )
    raw = path.read_text()
    text = raw.replace("{question}", question).replace(
        "{options}", "\n".join("- " + o for o in options))
    if "{" in text.replace("{{", "").replace("}}", ""):
        leftover = [w for w in text.split() if w.startswith("{")]
        if leftover:
            print("note: the prompt still holds %s, which nothing filled in" % ", ".join(leftover))
    return text, path


def dan_judgements(task: str, rater: str, labels_file: "str | None") -> dict:
    """Item id to (verdict, label). Last row per item wins, as the app itself reads it."""
    path = Path(labels_file) if labels_file else (LABEL_DIR / ("%s.csv" % task))
    if not path.exists():
        raise SystemExit(
            "no judgements at %s. Dan labels in the evaluator first, then this tool scores it."
            % path
        )
    latest = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("item_id") and (row.get("rater_id") or "").strip() == rater:
                latest[row["item_id"]] = row
    return {
        item_id: ((row.get("verdict") or "").strip(), (row.get("human_label") or "").strip())
        for item_id, row in latest.items()
        if (row.get("verdict") or "").strip() in FINAL_VERDICTS
    }


def read_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(newline="") as fh:
        return {r["item_id"]: r for r in csv.DictReader(fh) if r.get("item_id")}


def append_checkpoint(path: Path, row: dict) -> None:
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CHECKPOINT_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
        fh.flush()


# ---------------------------------------------------------------------------
# the model call
# ---------------------------------------------------------------------------
def schema_for(options: list) -> dict:
    """No minimum or maximum keywords anywhere: Anthropic structured outputs reject them."""
    return {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": list(options)},
            "reason": {"type": "string", "description": "at most fifteen words"},
        },
        "required": ["label", "reason"],
        "additionalProperties": False,
    }


def estimate_input_tokens(system: str, schema: dict) -> int:
    """Fallback when the API cannot be asked: prompt plus schema plus a short name."""
    chars = len(system) + len(json.dumps(schema)) + 80
    return int(chars / CHARS_PER_TOKEN * SAFETY)


def user_text(item: dict) -> str:
    t = "Project name: %s" % item["primary"]
    title = (item.get("fields") or {}).get("page title")
    if title:
        t += "\nPage title: %s" % title
    return t


class Judge:
    """One model, one prompt, one JSON answer per item."""

    def __init__(self, model: str, system: str, options: list, max_output_tokens: int,
                 cache_system: bool = False):
        self.model = model
        self.cache_system = cache_system
        self.provider = provider_of(model)
        self.system = system
        self.schema = schema_for(options)
        self.max_output_tokens = max_output_tokens
        self.no_thinking = True
        if self.provider == "anthropic":
            import anthropic
            self.anthropic = anthropic
            self.client = anthropic.Anthropic()
        else:
            from openai import OpenAI
            self.client = OpenAI()

    def __call__(self, item: dict) -> "tuple[dict, int, int]":
        return (self._anthropic if self.provider == "anthropic" else self._openai)(item)

    def input_tokens(self, item: dict) -> "int | None":
        """What one request really costs to send, counted by the API, not guessed.

        The schema is part of the request, and an enum of twenty-five options is not
        small, so a character count of the prompt alone understates the bill by more
        than half. Counting is free on Anthropic. OpenAI has no free counter, so that
        path falls back to the estimate in estimate_input_tokens below.
        """
        if self.provider != "anthropic":
            return None
        try:
            kwargs = dict(
                model=self.model,
                system=[{"type": "text", "text": self.system}],
                messages=[{"role": "user", "content": user_text(item)}],
                output_config={"effort": "low",
                               "format": {"type": "json_schema", "schema": self.schema}},
            )
            if self.no_thinking:
                kwargs["thinking"] = {"type": "disabled"}
            return self.client.messages.count_tokens(**kwargs).input_tokens
        except Exception as exc:                          # noqa: BLE001
            print("note: could not count tokens (%s), falling back to an estimate"
                  % type(exc).__name__)
            return None

    def _anthropic(self, item: dict):
        system_block = {"type": "text", "text": self.system}
        if self.cache_system:
            system_block["cache_control"] = {"type": "ephemeral"}
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_output_tokens,
            system=[system_block],
            messages=[{"role": "user", "content": user_text(item)}],
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": self.schema}},
        )
        if self.no_thinking:
            kwargs["thinking"] = {"type": "disabled"}
        try:
            resp = self.client.messages.create(**kwargs)
        except self.anthropic.BadRequestError as exc:
            if self.no_thinking and "thinking" in str(exc).lower():
                print("note: %s would not take thinking disabled, leaving it on" % self.model)
                self.no_thinking = False
                kwargs.pop("thinking")
                resp = self.client.messages.create(**kwargs)
            else:
                raise
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return json.loads(text), resp.usage.input_tokens, resp.usage.output_tokens

    def _openai(self, item: dict):
        kwargs = dict(
            model=self.model,
            messages=[{"role": "system", "content": self.system},
                      {"role": "user", "content": user_text(item)}],
            max_completion_tokens=self.max_output_tokens,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "judgement", "strict": True,
                                             "schema": self.schema}},
        )
        if self.model.startswith("gpt-4"):
            kwargs["temperature"] = 0
        resp = self.client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        usage = resp.usage
        return (json.loads(content),
                getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0))


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------
def prices_for(model: str, price_in: "float | None", price_out: "float | None"):
    if price_in is not None and price_out is not None:
        return price_in, price_out
    p = PRICES.get(model)
    if p is None:
        raise SystemExit(
            "no price on file for %s, so the budget rule cannot be honoured. "
            "Give --price-in and --price-out in dollars per million tokens, "
            "or add the model to PRICES in this file." % model
        )
    return p


def usd(in_tokens: int, out_tokens: int, price: "tuple[float, float]") -> float:
    return (in_tokens * price[0] + out_tokens * price[1]) / 1e6


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def report(pairs: list, rejects: int, cannot_tell: str) -> None:
    """pairs is (name, Dan's label, the model's label) for every item both judged."""
    n = len(pairs)
    if n == 0:
        print("nothing to score yet")
        return
    agree = sum(1 for _, h, m in pairs if h == m)
    p, lo, hi = wilson(agree, n)
    import pandas as pd
    k = kappa(pd.Series([h for _, h, _ in pairs]), pd.Series([m for _, _, m in pairs]))
    print("\nagreement %d/%d = %.0f per cent (95 per cent Wilson %.0f to %.0f), kappa %.2f"
          % (agree, n, 100 * p, 100 * lo, 100 * hi, k))
    if cannot_tell:
        firm = [(s, h, m) for s, h, m in pairs if h != cannot_tell]
        if firm and len(firm) != n:
            a2 = sum(1 for _, h, m in firm if h == m)
            p2, lo2, hi2 = wilson(a2, len(firm))
            print("agreement where Dan named a category %d/%d = %.0f per cent "
                  "(95 per cent Wilson %.0f to %.0f)"
                  % (a2, len(firm), 100 * p2, 100 * lo2, 100 * hi2))
    if rejects:
        print("%d item(s) Dan rejected as not folk software are outside these numbers" % rejects)
    bad = [(s, h, m) for s, h, m in pairs if h != m]
    print("\ndisagreements, %d of %d (name | Dan | model):" % (len(bad), n))
    for s, h, m in bad:
        print("  %s | %s | %s" % (s, h, m))
    if not bad:
        print("  none")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True, help="task key, for example kind")
    ap.add_argument("--model", default="claude-sonnet-5",
                    help="claude-sonnet-5, claude-opus-5, gpt-4.1, gpt-5.2")
    ap.add_argument("--prompt-version", type=int, default=1)
    ap.add_argument("--rater", default="primary")
    ap.add_argument("--labels-file", default=None,
                    help="read judgements from this file instead of the task's own")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fold", type=int, choices=[0, 1, 2, 3], default=None,
                   help="dev fold k of 4 within the working 40: score items 10k..10k+9, tune on the other 30")
    g.add_argument("--tune", action="store_true", help="score the 30 tuning items outside --fold (default fold 0)")
    g.add_argument("--final", action="store_true",
                   help="score the SEALED items 41 to 50 exactly once, at the very end")
    g.add_argument("--all", action="store_true", help="score every item Dan judged")
    ap.add_argument("--limit", type=int, default=None, help="stop after this many items")
    ap.add_argument("--budget-usd", type=float, default=2.0, help="refuse to spend more (default 2)")
    ap.add_argument("--estimate", action="store_true", help="price the run and stop")
    ap.add_argument("--price-in", type=float, default=None, help="dollars per million input tokens")
    ap.add_argument("--price-out", type=float, default=None, help="dollars per million output tokens")
    ap.add_argument("--max-output-tokens", type=int, default=300)
    a = ap.parse_args()

    task = load_task(a.task)
    options = task["options"]
    cannot_tell = (task.get("cannot_tell") or "").strip()
    system, prompt_path = load_prompt(a.task, a.prompt_version, task["question"], options)
    judged = dan_judgements(a.task, a.rater, a.labels_file)

    # Split by task order, which is the sample's shuffled order: items 1 to 40 are the
    # working set (four rotating dev folds of 10), items 41 to 50 are sealed until --final.
    order = [it for it in task["items"] if it["id"] in judged]
    working, sealed = order[:TUNING_SIZE], order[TUNING_SIZE:TUNING_SIZE + 10]
    k = a.fold if a.fold is not None else 0
    dev = working[10 * k:10 * k + 10]
    tune = [it for it in working if it not in dev]
    if a.all:
        chosen, which = order, "all %d items Dan judged" % len(order)
    elif a.final:
        if len(sealed) < 10:
            print("warning: only %d sealed items judged so far" % len(sealed))
        chosen, which = sealed, "SEALED final hold-out, items 41 to 50, score once"
    elif a.fold is not None and not a.tune:
        chosen, which = dev, "dev fold %d of 4 (items %d to %d)" % (k, 10 * k + 1, 10 * k + 10)
    else:
        chosen, which = tune, "tuning set, 30 items outside dev fold %d" % k
    if a.limit:
        chosen = chosen[:a.limit]

    price = prices_for(a.model, a.price_in, a.price_out)
    checkpoint = ALIGN_DIR / ("%s_%s_v%d.csv" % (a.task, a.model, a.prompt_version))
    done = read_checkpoint(checkpoint)
    todo = [it for it in chosen if it["id"] not in done]

    print("task %s, model %s, prompt %s" % (a.task, a.model, prompt_path.relative_to(ROOT)))
    print("Dan judged %d of %d items as %s; this run scores %d (%s)"
          % (len(judged), len(task["items"]), a.rater, len(chosen), which))
    print("checkpoint %s holds %d of them already, so %d call(s) to make"
          % (checkpoint.relative_to(ROOT), len(chosen) - len(todo), len(todo)))

    judge = None
    if todo:
        try:
            judge = Judge(a.model, system, options, a.max_output_tokens)
        except Exception as exc:                          # noqa: BLE001
            print("note: no client yet (%s). Load the keys with: set -a; source .env; set +a"
                  % type(exc).__name__)
    per_item_in = (judge.input_tokens(todo[0]) if judge else None)
    counted = per_item_in is not None
    if per_item_in is None:
        per_item_in = estimate_input_tokens(system, schema_for(options))
    est_in = per_item_in * len(todo)
    est_out = OUTPUT_TOKENS_PER_CALL * len(todo)
    est = usd(est_in, est_out, price)
    print("estimate: %s input tokens (%s) and about %s output, about $%.3f at $%.2f and $%.2f "
          "per million. Budget $%.2f."
          % (format(est_in, ","), "counted by the API" if counted else "estimated",
             format(est_out, ","), est, price[0], price[1], a.budget_usd))
    if est > a.budget_usd:
        raise SystemExit(
            "refusing to run: the estimate is over the budget. Raise --budget-usd deliberately, "
            "or score fewer items with --limit."
        )
    if a.estimate:
        print("estimate only, nothing was sent")
        return

    spent = 0.0
    if todo:
        if judge is None:
            raise SystemExit("no client to call with. Load the keys with: set -a; source .env; set +a")
        for i, item in enumerate(todo, 1):
            try:
                answer, tin, tout = judge(item)
            except Exception as exc:                      # noqa: BLE001
                print("  %s failed: %s: %s" % (item["primary"], type(exc).__name__, str(exc)[:160]))
                continue
            cost = usd(tin, tout, price)
            spent += cost
            append_checkpoint(checkpoint, {
                "item_id": item["id"], "repo_slug": item["primary"], "task": a.task,
                "model": a.model, "prompt_version": a.prompt_version,
                "label": answer.get("label", ""), "reason": answer.get("reason", ""),
                "input_tokens": tin, "output_tokens": tout, "usd": "%.6f" % cost,
                "called_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            if i % 10 == 0 or i == len(todo):
                print("  %d/%d labelled, $%.4f so far" % (i, len(todo), spent))
            if spent > a.budget_usd:
                print("stopping: spent $%.4f, which is over the budget. "
                      "Everything so far is in the checkpoint." % spent)
                break
        print("spent $%.4f on %d call(s)" % (spent, len(todo)))

    done = read_checkpoint(checkpoint)
    pairs, rejects, missing = [], 0, 0
    for item in chosen:
        verdict, human = judged[item["id"]]
        if verdict == "reject":
            rejects += 1
            continue
        row = done.get(item["id"])
        if not row:
            missing += 1
            continue
        pairs.append((item["primary"], human, row["label"]))
    if missing:
        print("%d item(s) have no model label yet and are not scored" % missing)
    report(pairs, rejects, cannot_tell)
    print("\ncheckpoint: %s" % checkpoint.relative_to(ROOT))


if __name__ == "__main__":
    main()
