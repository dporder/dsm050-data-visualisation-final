"""Collect Lovable repositories from fixed creation-date windows.

The query uses the default README heading. Search totals and window coverage
are saved with the responses so capped windows can be identified."""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import RAW, cache_has, cache_get, cache_put, gh, log, now, repo_row, call_counts  # noqa: E402

QUERY = '"Welcome to your Lovable project" in:readme'
# Two day-windows a month is the design. A second pass can add more days (the
# page cache means the first pass is not re-fetched) when the yield from two
# windows falls short of the sample size the analysis needs.
DAYS = tuple(int(d) for d in os.environ.get("LOVABLE_DAYS", "10,24").split(","))
PER_PAGE = 100
MAX_PAGES = 10          # 100 * 10 = the 1,000-result cap


def months(y0, m0, y1, m1):
    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def windows():
    for (y, m) in months(2024, 6, 2026, 9):
        for d in DAYS:
            yield f"{y}-{m:02d}-{d:02d}"


def collect_window(day: str) -> dict:
    """Fetch every page of one day-window, caching each page. Returns a summary."""
    q = f"{QUERY} created:{day}..{day}"
    total_count = None
    incomplete = None
    rows, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        name = f"{day}_p{page:02d}"
        if cache_has("gh_lovable", name):
            data = cache_get("gh_lovable", name)
        else:
            ok, data = gh("search/repositories",
                          {"q": q, "per_page": str(PER_PAGE), "page": str(page),
                           "sort": "updated", "order": "desc"},
                          ["Accept: application/vnd.github+json"], bucket="search")
            if not ok:
                log(f"  ! {day} page {page} failed: {str(data)[:140]}")
                break
            cache_put("gh_lovable", name, data)
        if total_count is None:
            total_count = data.get("total_count")
            incomplete = data.get("incomplete_results")
        items = data.get("items") or []
        for it in items:
            fn = it.get("full_name")
            if fn and fn not in seen:
                seen.add(fn)
                r = repo_row(it)
                r["window_start"] = day
                rows.append(r)
        if len(items) < PER_PAGE:
            break
    return {"window": day, "query": q, "total_count": total_count,
            "incomplete_results": incomplete, "returned": len(rows), "rows": rows}


def main():
    log("STAGE 1: Lovable default-README spine, two one-day windows per month")
    all_rows, wins = [], []
    for day in windows():
        w = collect_window(day)
        wins.append({k: v for k, v in w.items() if k != "rows"})
        all_rows.extend(w["rows"])
        log(f"  {day}  total_count={w['total_count']}  returned={w['returned']}  "
            f"(running {len(all_rows)})")
    # de-duplicate across windows (a repo can only be in one day, but be safe)
    seen, uniq = set(), []
    for r in all_rows:
        if r["full_name"] not in seen:
            seen.add(r["full_name"])
            uniq.append(r)
    out = {"stage": 1, "stratum": "lovable", "query": QUERY, "days": DAYS,
           "run_finished": now(), "n_windows": len(wins), "n_rows": len(uniq),
           "windows": wins, "rows": uniq, "gh_calls": call_counts()}
    with open(os.path.join(RAW, "stage1_lovable.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    log(f"STAGE 1 done: {len(uniq)} distinct repositories across {len(wins)} windows")


if __name__ == "__main__":
    main()
