"""Summarize the saved collection files and their coverage."""
from __future__ import annotations

import collections
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import RAW, PROCESSED   # noqa: E402


def jload(name):
    p = os.path.join(RAW, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def main():
    s0, s1, s2 = jload("stage0_readme_check.json"), jload("stage1_lovable.json"), jload("stage2_strata.json")
    s3, s4, s5 = jload("stage3_owners.json"), jload("stage4_liveness.json"), jload("stage5_wayback.json")

    rows = list(csv.DictReader(open(os.path.join(PROCESSED, "corpus.csv"), encoding="utf-8")))
    cols = rows[0].keys() if rows else []
    n = len(rows)
    filled = {c: sum(1 for r in rows if r[c] not in ("", "None")) for c in cols}

    print(f"## Run record\n")
    print(f"corpus.csv rows: {n}")
    print("by stratum:", dict(collections.Counter(r["stratum"] for r in rows)))
    print("by live_class:", dict(collections.Counter(r["live_class"] for r in rows if r["live_class"])))
    print("live_class within checked rows, per stratum:")
    for st in sorted({r["stratum"] for r in rows}):
        c = collections.Counter(r["live_class"] for r in rows if r["stratum"] == st and r["live_class"])
        tot = sum(c.values())
        if tot:
            print(f"   {st:8s} n={tot:5d} " + "  ".join(f"{k}={v}({100*v/tot:.0f}%)" for k, v in c.most_common()))
    created = sorted(r["created_at"] for r in rows if r["created_at"])
    print("created_at range:", created[0] if created else "-", "..", created[-1] if created else "-")
    months = collections.Counter(r["created_at"][:7] for r in rows if r["created_at"])
    print("rows per month:", dict(sorted(months.items())))
    print("distinct owner_hash:", len({r["owner_hash"] for r in rows if r["owner_hash"]}))
    print("distinct app_host:", len({r["app_host"] for r in rows if r["app_host"]}))
    print("top app host suffixes:", collections.Counter(
        ".".join(r["app_host"].split(".")[-2:]) for r in rows if r["app_host"]).most_common(8))
    print("languages:", collections.Counter(r["language"] for r in rows).most_common(6))
    print()
    print("| column | non-empty | fill rate |")
    print("|---|---|---|")
    for c in cols:
        print(f"| `{c}` | {filled[c]} | {100 * filled[c] / max(n, 1):.1f}% |")
    print()
    print("### stage totals")
    if s0:
        v = s0["verdict"]
        print(f"stage 0: {v['n_readmes_read']} READMEs read, "
              f"{v['n_first_line_is_welcome']} open with the welcome line; "
              f"distinct first lines {v['distinct_first_lines']}")
    if s1:
        print(f"stage 1: {s1['n_rows']} rows, {s1['n_windows']} windows, days={s1['days']}, "
              f"gh_calls={s1['gh_calls']}")
        inc = sum(1 for w in s1["windows"] if w.get("incomplete_results"))
        trunc = sum(1 for w in s1["windows"] if (w.get("total_count") or 0) > w.get("returned", 0))
        print(f"         windows with incomplete_results: {inc}; "
              f"windows truncated by the 1,000 cap: {trunc}")
    if s2:
        print(f"stage 2: {s2['n_rows']} rows, strata={s2['strata']}, gh_calls={s2['gh_calls']}")
    if s3:
        print(f"stage 3: {s3['n_fetched']} owners of {s3['n_sampled']} sampled "
              f"(target {s3['target']}, failed {s3['n_failed']}, "
              f"rest {s3.get('n_via_rest')}, stopped_at_deadline={s3.get('stopped_at_deadline')}), "
              f"gh_calls={s3['gh_calls']}")
    if s4:
        print(f"stage 4: {s4['n_checked']} URLs checked, cap {s4['cap']}, "
              f"{s4['n_unknown_homepage']} rows with no usable homepage; by_class={s4['by_class']}")
        print(f"         by_status={s4['by_status']}")
    if s5:
        print(f"stage 5: census {s5['n_census_hosts']} hosts; app hosts wanted "
              f"{s5['n_app_hosts_wanted']}, covered by census {s5['n_covered_by_census']}, "
              f"per-host looked up {s5['n_per_host_looked_up']}, found {s5['n_per_host_found']}")
    cen = os.path.join(PROCESSED, "wayback_census.csv")
    if os.path.exists(cen):
        plats = collections.Counter()
        stat = collections.Counter()
        with open(cen, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                plats[r["platform"]] += 1
                stat[r["last_status"]] += 1
        print("wayback_census.csv hosts per platform:", dict(plats))
        print("  last_status mix:", stat.most_common(6))
    log = os.path.join(RAW, "collection.log")
    if os.path.exists(log):
        print("collection.log lines:", sum(1 for _ in open(log, encoding="utf-8")))
    calls = os.path.join(RAW, "gh_calls.jsonl")
    if os.path.exists(calls):
        b = collections.Counter()
        for line in open(calls, encoding="utf-8"):
            try:
                b[json.loads(line).get("bucket")] += 1
            except Exception:
                pass
        print("GitHub API calls by bucket:", dict(b), "total", sum(b.values()))
    rl = os.path.join(os.path.dirname(HERE), "request-log.tsv")
    if os.path.exists(rl):
        hosts = collections.Counter()
        n_req = 0
        for line in open(rl, encoding="utf-8", errors="replace"):
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0] >= "2026-09-12":
                n_req += 1
                try:
                    hosts[parts[2].split("/")[2]] += 1
                except Exception:
                    pass
        print(f"HTTP requests logged today: {n_req}; top hosts: {hosts.most_common(6)}")


if __name__ == "__main__":
    main()
