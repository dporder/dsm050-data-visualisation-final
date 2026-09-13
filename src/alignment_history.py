"""Reproduce evaluation scores from saved labels and model checkpoints.

The public evaluation_labels.csv snapshot takes precedence over private task
files. accepted.json fixes the versions reported on the final ten items. Earlier
Kind checkpoints contain final-item predictions, which limits the claim that
those items formed an untouched holdout. Development blocks summarize predictions
from one prompt version. The script writes history.csv and the alignment figure."""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from score_validation import kappa, wilson  # noqa: E402

ALIGN = ROOT / "data/processed/alignment"
LABELS = ROOT / "data/processed/human_labels"
TASKS = ROOT / "tools/evaluator/tasks"
ACCEPTED = ALIGN / "accepted.json"
EVALUATION_LABELS = ALIGN / "evaluation_labels.csv"
SNAPSHOT_FIELDS = ["task_id", "item_id", "position", "human_label", "verdict"]
CANNOT_TELL = {"kind": "Cannot tell", "audience": "Cannot tell from the name",
               "maker": "Cannot tell from the evidence", "namestyle": "Cannot tell"}
FOLDS, FOLD_SIZE, WORKING = 4, 10, 40
PATTERN = re.compile(r"^(?P<task>[a-z]+)_(?P<model>.+)_v(?P<v>\d+)\.csv$")


def dan(task: str, rater: str = "primary") -> dict:
    latest = {}
    with (LABELS / f"{task}.csv").open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("item_id") and (row.get("rater_id") or "") == rater:
                latest[row["item_id"]] = row
    return {i: (r["verdict"], r["human_label"]) for i, r in latest.items()
            if r["verdict"] in ("label", "reject")}


def order(task: str, judged: dict) -> list:
    items = json.loads((TASKS / f"{task}.json").read_text())["items"]
    return [it for it in items if it["id"] in judged]


def evaluation(task: str) -> tuple[dict, list, str]:
    """Prefer the frozen public snapshot, without consulting private evaluator data."""
    if EVALUATION_LABELS.exists():
        with EVALUATION_LABELS.open(newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames != SNAPSHOT_FIELDS:
                raise ValueError(f"unexpected columns in {EVALUATION_LABELS}")
            rows = [r for r in reader if r["task_id"] == task]
        if task not in CANNOT_TELL or not rows:
            raise ValueError(f"no supported evaluation snapshot for {task}")
        rows.sort(key=lambda r: int(r["position"]))
        if [int(r["position"]) for r in rows] != list(range(1, 51)):
            raise ValueError(f"{task}: snapshot must contain positions 1 to 50 exactly once")
        if len({r["item_id"] for r in rows}) != len(rows):
            raise ValueError(f"{task}: duplicate item IDs in evaluation snapshot")
        if any(not r["item_id"] or r["verdict"] not in ("label", "reject")
               or (r["verdict"] == "label" and not r["human_label"]) for r in rows):
            raise ValueError(f"{task}: incomplete final judgement in evaluation snapshot")
        judged = {r["item_id"]: (r["verdict"], r["human_label"]) for r in rows}
        return judged, [{"id": r["item_id"]} for r in rows], CANNOT_TELL[task]
    spec = json.loads((TASKS / f"{task}.json").read_text())
    judged = dan(task)
    return judged, order(task, judged), (spec.get("cannot_tell") or "").strip()


def score(items: list, judged: dict, model_rows: dict, cannot_tell: str) -> dict:
    pairs = [(judged[it["id"]][1], model_rows[it["id"]]["label"]) for it in items
             if judged[it["id"]][0] == "label" and it["id"] in model_rows]
    n = len(pairs)
    agree = sum(1 for h, m in pairs if h == m)
    p, lo, hi = wilson(agree, n) if n else (float("nan"),) * 3
    k = kappa(pd.Series([h for h, _ in pairs]), pd.Series([m for _, m in pairs])) if n > 1 else float("nan")
    firm = [(h, m) for h, m in pairs if h != cannot_tell]
    a2 = sum(1 for h, m in firm if h == m)
    return {"n": n, "agree": agree, "agreement": p, "wilson_lo": lo, "wilson_hi": hi, "kappa": k,
            "n_firm": len(firm), "agree_firm": a2,
            "agreement_firm": a2 / len(firm) if firm else float("nan"),
            "missing": sum(1 for it in items if judged[it["id"]][0] == "label" and it["id"] not in model_rows)}


def build() -> pd.DataFrame:
    accepted = json.loads(ACCEPTED.read_text()) if ACCEPTED.exists() else {}
    rows = []
    for path in sorted(glob.glob(str(ALIGN / "*_v*.csv"))):
        m = PATTERN.match(Path(path).name)
        if not m:
            continue
        task, model, v = m["task"], m["model"], int(m["v"])
        judged, items, cannot_tell = evaluation(task)
        ck = pd.read_csv(path, dtype=str, keep_default_na=False)
        model_rows = {r["item_id"]: r for r in ck.to_dict("records")}
        usd = pd.to_numeric(ck["usd"], errors="coerce").fillna(0).sum()
        working = items[:WORKING]
        fold_scores = []
        for k in range(FOLDS):
            s = score(working[FOLD_SIZE * k:FOLD_SIZE * (k + 1)], judged, model_rows, cannot_tell)
            fold_scores.append(s)
            rows.append({"task": task, "model": model, "prompt_version": v, "split": f"dev fold {k}", **s, "usd": ""})
        pooled = score(working, judged, model_rows, cannot_tell)
        agreements = [s["agreement"] for s in fold_scores if s["n"]]
        rows.append({"task": task, "model": model, "prompt_version": v, "split": "working 40 pooled",
                     **pooled, "usd": f"{usd:.4f}",
                     "mean_dev_agreement": sum(agreements) / len(agreements) if agreements else float("nan"),
                     "min_fold_agreement": min(agreements) if agreements else float("nan"),
                     "passes": bool(agreements) and sum(agreements) / len(agreements) >= 0.80 and min(agreements) >= 0.70})
        acc = accepted.get(task)
        if acc and acc.get("model") == model and int(acc.get("prompt_version", -1)) == v:
            sealed = items[WORKING:WORKING + 10]
            s = score(sealed, judged, model_rows, cannot_tell)
            rows.append({"task": task, "model": model, "prompt_version": v, "split": "sealed 10 (selected version)",
                         **s, "usd": "", "accepted": acc.get("status", "")})
    hist = pd.DataFrame(rows)
    hist.to_csv(ALIGN / "history.csv", index=False)
    return hist


def plot(hist: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt
    import folkviz as fv
    pooled = hist[hist["split"] == "working 40 pooled"].copy()
    if pooled.empty:
        print("nothing to draw")
        return
    fig, axes = plt.subplots(1, 4, figsize=(9.6, 3.4), sharey=True)
    colours = {"claude-sonnet-5": fv.STRATUM_COLOUR.get("lovable", "#4477aa"),
               "claude-opus-5": fv.STRATUM_COLOUR.get("claude", "#cc6677"),
               "gpt-4.1-mini": fv.STRATUM_COLOUR.get("replit", "#999933"),
               "gpt-4.1": "#882255"}
    for ax, task in zip(axes, ["kind", "audience", "namestyle", "maker"]):
        g = pooled[pooled["task"] == task]
        for model, gm in g.groupby("model"):
            gm = gm.sort_values("prompt_version")
            ax.errorbar(gm["prompt_version"], 100 * gm["agreement"],
                        yerr=[100 * (gm["agreement"] - gm["wilson_lo"]), 100 * (gm["wilson_hi"] - gm["agreement"])],
                        marker="o", capsize=3, label=model, color=colours.get(model, "#444444"))
        sealed = hist[(hist["task"] == task) & (hist["split"].str.startswith("sealed"))]
        for _, r in sealed.iterrows():
            ax.scatter([r["prompt_version"]], [100 * r["agreement"]], marker="*", s=140, zorder=5,
                       color="black", label="final ten, selected version")
        ax.axhline(80, ls=":", color="grey", lw=1)
        ax.set_title(task); ax.set_xlabel("prompt version"); ax.set_ylim(0, 100)
        ax.set_xticks(sorted(g["prompt_version"].unique()))
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("agreement with the author (%)")
    handles, labels = [], []
    for ax in axes:
        for h, l in zip(*ax.get_legend_handles_labels()):
            if l not in labels:
                handles.append(h); labels.append(l)
    fig.legend(handles, labels, loc="lower center", ncol=len(labels), fontsize=7.5, frameon=False,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Model agreement with the final evaluation labels", fontsize=11)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fv.save(fig, "fig11_alignment_history",
            "Pooled agreement on development items 1 to 40 per prompt version, "
            "with Wilson 95 per cent intervals over available pairs; the dotted line marks 80 per cent; "
            "a star is the final ten for the selected version. Blocks are not independent cross-validation fits.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-figure", action="store_true")
    a = ap.parse_args()
    hist = build()
    show = hist[hist["split"].isin(["working 40 pooled"]) | hist["split"].str.startswith("sealed")]
    cols = ["task", "model", "prompt_version", "split", "n", "agree", "agreement", "wilson_lo", "wilson_hi",
            "kappa", "agreement_firm", "mean_dev_agreement", "min_fold_agreement", "passes", "usd"]
    cols = [c for c in cols if c in show.columns]
    with pd.option_context("display.width", 200, "display.float_format", "{:.2f}".format):
        print(show[cols].to_string(index=False))
    print(f"\nwrote {ALIGN / 'history.csv'} ({len(hist)} rows)")
    if not a.no_figure:
        plot(hist)


if __name__ == "__main__":
    main()
