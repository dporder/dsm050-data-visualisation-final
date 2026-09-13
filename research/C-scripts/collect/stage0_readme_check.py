"""Check whether the Lovable README search marker persists across creation dates.

The independent project-URL marker provides a comparison. Saved responses record
the evidence behind the selected heading query."""
from __future__ import annotations

import base64
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from common import RAW, gh, log, now, call_counts          # noqa: E402
from polite import get as polite_get                        # noqa: E402

HEAD_ANCHOR = '"Welcome to your Lovable project" in:readme'
URL_ANCHOR = '"lovable.dev/projects" in:readme'

# Every month in the study range, for the two-series comparison.
def months(y0, m0, y1, m1):
    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


ALL_MONTHS = months(2024, 6, 2026, 9)
# Eras to draw actual READMEs from: spread across the whole range.
ERA_MONTHS = [(2024, 6), (2024, 11), (2025, 2), (2025, 5), (2025, 8), (2025, 11),
              (2026, 2), (2026, 4), (2026, 6), (2026, 8), (2026, 9)]
PER_ERA = 2

WELCOME = "# Welcome to your Lovable project"


def month_range(y, m):
    last = {1: 31, 2: 29 if y % 4 == 0 else 28, 3: 31, 4: 30, 5: 31, 6: 30,
            7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[m]
    return f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last:02d}"


def count(anchor, y, m):
    a, b = month_range(y, m)
    ok, d = gh("search/repositories",
               {"q": f"{anchor} created:{a}..{b}", "per_page": "1"},
               ["Accept: application/vnd.github+json"], bucket="search")
    if not ok:
        return None, None
    return d.get("total_count"), d.get("incomplete_results")


def sample_repos(anchor, y, m, n):
    a, b = month_range(y, m)
    ok, d = gh("search/repositories",
               {"q": f"{anchor} created:{a}..{b}", "per_page": str(max(n, 5)),
                "sort": "updated", "order": "desc"},
               ["Accept: application/vnd.github+json"], bucket="search")
    if not ok:
        return []
    return [it["full_name"] for it in d.get("items", [])][:n]


def fetch_readme(full_name):
    """Return (text, route) or (None, reason). Never persisted verbatim."""
    for branch in ("HEAD",):
        r = polite_get(f"https://raw.githubusercontent.com/{full_name}/{branch}/README.md")
        if r is not None and r.status_code == 200 and r.text.strip():
            return r.text, "raw.githubusercontent.com"
    ok, d = gh(f"repos/{full_name}/readme", bucket="core")
    if ok and d.get("content"):
        try:
            return base64.b64decode(d["content"]).decode("utf-8", "replace"), "api:repos/readme"
        except Exception:
            pass
    return None, "unavailable"


def derive(full_name, text, route):
    lines = [l for l in (text or "").splitlines()]
    first = next((l.strip() for l in lines if l.strip()), "")
    low = (text or "").lower()
    return {
        "repo": full_name,
        "route": route,
        "ok": bool(text),
        "readme_len": len(text or ""),
        "first_line": first[:160],
        "has_welcome_line": WELCOME.lower() in low,
        "first_line_is_welcome": first.strip().lower() == WELCOME.lower(),
        "has_project_url": "lovable.dev/projects" in low,
        "mentions_lovable": "lovable" in low,
        "mentions_publish": "publish" in low,
        "mentions_custom_domain": "custom domain" in low,
        "n_headings": sum(1 for l in lines if l.startswith("#")),
    }


def main():
    out = {"run_started": now(), "purpose": "stage 0 blocking check: is the Lovable README first line stable",
           "head_anchor": HEAD_ANCHOR, "url_anchor": URL_ANCHOR,
           "monthly": {}, "readmes": [], "eras": {}}

    log("STAGE 0: monthly total_count for the two anchors, 2024-06..2026-09")
    for (y, m) in ALL_MONTHS:
        key = f"{y}-{m:02d}"
        h, hi = count(HEAD_ANCHOR, y, m)
        u, ui = count(URL_ANCHOR, y, m)
        out["monthly"][key] = {"heading_anchor": h, "heading_incomplete": hi,
                               "url_anchor": u, "url_incomplete": ui,
                               "ratio_url_over_heading": (round(u / h, 3) if (h and u) else None)}
        log(f"  {key}  welcome-line={h}  lovable.dev/projects={u}")

    log("STAGE 0: reading actual README first lines from an independent anchor")
    seen = set()
    for (y, m) in ERA_MONTHS:
        key = f"{y}-{m:02d}"
        names = sample_repos(URL_ANCHOR, y, m, PER_ERA)
        # a second draw from the heading anchor only if the URL anchor is empty
        if not names:
            names = sample_repos(HEAD_ANCHOR, y, m, PER_ERA)
        era_rows = []
        for fn in names:
            if fn in seen:
                continue
            seen.add(fn)
            text, route = fetch_readme(fn)
            row = derive(fn, text, route)
            row["era"] = key
            out["readmes"].append(row)
            era_rows.append(row)
            log(f"  {key} {fn} len={row['readme_len']} first={row['first_line'][:70]!r}")
        out["eras"][key] = {"n": len(era_rows),
                            "n_welcome_first_line": sum(1 for r in era_rows if r["first_line_is_welcome"]),
                            "distinct_first_lines": sorted({r["first_line"] for r in era_rows if r["ok"]})}

    got = [r for r in out["readmes"] if r["ok"]]
    out["verdict"] = {
        "n_readmes_read": len(got),
        "n_first_line_is_welcome": sum(1 for r in got if r["first_line_is_welcome"]),
        "n_contains_welcome_anywhere": sum(1 for r in got if r["has_welcome_line"]),
        "distinct_first_lines": sorted({r["first_line"] for r in got}),
        "readme_len_values": sorted({r["readme_len"] for r in got}),
    }
    out["run_finished"] = now()
    out["gh_calls"] = call_counts()
    with open(os.path.join(RAW, "stage0_readme_check.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    log("STAGE 0 verdict:", json.dumps(out["verdict"])[:900])


if __name__ == "__main__":
    main()
