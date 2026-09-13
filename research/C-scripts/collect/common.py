"""Shared helpers for repository collection.

Requests are paced by API bucket and saved so an interrupted collection can
resume. These routines support acquisition. The notebook reads the frozen data."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
import subprocess
import threading
import time

FINAL = "/Users/testdan/Projects/masters_degree_2026/data_visualisation_course/final"
RAW = os.path.join(FINAL, "data", "raw")
PROCESSED = os.path.join(FINAL, "data", "processed")
LOG_PATH = os.path.join(RAW, "collection.log")
CALLS_PATH = os.path.join(RAW, "gh_calls.jsonl")
SALT_PATH = os.path.join(RAW, "SALT.txt")
LOOKUP_PATH = os.path.join(RAW, "owner_lookup.csv")

for _d in (RAW, PROCESSED):
    os.makedirs(_d, exist_ok=True)

_log_lock = threading.Lock()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def log(*parts) -> None:
    msg = " ".join(str(p) for p in parts)
    line = f"{now()}  {msg}"
    print(line, flush=True)
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


# --------------------------------------------------------------------------
# GitHub REST, read-only, through the authenticated gh CLI (account dporder)
# --------------------------------------------------------------------------
# Documented limits: 30 search req/min, 10 code-search req/min, 5000 core/hour.
PACE = {"search": 2.1, "code": 6.5, "core": 0.75, "graphql": 1.0}
_last_call: dict[str, float] = {}
_calls = {"search": 0, "code": 0, "core": 0, "graphql": 0}


def gh(endpoint: str, params: dict | None = None, headers: list | None = None,
       bucket: str = "core", tries: int = 4):
    """GET `endpoint` via `gh api`. Returns (ok, data). Never writes."""
    delay = PACE.get(bucket, 1.0)
    for attempt in range(tries):
        gap = time.time() - _last_call.get(bucket, 0.0)
        if gap < delay:
            time.sleep(delay - gap)
        cmd = ["gh", "api", "-X", "GET", endpoint]
        for k, v in (params or {}).items():
            cmd += ["-f", f"{k}={v}"]
        for h in (headers or []):
            cmd += ["-H", h]
        t0 = now()
        p = subprocess.run(cmd, capture_output=True, text=True)
        _last_call[bucket] = time.time()
        _calls[bucket] += 1
        out = p.stdout.strip()
        try:
            data = json.loads(out) if out else {}
        except json.JSONDecodeError:
            data = {"_raw": out[:400]}
        err = p.stderr.strip()[:300]
        with _log_lock:
            with open(CALLS_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "t": t0, "endpoint": endpoint, "params": params, "bucket": bucket,
                    "rc": p.returncode, "attempt": attempt,
                    "total_count": data.get("total_count") if isinstance(data, dict) else None,
                    "err": err if p.returncode else "",
                }) + "\n")
        if p.returncode == 0:
            return True, data
        low = err.lower()
        if "rate limit" in low or "secondary" in low or "abuse" in low or "403" in low or "429" in low:
            wait = 20 * (attempt + 1) + (30 if "secondary" in low else 0)
            log(f"  rate-limited on {endpoint} ({err[:90]}); sleeping {wait}s")
            time.sleep(wait)
            continue
        if "502" in low or "503" in low or "timeout" in low or "connection" in low:
            time.sleep(5 * (attempt + 1))
            continue
        return False, {"_err": err}
    return False, {"_err": "retries exhausted"}


def gh_graphql(query: str, bucket: str = "graphql", tries: int = 3):
    """Run one GraphQL query. Still read-only: GraphQL queries are sent as POST
    because that is how the endpoint is defined, and nothing here mutates.

    One query can carry ~60 `repositoryOwner` lookups for a cost of 1 point out of
    5,000 an hour, where the REST route costs one of 5,000 requests per owner. That
    is the difference between fetching 6,000 owners in minutes and in hours.
    """
    delay = PACE.get(bucket, 1.0)
    tmp = os.path.join(RAW, ".gql_query.tmp")
    for attempt in range(tries):
        gap = time.time() - _last_call.get(bucket, 0.0)
        if gap < delay:
            time.sleep(delay - gap)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(query)
        t0 = now()
        p = subprocess.run(["gh", "api", "graphql", "-F", f"query=@{tmp}"],
                           capture_output=True, text=True)
        _last_call[bucket] = time.time()
        _calls[bucket] = _calls.get(bucket, 0) + 1
        out = p.stdout.strip()
        try:
            data = json.loads(out) if out else {}
        except json.JSONDecodeError:
            data = {}
        err = p.stderr.strip()[:300]
        with _log_lock:
            with open(CALLS_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": t0, "endpoint": "graphql", "bucket": bucket,
                                     "rc": p.returncode, "attempt": attempt,
                                     "chars": len(query),
                                     "err": err if p.returncode else ""}) + "\n")
        if p.returncode == 0 and data.get("data"):
            return True, data["data"]
        low = err.lower()
        if "rate limit" in low or "secondary" in low or "502" in low or "timeout" in low:
            time.sleep(20 * (attempt + 1))
            continue
        return False, {"_err": err or "graphql failed"}
    return False, {"_err": "retries exhausted"}


def call_counts() -> dict:
    return dict(_calls)


# --------------------------------------------------------------------------
# Anonymization
# --------------------------------------------------------------------------
_salt_cache: str | None = None


def salt() -> str:
    global _salt_cache
    if _salt_cache is not None:
        return _salt_cache
    if os.path.exists(SALT_PATH):
        _salt_cache = open(SALT_PATH, encoding="utf-8").read().strip()
    else:
        _salt_cache = secrets.token_hex(32)
        with open(SALT_PATH, "w", encoding="utf-8") as fh:
            fh.write(_salt_cache + "\n")
        os.chmod(SALT_PATH, 0o600)
    return _salt_cache


def owner_hash(login: str | None) -> str:
    if not login:
        return ""
    return hashlib.sha256((salt() + "|" + login.lower()).encode("utf-8")).hexdigest()[:32]


# --------------------------------------------------------------------------
# Resumable JSON caching
# --------------------------------------------------------------------------
def cache_path(subdir: str, name: str) -> str:
    d = os.path.join(RAW, subdir)
    os.makedirs(d, exist_ok=True)
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)
    return os.path.join(d, safe + ".json")


def cache_has(subdir: str, name: str) -> bool:
    p = cache_path(subdir, name)
    return os.path.exists(p) and os.path.getsize(p) > 1


def cache_get(subdir: str, name: str):
    try:
        with open(cache_path(subdir, name), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def cache_put(subdir: str, name: str, obj) -> None:
    p = cache_path(subdir, name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    os.replace(tmp, p)


# --------------------------------------------------------------------------
# Row shaping - exactly the fields proven in data/samples/*.json
# --------------------------------------------------------------------------
def repo_row(r: dict) -> dict:
    o = r.get("owner") or {}
    return {
        "full_name": r.get("full_name"),
        "html_url": r.get("html_url"),
        "created_at": r.get("created_at"),
        "pushed_at": r.get("pushed_at"),
        "updated_at": r.get("updated_at"),
        "stargazers_count": r.get("stargazers_count"),
        "forks_count": r.get("forks_count"),
        "language": r.get("language"),
        "has_pages": r.get("has_pages"),
        "homepage": r.get("homepage"),
        "description": (r.get("description") or "")[:200],
        "size": r.get("size"),
        "fork": r.get("fork"),
        "license": (r.get("license") or {}).get("spdx_id"),
        "owner_login": o.get("login"),
        "owner_type": o.get("type"),
    }


def owner_row(u: dict) -> dict:
    """Derived booleans only. No bio text, no location string, no blog URL,
    no name, no email - see the ethics rules in the project charter."""
    return {
        "login": u.get("login"),
        "type": u.get("type"),
        "public_repos": u.get("public_repos"),
        "public_gists": u.get("public_gists"),
        "followers": u.get("followers"),
        "following": u.get("following"),
        "created_at": u.get("created_at"),
        "has_bio": bool(u.get("bio")),
        "has_location": bool(u.get("location")),
        "has_company": bool(u.get("company")),
        "has_blog": bool(u.get("blog")),
    }
