"""Draw the legacy dictionary-validation sample and calculate sample sizes.

Classified and unclassified names form separate populations. Sampling uses a
fixed seed and proportional allocation. The saved 105-row legacy sheet has no
completed answers. The notebook retains its sizing calculation as an illustration."""
from __future__ import annotations
import math
import pandas as pd

Z = 1.96
SEED = 20260913


def sample_size(p: float, e: float, N: int) -> int:
    n0 = Z * Z * p * (1 - p) / (e * e)
    return math.ceil(n0 / (1 + (n0 - 1) / N))


def margin_of_error(n: int, p: float, N: int) -> float:
    if n <= 1:
        return float("nan")
    return Z * math.sqrt(p * (1 - p) / n) * math.sqrt((N - n) / (N - 1))


UNREADABLE = ("Unclassified", "Generic or brand-style name")


def draw(corpus: pd.DataFrame, codebook, n_classified: int = 62, n_unclassified: int = 43):
    """Return (sheet, machine_answers). The sheet carries no machine labels."""
    f = corpus[(corpus.stratum == "lovable")].copy()
    f = f[~f.repo_slug.map(codebook.is_auto_slug)]
    f["genre"] = f.repo_slug.map(codebook.genre)
    f["commercial"] = f.repo_slug.map(codebook.is_commercial)

    classified = f[~f.genre.isin(UNREADABLE)]
    unclassified = f[f.genre.isin(UNREADABLE)]

    # Proportional allocation across genre families, largest remainder so the
    # parts sum to exactly n_classified.
    shares = classified.genre.value_counts(normalize=True)
    exact = shares * n_classified
    alloc = exact.apply(math.floor).astype(int)
    for fam in (exact - alloc).sort_values(ascending=False).index:
        if alloc.sum() >= n_classified:
            break
        alloc[fam] += 1

    parts = [
        classified[classified.genre == fam].sample(min(k, (classified.genre == fam).sum()),
                                                   random_state=SEED)
        for fam, k in alloc.items() if k > 0
    ]
    picked_cl = pd.concat(parts)
    picked_un = unclassified.sample(min(n_unclassified, len(unclassified)), random_state=SEED)

    picked_cl = picked_cl.assign(population="classified")
    picked_un = picked_un.assign(population="unclassified")
    s = pd.concat([picked_cl, picked_un]).sample(frac=1, random_state=SEED).reset_index(drop=True)
    s.index = s.index + 1

    answers = s[["repo_id"]].copy()
    answers["population"] = s["population"].values
    answers["machine_genre"] = s["genre"].values
    answers["machine_commercial"] = s["commercial"].values
    answers["machine_live_class"] = s["live_class"].values

    sheet = pd.DataFrame({
        "n": s.index,
        "project_name": s["repo_slug"],
        "YOUR_kind": "",
        "YOUR_money": "",
        "YOUR_alive": "",
        "YOUR_belongs": "",
        "why_not": "",
        "page_title": s["page_title"].fillna(""),
        "live_app": s["homepage_url"].fillna(""),
        "code": s.get("html_url", pd.Series(index=s.index, dtype=object)).fillna(""),
    })
    return sheet, answers, {"N_classified": len(classified), "N_unclassified": len(unclassified),
                            "n_classified": len(picked_cl), "n_unclassified": len(picked_un)}
