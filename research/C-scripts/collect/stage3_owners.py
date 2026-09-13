"""Collect public account counts and profile-field presence.

The analysis uses counts, dates and booleans. Private response caches support
collection and are excluded from the submission."""
from __future__ import annotations

import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import (RAW, LOOKUP_PATH, cache_has, cache_get, cache_put, gh, gh_graphql,
                    log, now, owner_hash, owner_row, call_counts)  # noqa: E402

SEED = 20260912
TARGET = int(os.environ.get("OWNER_TARGET", "6000"))
DEADLINE_MIN = float(os.environ.get("OWNER_DEADLINE_MIN", "85"))
QUOTA = {"lovable": 0.50, "replit": 0.1667, "v0_bolt": 0.1667, "claude": 0.1667}
BATCH = int(os.environ.get("OWNER_BATCH", "60"))

OWNER_FRAGMENT = (
    "__typename "
    "... on User { login repositories(privacy: PUBLIC){totalCount} "
    "followers{totalCount} following{totalCount} createdAt bio location company websiteUrl } "
    "... on Organization { login repositories(privacy: PUBLIC){totalCount} "
    "createdAt description location websiteUrl }")


def gql_rows(logins: list[str]) -> dict:
    """One GraphQL query for up to BATCH owners. Returns {login: owner_row}.

    Organization has no `followers`/`following`/`bio`/`company` in GraphQL, so an
    organisation's follower counts come back None here and are topped up over REST
    afterwards. Everything else maps one to one onto the REST fields, which was
    checked against `users/<login>` for one user and one organisation before this
    route was used.
    """
    q = ["{"]
    for i, lg in enumerate(logins):
        q.append(f"  a{i}: repositoryOwner(login: {json.dumps(lg)}) {{ {OWNER_FRAGMENT} }}")
    q.append("}")
    ok, data = gh_graphql("\n".join(q))
    if not ok:
        return {}
    out = {}
    for i, lg in enumerate(logins):
        n = data.get(f"a{i}")
        if not n:
            continue
        is_user = n.get("__typename") == "User"
        out[lg] = {
            "login": n.get("login") or lg,
            "type": n.get("__typename"),
            "public_repos": (n.get("repositories") or {}).get("totalCount"),
            "public_gists": None,
            "followers": (n.get("followers") or {}).get("totalCount") if is_user else None,
            "following": (n.get("following") or {}).get("totalCount") if is_user else None,
            "created_at": n.get("createdAt"),
            "has_bio": bool(n.get("bio") if is_user else n.get("description")),
            "has_location": bool(n.get("location")),
            "has_company": bool(n.get("company")) if is_user else False,
            "has_blog": bool(n.get("websiteUrl")),
        }
    return out


def core_guard(every_n: int, i: int) -> None:
    """The core limit is 5,000 requests an hour and this stage wants ~6,000, so it
    will run into it. Blind retries would burn the remaining budget and lose
    owners. Check the remaining allowance and wait for the reset."""
    if i % every_n:
        return
    ok, d = gh("rate_limit", bucket="core")
    if not ok:
        return
    core = ((d.get("resources") or {}).get("core") or {})
    rem, reset = core.get("remaining"), core.get("reset")
    if rem is None:
        return
    log(f"  core rate limit: {rem} remaining")
    if rem < 80 and reset:
        wait = max(0, reset - time.time()) + 5
        log(f"  waiting {wait / 60:.1f} min for the core limit to reset")
        time.sleep(wait)


def load_rows():
    rows = []
    for f, stratum in (("stage1_lovable.json", "lovable"), ("stage2_strata.json", None)):
        p = os.path.join(RAW, f)
        if not os.path.exists(p):
            log(f"  ! missing {f}; skipping")
            continue
        d = json.load(open(p, encoding="utf-8"))
        for r in d["rows"]:
            r.setdefault("stratum", stratum or r.get("stratum"))
            rows.append(r)
    return rows


def main():
    log("STAGE 3: owner metadata")
    rows = load_rows()
    by_stratum: dict[str, set] = {}
    for r in rows:
        lg = r.get("owner_login")
        if lg:
            by_stratum.setdefault(r.get("stratum") or "lovable", set()).add(lg)
    log("  distinct owners per stratum:",
        json.dumps({k: len(v) for k, v in by_stratum.items()}))

    rng = random.Random(SEED)
    chosen, seen = [], set()
    for stratum, share in QUOTA.items():
        pool = sorted(by_stratum.get(stratum, set()) - seen)
        want = int(TARGET * share)
        pick = pool if len(pool) <= want else rng.sample(pool, want)
        for lg in pick:
            seen.add(lg)
            chosen.append((lg, stratum))
    # spend any unused quota on whatever is left, biggest pool first
    leftovers = sorted(set().union(*by_stratum.values()) - seen) if by_stratum else []
    rng.shuffle(leftovers)
    for lg in leftovers[:max(0, TARGET - len(chosen))]:
        chosen.append((lg, "topup"))
    log(f"  sampled {len(chosen)} distinct owners (seed {SEED}, target {TARGET})")

    t0 = time.time()
    n_new, n_fail, n_rest = 0, 0, 0
    rows_by_login: dict[str, dict] = {}
    todo = []
    for login, stratum in chosen:
        key = login.replace("/", "_")
        if cache_has("gh_owners", key):
            r = cache_get("gh_owners", key)
            if r:
                rows_by_login[login] = r
                continue
        todo.append(login)
    log(f"  {len(rows_by_login)} already cached, {len(todo)} to fetch "
        f"in GraphQL batches of {BATCH}")

    stopped = False
    for b in range(0, len(todo), BATCH):
        if (time.time() - t0) / 60 > DEADLINE_MIN:
            log(f"  deadline {DEADLINE_MIN} min reached after {n_new} new owners; stopping")
            stopped = True
            break
        batch = todo[b:b + BATCH]
        got = gql_rows(batch)
        if not got:
            # one bad login can fail a whole batch, so fall back to REST for it
            log(f"  ! GraphQL batch {b // BATCH} returned nothing; falling back to REST")
            core_guard(1, 0)
            for lg in batch:
                ok, u = gh(f"users/{lg}", bucket="core")
                if ok and u.get("login"):
                    got[lg] = owner_row(u)
                    n_rest += 1
                else:
                    n_fail += 1
        for lg in batch:
            r = got.get(lg)
            if not r:
                n_fail += 1
                continue
            cache_put("gh_owners", lg.replace("/", "_"), r)
            rows_by_login[lg] = r
            n_new += 1
        if (b // BATCH) % 10 == 0:
            log(f"  {b + len(batch)}/{len(todo)} fetched (new {n_new}, rest {n_rest}, "
                f"failed {n_fail}, {(time.time() - t0) / 60:.1f} min)")

    # Organizations have no follower count in GraphQL. Top those up over REST so
    # the column is not silently empty for 2% of rows.
    orgs = [lg for lg, r in rows_by_login.items()
            if r.get("type") == "Organization" and r.get("followers") is None]
    log(f"  topping up {len(orgs)} organisation follower counts over REST")
    for lg in orgs[:600]:
        ok, u = gh(f"users/{lg}", bucket="core")
        if ok and u.get("login"):
            r = owner_row(u)
            cache_put("gh_owners", lg.replace("/", "_"), r)
            rows_by_login[lg] = r
            n_rest += 1

    owners, lookup = [], []
    for login, stratum in chosen:
        row = rows_by_login.get(login)
        if not row:
            continue
        h = owner_hash(row.get("login") or login)
        pub = {k: v for k, v in row.items() if k != "login"}
        pub["owner_hash"] = h
        pub["sampled_from_stratum"] = stratum
        owners.append(pub)
        lookup.append((h, login))

    # private join file, gitignored, so Dan can re-check a hashed row later
    with open(LOOKUP_PATH, "w", encoding="utf-8") as fh:
        fh.write("owner_hash,owner_login\n")
        for h, lg in lookup:
            fh.write(f"{h},{lg}\n")
    os.chmod(LOOKUP_PATH, 0o600)

    out = {"stage": 3, "run_finished": now(), "seed": SEED, "target": TARGET,
           "n_sampled": len(chosen), "n_fetched": len(owners), "n_failed": n_fail,
           "n_via_rest": n_rest, "stopped_at_deadline": stopped,
           "route": "GraphQL repositoryOwner in batches, REST for organisations "
                    "and for any batch GraphQL refused",
           "quota": QUOTA, "owners": owners, "gh_calls": call_counts()}
    with open(os.path.join(RAW, "stage3_owners.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    log(f"STAGE 3 done: {len(owners)} owners ({n_new} newly fetched, {n_rest} via REST, "
        f"{n_fail} failed)")


if __name__ == "__main__":
    main()
