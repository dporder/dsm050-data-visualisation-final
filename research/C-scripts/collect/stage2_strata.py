"""Collect the three comparison strata using tool-specific repository signals.

The Replit file search uses size slices because the code-search endpoint does
not support the repository creation-date filter used by the README searches."""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import RAW, cache_has, cache_get, cache_put, gh, log, now, repo_row, call_counts  # noqa: E402

TARGET_PER_STRATUM = 2500
PAGES_PER_WINDOW = 3          # 300 rows per (query, quarter): spread over depth
PER_PAGE = 100
REPLIT_CODE_PAGES = 4         # per size slice. 6 slices x 4 x 100 = up to 2,400 hits
REPLIT_FILL_CAP = 800         # core calls spent filling slim code-search rows
# GitHub deprecated sort=indexed on code search: it is accepted and ignored, so
# every code query comes back best-match ordered, which puts famous repositories
# first (legit, canvas-gauges, PGM-index were the top three on a bare query).
# Partitioning by file size gives six disjoint sub-populations, each with its own
# best-match head, which spreads the sample far wider than one query's top 1,000.
REPLIT_SLICES = ["filename:.replit", "filename:.replit size:<80",
                 "filename:.replit size:80..160", "filename:.replit size:160..320",
                 "filename:.replit size:320..800", "filename:.replit size:>800"]

QUARTERS = [("2024-06-01", "2024-09-30"), ("2024-10-01", "2024-12-31"),
            ("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"),
            ("2025-07-01", "2025-09-30"), ("2025-10-01", "2025-12-31"),
            ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"),
            ("2026-07-01", "2026-09-30")]

REPO_QUERIES = {
    "replit": ['"replit.app" in:readme', '"Replit Agent" in:readme'],
    "v0_bolt": ['"Built with v0" in:readme', '"v0.app" in:readme',
                '"v0.dev" in:readme', '"bolt.new" in:readme'],
    "claude": ['"Generated with Claude Code" in:readme',
               '"Co-Authored-By: Claude" in:readme',
               '"Claude Code" in:readme'],
}


def qtag(q: str) -> str:
    """Stable short id for a query. `hash()` is salted per process, so it cannot
    be used here: the page cache has to survive a restart."""
    return hashlib.sha1(q.encode()).hexdigest()[:8]


def repo_search_window(q, a, b, tag):
    rows, total, incomplete = [], None, None
    for page in range(1, PAGES_PER_WINDOW + 1):
        name = f"{tag}_p{page:02d}"
        if cache_has("gh_strata", name):
            data = cache_get("gh_strata", name)
        else:
            ok, data = gh("search/repositories",
                          {"q": f"{q} created:{a}..{b}", "per_page": str(PER_PAGE),
                           "page": str(page), "sort": "updated", "order": "desc"},
                          ["Accept: application/vnd.github+json"], bucket="search")
            if not ok:
                log(f"  ! {tag} page {page}: {str(data)[:120]}")
                break
            cache_put("gh_strata", name, data)
        if total is None:
            total, incomplete = data.get("total_count"), data.get("incomplete_results")
        items = data.get("items") or []
        for it in items:
            r = repo_row(it)
            r["window_start"] = a
            r["window_total_count"] = total
            r["window_key"] = f"{tag}|{a}"
            rows.append(r)
        if len(items) < PER_PAGE:
            break
    return rows, total, incomplete


def replit_code_rows():
    """Code search for `.replit` over six disjoint size slices, then fill the
    slim repository objects that code search returns."""
    slim, order = {}, []
    for si, q in enumerate(REPLIT_SLICES):
        for page in range(1, REPLIT_CODE_PAGES + 1):
            name = f"replitcode_s{si}_p{page:02d}"
            if cache_has("gh_strata", name):
                data = cache_get("gh_strata", name)
            else:
                ok, data = gh("search/code",
                              {"q": q, "per_page": str(PER_PAGE), "page": str(page)},
                              ["Accept: application/vnd.github+json"], bucket="code")
                if not ok:
                    log(f"  ! .replit {q!r} page {page}: {str(data)[:120]}")
                    break
                cache_put("gh_strata", name, data)
            items = data.get("items") or []
            tc = data.get("total_count")
            for it in items:
                r = (it.get("repository") or {})
                fn = r.get("full_name")
                if fn and fn not in slim:
                    slim[fn] = tc
                    order.append(fn)
            if len(items) < PER_PAGE:
                break
        log(f"  .replit {q!r}: {len(order)} distinct repos so far")
    # Fill a seeded random subset rather than the head of the list, so the core
    # budget is not spent entirely on the best-match top of the first slice.
    rng = random.Random(20260912)
    pick = order[:] if len(order) <= REPLIT_FILL_CAP else rng.sample(order, REPLIT_FILL_CAP)
    rows = []
    for i, fn in enumerate(pick):
        if cache_has("gh_strata", "fill_" + fn.replace("/", "__")):
            full = cache_get("gh_strata", "fill_" + fn.replace("/", "__"))
        else:
            ok, full = gh(f"repos/{fn}", bucket="core")
            if not ok:
                continue
            cache_put("gh_strata", "fill_" + fn.replace("/", "__"), full)
        r = repo_row(full)
        r["window_start"] = "code-search (no date qualifier)"
        r["window_total_count"] = slim[fn]
        r["window_key"] = "replit|filename:.replit|code-search"
        rows.append(r)
        if (i + 1) % 100 == 0:
            log(f"  .replit fill {i + 1}/{len(pick)}")
    return rows


def main():
    log("STAGE 2: contrast strata")
    out = {"stage": 2, "run_started": now(), "strata": {}, "windows": []}
    all_rows = []

    # --- replit: code search first, then README routes to top up -------------
    seen = set()
    rows = replit_code_rows()
    for r in rows:
        if r["full_name"] not in seen:
            seen.add(r["full_name"])
            r["stratum"] = "replit"
            all_rows.append(r)
    log(f"  replit after .replit code search: {len(seen)}")

    for stratum, queries in REPO_QUERIES.items():
        s_seen = set(r["full_name"] for r in all_rows if r["stratum"] == stratum) \
            if any(r.get("stratum") == stratum for r in all_rows) else set()
        for q in queries:
            for (a, b) in QUARTERS:
                if len(s_seen) >= TARGET_PER_STRATUM:
                    break
                tag = f"{stratum}_{qtag(q)}_{a}"
                rws, total, incomplete = repo_search_window(q, a, b, tag)
                out["windows"].append({"stratum": stratum, "q": q, "window_start": a,
                                       "window_end": b, "total_count": total,
                                       "incomplete_results": incomplete,
                                       "returned": len(rws)})
                new = 0
                for r in rws:
                    if r["full_name"] in seen:
                        continue
                    seen.add(r["full_name"])
                    s_seen.add(r["full_name"])
                    r["stratum"] = stratum
                    all_rows.append(r)
                    new += 1
                log(f"  {stratum} {q[:34]!r} {a}: total={total} got={len(rws)} new={new} "
                    f"(stratum {len(s_seen)})")
            if len(s_seen) >= TARGET_PER_STRATUM:
                break
        out["strata"][stratum] = len(s_seen)

    out["strata"]["replit"] = sum(1 for r in all_rows if r["stratum"] == "replit")
    out["n_rows"] = len(all_rows)
    out["rows"] = all_rows
    out["run_finished"] = now()
    out["gh_calls"] = call_counts()
    with open(os.path.join(RAW, "stage2_strata.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    log("STAGE 2 done:", json.dumps(out["strata"]))


if __name__ == "__main__":
    main()
