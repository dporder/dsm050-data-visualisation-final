"""Collect archive-host records and attempt the repository-level join.

Archive observations describe what was captured. The sparse repository join
is retained as a limitation, while the host table is analyzed separately."""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.parse as up
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from common import RAW, PROCESSED, cache_has, cache_get, cache_put, log, now  # noqa: E402
import polite                                                                 # noqa: E402
from polite import get as pget                                                # noqa: E402

polite.MAX_PER_HOST = 20000
# The census sweep is fine at 1 s, but a long run of single-host CDX queries earns
# HTTP 429, so the per-host pass slows down to one request every 3 s.
polite.DELAY = float(os.environ.get("WB_DELAY", "3.0"))
polite._log("NOTE-cap-raised", "web.archive.org: polite.MAX_PER_HOST raised 300->20000 for "
            "the stage 5 CDX census; 1 s gap kept, single-threaded, read-only, "
            "IA Access Policy permits research use", "-", 0)

PARTS = os.path.join(os.path.dirname(HERE), "..", "research", "C-parts")
PARTS = os.path.normpath(os.path.join(os.path.dirname(HERE), "..", "C-parts"))
DOMAINS = ["lovable.app", "lovableproject.com", "replit.app", "base44.app", "bolt.host"]
BASE = "https://web.archive.org/cdx/search/cdx?"
PER_HOST_CAP = int(os.environ.get("WB_HOST_CAP", "3000"))
DEADLINE_MIN = float(os.environ.get("WB_DEADLINE_MIN", "55"))
SEED = 20260912


def surt_to_host(key: str) -> str:
    return ".".join(reversed(key.split(")")[0].split(",")))


def num_pages(domain: str) -> int:
    r = pget(BASE + up.urlencode({"url": domain, "matchType": "domain", "from": "2024",
                                  "showNumPages": "true"}))
    if r is None or r.status_code != 200:
        return 0
    try:
        return int(r.text.strip())
    except ValueError:
        return 0


def census(domain: str) -> dict:
    """host -> {first,last,last_status,n}. Cached per domain."""
    if cache_has("wayback", "census_" + domain):
        d = cache_get("wayback", "census_" + domain)
        log(f"  census {domain}: {len(d)} hosts (cached)")
        return d
    n = num_pages(domain)
    log(f"  census {domain}: {n} CDX pages")
    hosts: dict[str, dict] = {}
    failed = []
    for page in range(n):
        r = pget(BASE + up.urlencode({"url": domain, "matchType": "domain", "from": "2024",
                                      "fl": "urlkey,timestamp,statuscode", "page": page}))
        if r is None or r.status_code != 200:
            failed.append(page)
            continue
        for ln in r.text.splitlines():
            p = ln.split(" ")
            if len(p) < 3:
                continue
            host = surt_to_host(p[0])
            if "*" in host or not host.endswith(domain):
                continue                        # SURT wildcard artifacts, see C section 4
            h = hosts.get(host)
            if h is None:
                hosts[host] = {"first": p[1], "last": p[1], "n": 1, "last_status": p[2]}
            else:
                h["n"] += 1
                if p[1] < h["first"]:
                    h["first"] = p[1]
                if p[1] >= h["last"]:
                    h["last"], h["last_status"] = p[1], p[2]
        if (page + 1) % 20 == 0:
            log(f"    {domain} page {page + 1}/{n}, {len(hosts)} hosts")
    if failed:
        log(f"    {domain}: {len(failed)} pages failed {failed[:10]}")
    cache_put("wayback", "census_" + domain, hosts)
    log(f"  census {domain}: {len(hosts)} distinct hosts")
    return hosts


def per_host(host: str):
    """First and last capture for one host. Returns None if the API would not answer.

    The Internet Archive throttles a long run of CDX queries with HTTP 429. The
    first version of this function read any non-200 as "no captures", which wrote
    492 false "not in the archive" records into the cache before the 429s were
    spotted. Those were deleted. Now only a genuine 200 is cached, a 429 backs off
    and retries, and a host we could not ask about stays absent rather than being
    recorded as absent from the archive.
    """
    key = "h_" + host
    if cache_has("wayback", key):
        return cache_get("wayback", key)
    for attempt in range(3):
        r = pget(BASE + up.urlencode({"url": host, "matchType": "domain", "from": "2024",
                                      "fl": "timestamp,statuscode", "limit": "2000"}))
        if r is None:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 429 or (r.status_code == 200 and "429 Too Many Requests" in r.text[:200]):
            wait = 30 * (attempt + 1)
            log(f"  429 from web.archive.org on {host}; backing off {wait}s")
            time.sleep(wait)
            continue
        if r.status_code != 200:
            time.sleep(3 * (attempt + 1))
            continue
        rows = [ln.split(" ") for ln in r.text.splitlines() if ln.strip()]
        rows = [pp for pp in rows if len(pp) >= 2 and pp[0].isdigit()]
        rec = {"host": host, "first": None, "last": None, "last_status": None,
               "n": 0, "asked": True}
        if rows:
            rows.sort(key=lambda pp: pp[0])
            rec.update({"first": rows[0][0], "last": rows[-1][0],
                        "last_status": rows[-1][1], "n": len(rows)})
        cache_put("wayback", key, rec)
        return rec
    return None


def wanted_hosts():
    """Distinct app hosts, in a seeded random order.

    Order matters because the per-host budget is smaller than the host list.
    Row order is window order, so taking the head would have looked up only the
    earliest months. A seeded shuffle makes the hosts that do get a Wayback
    lookup a random subset of the hosts that have one to give.
    """
    hosts = []
    seen = set()
    for f in ("stage1_lovable.json", "stage2_strata.json"):
        p = os.path.join(RAW, f)
        if not os.path.exists(p):
            continue
        for r in json.load(open(p, encoding="utf-8"))["rows"]:
            hp = (r.get("homepage") or "").strip()
            if not hp:
                continue
            if not hp.startswith("http"):
                hp = "https://" + hp
            try:
                h = up.urlsplit(hp).netloc.lower().split("@")[-1].split(":")[0]
            except ValueError:
                continue
            if h and "." in h and " " not in h and h not in seen:
                seen.add(h)
                hosts.append(h)
    random.Random(SEED).shuffle(hosts)
    return hosts


def main():
    log("STAGE 5: Wayback first-seen / last-seen per app host")
    cen = {}
    plat = {}
    for dom in DOMAINS:
        c = census(dom)
        for h, v in c.items():
            cen[h] = v
            plat[h] = dom

    # host-level census CSV, one row per host ever captured on a builder domain
    out_csv = os.path.join(PROCESSED, "wayback_census.csv")
    with open(out_csv, "w", encoding="utf-8") as fh:
        fh.write("host,platform,first_seen,last_seen,last_status,n_captures\n")
        for h, v in sorted(cen.items()):
            fh.write(f"{h},{plat[h]},{v['first']},{v['last']},{v['last_status']},{v['n']}\n")
    log(f"  wrote {out_csv} with {len(cen)} hosts")

    # refresh the aggregate census file used by research/C
    agg = {"refreshed_utc": now(), "from": "2024", "domains": {}}
    for dom in DOMAINS:
        sub = {h: v for h, v in cen.items() if plat[h] == dom and h != dom}
        agg["domains"][dom] = {
            "unique_subdomain_hosts": len(sub),
            "hosts_by_first_seen_month": dict(sorted(Counter(v["first"][:6] for v in sub.values()).items())),
            "hosts_by_last_seen_month": dict(sorted(Counter(v["last"][:6] for v in sub.values()).items())),
            "last_status_mix": dict(Counter(v["last_status"] for v in sub.values()).most_common(10)),
        }
    with open(os.path.join(PARTS, "wayback_host_census_refresh.json"), "w", encoding="utf-8") as fh:
        json.dump(agg, fh, indent=1)

    # per-host lookups for whatever the census cannot cover
    want = wanted_hosts()
    missing = [h for h in want if h not in cen]
    log(f"  {len(want)} distinct app hosts; {len(want) - len(missing)} covered by the census, "
        f"{len(missing)} need a per-host CDX call (cap {PER_HOST_CAP})")
    t0 = time.time()
    extra, n_asked, n_refused = {}, 0, 0
    for i, h in enumerate(missing[:PER_HOST_CAP]):
        if (time.time() - t0) / 60 > DEADLINE_MIN:
            log(f"  deadline reached at {i}/{min(len(missing), PER_HOST_CAP)}")
            break
        rec = per_host(h)
        if rec is None:
            n_refused += 1
            continue
        n_asked += 1
        if rec.get("first"):
            extra[h] = {"first": rec["first"], "last": rec["last"],
                        "last_status": rec["last_status"], "n": rec["n"]}
        if (i + 1) % 50 == 0:
            log(f"  per-host {i + 1}/{min(len(missing), PER_HOST_CAP)} "
                f"(asked {n_asked}, found {len(extra)}, refused {n_refused}, "
                f"{(time.time() - t0) / 60:.1f} min)")

    out = {"stage": 5, "run_finished": now(),
           "n_census_hosts": len(cen), "n_app_hosts_wanted": len(want),
           "n_covered_by_census": len(want) - len(missing),
           "n_per_host_looked_up": min(len(missing), PER_HOST_CAP),
           "n_per_host_answered": n_asked, "n_per_host_refused_429": n_refused,
           "n_per_host_found": len(extra),
           "per_host": extra}
    with open(os.path.join(RAW, "stage5_wayback.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    log(f"STAGE 5 done: census {len(cen)} hosts, per-host extra {len(extra)}")


if __name__ == "__main__":
    main()
