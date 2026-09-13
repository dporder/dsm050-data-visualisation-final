"""Create the evaluator tasks from a seeded, stratified sample.

Each task contains 50 items from the Lovable stratum, excluding auto-generated
names. Allocation and seeds are stored with the task. Private lookup files can
add evidence links for the human judge. The submission uses the executed option
lists and sampling details frozen in evaluation_tasks.json. Rebuilding a task
creates a new working file and does not replace that record of the completed study."""
from __future__ import annotations

import argparse
import vocabularies as V
import html
import json
import math
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import codebook as cb  # noqa: E402

SEED = 20260913
N_ITEMS = 50
BUILDER_STRATUM = "lovable"

CORPUS = ROOT / "data/processed/corpus.csv"
LOOKUP = ROOT / "data/raw/repo_lookup.csv"          # private, gitignored
TASK_DIR = ROOT / "tools/evaluator/tasks"
SAMPLE_DIR = ROOT / "data/processed/alignment"

GENRE_FAMILIES = list(cb.GENRE_RULES)               # the 23 dictionary families

# ---------------------------------------------------------------------------
# Fixed vocabularies. One line each. Replace the list, keep everything else.
# ---------------------------------------------------------------------------
KIND_VOCABULARY = GENRE_FAMILIES + ["Generic or brand-style name", "Cannot tell"]

AUDIENCE_VOCABULARY = [
    "For the maker or their household",
    "For a club, class or community",
    "For a business or market",
    "Cannot tell",
]

# ---------------------------------------------------------------------------
# One dict, one entry per judgment. This is the only place to edit.
# ---------------------------------------------------------------------------
TASKS: "OrderedDict[str, dict]" = OrderedDict([
    ("kind", {
        "title": "What kind of software is this?",
        "question": "What kind of software is this?",
        "finding": "Protects the main result: what non-programmers build.",
        "instructions": (
            "Categories are Google Play's 32 published app categories plus one Games label, the scheme app-store research uses as its ground truth (Martin, Sarro, Jia, Zhang and Harman 2017, IEEE TSE). Read the project name first; it is all the automatic classifier ever saw. Use the page title or links only when the name alone cannot be placed. Choose Cannot tell instead of guessing."
        ),
        "options": KIND_VOCABULARY,
        "cannot_tell": "Cannot tell",
        "stratify": "genre",
        "min_per_cell": 0,
        "seed_offset": 0,
        "vocabulary_note": (
            "The 23 adapted dictionary families from src/codebook.py, plus a generic "
            "name option and Cannot tell. These were the executed Kind options."
        ),
    }),
    ("audience", {
        "title": "Who is this software for?",
        "question": "Who is this software for?",
        "finding": "Protects the result about who folk software is aimed at, including the commercial share.",
        "instructions": (
            'Two sectors from the free-innovation literature (von Hippel, de Jong and Flowers 2012; von Hippel 2017). Household sector: made for the maker, their family, friends, a club or a community, at private cost and not for sale. Producer sector: made for a business, for clients, or to be sold or charged for. Judge from the name and page title; choose Cannot tell instead of guessing.'
        ),
        "options": V.AUDIENCE_OPTIONS,
        "cannot_tell": "Cannot tell from the name",
        "stratify": "genre",
        "min_per_cell": 0,
        "seed_offset": 0,
        "vocabulary_note": (
            "Household and producer sectors from von Hippel and colleagues (2012, 2017). "
            "The executed options are also preserved in evaluation_tasks.json."
        ),
    }),
    ("maker", {
        "title": "Who made this?",
        "question": "From the name, the page title and the account signals shown, who does this look made by?",
        "finding": "An exploratory account classification. The completed reference cannot validate non-programmer status.",
        "instructions": (
            'Three types from end-user programming research (Nardi 1993; Ko et al. 2011; Scaffidi, Shaw and Myers 2005). Professional developer: programming is their job or training. Technical but not a professional developer: comfortable with tools, code-adjacent work, not a developer by trade. Non-programmer: programming is only a means to their own end, no coding background evident. Use the name, page title and the account signals shown (repositories, followers, biography, age). Choose Cannot tell instead of guessing.'
        ),
        "options": V.MAKER_OPTIONS,
        "cannot_tell": "Cannot tell from the evidence",
        "stratify": "owner_has_bio",
        "min_per_cell": 0,
        "seed_offset": 2,
        "vocabulary_note": "Three categories informed by end-user programming research (Nardi 1993, Ko et al. 2011).",
    }),
    ("namestyle", {
        "title": "What kind of name is this?",
        "question": "How much does the project's name describe what the software does?",
        "finding": "Protects the naming finding: people name folk software like products.",
        "instructions": (
            "The trademark distinctiveness spectrum (Abercrombie and Fitch v. Hunting World, 1976). Generic: names the thing itself, 'tracker'. Descriptive: says what it does, 'habit-tracker'. Suggestive: hints at the purpose, 'golden-hour-hairdresser'. Arbitrary: a real word unrelated to the purpose, 'aurora'. Fanciful: an invented word, 'vibescudo'. Judge the name alone."
        ),
        "options": V.NAMESTYLE_OPTIONS,
        "cannot_tell": "Cannot tell",
        "stratify": "genre",
        "min_per_cell": 0,
        "seed_offset": 3,
        "vocabulary_note": "The Abercrombie spectrum (2d Cir. 1976), with Adarsh et al. (2024) as a software-naming precedent.",
    }),
])

_URL_OK = re.compile(r"^https?://[^\s]+$")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def text(value) -> str:
    """Trim a cell to a clean string. NaN and whitespace become an empty string."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return html.unescape(html.unescape(str(value))).strip()


def url(value) -> str:
    """Return the cell only when it holds one well formed http or https URL.

    A few rows carry two URLs pasted into one field. Those are treated as missing
    rather than published as a broken link.
    """
    s = text(value)
    return s if _URL_OK.match(s) else ""


def readable_slug(value) -> bool:
    """A name the judge can actually read has at least one letter or digit."""
    return bool(re.search(r"[A-Za-z0-9]", text(value)))


def allocate(counts: "dict[str, int]", total: int, floor: int) -> "OrderedDict[str, int]":
    """Split `total` seats across cells in proportion to `counts`.

    Largest remainder first, then every cell is raised to `floor`, then the
    overshoot is taken back from whichever allocations sit furthest above their
    proportional share. The result sums to `total` exactly, keeps the sample
    shaped like the population, and still tests every cell.
    """
    cells = list(counts)
    pool = sum(counts.values())
    if pool == 0:
        raise SystemExit("the stratification column has no rows to draw from")
    if floor * len(cells) > total:
        raise SystemExit(
            "cannot give every one of %d cells at least %d item(s) inside %d items"
            % (len(cells), floor, total)
        )
    exact = {c: total * counts[c] / pool for c in cells}
    alloc = {c: int(exact[c]) for c in cells}
    order = sorted(cells, key=lambda c: (-(exact[c] - int(exact[c])), -counts[c]))
    for c in order[: total - sum(alloc.values())]:
        alloc[c] += 1
    for c in cells:
        alloc[c] = min(max(alloc[c], floor), counts[c])
    while sum(alloc.values()) > total:
        c = max((c for c in cells if alloc[c] > floor), key=lambda c: alloc[c] - exact[c])
        alloc[c] -= 1
    while sum(alloc.values()) < total:
        c = max((c for c in cells if alloc[c] < counts[c]), key=lambda c: exact[c] - alloc[c])
        alloc[c] += 1
    return OrderedDict((c, alloc[c]) for c in sorted(cells, key=lambda c: -counts[c]))


def load_pool(stratify: str) -> "tuple[pd.DataFrame, dict]":
    """The builder-tool stratum, auto-named projects removed, with a cell column."""
    df = pd.read_csv(CORPUS, low_memory=False)
    df = df[df.stratum == BUILDER_STRATUM]
    n_stratum = len(df)
    df = df[df.repo_slug.map(readable_slug)].copy()
    auto = df.repo_slug.map(cb.is_auto_slug)
    n_auto = int(auto.sum())
    df = df[~auto].copy()

    if stratify == "genre":
        df["cell"] = df.repo_slug.map(cb.genre)
    elif stratify in df.columns:
        df["cell"] = df[stratify].map(lambda v: text(v) or "(blank)")
    else:
        raise SystemExit(
            "unknown stratification column %r: use genre or a column of corpus.csv" % stratify
        )

    if LOOKUP.exists():
        lookup = pd.read_csv(LOOKUP)[["repo_id", "html_url"]]
        df = df.merge(lookup, on="repo_id", how="left")
    else:
        print("note: %s is missing, so items carry no code link" % LOOKUP.relative_to(ROOT))
        df["html_url"] = ""
    return df, {"stratum_rows": n_stratum, "auto_named_excluded": n_auto, "pool": len(df)}


def draw(pool: pd.DataFrame, n: int, floor: int, seed: int) -> "tuple[pd.DataFrame, OrderedDict]":
    """Proportional allocation across cells, then a fixed-seed shuffle."""
    alloc = allocate(Counter(pool.cell), total=n, floor=floor)
    parts = [pool[pool.cell == cell].sample(k, random_state=seed)
             for cell, k in alloc.items() if k > 0]
    drawn = pd.concat(parts).sample(frac=1, random_state=seed).reset_index(drop=True)
    return drawn, alloc


def items_of(drawn: pd.DataFrame) -> list:
    """Task items. No machine label is written, so the judge has nothing to anchor on."""
    out = []
    for _, r in drawn.iterrows():
        fields = {}
        if text(r.get("page_title")):
            fields["page title"] = text(r["page_title"])
        if url(r.get("homepage_url")):
            fields["live app"] = url(r["homepage_url"])
        if url(r.get("html_url")):
            fields["code"] = url(r["html_url"])
        item = {"id": text(r["repo_id"]), "primary": text(r["repo_slug"])}
        if fields:
            item["fields"] = fields
        out.append(item)
    return out


def build(key: str, spec: dict, n: int, seed: int, stratify: str, question: str,
          options: list, write_files: bool = True) -> dict:
    pool, counts = load_pool(stratify)
    drawn, alloc = draw(pool, n=n, floor=int(spec.get("min_per_cell", 1)), seed=seed)

    sample_note = (
        "%d items drawn from the %s builder-tool names that a person named, in proportion to the "
        "%s mix, with at least %d item per cell. Seed %d. The judge sees no machine label, so the "
        "app reports labeling progress. Alignment is scored separately by src/align_judge.py."
        % (n, format(counts["pool"], ","), stratify, int(spec.get("min_per_cell", 1)), seed)
    )
    payload = {
        "task_id": key,
        "title": spec["title"],
        "question": question,
        "finding": spec.get("finding", ""),
        "sample_note": sample_note,
        "instructions": spec["instructions"],
        "options": list(options),
        "cannot_tell": spec.get("cannot_tell", ""),
        "sampling": {
            "seed": seed,
            "method": (
                "proportional stratified sampling on %s with a floor of %d per cell, "
                "largest remainder allocation, then a fixed-seed shuffle"
                % (stratify, int(spec.get("min_per_cell", 1)))
            ),
            "stratify_column": stratify,
            "builder_stratum_rows": counts["stratum_rows"],
            "auto_named_excluded": counts["auto_named_excluded"],
            "vocabulary_note": spec.get("vocabulary_note", ""),
            "allocation": dict(alloc),
            "populations": [{
                "id": "all",
                "label": "builder-tool names a person named",
                "N": counts["pool"],
                "assumed_p": 0.5,
                "target_margin": None,
                "target_n": n,
            }],
        },
        "scoring": {"cohen_kappa": False},
        "items": items_of(drawn),
    }

    if write_files:
        TASK_DIR.mkdir(parents=True, exist_ok=True)
        SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
        (TASK_DIR / ("%s.json" % key)).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        sample = pd.DataFrame({
            "position": range(1, len(drawn) + 1),
            "repo_id": drawn.repo_id.values,
            "repo_slug": drawn.repo_slug.values,
            "stratum_cell": drawn.cell.values,
        })
        sample.to_csv(SAMPLE_DIR / ("%s_sample.csv" % key), index=False)
        print("%s: %d items, %d cells, pool %s, wrote %s and %s"
              % (key, len(drawn), len(alloc), format(counts["pool"], ","),
                 (TASK_DIR / ("%s.json" % key)).relative_to(ROOT),
                 (SAMPLE_DIR / ("%s_sample.csv" % key)).relative_to(ROOT)))
        top = ", ".join("%s %d" % (c, k) for c, k in list(alloc.items())[:6])
        print("   largest cells: %s" % top)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", choices=list(TASKS), help="which judgement to build")
    ap.add_argument("--all", action="store_true", help="build every judgement in TASKS")
    ap.add_argument("--n", type=int, default=N_ITEMS, help="items to draw (default 50)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--stratify", default=None,
                    help="stratification column: genre, or any column of corpus.csv")
    ap.add_argument("--question", default=None, help="override the question put to the judge")
    ap.add_argument("--options-file", default=None,
                    help="a text file with one option per line, replacing the vocabulary")
    a = ap.parse_args()
    if not a.all and not a.task:
        ap.error("give --task KEY or --all")

    keys = list(TASKS) if a.all else [a.task]
    if a.options_file and len(keys) > 1:
        ap.error("--options-file applies to one task; give --task as well")

    for key in keys:
        spec = TASKS[key]
        options = list(spec["options"])
        if a.options_file:
            lines = [ln.strip() for ln in Path(a.options_file).read_text().splitlines()]
            options = [ln for ln in lines if ln and not ln.startswith("#")]
            if len(options) < 2:
                raise SystemExit("%s holds fewer than two options" % a.options_file)
        build(
            key,
            spec,
            n=a.n,
            seed=a.seed + int(spec.get("seed_offset", 0)),
            stratify=a.stratify or spec.get("stratify", "genre"),
            question=a.question or spec["question"],
            options=options,
        )


if __name__ == "__main__":
    main()
