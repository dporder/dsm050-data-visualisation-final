"""Assemble the repository corpus from saved collection stages.

The script joins records, hashes identifiers and derives the analysis fields.
Private lookup files and salts are kept outside the published data."""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys
import urllib.parse as up
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import RAW, PROCESSED, log, now, owner_hash, salt  # noqa: E402

COLUMNS = ["repo_id", "stratum", "created_at", "pushed_at", "updated_at",
           "days_repo_active", "stars", "forks", "language", "size_kb", "is_fork",
           "has_license", "has_description", "description_len", "repo_slug",
           "homepage_url", "app_host", "live_status", "live_class", "page_title",
           "page_meta_desc", "wayback_first_seen", "wayback_last_seen",
           "wayback_last_status", "owner_hash", "owner_public_repos",
           "owner_followers", "owner_account_created",
           "owner_account_age_days_at_repo", "owner_has_bio", "owner_has_location",
           "owner_has_company", "owner_has_blog", "window_start",
           "window_total_count", "sample_weight", "collected_utc"]

import hashlib


def repo_id(full_name: str) -> str:
    return hashlib.sha256((salt() + "|repo|" + full_name.lower()).encode()).hexdigest()[:32]


def parse_iso(s):
    if not s:
        return None
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def wb_iso(ts):
    if not ts or len(ts) < 8:
        return ""
    try:
        return dt.datetime.strptime(ts[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return ts[:4] + "-" + ts[4:6] + "-" + ts[6:8]


def norm_host(hp):
    if not hp:
        return "", ""
    hp = hp.strip()
    if not re.match(r"^https?://", hp, re.I):
        if not re.match(r"^[\w.-]+\.[a-z]{2,}", hp, re.I):
            return "", ""
        hp = "https://" + hp
    try:
        u = up.urlsplit(hp)
    except ValueError:
        return "", ""
    host = (u.netloc or "").lower().split("@")[-1].split(":")[0]
    if not host or "." not in host or " " in host:
        return "", ""
    return up.urlunsplit((u.scheme.lower(), host, u.path or "/", u.query, "")), host


def load(name):
    p = os.path.join(RAW, name)
    if not os.path.exists(p):
        log(f"  ! {name} missing; those columns will be empty")
        return None
    return json.load(open(p, encoding="utf-8"))


def main():
    log("STAGE 6: assembling data/processed/corpus.csv")
    s1 = load("stage1_lovable.json")
    s2 = load("stage2_strata.json")
    s3 = load("stage3_owners.json")
    s4 = load("stage4_liveness.json")
    s5 = load("stage5_wayback.json")

    rows = []
    if s1:
        for r in s1["rows"]:
            r["stratum"] = "lovable"
            rows.append(r)
    if s2:
        rows.extend(s2["rows"])
    log(f"  {len(rows)} repository rows in")

    # Sample weights. A day-window (or a stratum query-quarter) is a sample of a
    # bigger population: `window_total_count` is what GitHub said the window holds,
    # and the denominator is how many rows from that window actually survived into
    # the corpus after de-duplication. One key per (query, window), because the
    # contrast strata run several queries over the same quarter.
    def wkey(r):
        return r.get("window_key") or (r.get("stratum"), r.get("window_start"))

    returned = Counter(wkey(r) for r in rows)
    win_total = {}
    if s1:
        for w in s1["windows"]:
            win_total[("lovable", w["window"])] = w["total_count"]
    for r in rows:
        if r.get("window_total_count") is not None:
            win_total.setdefault(wkey(r), r["window_total_count"])

    # Owner attributes join on the HASH, not the login: stage 3 never wrote a
    # login into its output, and hashing each row's login here reproduces the key.
    owners = {}
    if s3:
        for o in s3["owners"]:
            owners[o["owner_hash"]] = o

    live = {}
    if s4:
        for rec in s4["results"]:
            live[rec["url"]] = rec

    wb = {}
    if s5:
        for h, v in (s5.get("per_host") or {}).items():
            wb[h] = v
    cen_csv = os.path.join(PROCESSED, "wayback_census.csv")
    if os.path.exists(cen_csv):
        with open(cen_csv, encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            for rec in rd:
                wb.setdefault(rec["host"], {"first": rec["first_seen"], "last": rec["last_seen"],
                                            "last_status": rec["last_status"]})
    log(f"  joins ready: {len(owners)} owners, {len(live)} liveness checks, {len(wb)} wayback hosts")

    stamp = now()
    out_rows, repo_lookup = [], []
    for r in rows:
        fn = r.get("full_name") or ""
        if not fn:
            continue
        slug = fn.split("/", 1)[-1].lower()
        created, pushed = parse_iso(r.get("created_at")), parse_iso(r.get("pushed_at"))
        url, host = norm_host(r.get("homepage"))
        lv = live.get(url, {})
        w = wb.get(host, {})
        oh = owner_hash(r.get("owner_login"))
        o = owners.get(oh, {})
        oc = parse_iso(o.get("created_at"))
        key = wkey(r)
        tot = win_total.get(key)
        ret = returned.get(key) or 0
        desc = r.get("description") or ""
        out_rows.append({
            "repo_id": repo_id(fn),
            "stratum": r.get("stratum"),
            "created_at": r.get("created_at") or "",
            "pushed_at": r.get("pushed_at") or "",
            "updated_at": r.get("updated_at") or "",
            "days_repo_active": ((pushed - created).days if (created and pushed) else ""),
            "stars": r.get("stargazers_count"),
            "forks": r.get("forks_count"),
            "language": r.get("language") or "",
            "size_kb": r.get("size"),
            "is_fork": int(bool(r.get("fork"))),
            "has_license": int(bool(r.get("license"))),
            "has_description": int(bool(desc.strip())),
            "description_len": len(desc),
            "repo_slug": slug,
            "homepage_url": url,
            "app_host": host,
            "live_status": lv.get("status", ""),
            "live_class": lv.get("class", ""),
            "page_title": lv.get("title", ""),
            "page_meta_desc": lv.get("meta_desc", ""),
            "wayback_first_seen": wb_iso(w.get("first")),
            "wayback_last_seen": wb_iso(w.get("last")),
            "wayback_last_status": w.get("last_status", ""),
            "owner_hash": oh,
            "owner_public_repos": o.get("public_repos", ""),
            "owner_followers": o.get("followers", ""),
            "owner_account_created": o.get("created_at", "") or "",
            "owner_account_age_days_at_repo": ((created - oc).days if (created and oc) else ""),
            "owner_has_bio": (int(o["has_bio"]) if "has_bio" in o else ""),
            "owner_has_location": (int(o["has_location"]) if "has_location" in o else ""),
            "owner_has_company": (int(o["has_company"]) if "has_company" in o else ""),
            "owner_has_blog": (int(o["has_blog"]) if "has_blog" in o else ""),
            "window_start": r.get("window_start") or "",
            "window_total_count": tot if tot is not None else "",
            "sample_weight": (round(tot / ret, 4) if (tot and ret) else ""),
            "collected_utc": stamp,
        })
        repo_lookup.append((out_rows[-1]["repo_id"], fn, r.get("html_url") or ""))

    out_path = os.path.join(PROCESSED, "corpus.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    # The two private join files, gitignored and chmod 600, so a surprising row can
    # be traced back to the live API later. Stage 3 writes owner_lookup.csv for the
    # owners it sampled. This rewrites it for EVERY owner in the corpus, so no row
    # is left with a hash nobody can resolve.
    lk = os.path.join(RAW, "repo_lookup.csv")
    with open(lk, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["repo_id", "full_name", "html_url"])
        w.writerows(repo_lookup)
    os.chmod(lk, 0o600)

    ol = os.path.join(RAW, "owner_lookup.csv")
    seen_owner = {}
    for r in rows:
        lg = r.get("owner_login")
        if lg:
            seen_owner.setdefault(owner_hash(lg), lg)
    with open(ol, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["owner_hash", "owner_login"])
        w.writerows(sorted(seen_owner.items()))
    os.chmod(ol, 0o600)

    # a small completeness report so data/README.md can state real coverage
    filled = {c: sum(1 for r in out_rows if str(r[c]) not in ("", "None")) for c in COLUMNS}
    summary = {
        "built_utc": stamp, "n_rows": len(out_rows),
        "by_stratum": dict(Counter(r["stratum"] for r in out_rows)),
        "by_live_class": dict(Counter(r["live_class"] for r in out_rows if r["live_class"])),
        "date_range": [min((r["created_at"] for r in out_rows if r["created_at"]), default=""),
                       max((r["created_at"] for r in out_rows if r["created_at"]), default="")],
        "column_fill_rate": {c: round(filled[c] / max(len(out_rows), 1), 4) for c in COLUMNS},
        "n_with_homepage": sum(1 for r in out_rows if r["homepage_url"]),
        "n_with_liveness": sum(1 for r in out_rows if r["live_class"]),
        "n_with_wayback": sum(1 for r in out_rows if r["wayback_first_seen"]),
        "n_with_owner": sum(1 for r in out_rows if r["owner_public_repos"] != ""),
        "n_distinct_owner_hash": len({r["owner_hash"] for r in out_rows if r["owner_hash"]}),
    }
    with open(os.path.join(RAW, "stage6_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    log(f"STAGE 6 done: {len(out_rows)} rows -> {out_path}")
    log("  ", json.dumps({k: v for k, v in summary.items() if k != "column_fill_rate"})[:700])


if __name__ == "__main__":
    main()
