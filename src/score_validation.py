"""Score the legacy dictionary-validation files or local evaluator answers.

Wilson intervals and Cohen's kappa are also imported by the final analysis.
The completed four-task evaluation is reproduced by alignment_history.py from
the frozen reference snapshot."""
from __future__ import annotations
import argparse, math, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent)); import codebook as cb

ROOT = Path(__file__).resolve().parents[1]
FAM = list(cb.GENRE_RULES)
CODE = {i + 1: f for i, f in enumerate(FAM)}
CODE[len(FAM) + 1] = "Generic or brand-style name"; CODE[len(FAM) + 2] = "Cannot tell"
JUDGE_UNREAD = {"Generic or brand-style name", "Unreadable: invented or brand name", "Unreadable: not English", "Cannot tell"}


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0: return (float("nan"),) * 3
    p = k / n; den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, c - h, c + h


def kappa(a: pd.Series, b: pd.Series) -> float:
    if len(a) == 0: return float("nan")
    po = (a == b).mean(); cats = set(a) | set(b)
    pe = sum((a == c).mean() * (b == c).mean() for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def norm_judge(x: str) -> str:
    return "Unclassified" if x in JUDGE_UNREAD and x != "Generic or brand-style name" else x


def sheet_from_app() -> pd.DataFrame:
    """Rebuild the sheet's shape from the evaluator's genre.csv (last row per item wins).
    Row order n follows the task file, which is the stratified sample's shuffled order."""
    import json
    task = json.loads((ROOT / "tools/evaluator/tasks/genre.json").read_text())
    order = {it["id"]: i + 1 for i, it in enumerate(task["items"])}
    app = pd.read_csv(ROOT / "data/processed/human_labels/genre.csv", dtype=str, keep_default_na=False)
    app = app[app["rater_id"] == "primary"].sort_values("judged_utc").drop_duplicates("item_id", keep="last")
    app = app[app["verdict"].isin(["label", "reject"])]
    base = pd.read_csv(ROOT / "data/processed/validation_sheet.csv", dtype=str, keep_default_na=False)
    ans = pd.read_csv(ROOT / "data/processed/validation_machine_answers.csv", dtype=str, keep_default_na=False)
    base = base.reset_index(drop=True); ans = ans.reset_index(drop=True)
    base["repo_id"] = ans["repo_id"].iloc[:len(base)].values
    inv = {v: k for k, v in CODE.items()}
    lab = app.set_index("item_id")
    def kind(rid):
        if rid not in lab.index: return ""
        r = lab.loc[rid]
        if r["verdict"] == "reject": return str(inv.get("Cannot tell", 25))
        fam = r["human_label"]
        return str(inv.get(fam, "")) if fam in inv else ("25" if fam else "")
    base["YOUR_kind"] = base["repo_id"].map(kind)
    base["YOUR_belongs"] = base["repo_id"].map(lambda rid: ("n" if lab.loc[rid, "verdict"] == "reject" else ("y" if rid in lab.index else "")) if rid in lab.index else "")
    base["why_not"] = base["repo_id"].map(lambda rid: lab.loc[rid, "reject_reason"] if rid in lab.index else "")
    base = base.drop(columns=["repo_id"])
    return base


def main(first: int | None, from_app: bool = False):
    sheet = sheet_from_app() if from_app else pd.read_csv(ROOT / "data/processed/validation_sheet.csv", dtype=str, keep_default_na=False)
    ans = pd.read_csv(ROOT / "data/processed/validation_machine_answers.csv", dtype=str, keep_default_na=False)
    sheet["n"] = sheet["n"].astype(int)
    if first: sheet = sheet[sheet["n"] <= first]
    # Dan's genre code -> family. Blanks and 25 are "cannot tell" and excluded from agreement.
    def dan_family(v):
        v = v.strip()
        if not v.isdigit(): return None
        f = CODE.get(int(v)); return None if f == "Cannot tell" else f
    sheet["human"] = sheet["YOUR_kind"].map(dan_family)
    df = sheet.merge(ans.assign(n=None).drop(columns="n"), left_on="project_name", right_on=None, how="left", left_index=False, right_index=False) if False else sheet
    # join on row order: the answers file was written in the same order as the sheet
    ans = ans.reset_index(drop=True); sheet = sheet.reset_index(drop=True)
    df = pd.concat([sheet, ans[["repo_id", "population", "machine_genre", "machine_commercial"]].iloc[:len(sheet)].reset_index(drop=True)], axis=1)
    judged = df[df["human"].notna()]
    print(f"rows on sheet: {len(df)}   judged with a family: {len(judged)}   cannot tell or blank: {len(df) - len(judged)}\n")

    # Load judges
    lab_path = ROOT / "data/processed/llm_labels.csv"
    judges = pd.read_csv(lab_path, dtype=str) if lab_path.exists() else pd.DataFrame(columns=["repo_id", "model", "llm_genre"])

    for pop in ["classified", "unclassified"]:
        sub = judged[judged["population"] == pop]
        print(f"== population: {pop}  (n judged = {len(sub)}) ==")
        if pop == "classified":
            k = int((sub["human"] == sub["machine_genre"]).sum()); p, lo, hi = wilson(k, len(sub))
            print(f"  codebook precision: {k}/{len(sub)} = {100*p:.0f}%  (95% CI {100*lo:.0f} to {100*hi:.0f})   kappa {kappa(sub['human'], sub['machine_genre']):.2f}")
        else:
            readable = int(sub["human"].notna().sum())
            print(f"  names the codebook could not read but a human could: {readable}/{len(sub)}")
        for model, jg in judges.groupby("model"):
            j = sub.merge(jg[["repo_id", "llm_genre"]], on="repo_id", how="inner")
            j["judge"] = j["llm_genre"].map(norm_judge)
            jj = j[~j["judge"].isin(["Unclassified"])]
            if len(jj) == 0: continue
            k = int((jj["human"] == jj["judge"]).sum()); p, lo, hi = wilson(k, len(jj))
            print(f"  judge {model:12s}: agrees with human {k}/{len(jj)} = {100*p:.0f}%  (95% CI {100*lo:.0f} to {100*hi:.0f})   kappa {kappa(jj['human'], jj['judge']):.2f}   judge said unreadable on {int((j['judge']=='Unclassified').sum())}")
        print()

    # Held-out protocol: tune on 1..40, test on 41..50
    for lo_, hi_, label in [(1, 40, "tune 1-40"), (41, 50, "held-out 41-50")]:
        s = judged[(judged["n"] >= lo_) & (judged["n"] <= hi_)]
        if len(s) == 0: continue
        line = [f"{label}: n={len(s)}"]
        for model, jg in judges.groupby("model"):
            j = s.merge(jg[["repo_id", "llm_genre"]], on="repo_id", how="inner"); j["judge"] = j["llm_genre"].map(norm_judge)
            line.append(f"{model} {100*(j['human']==j['judge']).mean():.0f}%")
        print(" | ".join(line))

    # Confusions for the strongest judge
    if len(judges):
        best = judges["model"].value_counts().index[0]
        j = judged.merge(judges[judges["model"] == best][["repo_id", "llm_genre"]], on="repo_id"); j["judge"] = j["llm_genre"].map(norm_judge)
        conf = j[j["human"] != j["judge"]].groupby(["judge", "human"]).size().sort_values(ascending=False).head(8)
        print(f"\nmost common disagreements, {best} (judge -> human):"); print(conf.to_string())

    # money and belongs, if filled
    m = df[df["YOUR_money"].str.lower().isin(["y", "n"])]
    if len(m):
        mc = m["machine_commercial"].map(lambda v: "y" if str(v).lower() in ("true", "1", "y") else "n")
        k = int((m["YOUR_money"].str.lower() == mc).sum()); p, lo, hi = wilson(k, len(m))
        print(f"\nmoney: codebook agrees with human {k}/{len(m)} = {100*p:.0f}% (CI {100*lo:.0f} to {100*hi:.0f})")
    b = df[df["YOUR_belongs"].str.lower().isin(["y", "n"])]
    if len(b):
        k = int((b["YOUR_belongs"].str.lower() == "n").sum()); p, lo, hi = wilson(k, len(b))
        print(f"belongs: {k}/{len(b)} judged NOT folk software = {100*p:.0f}% (CI {100*lo:.0f} to {100*hi:.0f}); reasons: {b.loc[b['YOUR_belongs'].str.lower()=='n','why_not'].value_counts().to_dict()}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--first", type=int, default=None)
    ap.add_argument("--from-app", action="store_true", help="read the evaluator app's genre.csv instead of the Numbers sheet")
    a = ap.parse_args(); main(a.first, a.from_app)
