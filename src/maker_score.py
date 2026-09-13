"""Calculate an exploratory account-footprint score.

Public repository counts, followers, account age and profile fields are combined
with activity indicators. A model label supplies one additional term for the
50 reference items. The saved comparison groups professional or technical labels
against Cannot tell. Its AUC therefore describes discrimination between those
answers, without establishing who is a non-programmer. The script reads private
evaluator files. The notebook reads its saved outputs."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
CORPUS = ROOT / "data/processed/corpus.csv"
ALIGN = ROOT / "data/processed/alignment"
TASK = ROOT / "tools/evaluator/tasks/maker.json"
LABELS = ROOT / "data/processed/human_labels/maker.csv"

SIGN = {"log_repos": 1, "log_followers": 1, "log_age": 1, "has_bio": 1, "one_burst": -1, "all_in_corpus": -1}
CODER = {"Looks made by a professional developer": 1.0,
         "Looks made by someone technical but not a professional developer": 0.5}


def auc(score: np.ndarray, y: np.ndarray) -> float:
    pos, neg = score[y == 1], score[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    wins = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(wins / (len(pos) * len(neg)))


def boot_auc(score, y, n=2000, seed=20260913):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        out.append(auc(score[i], y[i]))
    return np.nanpercentile(out, [2.5, 97.5])


def main() -> None:
    c = pd.read_csv(CORPUS, dtype=str, keep_default_na=False, low_memory=False)
    c = c[c.stratum == "lovable"].copy()
    num = lambda s: pd.to_numeric(s, errors="coerce")
    per_owner = c.groupby("owner_hash")["repo_id"].transform("count")
    t = pd.DataFrame({
        "repo_id": c.repo_id,
        "log_repos": np.log1p(num(c.owner_public_repos)),
        "log_followers": np.log1p(num(c.owner_followers)),
        "log_age": np.log1p(num(c.owner_account_age_days_at_repo).clip(lower=0)),
        "has_bio": num(c.owner_has_bio),
        "one_burst": (num(c.days_repo_active) <= 1).astype(float),
        "all_in_corpus": (per_owner >= num(c.owner_public_repos)).astype(float),
    })
    terms = list(SIGN)
    mu, sd = t[terms].mean(), t[terms].std().replace(0, 1)
    z = (t[terms] - mu) / sd
    t["det_score"] = sum(SIGN[k] * z[k] for k in terms) / len(terms)
    t["det_score"] = t["det_score"].fillna(t["det_score"].median())

    # Dan's labels and the coder's accepted answers for the 50 sampled items.
    task = json.loads(TASK.read_text())
    latest = {}
    for r in csv.DictReader(LABELS.open(newline="")):
        if r["rater_id"] == "primary":
            latest[r["item_id"]] = r
    dan = {i: r["human_label"] for i, r in latest.items() if r["verdict"] == "label"}
    acc = json.loads((ALIGN / "accepted.json").read_text())["maker"]
    ck = pd.read_csv(ALIGN / ("maker_%s_v%d.csv" % (acc["model"], acc["prompt_version"])), dtype=str)
    coder = dict(zip(ck.item_id, ck.label))
    order = [it["id"] for it in task["items"] if it["id"] in dan]
    s = t.set_index("repo_id").loc[order].copy()
    s["dan_label"] = [dan[i] for i in order]
    s["y"] = (s["dan_label"] != "Cannot tell from the evidence").astype(int)
    s["coder_label"] = [coder.get(i, "") for i in order]
    s["coder_term"] = s["coder_label"].map(CODER).fillna(0.0)
    zc = (s["coder_term"] - s["coder_term"].mean()) / (s["coder_term"].std() or 1)
    s["full_score"] = (s["det_score"] * len(terms) + zc) / (len(terms) + 1)
    s["position"] = range(1, len(s) + 1)
    s.reset_index().to_csv(ALIGN / "maker_score_items.csv", index=False)

    w, h = s.iloc[:40], s.iloc[40:50]
    print("maker score, validated against Dan's labels (positive = professional or technical)")
    print("  positives: %d of 40 working, %d of 10 sealed" % (w.y.sum(), h.y.sum()))
    for name, col in [("deterministic terms only", "det_score"), ("deterministic plus coder term", "full_score")]:
        a40, ci40 = auc(w[col].values, w.y.values), boot_auc(w[col].values, w.y.values)
        a10 = auc(h[col].values, h.y.values)
        a50, ci50 = auc(s[col].values, s.y.values), boot_auc(s[col].values, s.y.values)
        print("  %s: AUC working 40 = %.2f (bootstrap 95%% %.2f to %.2f); sealed 10 = %.2f; all 50 = %.2f (%.2f to %.2f)"
              % (name, a40, *ci40, a10, a50, *ci50))
    print("  single terms, AUC on all 50:")
    for k in terms:
        print("    %-14s sign %+d  AUC %.2f" % (k, SIGN[k], auc((SIGN[k] * z.set_index(t.repo_id).loc[order, k]).values, s.y.values)))
    print("    %-14s          AUC %.2f" % ("coder_term", auc(s.coder_term.values, s.y.values)))
    try:
        from sklearn.linear_model import LogisticRegression
        X = np.nan_to_num(np.column_stack([z.set_index(t.repo_id).loc[order][terms].values, zc.values]))
        m = LogisticRegression(C=1.0).fit(X[:40], w.y.values)
        print("  for comparison only, an over-parameterised logistic fit on the 40 (7 terms, %d positives): "
              "in-sample AUC %.2f, sealed-10 AUC %.2f; standardised coefficients %s"
              % (w.y.sum(), auc(m.decision_function(X[:40]), w.y.values), auc(m.decision_function(X[40:]), h.y.values),
                 ", ".join("%s %+.2f" % (k, b) for k, b in zip(terms + ["coder"], m.coef_[0]))))
    except Exception as exc:                              # noqa: BLE001
        print("  (logistic comparison skipped: %s)" % exc)

    # The deterministic score over the whole stratum, with cut-offs for the report's "several cut-offs".
    q = t["det_score"].quantile([0.25, 0.5, 0.75])
    print("\ndeterministic score over the builder-tool stratum (n=%s): quartile cut-offs %.2f, %.2f, %.2f"
          % (format(len(t), ","), q[0.25], q[0.5], q[0.75]))
    for cut, lab in [(q[0.75], "top quarter (most professional-looking)"), (q[0.5], "top half"), (q[0.25], "top three quarters")]:
        print("  share of stratum at or above %.2f: %.1f%% (%s)" % (cut, 100 * (t["det_score"] >= cut).mean(), lab))
    t[["repo_id", "det_score"]].to_csv(ALIGN / "maker_score_stratum.csv", index=False)
    print("wrote maker_score_items.csv and maker_score_stratum.csv in data/processed/alignment/")


if __name__ == "__main__":
    main()
