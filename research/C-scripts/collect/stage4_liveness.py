"""Check the saved application addresses once.

Requests respect robots.txt and the per-host delay. The recorded status, title
and metadata support a snapshot of availability. They do not supply failure
dates for survival analysis."""
from __future__ import annotations

import json
import os
import random
import re
import sys
import socket
import threading
import time
import urllib.parse as up
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from common import RAW, cache_has, cache_get, cache_put, log, now   # noqa: E402
import polite                                                        # noqa: E402
from polite import get as pget, head as phead                        # noqa: E402

CAP = int(os.environ.get("LIVE_CAP", "6000"))
WORKERS = int(os.environ.get("LIVE_WORKERS", "10"))
DEADLINE_MIN = float(os.environ.get("LIVE_DEADLINE_MIN", "80"))

NOT_FOUND_RE = re.compile(
    r"(project not found|website not found|app not found|page not found|isn.t live yet|"
    r"no longer available|has been deleted|doesn.t exist|not found|404)", re.I)
PARKED_RE = re.compile(
    r"(domain (is )?for sale|parked|buy this domain|coming soon|sedo|godaddy|namecheap|"
    r"this site can.t be reached)", re.I)
CHALLENGE_RE = re.compile(
    r"(just a moment|attention required|cf-chl|captcha|verify you are human|access denied)", re.I)
# Hosts that serve a 200 shell for any id - a 200 there means nothing.
SHELL_HOSTS = ("claude.ai", "claude.site", "app.base44.com")
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"AKIA[0-9A-Z]{12,}|(?:api[_-]?key|secret|token|password)\s*[=:]\s*\S{12,})")

_lock = threading.Lock()
_orig_log = polite._log


def _locked_log(*a, **kw):
    with _lock:
        _orig_log(*a, **kw)


polite._log = _locked_log
# Per netloc, and an app host is hit 2-3 times (robots.txt, HEAD, sometimes GET).
# Raised from polite.py's default 300 only so that a host which many repositories
# point at (e.g. Lovable.dev itself) does not start failing mid-run and get
# mis-classed. The 1 s per-host gap is untouched. Justification logged below.
polite.MAX_PER_HOST = 400
polite.TIMEOUT = 12               # a liveness check that takes 12 s has answered
polite._log("NOTE-cap-raised", "stage 4: polite.MAX_PER_HOST 300->400 for shared app hosts; "
            "1 s per-host gap kept, HEAD-first, read-only", "-", 0)
try:                               # a bigger connection pool for the thread pool
    import requests.adapters as _ad
    polite.session.mount("https://", _ad.HTTPAdapter(pool_connections=WORKERS * 2,
                                                     pool_maxsize=WORKERS * 4))
    polite.session.mount("http://", _ad.HTTPAdapter(pool_connections=WORKERS * 2,
                                                    pool_maxsize=WORKERS * 4))
except Exception:
    pass

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
DESC_RE = re.compile(
    r"<meta[^>]+(?:name|property)\s*=\s*[\"'](?:description|og:description)[\"'][^>]*"
    r"content\s*=\s*[\"'](.*?)[\"']", re.I | re.S)
DESC_RE2 = re.compile(
    r"<meta[^>]+content\s*=\s*[\"'](.*?)[\"'][^>]*(?:name|property)\s*=\s*"
    r"[\"'](?:description|og:description)[\"']", re.I | re.S)


def clean(s, n=300):
    if not s:
        return ""
    s = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()
    if SECRET_RE.search(s):
        return "[redacted: looked like a key or token]"
    return s[:n]


def normalise(hp: str | None):
    """Return (url, host) or (None, '') for a homepage value that is not a URL."""
    if not hp:
        return None, ""
    hp = hp.strip()
    if not re.match(r"^https?://", hp, re.I):
        if not re.match(r"^[\w.-]+\.[a-z]{2,}", hp, re.I):
            return None, ""
        hp = "https://" + hp
    try:
        u = up.urlsplit(hp)
    except ValueError:
        return None, ""
    host = (u.netloc or "").lower().split("@")[-1]
    if not host or "." not in host or " " in host:
        return None, ""
    return up.urlunsplit((u.scheme.lower(), host, u.path or "/", u.query, "")), host


def classify(status, title, body_head, err, host, final_url):
    if err:
        if any(k in err for k in ("NameResolution", "ConnectionError", "SSLError",
                                  "ConnectTimeout", "TooManyRedirects")):
            return "dead_404"
        return "indeterminate"
    if status in (401, 403, 429) or (body_head and CHALLENGE_RE.search(body_head)):
        return "blocked"
    if status in (404, 410):
        return "dead_404"
    if status and status >= 500:
        return "indeterminate"
    if status and 200 <= status < 400:
        if any(h in (host or "") for h in SHELL_HOSTS) or any(h in (final_url or "") for h in SHELL_HOSTS):
            return "indeterminate"          # 200 shell for any id. Proves nothing
        blob = f"{title} {body_head or ''}"[:3000]
        if PARKED_RE.search(title or "") or (body_head and PARKED_RE.search(body_head[:2000])):
            return "parked"
        if NOT_FOUND_RE.search(title or "") or (body_head and NOT_FOUND_RE.search(body_head[:1200])):
            return "dead_404"               # e.g. Bolt.host serves 200 "Website Not Found"
        del blob
        return "live"
    return "indeterminate"


def check(url, host):
    key = re.sub(r"[^\w.-]", "_", url)[:150]
    if cache_has("liveness", key):
        return cache_get("liveness", key)
    t0 = time.time()
    err, method, body = None, "HEAD", ""
    r = phead(url)
    if r is None or r.status_code in (400, 403, 404, 405, 429, 501, 502, 503):
        r2 = pget(url)
        if r2 is not None:
            r, method = r2, "GET"
    if r is None:
        # polite.get returns None for a robots block AND for a transport failure.
        # A host that no longer resolves in DNS is a dead app, not an unknown one,
        # so separate the two with a name lookup rather than guessing.
        try:
            socket.getaddrinfo(host, 443)
            why, cls = "no-response (robots block, timeout or transport error)", "indeterminate"
        except Exception:
            why, cls = "dns-nxdomain", "dead_404"
        rec = {"url": url, "host": host, "method": method, "status": None,
               "final_url": None, "redirected": False, "title": "", "meta_desc": "",
               "elapsed_s": round(time.time() - t0, 2), "error": why}
        rec["class"] = cls
        cache_put("liveness", key, rec)
        return rec
    try:
        body = r.text[:20000] if (method == "GET" and r.content) else ""
    except Exception:
        body = ""
    title = clean((TITLE_RE.search(body).group(1) if TITLE_RE.search(body) else ""), 200)
    m = DESC_RE.search(body) or DESC_RE2.search(body)
    desc = clean(m.group(1) if m else "", 300)
    # A HEAD-only 200 tells us nothing about the page, so fetch the body once.
    if method == "HEAD" and r.status_code == 200 and not title:
        r2 = pget(url)
        if r2 is not None:
            r, method = r2, "GET"
            body = r.text[:20000] if r.content else ""
            title = clean((TITLE_RE.search(body).group(1) if TITLE_RE.search(body) else ""), 200)
            m = DESC_RE.search(body) or DESC_RE2.search(body)
            desc = clean(m.group(1) if m else "", 300)
    rec = {"url": url, "host": host, "method": method, "status": r.status_code,
           "final_url": r.url, "redirected": bool(r.history),
           "title": title, "meta_desc": desc,
           "elapsed_s": round(time.time() - t0, 2), "error": err}
    rec["class"] = classify(r.status_code, title, body[:3000], err, host, r.url)
    cache_put("liveness", key, rec)
    return rec


SEED = 20260912
MIN_PER_STRATUM = 400


def select(by_stratum: dict[str, list], cap: int) -> list:
    """A seeded random sample of URLs to check, not the first `cap` in row order.

    Row order is window order, so taking the head would have checked only the
    earliest months and only the biggest stratum. Each stratum gets a floor of
    MIN_PER_STRATUM so the three small contrast strata stay comparable, and the
    remainder of the cap is shared out in proportion to stratum size.
    """
    rng = random.Random(SEED)
    pools = {k: v[:] for k, v in by_stratum.items()}
    for v in pools.values():
        rng.shuffle(v)
    total = sum(len(v) for v in pools.values())
    if total <= cap:
        return [t for v in pools.values() for t in v]
    quota = {k: min(len(v), MIN_PER_STRATUM) for k, v in pools.items()}
    left = cap - sum(quota.values())
    if left > 0:
        rest = {k: len(v) - quota[k] for k, v in pools.items()}
        rest_total = sum(rest.values()) or 1
        for k in pools:
            quota[k] += int(left * rest[k] / rest_total)
    out = []
    for k, v in pools.items():
        out.extend(v[:quota[k]])
    rng.shuffle(out)               # spread hosts so threads rarely share one
    return out[:cap]


def main():
    log("STAGE 4: liveness of published app URLs")
    by_stratum: dict[str, list] = {}
    unknown = 0
    seen = set()
    for f in ("stage1_lovable.json", "stage2_strata.json"):
        p = os.path.join(RAW, f)
        if not os.path.exists(p):
            continue
        for r in json.load(open(p, encoding="utf-8"))["rows"]:
            url, host = normalise(r.get("homepage"))
            if not url:
                unknown += 1
                continue
            if url in seen:
                continue
            seen.add(url)
            by_stratum.setdefault(r.get("stratum") or "lovable", []).append((url, host))
    log(f"  distinct resolvable URLs per stratum: "
        f"{json.dumps({k: len(v) for k, v in by_stratum.items()})}; "
        f"{unknown} rows with no usable homepage")
    targets = select(by_stratum, CAP)
    log(f"  checking {len(targets)} (cap {CAP}, seed {SEED}) with {WORKERS} workers")

    t0 = time.time()
    done, results = 0, []
    stop = threading.Event()

    def work(item):
        if stop.is_set():
            return None
        try:
            return check(*item)
        except Exception as e:                                   # never lose the run
            return {"url": item[0], "host": item[1], "status": None, "final_url": None,
                    "redirected": False, "title": "", "meta_desc": "", "error": str(e)[:120],
                    "class": "indeterminate", "method": "ERR"}

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for rec in ex.map(work, targets):
            if rec is None:
                continue
            results.append(rec)
            done += 1
            if done % 200 == 0:
                mins = (time.time() - t0) / 60
                log(f"  {done}/{len(targets)} checked ({mins:.1f} min, "
                    f"{done / max(mins, .01):.0f}/min)")
                if mins > DEADLINE_MIN:
                    log("  deadline reached; stopping early")
                    stop.set()

    from collections import Counter
    out = {"stage": 4, "run_finished": now(), "n_checked": len(results),
           "n_unknown_homepage": unknown, "cap": CAP,
           "by_class": dict(Counter(r["class"] for r in results)),
           "by_status": dict(Counter(str(r["status"]) for r in results).most_common(12)),
           "results": results}
    with open(os.path.join(RAW, "stage4_liveness.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    log("STAGE 4 done:", json.dumps(out["by_class"]))


if __name__ == "__main__":
    main()
