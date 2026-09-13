"""Draw a sample for the earlier dictionary hand-check.

This helper writes a local review sample. The completed four-task evaluation
is recorded separately in data/processed/alignment/evaluation_labels.csv."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import codebook as cb

OUT = ROOT / "data" / "processed" / "handcheck_sample.csv"
SEED = 20260912
N = 100


def draw() -> None:
    df = pd.read_csv(ROOT / "data" / "processed" / "corpus.csv", low_memory=False)
    folk = df[(df["stratum"] == "lovable") & (~df["is_fork"].fillna(False).astype(bool))].copy()
    folk["genre"] = folk["repo_slug"].map(cb.genre)
    folk["purpose"] = folk["repo_slug"].map(cb.purpose)
    folk["auto_slug"] = folk["repo_slug"].map(cb.is_auto_slug)

    # Stratify by genre so rare families are actually checked, not just the big ones.
    per = max(1, N // max(1, folk["genre"].nunique()))
    sample = (folk.groupby("genre", group_keys=False)
                  .apply(lambda g: g.sample(min(len(g), per), random_state=SEED)))
    if len(sample) < N:
        extra = folk.drop(sample.index).sample(N - len(sample), random_state=SEED)
        sample = pd.concat([sample, extra])

    out = sample[["repo_slug", "page_title", "genre", "purpose", "auto_slug"]].copy()
    out["genre_correct"] = ""     # y / n
    out["purpose_correct"] = ""   # y / n
    out["your_genre_if_wrong"] = ""
    out.to_csv(OUT, index=False)

    print(f"Wrote {len(out)} rows to {OUT.relative_to(ROOT)}\n")
    print("Open it in a spreadsheet and put y or n in genre_correct and purpose_correct.")
    print("Rough guide: does the label describe what this project obviously is?\n")
    for i, r in out.reset_index(drop=True).iterrows():
        title = f"  [{str(r['page_title'])[:40]}]" if pd.notna(r["page_title"]) else ""
        print(f"{i+1:>3}. {r['repo_slug'][:44]:46s} {r['genre'][:24]:26s} {r['purpose']}{title}")


def score() -> None:
    d = pd.read_csv(OUT)
    for col, label in [("genre_correct", "Genre"), ("purpose_correct", "Purpose")]:
        marked = d[d[col].astype(str).str.lower().isin(["y", "n"])]
        if marked.empty:
            print(f"{label}: nothing marked yet")
            continue
        acc = marked[col].str.lower().eq("y").mean()
        print(f"{label}: {acc:.1%} agreement on {len(marked)} checked "
              f"({marked[col].str.lower().eq('n').sum()} disagreements)")
    wrong = d[d["genre_correct"].astype(str).str.lower().eq("n")]
    if len(wrong):
        print("\nWhere the codebook went wrong (this goes in the evaluation section):")
        for _, r in wrong.head(15).iterrows():
            print(f"  {r['repo_slug'][:40]:42s} said {r['genre'][:22]:24s} "
                  f"should be {r['your_genre_if_wrong']}")


if __name__ == "__main__":
    score() if "--score" in sys.argv else draw()
