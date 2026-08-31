# Company Watchlist v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user watches companies by name; every run additionally fetches those companies' postings via the cheapest working source; the rows ride the existing pipeline unchanged; the map marks what survives.

**Architecture:** One new table (`watched_company`, migration v10), one new store module, one new scraper module holding the resolver and both fetch rungs, a branch in `run_core.execute` that appends watched steps to the plan, two Flask routes, a profile-page section, and a company-card marker. The invariant that shapes every task: *watching a company changes where we search, not what qualifies as a job for the user* — no gate, scope, or scoring code may mention the watchlist.

**Tech Stack:** Python 3.13, pytest, SQLite, Apify actors via `requests`, Flask.

**Spec:** `docs/superpowers/specs/2026-08-31-company-watchlist-v1-design.md`. Its Pre-implementation validation is DONE (2026-08-31): `companyId` is dead; `companyName` arrays batch as OR; `companyUrl` slugs disambiguate. Nothing below uses `companyId`.

Run all commands from `job_hunt/`. Baseline: **825 passing**.

---

## File structure

**Create:**
- `job_hunt/src/store/watchlist.py` — CRUD + resolution/yield persistence. One concern: rows in, rows out, transactions.
- `job_hunt/src/scrapers/watched.py` — the resolver and the two fetch rungs, wrapping `call_actor`. Owns the ingest purity filter and yield recording.
- `job_hunt/tests/test_watchlist_store.py`
- `job_hunt/tests/test_watched_scraper.py`

**Modify:**
- `job_hunt/src/store/schema.py` — v10.
- `job_hunt/src/run_core.py` — plan + execute watched steps; rows join the stream before dedupe.
- `job_hunt/src/app.py` — `POST /api/watchlist`, `DELETE /api/watchlist/<id>`; pass watchlist to profile page.
- `job_hunt/src/setup_page.py` — watchlist section on `/profile`.
- `job_hunt/src/store/queries.py` — `map_sections` marks watched companies.
- `job_hunt/src/map_page.py` — WATCHLIST chip.
- `job_hunt/config.yaml` — `apify.careers_actor`, `search.watched_jobs_per_company`.
- `CLAUDE.md` — one bullet: the invariant.

---

### Task 1: Migration v10 + the store module

**Files:** `src/store/schema.py`, `src/store/watchlist.py`, `tests/test_store_migration.py`, `tests/test_watchlist_store.py`

- [ ] **Step 1: failing tests**

`tests/test_watchlist_store.py`:

```python
"""Tests for src/store/watchlist.py — who a user watches, and what we know."""
import pytest

from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.schema import init_db
from src.store import watchlist


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "wl.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def user(conn):
    return ensure_user(conn, "default")


def test_add_stores_identity_and_starts_unresolved(conn, user):
    wid = watchlist.add(conn, user, name="DataArt", domain="dataart.com")
    row = watchlist.get(conn, user, wid)
    assert row["company_name"] == "DataArt"
    assert row["domain"] == "dataart.com"
    assert row["resolution"] == "unresolved"
    assert row["company_fingerprint"]        # join path to company rows


def test_the_same_company_cannot_be_watched_twice(conn, user):
    watchlist.add(conn, user, name="DataArt")
    with pytest.raises(watchlist.AlreadyWatched):
        watchlist.add(conn, user, name="DataArt Inc")   # same fingerprint


def test_a_pasted_linkedin_url_resolves_immediately(conn, user):
    """A slug is the disambiguator; with it there is nothing to probe."""
    wid = watchlist.add(conn, user, name="Andersen",
                        linkedin_url="https://www.linkedin.com/company/andersenus/")
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "linkedin"
    assert row["linkedin_slug"] == "andersenus"
    assert row["linkedin_name"] == "Andersen"


def test_remove_deletes_the_row(conn, user):
    wid = watchlist.add(conn, user, name="EPAM Systems")
    watchlist.remove(conn, user, wid)
    assert watchlist.get(conn, user, wid) is None


def test_set_resolution_records_when(conn, user):
    wid = watchlist.add(conn, user, name="GitLab", domain="gitlab.com")
    watchlist.set_resolution(conn, user, wid, "ats")
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "ats" and row["resolved_at"]


def test_the_linkedin_invariant_is_enforced_by_the_database(conn, user):
    """resolution='linkedin' with neither name nor slug must be rejected
    by SQLite itself, not by whichever caller remembered to check."""
    import sqlite3
    wid = watchlist.add(conn, user, name="X Co")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE watched_company SET resolution='linkedin', "
                     "linkedin_name=NULL, linkedin_slug=NULL WHERE id=?",
                     (wid,))


def test_record_yield(conn, user):
    wid = watchlist.add(conn, user, name="GitLab", domain="gitlab.com")
    watchlist.set_resolution(conn, user, wid, "ats")
    watchlist.record_yield(conn, user, {watchlist.get(conn, user, wid)
                                        ["company_fingerprint"]: 7})
    row = watchlist.get(conn, user, wid)
    assert row["last_yield_count"] == 7 and row["last_fetched_at"]
```

`tests/test_store_migration.py` — append:

```python
def test_migration_v10_adds_watched_company(tmp_path):
    conn = connect(tmp_path / "v10.db")
    init_db(conn)
    cols = {r["name"] for r in conn.execute(
        "PRAGMA table_info(watched_company)")}
    assert {"company_fingerprint", "resolution", "linkedin_slug",
            "resolved_at", "last_yield_count"} <= cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()
```

- [ ] **Step 2: run, verify failure** — `python -m pytest tests/test_watchlist_store.py -q` → import error.

- [ ] **Step 3: schema v10** — in `src/store/schema.py`: `SCHEMA_VERSION = 10`; append the spec's `CREATE TABLE watched_company` (verbatim from the spec, including both CHECKs and `UNIQUE(user_id, company_fingerprint)`) to `_DDL`; add migration entry:

```python
    10: (
        # Migrations add columns; a whole new table just runs its DDL.
        # (None, None, sql) is the always-run data-migration shape.
        (None, None, _WATCHED_DDL),
    ),
```

where `_WATCHED_DDL` is the same `CREATE TABLE IF NOT EXISTS` string used in `_DDL` (define once, interpolate into `_DDL`). Match the existing `_MIGRATIONS` handling of `column=None` — check how `(table, column, sql)` triples are executed and follow it exactly.

- [ ] **Step 4: the store module** — `src/store/watchlist.py`:

```python
"""Who a user watches, and what resolution learned about each company.

Identity, resolution state, and execution state for the company
watchlist. This module is a pure store: nothing here calls an actor —
`scrapers/watched.py` decides, this module remembers.
"""
import re
import sqlite3
from datetime import datetime, timezone

from .db import transaction
from ..tracker.dedup import fingerprint


class AlreadyWatched(ValueError):
    """The same company (by fingerprint) is already on this user's list."""


_SLUG_RE = re.compile(r"linkedin\.com/company/([^/?#]+)", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug_from_url(url: str | None) -> str | None:
    match = _SLUG_RE.search(str(url or ""))
    return match.group(1).lower() if match else None


def add(conn: sqlite3.Connection, user_id: int, *, name: str,
        domain: str = "", linkedin_url: str = "") -> int:
    """Watch a company. Returns the new row id.

    With a pasted LinkedIn URL the row resolves immediately — the slug is
    the disambiguator, so there is nothing left to probe. Without one it
    starts 'unresolved' and the next run's watched step resolves it; the
    POST handler must stay fast, so no probe ever runs here.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("a company needs a name")
    fp = fingerprint({"company": name, "title": ""})
    slug = slug_from_url(linkedin_url)
    try:
        with transaction(conn):
            cursor = conn.execute(
                """INSERT INTO watched_company
                       (user_id, company_name, company_fingerprint, domain,
                        resolution, resolution_note, linkedin_name,
                        linkedin_slug, resolved_at, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (user_id, name, fp, (domain or "").strip().lower() or None,
                 "linkedin" if slug else "unresolved",
                 None if slug else "pending next run",
                 name if slug else None, slug,
                 _now() if slug else None, _now()))
            return cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise AlreadyWatched(name) from exc


def get(conn, user_id: int, watch_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM watched_company WHERE user_id = ? AND id = ?",
        (user_id, watch_id)).fetchone()
    return dict(row) if row else None


def list_watched(conn, user_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM watched_company WHERE user_id = ? ORDER BY company_name",
        (user_id,))]


def remove(conn, user_id: int, watch_id: int) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM watched_company WHERE user_id=? AND id=?",
                     (user_id, watch_id))


def set_resolution(conn, user_id: int, watch_id: int, resolution: str, *,
                   note: str | None = None, linkedin_name: str | None = None,
                   linkedin_slug: str | None = None) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE watched_company
                  SET resolution=?, resolution_note=?,
                      linkedin_name=COALESCE(?, linkedin_name),
                      linkedin_slug=COALESCE(?, linkedin_slug),
                      resolved_at=?
                WHERE user_id=? AND id=?""",
            (resolution, note, linkedin_name, linkedin_slug, _now(),
             user_id, watch_id))


def record_yield(conn, user_id: int, counts: dict[str, int]) -> None:
    """counts: company_fingerprint -> rows that survived the ingest filter."""
    now = _now()
    with transaction(conn):
        for fp, n in counts.items():
            conn.execute(
                """UPDATE watched_company
                      SET last_fetched_at=?, last_yield_count=?
                    WHERE user_id=? AND company_fingerprint=?""",
                (now, n, user_id, fp))


def watched_fingerprints(conn, user_id: int) -> set[str]:
    return {r["company_fingerprint"] for r in conn.execute(
        "SELECT company_fingerprint FROM watched_company WHERE user_id=?",
        (user_id,))}
```

- [ ] **Step 5: run tests** — both files PASS; check the `column=None` migration shape actually executes table DDL (read `_MIGRATIONS` runner first; adapt if triples are handled differently).
- [ ] **Step 6: full suite, commit** — `feat: watched_company table and store (migration v10)`.

---

### Task 2: The resolver

**Files:** `src/scrapers/watched.py`, `tests/test_watched_scraper.py`

- [ ] **Step 1: failing tests** — `tests/test_watched_scraper.py`:

```python
"""Tests for src/scrapers/watched.py — resolver and both fetch rungs.

No network: `call` is injected everywhere.
"""
import pytest

from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.schema import init_db
from src.store import watchlist
from src.scrapers import watched


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "w.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def user(conn):
    return ensure_user(conn, "default")


_CFG = {"apify": {}, "search": {}}


def test_a_domain_that_resolves_on_the_ats_actor_is_ats(conn, user):
    wid = watchlist.add(conn, user, name="GitLab", domain="gitlab.com")

    def call(actor, payload, label, timeout):
        assert payload["companies"] == ["gitlab.com"]
        return [{"title": "Data Engineer", "company_name": "GitLab"}]

    watched.resolve_pending(conn, user, _CFG, call=call)
    assert watchlist.get(conn, user, wid)["resolution"] == "ats"


def test_a_clean_linkedin_name_resolves_linkedin(conn, user):
    wid = watchlist.add(conn, user, name="EPAM Systems")
    calls = []

    def call(actor, payload, label, timeout):
        calls.append(payload)
        if "companies" in payload:
            return []                                   # no domain -> skipped anyway
        return [{"companyName": "EPAM Systems",
                 "companyUrl": "https://www.linkedin.com/company/epam-systems"}]

    watched.resolve_pending(conn, user, _CFG, call=call)
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "linkedin"
    assert row["linkedin_name"] == "EPAM Systems"
    assert row["linkedin_slug"] == "epam-systems"


def test_an_ambiguous_name_stays_unresolved_with_a_note(conn, user):
    """Two distinct slugs behind one display name is the Andersen case."""
    wid = watchlist.add(conn, user, name="Andersen")

    def call(actor, payload, label, timeout):
        return [
            {"companyName": "Andersen",
             "companyUrl": "https://www.linkedin.com/company/andersenus"},
            {"companyName": "Andersen",
             "companyUrl": "https://www.linkedin.com/company/andersen-corp"},
        ]

    watched.resolve_pending(conn, user, _CFG, call=call)
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "unresolved"
    assert "linkedin" in (row["resolution_note"] or "").lower()


def test_no_rows_anywhere_stays_unresolved(conn, user):
    wid = watchlist.add(conn, user, name="DataArt", domain="dataart.com")
    watched.resolve_pending(conn, user, _CFG, call=lambda *a: [])
    row = watchlist.get(conn, user, wid)
    assert row["resolution"] == "unresolved"
    assert row["resolution_note"]


def test_a_probe_crash_leaves_the_row_unresolved_and_does_not_raise(conn, user):
    watchlist.add(conn, user, name="GitLab", domain="gitlab.com")

    def call(*a):
        raise RuntimeError("actor down")

    watched.resolve_pending(conn, user, _CFG, call=call)   # must not raise
```

- [ ] **Step 2: verify failure**, then **Step 3: implement** in `src/scrapers/watched.py`:

```python
"""Watched companies — the resolver and both fetch rungs.

Resolution is a SOURCE STRATEGY, not authority: it decides where v1
ingests a company's postings from, nothing more. Try ATS (needs a
domain), else LinkedIn (batched by exact name, disambiguated by
companyUrl slug), else stay unresolved with a user-facing note.

Everything network goes through the injected `call` (default
`base.call_actor`), so tests never touch an actor and the run's failure
isolation wraps each rung exactly as it wraps a source.

Validated 2026-08-31 against the live LinkedIn actor: `companyId` is
DEAD (a nonsense id returns unfiltered rows - the Ship 7 failure mode),
`companyName` ARRAYS batch as OR and purely, and rows carry `companyUrl`
whose slug distinguishes the two companies that share the display name
"Andersen". Nothing in this module uses companyId.
"""
import logging
from datetime import date

from .base import call_actor, extract_description
from ..store import watchlist
from ..utils._dates import normalize_date, parse_salary

logger = logging.getLogger(__name__)

_CAREERS_ACTOR_DEFAULT = "fabro.dev~company-career-page-jobs"
_LINKEDIN_ACTOR_DEFAULT = "valig~linkedin-jobs-scraper"


def resolve_pending(conn, user_id: int, config: dict, call=call_actor) -> None:
    """Give every 'unresolved' row one resolution attempt.

    At most two probe calls per row: the ATS actor when a domain is
    stored, then LinkedIn by exact name. A crash marks nothing failed -
    the row simply stays unresolved and is retried next run, because a
    flaky probe must never take the run down.
    """
    apify = config.get("apify", {})
    careers = apify.get("careers_actor", _CAREERS_ACTOR_DEFAULT)
    linkedin = apify.get("linkedin_actor", _LINKEDIN_ACTOR_DEFAULT)

    for row in watchlist.list_watched(conn, user_id):
        if row["resolution"] != "unresolved":
            continue
        try:
            _resolve_one(conn, user_id, row, careers, linkedin, call)
        except Exception:
            logger.exception("resolution probe failed for %s (stays "
                             "unresolved, retried next run)",
                             row["company_name"])


def _resolve_one(conn, user_id, row, careers_actor, linkedin_actor, call):
    if row["domain"]:
        hits = call(careers_actor, {"companies": [row["domain"]],
                                    "maxJobsPerCompany": 1},
                    f"Watched/resolve-ats/{row['company_name']}", 180) or []
        if hits:
            watchlist.set_resolution(conn, user_id, row["id"], "ats")
            return

    name = row["company_name"]
    rows = call(linkedin_actor,
                {"companyName": [name], "limit": 10,
                 "datePosted": "r2592000"},
                f"Watched/resolve-li/{name}", 120) or []
    mine = [r for r in rows if (r.get("companyName") or "").strip() == name]
    slugs = {watchlist.slug_from_url(r.get("companyUrl"))
             for r in mine} - {None}
    if len(slugs) == 1:
        watchlist.set_resolution(conn, user_id, row["id"], "linkedin",
                                 linkedin_name=name,
                                 linkedin_slug=slugs.pop())
    elif len(slugs) > 1:
        watchlist.set_resolution(
            conn, user_id, row["id"], "unresolved",
            note="several companies share this name on LinkedIn - paste "
                 "the right one's LinkedIn URL")
    else:
        watchlist.set_resolution(
            conn, user_id, row["id"], "unresolved",
            note="not found on a careers ATS or LinkedIn in the last 30 "
                 "days; add a domain or a LinkedIn URL")
```

- [ ] **Step 4: run, PASS; commit** — `feat: watched-company resolver - a source strategy, not authority`.

---

### Task 3: The two fetch rungs + ingest filter + yields

**Files:** `src/scrapers/watched.py`, `tests/test_watched_scraper.py`

- [ ] **Step 1: failing tests** — append:

```python
def _watch_resolved(conn, user, name, resolution, **kw):
    wid = watchlist.add(conn, user, name=name, domain=kw.pop("domain", ""))
    watchlist.set_resolution(conn, user, wid, resolution, **kw)
    return watchlist.get(conn, user, wid)


def test_ats_rung_is_one_call_for_all_companies(conn, user):
    _watch_resolved(conn, user, "GitLab", "ats", domain="gitlab.com")
    _watch_resolved(conn, user, "Supabase", "ats", domain="supabase.com")
    calls = []

    def call(actor, payload, label, timeout):
        calls.append(payload)
        return [{"title": "Data Engineer", "company_name": "GitLab",
                 "location": {"raw": "Remote"}, "job_url": "https://g/1",
                 "description_text": "dbt."}]

    jobs = watched.fetch(conn, user, "ats", _CFG, call=call)
    assert len(calls) == 1
    assert sorted(calls[0]["companies"]) == ["gitlab.com", "supabase.com"]
    assert jobs[0]["company"] == "GitLab" and jobs[0]["url"] == "https://g/1"
    assert jobs[0]["platform"] == "Careers page"


def test_linkedin_rung_is_one_call_and_filters_purity(conn, user):
    """The batch returns whatever LinkedIn likes; only exact-name rows
    survive, and a stored slug must also match (the Andersen rule)."""
    _watch_resolved(conn, user, "Andersen", "linkedin",
                    linkedin_name="Andersen", linkedin_slug="andersenus")
    calls = []

    def call(actor, payload, label, timeout):
        calls.append(payload)
        return [
            {"companyName": "Andersen", "title": "Data Analyst",
             "companyUrl": "https://www.linkedin.com/company/andersenus",
             "jobUrl": "https://l/1", "description": "sql."},
            {"companyName": "Andersen", "title": "Window Installer",
             "companyUrl": "https://www.linkedin.com/company/andersen-corp",
             "jobUrl": "https://l/2", "description": "windows."},
            {"companyName": "Totally Other Co", "title": "Data Analyst",
             "companyUrl": "https://www.linkedin.com/company/other",
             "jobUrl": "https://l/3", "description": "sql."},
        ]

    jobs = watched.fetch(conn, user, "linkedin", _CFG, call=call)
    assert len(calls) == 1
    assert calls[0]["companyName"] == ["Andersen"]
    assert [j["url"] for j in jobs] == ["https://l/1"]


def test_yields_are_recorded_per_company(conn, user):
    row = _watch_resolved(conn, user, "GitLab", "ats", domain="gitlab.com")

    def call(actor, payload, label, timeout):
        return [{"title": "A", "company_name": "GitLab",
                 "job_url": "https://g/1", "description_text": "x"},
                {"title": "B", "company_name": "GitLab",
                 "job_url": "https://g/2", "description_text": "y"}]

    watched.fetch(conn, user, "ats", _CFG, call=call)
    after = watchlist.get(conn, user, row["id"])
    assert after["last_yield_count"] == 2 and after["last_fetched_at"]


def test_an_empty_rung_makes_no_call(conn, user):
    def call(*a):
        raise AssertionError("no companies on this rung - must not bill")
    assert watched.fetch(conn, user, "ats", _CFG, call=call) == []
```

- [ ] **Step 2: verify failure**, **Step 3: implement** — append to `watched.py`:

```python
def fetch(conn, user_id: int, lane: str, config: dict,
          call=call_actor) -> list[dict]:
    """One batched call for every company on the rung. Empty rung, no call.

    Returned rows are already purity-filtered; run_core treats them like
    any scraped jobs - they join the stream BEFORE dedupe and pass every
    gate. Watching changes where we search, never what qualifies.
    """
    rows = [r for r in watchlist.list_watched(conn, user_id)
            if r["resolution"] == ("ats" if lane == "ats" else "linkedin")]
    if not rows:
        return []
    apify = config.get("apify", {})
    per_co = int(config.get("search", {}).get("watched_jobs_per_company", 25))

    if lane == "ats":
        jobs, counts = _fetch_ats(rows, apify, per_co, call)
    else:
        jobs, counts = _fetch_linkedin(rows, apify, per_co, call)
    watchlist.record_yield(conn, user_id, counts)
    return jobs


def _fetch_ats(rows, apify, per_co, call):
    actor = apify.get("careers_actor", _CAREERS_ACTOR_DEFAULT)
    raw = call(actor, {"companies": [r["domain"] for r in rows if r["domain"]],
                       "maxJobsPerCompany": per_co,
                       "includeDescription": True},
               "Watched/ats", 300) or []
    by_name = {r["company_name"]: r for r in rows}
    jobs, counts = [], {r["company_fingerprint"]: 0 for r in rows}
    today = date.today().isoformat()
    for item in raw:
        company = str(item.get("company_name") or "").strip()
        watch = by_name.get(company)
        if watch is None:
            # The actor resolved a domain to a company we did not ask
            # for, or renamed one. Counted nowhere, stored nowhere.
            logger.info("Watched/ats: unexpected company %r skipped", company)
            continue
        loc = item.get("location")
        loc = loc.get("raw") if isinstance(loc, dict) else loc
        url = (item.get("job_url") or item.get("apply_url") or "").strip()
        if not url:
            continue
        jobs.append({
            "cat": "watchlist", "title": item.get("title") or "",
            "company": company, "location": loc or "",
            "platform": "Careers page",
            "date": normalize_date(item.get("posted_at") or today),
            "url": url, "salary": "",
            "description": (item.get("description_text") or ""),
        })
        counts[watch["company_fingerprint"]] += 1
    return jobs, counts


def _fetch_linkedin(rows, apify, per_co, call):
    actor = apify.get("linkedin_actor", _LINKEDIN_ACTOR_DEFAULT)
    names = [r["linkedin_name"] or r["company_name"] for r in rows]
    raw = call(actor, {"companyName": names,
                       "limit": per_co * len(rows),
                       "datePosted": "r2592000"},
               "Watched/linkedin", 120) or []
    expect = {(r["linkedin_name"] or r["company_name"]): r for r in rows}
    jobs, counts = [], {r["company_fingerprint"]: 0 for r in rows}
    rejected = 0
    today = date.today().isoformat()
    for item in raw:
        name = str(item.get("companyName") or "").strip()
        watch = expect.get(name)
        slug = watchlist.slug_from_url(item.get("companyUrl"))
        if watch is None or (watch["linkedin_slug"]
                             and slug != watch["linkedin_slug"]):
            # Exact name, and the slug when we hold one: the purity
            # filter that replaces the dead companyId parameter.
            rejected += 1
            continue
        url = (item.get("jobUrl") or item.get("url") or "").strip()
        if not url:
            continue
        jobs.append({
            "cat": "watchlist", "title": item.get("title") or "",
            "company": watch["company_name"],
            "location": item.get("location") or "",
            "platform": "LinkedIn",
            "date": normalize_date(item.get("postedDate") or today),
            "url": url,
            "salary": parse_salary(item.get("salary") or {}),
            "description": extract_description(item),
        })
        counts[watch["company_fingerprint"]] += 1
    if rejected:
        logger.info("Watched/linkedin: %d row(s) failed the purity filter",
                    rejected)
    return jobs, counts
```

- [ ] **Step 4: run, PASS; full suite; commit** — `feat: watched fetch rungs - batched, purity-filtered, yield-recorded`.

---

### Task 4: run_core integration

**Files:** `src/run_core.py`, `tests/test_run_core_execute.py`

- [ ] **Step 1: failing tests** — append to `tests/test_run_core_execute.py`:

```python
def _watch(conn, user, name, resolution, **kw):
    from src.store import watchlist
    wid = watchlist.add(conn, user, name=name, domain=kw.pop("domain", ""))
    watchlist.set_resolution(conn, user, wid, resolution, **kw)


def test_watched_steps_appear_only_when_the_list_is_non_empty(conn, user,
                                                             resume):
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append, scrapers=_scrapers())
    assert not [s for s in seen[0]["steps"]
                if s["source"] == "Watched companies"]

    _watch(conn, user, "GitLab", "ats", domain="gitlab.com")
    seen2 = []
    run2 = start_run(conn, user)
    execute(conn, user, run2, _CONFIG, [resume], _PROFILE,
            on_progress=seen2.append, scrapers=_scrapers(),
            watched_fetch=lambda *a, **k: [])
    lanes = [s["lane"] for s in seen2[0]["steps"]
             if s["source"] == "Watched companies"]
    assert lanes == ["ats", "linkedin"]


def test_watched_rows_ride_the_existing_pipeline(conn, user, resume):
    """THE invariant: a watched hybrid role in a foreign country is
    dropped by the same presence rule as anything else."""
    _watch(conn, user, "Acme", "ats", domain="acme.com")
    good = _job("https://w/keep")            # BI Developer, Toronto (local)
    bad = {**_job("https://w/drop", company="Acme"),
           "location": "Bengaluru, Karnataka, India",
           "description": "hybrid work, three days in the office."}

    def watched_fetch(conn_, uid, lane, config):
        return [good, bad] if lane == "ats" else []

    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(), watched_fetch=watched_fetch)
    urls = {j["url"] for j in result.scored_jobs}
    assert "https://w/keep" in urls
    assert "https://w/drop" not in urls          # presence rule, unbypassed
    assert result.dropped >= 1


def test_a_failing_watched_rung_does_not_take_the_run_down(conn, user, resume):
    _watch(conn, user, "Acme", "ats", domain="acme.com")

    def watched_fetch(conn_, uid, lane, config):
        raise RuntimeError("actor down")

    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(
                         linkedin_jobs=[_job("https://ok/1")]),
                     watched_fetch=watched_fetch)
    assert result.kept == 1
    assert get_run(conn, run_id)["status"] == "OK"
```

- [ ] **Step 2: verify failure**, **Step 3: implement** in `src/run_core.py`:

In `execute()` signature add `watched_fetch=None`. After `steps = plan_steps(...)`:

```python
    # Watched companies: two extra steps, planned only when the user
    # watches anything. Resolution runs first inside the ats step (lazy -
    # never in a Flask request), then one batched call per rung. Rows
    # join the stream BEFORE dedupe and pass every gate unchanged:
    # watching a company changes where we search, not what qualifies as
    # a job for the user.
    from .store.watchlist import list_watched
    if list_watched(conn, user_id):
        steps += [{"source": "Watched companies", "role": "watchlist",
                   "lane": lane, "state": "pending", "found": 0}
                  for lane in ("ats", "linkedin")]
```

In the step loop, first branch:

```python
        if step["source"] == "Watched companies":
            step["state"] = "running"
            report("scraping")
            try:
                if step["lane"] == "ats":
                    from .scrapers.watched import resolve_pending
                    resolve_pending(conn, user_id, config)
                fetch = watched_fetch or _default_watched_fetch
                jobs = fetch(conn, user_id, step["lane"], config)
            except Exception as exc:
                logger.warning("Watched/%s failed: %s", step["lane"], exc)
                step["state"] = "failed"
            else:
                step["state"] = "done"
                step["found"] = len(jobs)
                all_scraped.extend(jobs)
                scraped_total += len(jobs)
            report("scraping")
            continue
```

with module-level:

```python
def _default_watched_fetch(conn, user_id, lane, config):
    from .scrapers.watched import fetch
    return fetch(conn, user_id, lane, config)
```

NOTE: when `watched_fetch` is injected, `resolve_pending` still runs — wrap it in the same try (a probe failure is a rung failure). Tests injecting `watched_fetch` use already-resolved rows, so `resolve_pending`'s real actor path is never reached without a token… **it is**: `resolve_pending` only probes `unresolved` rows, and the fixtures resolve theirs. Add one line to the test-3 fixture confirming no unresolved rows remain (or pass `call=` through). Keep `resolve_pending(conn, user_id, config)` inside the try and rely on resolved fixtures.

- [ ] **Step 4: run the new tests, then the full suite. Commit** — `feat: watched companies join the run - two steps, zero bypass`.

---

### Task 5: routes + profile page

**Files:** `src/app.py`, `src/setup_page.py`, `tests/test_setup_routes.py` (or `test_app.py` — follow where `/api/profile` is tested)

- [ ] **Step 1: failing tests** (in the file that already tests `/api/profile`):

```python
def test_watchlist_add_is_fast_and_returns_pending(...):
    # POST /api/watchlist {"name": "DataArt", "domain": "dataart.com"}
    # -> 201, body carries "resolution": "unresolved"
    # and the handler makes NO actor call (assert no APIFY hit: no
    # monkeypatching needed - the handler simply must not import watched)

def test_watchlist_rejects_a_duplicate(...):   # -> 409

def test_watchlist_delete(...):                # -> 204, row gone

def test_profile_page_lists_watched_companies(...):
    # GET /profile after adding one -> name and resolution note in HTML
```

- [ ] **Step 2: implement routes** in `create_app` (after the `/api/profile` route), body per the store module: `add` → 201 (row as JSON), `AlreadyWatched` → 409, `ValueError` → 400; DELETE → 204. Import only `src.store.watchlist` — never `scrapers.watched` — so the handler cannot probe.
- [ ] **Step 3: profile page** — in `render_profile`, a third card `YOUR WATCHLIST`: rows of `company_name · resolution (note)` + `last_yield_count`, a remove button per row (`fetch DELETE`), an add form (name, domain, LinkedIn URL) posting JSON to `/api/watchlist`, and a static suggestions line (GitLab, Supabase, Wikimedia, Zapier, Deel, Remote.com, PostHog, Buffer, Doist) as one-click adds prefilled with their domains. Follow the existing `_PROFILE_JS` / card / `.note` idioms and DESIGN.md tokens already used in the file. `app.py` passes `watchlist.list_watched(conn, user_id)` into `render_profile`.
- [ ] **Step 4: run, PASS; full suite; commit** — `feat: watchlist routes and profile section`.

---

### Task 6: the map marker

**Files:** `src/store/queries.py`, `src/map_page.py`, `tests/test_store_queries.py`, `tests/test_map_page.py`

- [ ] **Step 1: failing tests**

```python
# test_store_queries.py
def test_a_watched_companys_map_is_marked(conn):
    u = ensure_user(conn, "default")
    from src.store import watchlist
    watchlist.add(conn, u, name="Open Co")
    _run_with(conn, u, [_job("https://x/1", company="Open Co",
                             location_scope="open"),
                        _job("https://x/2", company="Other Co",
                             location_scope="open")])
    maps = {m["name"]: m for m in map_sections(conn, u, 7)["new"]}
    assert maps["Open Co"]["watched"] is True
    assert maps["Other Co"]["watched"] is False

# test_map_page.py
def test_a_watched_company_shows_the_watchlist_chip():
    html = render([{"id": 1, "name": "Open Co", "state": "DISCOVER",
                    "why": "", "roles": [], "section": "new",
                    "watched": True}],
                  meta={"companies": 1, "roles": 0})
    assert "WATCHLIST" in html
```

- [ ] **Step 2: implement** — in `_group` (queries.py): fetch `watched_fingerprints(conn, user_id)` once (needs `user_id` — it is available in `map_sections`; pass into `_group`), look up each company's fingerprint (`SELECT fingerprint FROM company WHERE id=?` — already queried for `name`; extend that SELECT), set `m["watched"] = fp in watched_fps`. In `map_page.render`, where the company name renders, append a small chip `WATCHLIST` when `m.get("watched")` (reuse an existing chip/badge style from the file; cyan `#00D4FF` per DESIGN.md).
- [ ] **Step 3: run, PASS; full suite; commit** — `feat: watched companies carry a WATCHLIST chip on the map`.

---

### Task 7: config, CLAUDE.md, verification, PR

- [ ] **Step 1: config** — `config.yaml` under `apify:` add `careers_actor: "fabro.dev~company-career-page-jobs"`; under `search:` add `watched_jobs_per_company: 25`.
- [ ] **Step 2: CLAUDE.md** — one bullet in the geography section: *Watching a company changes where we search, not what qualifies as a job for the user. Watched rows pass every gate; `if watched: include=True` is a spec violation (`2026-08-31-company-watchlist-v1-design.md`).*
- [ ] **Step 3: suite from both directories** — `python -m pytest tests -q` (job_hunt/) and `python -m pytest job_hunt/tests -q` (root). Expected: all green.
- [ ] **Step 4: live acceptance** (spends ~6 actor calls): via the API, add GitLab (gitlab.com), EPAM Systems, Andersen (no URL), DataArt (dataart.com); trigger `resolve_pending` once with the real `call_actor`; assert GitLab→`ats`, EPAM→`linkedin`, Andersen→`unresolved` + note, DataArt→`unresolved`. Paste `linkedin.com/company/andersenus` for Andersen via a second POST… (v1 has no update route — delete + re-add with the URL). Record results in the PR body.
- [ ] **Step 5: PR** — branch `ship-10-company-watchlist`, PR body: spec link, probe table, acceptance evidence, test count.

## Not in this plan

- DataArt custom adapter (5–10-company trigger), notifications, re-detect endpoint, source authority, global company identity, `companyId` in any form.
