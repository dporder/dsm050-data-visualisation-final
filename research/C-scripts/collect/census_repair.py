"""Recover missing archive-host pages and merge their records."""
from __future__ import annotations

import os
import re
import sys
import urllib.parse as up

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from common import cache_get, cache_put, log            # noqa: E402
import polite                                           # noqa: E402
from polite import get as pget                          # noqa: E402

polite.MAX_PER_HOST = 20000
BASE = "https://web.archive.org/cdx/search/cdx?"


def surt_to_host(key: str) -> str:
    return ".".join(reversed(key.split(")")[0].split(",")))


def repair(domain: str, pages: list[int]) -> None:
    hosts = cache_get("wayback", "census_" + domain)
    if hosts is None:
        log(f"  no cached census for {domain}; run stage 5 first")
        return
    before = len(hosts)
    for page in pages:
        r = pget(BASE + up.urlencode({"url": domain, "matchType": "domain", "from": "2024",
                                      "fl": "urlkey,timestamp,statuscode", "page": page}))
        if r is None or r.status_code != 200:
            log(f"  {domain} page {page} still failing ({getattr(r, 'status_code', None)})")
            continue
        n = 0
        for ln in r.text.splitlines():
            p = ln.split(" ")
            if len(p) < 3:
                continue
            host = surt_to_host(p[0])
            if "*" in host or not host.endswith(domain):
                continue
            n += 1
            h = hosts.get(host)
            if h is None:
                hosts[host] = {"first": p[1], "last": p[1], "n": 1, "last_status": p[2]}
            else:
                h["n"] += 1
                if p[1] < h["first"]:
                    h["first"] = p[1]
                if p[1] >= h["last"]:
                    h["last"], h["last_status"] = p[1], p[2]
        log(f"  {domain} page {page}: {n} captures merged")
    cache_put("wayback", "census_" + domain, hosts)
    log(f"  {domain}: {before} -> {len(hosts)} hosts")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--from-log":
        text = open(args[1], encoding="utf-8").read()
        jobs: dict[str, list[int]] = {}
        for dom, lst in re.findall(r"(\S+): \d+ pages failed \[([^\]]*)\]", text):
            jobs.setdefault(dom, []).extend(int(x) for x in re.findall(r"\d+", lst))
        if not jobs:
            log("  no failed pages in that log")
        for dom, pages in jobs.items():
            log(f"repairing {dom} pages {pages}")
            repair(dom, sorted(set(pages)))
        return
    repair(args[0], [int(x) for x in args[1:]])


if __name__ == "__main__":
    main()
