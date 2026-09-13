"""Apply the project's request pacing and robots.txt checks.

Requests to each host are spaced, while independent hosts can be checked
concurrently. Blocked paths remain recorded as unavailable evidence."""
from __future__ import annotations

import os
import time
import datetime as _dt
import urllib.parse as _up
import urllib.robotparser as _rp
from collections import defaultdict

import requests

UA = ("DSM050-folk-software-research/0.1 (MSc coursework, University of London; "
      "single-threaded, polite, read-only; contact via github.com/dporder)")
DELAY = 1.0            # seconds between requests to the same host
MAX_PER_HOST = 300     # hard cap per host for the whole probe
TIMEOUT = 30

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(_HERE, "request-log.tsv")

_last_hit: dict[str, float] = defaultdict(float)
_count: dict[str, int] = defaultdict(int)
_robots: dict[str, _rp.RobotFileParser | None] = {}
_robots_text: dict[str, str] = {}
_crawl_delay: dict[str, float] = {}
ROBOTS_NOTES: dict[str, str] = {}

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "*/*"})


def _host(url: str) -> str:
    return _up.urlsplit(url).netloc.lower()


def _log(method: str, url: str, status, nbytes) -> None:
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(f"{ts}\t{method}\t{url}\t{status}\t{nbytes}\n")


def _wait(host: str) -> None:
    delay = max(DELAY, _crawl_delay.get(host, 0.0))
    gap = time.time() - _last_hit[host]
    if gap < delay:
        time.sleep(delay - gap)


def _raw_request(method: str, url: str, **kw):
    host = _host(url)
    if _count[host] >= MAX_PER_HOST:
        raise RuntimeError(f"request cap {MAX_PER_HOST} reached for {host}")
    _wait(host)
    _count[host] += 1
    kw.setdefault("timeout", TIMEOUT)
    kw.setdefault("allow_redirects", True)
    try:
        r = session.request(method, url, **kw)
        _last_hit[host] = time.time()
        _log(method, url, r.status_code, len(r.content) if r.content else 0)
        return r
    except requests.RequestException as e:
        _last_hit[host] = time.time()
        _log(method, url, f"ERR {type(e).__name__}", 0)
        return None


def robots_txt(base_url: str) -> str:
    """Return the raw robots.txt text for the host of base_url ('' if none)."""
    host = _host(base_url)
    if host in _robots_text:
        return _robots_text[host]
    scheme = _up.urlsplit(base_url).scheme or "https"
    r = _raw_request("GET", f"{scheme}://{host}/robots.txt")
    txt = ""
    if r is not None and r.status_code == 200:
        ctype = r.headers.get("content-type", "")
        body = r.text
        # A SPA fallback or a redirect to another host returns HTML, not rules.
        if "html" in ctype.lower() or body.lstrip().lower().startswith("<!doctype") or body.lstrip().startswith("<"):
            txt = ""
            ROBOTS_NOTES[host] = (f"robots.txt returned {ctype!r} from {r.url} "
                                  f"(HTML, not a robots file): treated as no rules")
        else:
            txt = body
            ROBOTS_NOTES[host] = f"robots.txt 200 from {r.url} ({ctype})"
    else:
        ROBOTS_NOTES[host] = f"robots.txt status {r.status_code if r is not None else 'ERR'}"
    _robots_text[host] = txt
    parser = _rp.RobotFileParser()
    parser.parse(txt.splitlines())
    _robots[host] = parser
    cd = None
    try:
        cd = parser.crawl_delay(UA) or parser.crawl_delay("*")
    except Exception:
        cd = None
    if cd:
        _crawl_delay[host] = float(cd)
    return txt


def allowed(url: str) -> bool:
    host = _host(url)
    if host not in _robots:
        robots_txt(url)
    parser = _robots.get(host)
    if parser is None:
        return True
    # Check both our UA token and the generic agent. Be conservative.
    return parser.can_fetch(UA, url) and parser.can_fetch("*", url)


def rules_summary(base_url: str) -> str:
    """Short human summary of robots.txt for the report."""
    txt = robots_txt(base_url)
    note = ROBOTS_NOTES.get(_host(base_url), "")
    if not txt:
        return f"no usable robots.txt ({note})"
    lines = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith("#")]
    return " | ".join(lines[:40]) + (" | ..." if len(lines) > 40 else "")


def get(url: str, **kw):
    if not allowed(url):
        _log("SKIP-robots", url, "-", 0)
        return None
    return _raw_request("GET", url, **kw)


def head(url: str, **kw):
    if not allowed(url):
        _log("SKIP-robots", url, "-", 0)
        return None
    return _raw_request("HEAD", url, **kw)


def counts() -> dict[str, int]:
    return dict(_count)


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
