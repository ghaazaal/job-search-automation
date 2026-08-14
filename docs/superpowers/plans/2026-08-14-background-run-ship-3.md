# Ship 3 — Background Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start a scrape from the browser, watch it run, and land on a finished map — without opening a terminal.

**Architecture:** A new pure module `src/run_core.py` holds scrape → dedupe → score → persist and reports through an `on_progress` callback. `main.py` calls it and prints; a threaded worker calls it and writes JSON into the `run` row; tests call it with a list-appending callback. Three new routes start a run, poll it, and render a progress screen.

**Tech Stack:** Python 3.13, Flask, SQLite (WAL), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-14-background-run-design.md`

**Baseline:** `master` at the start of this ship is `dbcce8d` with **422 tests passing**. Every task states how many tests it adds.

---

## Read this before Task 1

Four things in this plan are deliberate decisions that a reader may otherwise
take for defects.

**1. The browser run stops after scoring.** It does not run the LLM shortlist,
does not generate resume variants, and does not write Excel. Those three feed
`Apply_Now`/`LLM_Reason`/`Risk_Flags` and the workbook, none of which the map
reads. `python main.py` keeps all eight steps. This is the decision the whole
ship rests on — see the spec's opening table.

**2. `start_run` and `finish_run` move out of `ingest.py`** into a new
`src/store/runs.py` in Task 1. `ingest.py` owns the rows a run produces;
`runs.py` owns the run itself. Both call sites are updated in the same task.

**3. `persist_run` stops creating the run row.** It takes a `run_id` instead.
The endpoint needs the id before the work starts so `POST` has something to
return and the 409 check has something to test.

**4. There is no schema migration.** `stage`, `progress` and `error` were
added by the version 2 migration in Ship 1 and have never been written.
`started_at` already exists. The schema stays at version 3 — if you find
yourself writing a migration, stop and re-read the spec.

---

## File structure

| File | Responsibility |
| --- | --- |
| `src/store/runs.py` | **new** — run lifecycle: start, progress, finish, fail, recover, query |
| `src/store/queries.py` | **modify** — add `known_listings` for store-based dedupe |
| `src/pipeline_store.py` | **modify** — `persist_run` takes a `run_id` |
| `src/run_core.py` | **new** — scrape → dedupe → score → persist, emits progress |
| `src/run_worker.py` | **new** — thread wrapper; own connection; writes progress |
| `src/searching_page.py` | **new** — the progress screen |
| `src/app.py` | **modify** — three new routes, boot cleanup, `/` routing, banner |
| `src/map_page.py` | **modify** — empty state, SEARCH AGAIN, in-flight banner |
| `src/setup_page.py` | **modify** — confirm and profile screens start runs |
| `main.py` | **modify** — `run_pipeline` calls `run_core` |

---

## Task 1: The run lifecycle module

**Files:**
- Create: `job_hunt/src/store/runs.py`
- Modify: `job_hunt/src/store/ingest.py` (remove `start_run`, `finish_run`)
- Modify: `job_hunt/src/pipeline_store.py` (import from the new module)
- Test: `job_hunt/tests/test_store_runs.py`

Adds 17 tests.

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_store_runs.py`:

```python
"""Tests for src/store/runs.py — the run lifecycle.

These cover what the poll endpoint and the boot recovery depend on. Time is
injected wherever staleness matters so no test sleeps.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.store import runs
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.schema import init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "runs.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def user(conn):
    return ensure_user(conn, "default")


def test_a_new_run_is_running(conn, user):
    run_id = runs.start_run(conn, user)
    assert runs.get_run(conn, run_id)["status"] == "RUNNING"


def test_progress_survives_a_round_trip(conn, user):
    run_id = runs.start_run(conn, user)
    payload = {"steps": [{"source": "Indeed", "role": "BI Developer",
                          "state": "done", "found": 50}], "scraped": 50}
    runs.set_progress(conn, run_id, "scraping", payload)

    stored = runs.get_run(conn, run_id)
    assert stored["stage"] == "scraping"
    assert stored["progress"] == payload


def test_progress_defaults_to_empty_before_anything_is_written(conn, user):
    run_id = runs.start_run(conn, user)
    assert runs.get_run(conn, run_id)["progress"] == {}


def test_unreadable_progress_does_not_crash_the_poll(conn, user):
    """A half-written row must not take the screen down with it."""
    run_id = runs.start_run(conn, user)
    conn.execute("UPDATE run SET progress = 'not json' WHERE id = ?", (run_id,))
    assert runs.get_run(conn, run_id)["progress"] == {}


def test_finishing_marks_it_ok_with_its_counts(conn, user):
    run_id = runs.start_run(conn, user)
    runs.finish_run(conn, run_id, scraped=300, kept=178)

    stored = runs.get_run(conn, run_id)
    assert stored["status"] == "OK"
    assert (stored["scraped"], stored["kept"]) == (300, 178)


def test_failing_records_the_message(conn, user):
    run_id = runs.start_run(conn, user)
    runs.fail_run(conn, run_id, "Apify returned 401")

    stored = runs.get_run(conn, run_id)
    assert stored["status"] == "FAILED"
    assert stored["error"] == "Apify returned 401"


def test_a_very_long_error_is_truncated_not_dropped(conn, user):
    run_id = runs.start_run(conn, user)
    runs.fail_run(conn, run_id, "x" * 5000)
    assert 0 < len(runs.get_run(conn, run_id)["error"]) <= 500


def test_get_run_returns_none_for_an_unknown_id(conn):
    assert runs.get_run(conn, 9999) is None


def test_active_run_finds_the_running_one(conn, user):
    run_id = runs.start_run(conn, user)
    assert runs.active_run(conn, user)["id"] == run_id


def test_active_run_ignores_finished_runs(conn, user):
    run_id = runs.start_run(conn, user)
    runs.finish_run(conn, run_id, scraped=1, kept=1)
    assert runs.active_run(conn, user) is None


def test_a_fresh_run_is_not_stale():
    now = datetime.now(timezone.utc)
    assert runs.is_stale(now.isoformat(timespec="seconds"), now=now) is False


def test_a_run_older_than_the_window_is_stale():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=runs.STALE_AFTER_MINUTES + 1))
    assert runs.is_stale(old.isoformat(timespec="seconds"), now=now) is True


def test_an_unparseable_start_time_counts_as_stale():
    """Better to let the user start a new run than to lock them out."""
    assert runs.is_stale("not a timestamp") is True


def test_clear_running_recovers_every_orphan(conn, user):
    first = runs.start_run(conn, user)
    second = runs.start_run(conn, user)
    cleared = runs.clear_running(conn, "interrupted")

    assert cleared == 2
    assert runs.get_run(conn, first)["status"] == "FAILED"
    assert runs.get_run(conn, second)["status"] == "FAILED"


def test_clear_running_leaves_finished_runs_alone(conn, user):
    done = runs.start_run(conn, user)
    runs.finish_run(conn, done, scraped=1, kept=1)
    runs.clear_running(conn, "interrupted")
    assert runs.get_run(conn, done)["status"] == "OK"


def test_latest_ok_run_ignores_a_run_still_going(conn, user):
    """The map keys 'what is new' off this. An in-flight run must not count."""
    done = runs.start_run(conn, user)
    runs.finish_run(conn, done, scraped=1, kept=1)
    runs.start_run(conn, user)          # still RUNNING

    assert runs.latest_ok_run(conn, user) == done


def test_latest_ok_run_is_none_before_any_run_succeeds(conn, user):
    runs.start_run(conn, user)
    assert runs.latest_ok_run(conn, user) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_store_runs.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'src.store.runs'`

- [ ] **Step 3: Create the module**

Create `job_hunt/src/store/runs.py`:

```python
"""The life of one scrape run: start, report, finish, fail, recover.

`ingest` owns the rows a run produces. This module owns the run itself — the
row the progress screen polls and the boot recovery repairs.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from .db import transaction

# A RUNNING run older than this is presumed abandoned. The worker writes no
# heartbeat, so age is the only evidence available. Long enough that a genuine
# slow scrape is never mistaken for a dead one: four Apify calls at a 120
# second timeout is eight minutes worst case.
STALE_AFTER_MINUTES = 15

# The error column is display text, not a log. Keep it short enough to render.
_MAX_ERROR = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start_run(conn: sqlite3.Connection, user_id: int) -> int:
    with transaction(conn):
        conn.execute(
            "INSERT INTO run (user_id, started_at, status) VALUES (?, ?, 'RUNNING')",
            (user_id, _now()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def finish_run(conn: sqlite3.Connection, run_id: int,
               scraped: int, kept: int, ok: bool = True) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE run SET status = ?, finished_at = ?, scraped = ?, kept = ?
               WHERE id = ?""",
            ("OK" if ok else "FAILED", _now(), scraped, kept, run_id))


def fail_run(conn: sqlite3.Connection, run_id: int, error: str) -> None:
    """Mark a run failed, carrying the message the screen will show."""
    with transaction(conn):
        conn.execute(
            "UPDATE run SET status = 'FAILED', finished_at = ?, error = ?"
            " WHERE id = ?",
            (_now(), str(error)[:_MAX_ERROR], run_id))


def set_progress(conn: sqlite3.Connection, run_id: int,
                 stage: str, progress: dict) -> None:
    with transaction(conn):
        conn.execute("UPDATE run SET stage = ?, progress = ? WHERE id = ?",
                     (stage, json.dumps(progress), run_id))


def get_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute(
        """SELECT id, status, stage, progress, error, scraped, kept
             FROM run WHERE id = ?""", (run_id,)).fetchone()
    if row is None:
        return None
    # A run killed mid-write can leave this unparseable. The screen matters
    # more than the payload, so fall back rather than raise.
    try:
        progress = json.loads(row["progress"] or "{}")
    except (json.JSONDecodeError, TypeError):
        progress = {}
    return {
        "id":       row["id"],
        "status":   row["status"],
        "stage":    row["stage"] or "",
        "progress": progress,
        "error":    row["error"] or "",
        "scraped":  row["scraped"],
        "kept":     row["kept"],
    }


def active_run(conn: sqlite3.Connection, user_id: int) -> dict | None:
    """The user's RUNNING run if there is one, at any age."""
    row = conn.execute(
        "SELECT id, started_at FROM run WHERE user_id = ? AND status = 'RUNNING'"
        " ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "started_at": row["started_at"]}


def is_stale(started_at: str, now: datetime | None = None) -> bool:
    """True when a RUNNING run is old enough to be presumed dead.

    An unreadable timestamp counts as stale. Letting the user start a new run
    is a smaller failure than locking them out of running anything.
    """
    now = now or datetime.now(timezone.utc)
    try:
        started = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return now - started > timedelta(minutes=STALE_AFTER_MINUTES)


def clear_running(conn: sqlite3.Connection, error: str) -> int:
    """Mark every RUNNING run FAILED. Boot recovery only.

    Never call this per-request: at boot no worker of ours is alive, so every
    RUNNING row is an orphan, but during normal operation one of them is the
    run currently in flight.
    """
    with transaction(conn):
        cur = conn.execute(
            "UPDATE run SET status = 'FAILED', finished_at = ?, error = ?"
            " WHERE status = 'RUNNING'", (_now(), str(error)[:_MAX_ERROR]))
    return cur.rowcount


def latest_ok_run(conn: sqlite3.Connection, user_id: int) -> int | None:
    """The newest successful run.

    The map marks roles seen up to this id. It must ignore a run still in
    flight: marking an unfinished run seen would file every role it is about
    to store as already seen, silently emptying the map's new section.
    """
    row = conn.execute(
        "SELECT MAX(id) AS i FROM run WHERE user_id = ? AND status = 'OK'",
        (user_id,)).fetchone()
    return row["i"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_store_runs.py -q`
Expected: `17 passed`

- [ ] **Step 5: Remove the moved functions from ingest.py**

In `job_hunt/src/store/ingest.py`, delete the `start_run` and `finish_run`
definitions (they sit between `ensure_user` and `_company_id`). Delete these
exact lines:

```python
def start_run(conn: sqlite3.Connection, user_id: int) -> int:
    with transaction(conn):
        conn.execute(
            "INSERT INTO run (user_id, started_at, status) VALUES (?, ?, 'RUNNING')",
            (user_id, _now()))
    return conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def finish_run(conn: sqlite3.Connection, run_id: int,
               scraped: int, kept: int, ok: bool = True) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE run SET status = ?, finished_at = ?, scraped = ?, kept = ?
               WHERE id = ?""",
            ("OK" if ok else "FAILED", _now(), scraped, kept, run_id))
```

Leave `_now`, `ensure_user`, and everything below untouched — `_now` is still
used by the rest of `ingest.py`.

- [ ] **Step 6: Point pipeline_store at the new module**

In `job_hunt/src/pipeline_store.py`, change the import line:

```python
from .store.ingest import finish_run, start_run, upsert_jobs
```

to:

```python
from .store.ingest import upsert_jobs
from .store.runs import finish_run, start_run
```

- [ ] **Step 7: Find and fix every other importer**

Run: `python -m pytest tests/ -q`

Any failure here is an import of `start_run`/`finish_run` from `ingest`.
Update each to import from `src.store.runs` instead. Do not re-export them
from `ingest` — one home per function.

Expected when done: `439 passed` (422 baseline + 17 new)

- [ ] **Step 8: Commit**

```bash
git add src/store/runs.py src/store/ingest.py src/pipeline_store.py tests/test_store_runs.py
git commit -m "feat: a module that owns the life of a run"
```

---

## Task 2: persist_run takes a run it did not create

**Files:**
- Modify: `job_hunt/src/pipeline_store.py`
- Modify: `job_hunt/main.py:425-439` (`_persist_and_launch`)
- Test: `job_hunt/tests/test_pipeline_store.py`

Adds 3 tests.

- [ ] **Step 1: Read the current behaviour**

Run: `cat src/pipeline_store.py`

`persist_run` calls `start_run` itself and returns the new id. The endpoint in
Task 7 needs that id *before* the work begins, so creation moves out.

- [ ] **Step 2: Write the failing tests**

Append to `job_hunt/tests/test_pipeline_store.py` (create the file with this
header if it does not exist):

```python
"""Tests for src/pipeline_store.py — the bridge from a scrape to the store."""
import pytest

from src.pipeline_store import persist_run
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.runs import get_run, start_run
from src.store.schema import init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "persist.db")
    init_db(c)
    yield c
    c.close()


_JOB = {"cat": "BI Developer", "title": "BI Developer", "company": "Acme",
        "location": "Toronto, ON", "platform": "Indeed", "date": "2026-08-14",
        "url": "https://example.com/j1", "salary": "", "description": "Power BI",
        "match_score": 8, "band": "STRONG FIT", "reason": "matches Power BI",
        "matched": ["Power BI"], "gaps": [], "resume_id": None,
        "description_captured": True}


def test_persist_writes_into_the_run_it_was_given(conn):
    user_id = ensure_user(conn, "default")
    run_id = start_run(conn, user_id)

    persist_run(conn, user_id, run_id, [_JOB], scraped=1)

    stored = get_run(conn, run_id)
    assert stored["status"] == "OK"
    assert (stored["scraped"], stored["kept"]) == (1, 1)


def test_persist_does_not_create_a_second_run(conn):
    user_id = ensure_user(conn, "default")
    run_id = start_run(conn, user_id)

    persist_run(conn, user_id, run_id, [_JOB], scraped=1)

    total = conn.execute("SELECT COUNT(*) AS n FROM run").fetchone()["n"]
    assert total == 1


def test_a_failing_ingest_marks_the_run_failed_and_re_raises(conn):
    user_id = ensure_user(conn, "default")
    run_id = start_run(conn, user_id)
    broken = {**_JOB, "url": None}      # NOT NULL on role.url

    with pytest.raises(Exception):
        persist_run(conn, user_id, run_id, [broken], scraped=1)

    assert get_run(conn, run_id)["status"] == "FAILED"
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_pipeline_store.py -q`
Expected: FAIL — `persist_run() takes 4 positional arguments but 5 were given`

- [ ] **Step 4: Rewrite pipeline_store.py**

Replace the whole of `job_hunt/src/pipeline_store.py`:

```python
"""Bridge between the scrape pipeline and the store.

Kept separate from `main.py` so the persistence path is testable without
running a scrape.
"""
import sqlite3

from .store.ingest import upsert_jobs
from .store.runs import finish_run


def persist_run(conn: sqlite3.Connection, user_id: int, run_id: int,
                scored_jobs: list[dict], scraped: int) -> int:
    """Write a completed scrape into a run that already exists.

    The caller creates the run. A browser-triggered run needs its id returned
    to the page before any scraping starts, so creating it here would be too
    late; the terminal path calls `start_run` for the same reason.
    """
    try:
        upsert_jobs(conn, user_id, run_id, scored_jobs)
    except Exception:
        finish_run(conn, run_id, scraped=scraped, kept=0, ok=False)
        raise
    finish_run(conn, run_id, scraped=scraped, kept=len(scored_jobs))
    return run_id
```

- [ ] **Step 5: Update the terminal caller**

In `job_hunt/main.py`, replace `_persist_and_launch` (currently at lines
425-439) with:

```python
def _persist_and_launch(scored_jobs: list[dict], scraped: int,
                        shortlist_min: int, config: dict) -> None:
    """Write the run to the store. Rendering happens separately via _serve()."""
    from src.pipeline_store import persist_run
    from src.store.runs import start_run

    conn = None
    try:
        conn, user_id = _open_store()
        run_id = start_run(conn, user_id)
        persist_run(conn, user_id, run_id, scored_jobs, scraped)
        print(f"  Stored {len(scored_jobs)} roles.")
    except Exception as e:
        logger.warning("Persisting the run failed: %s", e)
    finally:
        if conn is not None:
            conn.close()
```

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: `442 passed`

- [ ] **Step 7: Commit**

```bash
git add src/pipeline_store.py main.py tests/test_pipeline_store.py
git commit -m "refactor: persist_run writes into a run the caller opened"
```

---

## Task 3: What the store already knows

**Files:**
- Modify: `job_hunt/src/store/queries.py`
- Test: `job_hunt/tests/test_store_queries_known.py`

The browser run has no workbook to dedupe against. This is where it gets the
same information from the store. Adds 4 tests.

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_store_queries_known.py`:

```python
"""Tests for queries.known_listings — the store's answer to 'what have I seen'."""
import pytest

from src.store.db import connect
from src.store.ingest import ensure_user, upsert_jobs
from src.store.queries import known_listings
from src.store.runs import start_run
from src.store.schema import init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "known.db")
    init_db(c)
    yield c
    c.close()


def _job(url, title="BI Developer", company="Acme"):
    return {"cat": title, "title": title, "company": company,
            "location": "Toronto, ON", "platform": "Indeed",
            "date": "2026-08-14", "url": url, "salary": "",
            "description": "Power BI", "match_score": 8,
            "band": "STRONG FIT", "reason": "r", "matched": [], "gaps": [],
            "resume_id": None, "description_captured": True}


def test_nothing_is_known_in_an_empty_store(conn):
    user_id = ensure_user(conn, "default")
    urls, rows = known_listings(conn, user_id)
    assert (urls, rows) == ([], [])


def test_a_stored_role_is_reported_by_url(conn):
    user_id = ensure_user(conn, "default")
    upsert_jobs(conn, user_id, start_run(conn, user_id),
                [_job("https://example.com/j1")])

    urls, _ = known_listings(conn, user_id)
    assert urls == ["https://example.com/j1"]


def test_company_and_title_come_back_for_fingerprinting(conn):
    """dedupe needs these to catch a repost whose URL changed."""
    user_id = ensure_user(conn, "default")
    upsert_jobs(conn, user_id, start_run(conn, user_id),
                [_job("https://example.com/j1", company="Acme")])

    _, rows = known_listings(conn, user_id)
    assert rows == [{"company": "Acme", "title": "BI Developer"}]


def test_another_users_roles_are_not_reported(conn):
    mine = ensure_user(conn, "default")
    theirs = ensure_user(conn, "someone else")
    upsert_jobs(conn, theirs, start_run(conn, theirs),
                [_job("https://example.com/theirs")])

    urls, rows = known_listings(conn, mine)
    assert (urls, rows) == ([], [])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_store_queries_known.py -q`
Expected: FAIL — `ImportError: cannot import name 'known_listings'`

- [ ] **Step 3: Add the query**

Append to `job_hunt/src/store/queries.py`:

```python
def known_listings(conn: sqlite3.Connection,
                   user_id: int) -> tuple[list[str], list[dict]]:
    """Every role this user has already stored, shaped for `dedupe`.

    The terminal run reads this from the Excel workbook. A browser run has no
    workbook, so the store answers instead: the URLs it has seen, and the
    company/title pairs `dedupe` fingerprints to catch a repost that came back
    under a new URL.
    """
    rows = conn.execute(
        """SELECT r.url, r.title, c.name AS company
             FROM role r
             JOIN company c ON c.id = r.company_id
            WHERE r.user_id = ?""", (user_id,)).fetchall()
    urls = [row["url"] for row in rows]
    pairs = [{"company": row["company"], "title": row["title"]} for row in rows]
    return urls, pairs
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_store_queries_known.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/store/queries.py tests/test_store_queries_known.py
git commit -m "feat: the store can say which listings it has already seen"
```

---

## Task 4: The step list

**Files:**
- Create: `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_run_core_steps.py`

The progress screen renders the whole plan from the first poll, so the steps
are computed before any scraping happens. Adds 7 tests.

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_run_core_steps.py`:

```python
"""Tests for run_core's search titles and step planning — both pure."""
from src.run_core import SOURCES, plan_steps, search_titles


def _resume(label, roles):
    return {"id": 1, "label": label,
            "target_roles": [{"title": t} for t in roles]}


def test_titles_come_from_the_resumes_target_roles():
    assert search_titles([_resume("bi", ["BI Developer"])]) == ["BI Developer"]


def test_titles_from_several_resumes_are_combined_in_order():
    resumes = [_resume("bi", ["BI Developer"]), _resume("de", ["Data Engineer"])]
    assert search_titles(resumes) == ["BI Developer", "Data Engineer"]


def test_the_same_title_twice_is_searched_once():
    resumes = [_resume("bi", ["BI Developer"]),
               _resume("other", ["bi developer", "Data Analyst"])]
    assert search_titles(resumes) == ["BI Developer", "Data Analyst"]


def test_a_resume_with_no_target_roles_contributes_nothing():
    assert search_titles([_resume("empty", [])]) == []


def test_every_title_is_planned_against_every_source():
    steps = plan_steps(["BI Developer", "Data Analyst"])

    assert len(steps) == len(SOURCES) * 2
    assert {s["source"] for s in steps} == {name for name, _, _ in SOURCES}


def test_steps_start_pending_with_nothing_found():
    steps = plan_steps(["BI Developer"])
    assert all(s["state"] == "pending" and s["found"] == 0 for s in steps)


def test_steps_are_grouped_by_role_so_the_screen_reads_in_order():
    """A reader follows one role across both sources, then the next role."""
    steps = plan_steps(["BI Developer", "Data Analyst"])
    assert [s["role"] for s in steps] == [
        "BI Developer", "BI Developer", "Data Analyst", "Data Analyst"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_run_core_steps.py -q`
Expected: collection error — `No module named 'src.run_core'`

- [ ] **Step 3: Create run_core with the pure half**

Create `job_hunt/src/run_core.py`:

```python
"""Scrape, dedupe, score, store — the part of a run the map depends on.

Callers differ in how they report progress and in what they do afterwards, so
this module does neither. It emits events through `on_progress` and returns
what it produced. Printing, writing progress into the run row, and the LLM and
Excel steps all belong to the caller.

Nothing here imports Flask or threading.
"""
import logging

logger = logging.getLogger(__name__)

# (display name, config key for the actor id, default actor id)
SOURCES = (
    ("Indeed",   "indeed_actor",   "valig~indeed-jobs-scraper"),
    ("LinkedIn", "linkedin_actor", "valig~linkedin-jobs-scraper"),
)


def search_titles(resumes: list[dict]) -> list[str]:
    """Every distinct target role across the active resumes, in order.

    Case-insensitive on the key so 'BI Developer' and 'bi developer' are one
    search, but the first spelling seen is the one that gets searched.
    """
    titles: list[str] = []
    seen: set[str] = set()
    for resume in resumes:
        for role in resume.get("target_roles") or []:
            title = (role.get("title") or "").strip()
            key = title.lower()
            if title and key not in seen:
                seen.add(key)
                titles.append(title)
    return titles


def plan_steps(titles: list[str]) -> list[dict]:
    """The whole scrape, listed before any of it runs.

    Grouped by role rather than by source so the progress screen reads down
    one role at a time, which is the order they actually run in.
    """
    return [{"source": name, "role": title, "state": "pending", "found": 0}
            for title in titles
            for name, _, _ in SOURCES]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_core_steps.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/run_core.py tests/test_run_core_steps.py
git commit -m "feat: plan every scrape step before the first one runs"
```

---

## Task 5: The core run

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_run_core_execute.py`

Adds 11 tests.

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_run_core_execute.py`:

```python
"""Tests for run_core.execute — the shared scrape-and-score path.

No network: scrapers are injected. The scorer is real, because what it writes
into the store is exactly what this is for.
"""
import pytest

from src.run_core import execute
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.queries import map_sections
from src.store.runs import get_run, start_run
from src.store.schema import init_db

_CONFIG = {
    "apify": {},
    "search": {"days_posted": 7, "jobs_per_category": 50, "run_timeout": 120},
    "scoring": {"bands": {"strong": 8, "partial": 5}},
}

_RESUME = {
    "id": 1, "label": "bi",
    "target_roles": [{"title": "BI Developer", "aliases": []}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": []}],
    "seniority": "senior", "extracted_text": "Power BI",
}

_PROFILE = {"location": "Toronto, ON", "country": "ca",
            "work_modes": ["remote"], "setup_complete": 1}


def _job(url, title="BI Developer", company="Acme"):
    return {"cat": title, "title": title, "company": company,
            "location": "Toronto, ON", "platform": "Indeed",
            "date": "2026-08-14", "url": url, "salary": "",
            "description": "We need Power BI and SQL."}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def user(conn):
    return ensure_user(conn, "default")


def _scrapers(indeed_jobs=None, linkedin_jobs=None, fail=()):
    """Fake scrapers. `fail` names sources that raise instead of returning."""
    def make(name, jobs):
        def scrape(category, title, actor_id, *args, **kwargs):
            if name in fail:
                raise RuntimeError(f"{name} actor timed out")
            return list(jobs or [])
        return scrape
    return {"Indeed": make("Indeed", indeed_jobs),
            "LinkedIn": make("LinkedIn", linkedin_jobs)}


def test_scraped_jobs_are_scored_and_stored(conn, user):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [_RESUME], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    assert result.kept == 1
    sections = map_sections(conn, user, 7)
    assert sections["new"], "the stored role should appear on the map"


def test_the_run_finishes_ok(conn, user):
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [_RESUME], _PROFILE,
            scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    assert get_run(conn, run_id)["status"] == "OK"


def test_progress_is_emitted_for_every_step(conn, user):
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [_RESUME], _PROFILE,
            on_progress=seen.append,
            scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    stages = [event["stage"] for event in seen]
    assert stages[0] == "scraping"
    assert "scoring" in stages and "storing" in stages


def test_the_first_event_already_lists_every_step(conn, user):
    """The screen renders the whole plan from poll one."""
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [_RESUME], _PROFILE,
            on_progress=seen.append, scrapers=_scrapers())

    assert len(seen[0]["steps"]) == 2      # one role, two sources


def test_one_source_failing_does_not_lose_the_other(conn, user):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [_RESUME], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/1")],
                                        fail=("LinkedIn",)))

    assert result.kept == 1
    assert get_run(conn, run_id)["status"] == "OK"


def test_a_failed_source_is_marked_on_its_step(conn, user):
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [_RESUME], _PROFILE,
            on_progress=seen.append,
            scrapers=_scrapers(indeed_jobs=[_job("https://x/1")],
                               fail=("LinkedIn",)))

    final = seen[-1]["steps"]
    states = {step["source"]: step["state"] for step in final}
    assert states == {"Indeed": "done", "LinkedIn": "failed"}


def test_finding_nothing_is_a_successful_run(conn, user):
    """An empty search is an answer, not a failure."""
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [_RESUME], _PROFILE,
                     scrapers=_scrapers())

    assert result.kept == 0
    assert get_run(conn, run_id)["status"] == "OK"


def test_a_listing_already_in_the_store_is_not_stored_twice(conn, user):
    first = start_run(conn, user)
    execute(conn, user, first, _CONFIG, [_RESUME], _PROFILE,
            scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    second = start_run(conn, user)
    result = execute(conn, user, second, _CONFIG, [_RESUME], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    assert result.kept == 0


def test_duplicates_within_one_scrape_collapse(conn, user):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [_RESUME], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/1")],
                                        linkedin_jobs=[_job("https://x/1")]))

    assert result.scraped == 2
    assert result.kept == 1


def test_the_enrich_hook_sees_the_new_jobs(conn, user):
    """The terminal path uses this for company enrichment."""
    handed = {}

    def enrich(jobs):
        handed["count"] = len(jobs)
        return jobs

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [_RESUME], _PROFILE, enrich=enrich,
            scrapers=_scrapers(indeed_jobs=[_job("https://x/1")]))

    assert handed["count"] == 1


def test_a_run_with_no_resumes_refuses_rather_than_scraping(conn, user):
    run_id = start_run(conn, user)
    with pytest.raises(ValueError, match="resume"):
        execute(conn, user, run_id, _CONFIG, [], _PROFILE,
                scrapers=_scrapers())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_run_core_execute.py -q`
Expected: FAIL — `ImportError: cannot import name 'execute'`

- [ ] **Step 3: Add execute to run_core.py**

Append to `job_hunt/src/run_core.py`:

```python
from dataclasses import dataclass, field
from pathlib import Path

VOCABULARY_PATH = Path(__file__).resolve().parent.parent / "vocabulary.yaml"


@dataclass
class RunResult:
    """What a run produced, for whatever the caller does next."""
    scraped: int = 0
    kept: int = 0
    scored_jobs: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)


def _default_scrapers() -> dict:
    from .scrapers import indeed, linkedin
    return {"Indeed": indeed.scrape, "LinkedIn": linkedin.scrape}


def execute(conn, user_id: int, run_id: int, config: dict,
            resumes: list[dict], profile: dict,
            on_progress=None, scrapers=None, enrich=None) -> RunResult:
    """Scrape, dedupe, score and store one run.

    Args:
        run_id:      an already-open RUNNING run. This never creates one.
        on_progress: called with the whole progress payload after each step.
        scrapers:    {source name: scrape callable}. Injected by tests.
        enrich:      optional hook handed the deduped jobs before scoring,
                     returning the jobs to score. The terminal path uses it
                     for company enrichment; the browser run passes nothing.

    Raises:
        ValueError: when there is no active resume, or none of them name a
            target role. There is nothing to search for, and failing here is
            clearer than a run that scrapes nothing and looks broken.
    """
    from .pipeline_store import persist_run
    from .scoring.scorer import Scorer
    from .store.queries import known_listings
    from .tracker.dedup import dedupe

    if not resumes:
        raise ValueError("no active resume on file, so there is nothing to "
                         "search for")
    titles = search_titles(resumes)
    if not titles:
        raise ValueError("your resumes name no target roles between them")

    emit = on_progress or (lambda event: None)
    scrapers = scrapers or _default_scrapers()

    apify_cfg    = config.get("apify", {})
    search_cfg   = config.get("search", {})
    days_posted  = search_cfg.get("days_posted", 7)
    jobs_per_cat = search_cfg.get("jobs_per_category", 50)
    run_timeout  = search_cfg.get("run_timeout", 120)

    location   = profile.get("location") or ""
    country    = profile.get("country") or "us"
    work_modes = profile.get("work_modes") or ["remote"]

    steps = plan_steps(titles)
    scraped_total = 0

    def report(stage: str) -> None:
        emit({"stage": stage, "steps": steps, "scraped": scraped_total})

    # Announce the whole plan before doing any of it.
    report("scraping")

    all_scraped: list[dict] = []
    for step in steps:
        step["state"] = "running"
        report("scraping")

        name = step["source"]
        actor_key, actor_default = next(
            (key, default) for source, key, default in SOURCES
            if source == name)
        try:
            jobs = scrapers[name](
                step["role"], step["role"],
                apify_cfg.get(actor_key, actor_default),
                days_posted, jobs_per_cat, run_timeout,
                location=location, country=country, work_modes=work_modes)
        except Exception as exc:
            # One source failing must not throw away the other's results.
            logger.warning("%s/%s failed: %s", name, step["role"], exc)
            step["state"] = "failed"
            step["found"] = 0
        else:
            step["state"] = "done"
            step["found"] = len(jobs)
            all_scraped.extend(jobs)
            scraped_total += len(jobs)
        report("scraping")

    known_urls, known_rows = known_listings(conn, user_id)
    new_jobs = dedupe(all_scraped,
                      existing_urls=known_urls, existing_rows=known_rows)

    if enrich is not None:
        new_jobs = enrich(new_jobs)

    report("scoring")
    scorer = Scorer(config, VOCABULARY_PATH)
    scored_jobs = [
        {**job, **scorer.best_match(job["title"], job.get("description", ""),
                                    resumes)}
        for job in new_jobs
    ]

    report("storing")
    persist_run(conn, user_id, run_id, scored_jobs, scraped_total)

    return RunResult(scraped=scraped_total, kept=len(scored_jobs),
                     scored_jobs=scored_jobs, steps=steps, titles=titles)
```

Move the `from dataclasses import ...` and `from pathlib import Path` lines up
to join the existing imports at the top of the file rather than leaving them
mid-module.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_core_execute.py -q`
Expected: `11 passed`

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: `464 passed`

- [ ] **Step 6: Commit**

```bash
git add src/run_core.py tests/test_run_core_execute.py
git commit -m "feat: one scrape-and-score path both callers share"
```

---

## Task 6: The terminal runs on the core

**Files:**
- Modify: `job_hunt/main.py:120-421` (`run_pipeline`)
- Test: `job_hunt/tests/test_pipeline_titles.py` (existing — update the import)

No behaviour change is intended here. The live smoke test in Task 14 is what
proves it. Adds 0 tests.

- [ ] **Step 1: Move search_titles out of main.py**

`main.py` has its own `_search_titles`. `run_core.search_titles` is the same
function and is now the shared one. Delete `_search_titles` from `main.py` and
add to the imports inside `run_pipeline`:

```python
    from src.run_core import execute as run_core_execute, search_titles
```

Update `job_hunt/tests/test_pipeline_titles.py` to import from the new home —
change:

```python
from main import _search_titles
```

to:

```python
from src.run_core import search_titles as _search_titles
```

- [ ] **Step 2: Replace steps 2 through 6 of run_pipeline**

In `job_hunt/main.py`, replace everything from the `# ── 2. Read existing
tracker ───` comment through the `rows.sort(...)` line (currently lines
181-335) with:

```python
    # ── 2. Read existing tracker ───────────────────────────────────────────
    print("\n[2/8] Reading existing tracker...")
    existing = excel.read_existing(tracker_path)
    print(f"  Loaded {len(existing)} existing jobs.")

    # ── 3. Scrape ──────────────────────────────────────────────────────────
    if not os.environ.get("APIFY_TOKEN"):
        print("\n  ERROR: APIFY_TOKEN not set.")
        print("  PowerShell:  $env:APIFY_TOKEN = 'apify_api_xxx'")
        sys.exit(1)

    print(f"\n[3/8] Scraping Indeed + LinkedIn (last {days_posted} days)...")

    # Company enrichment is disabled by default; when it is on it runs between
    # dedupe and scoring, which is what run_core's enrich hook is for.
    def _enrich(new_jobs: list[dict]) -> list[dict]:
        print("\n[4/8] Deduplicating...")
        print(f"  {len(new_jobs)} new jobs")
        print("\n[5/8] Company enrichment: disabled "
              "(set company_enrichment.enabled: true in config.yaml "
              "to activate)")
        _passthrough = {"headcount_range": "", "stage": "", "growth_score": "",
                        "source": ""}
        for job in new_jobs:
            job["_intel"] = _passthrough
            job["_filter"] = {"verdict": "PASS", "reason": "", "warn": None}
        print(f"\n[6/8] Scoring {len(new_jobs)} jobs against "
              f"{len(resumes)} resume(s)...")
        return new_jobs

    def _announce(event: dict) -> None:
        """Print each scrape step as it finishes, as this always has."""
        for step in event["steps"]:
            if step.get("state") == "done" and not step.get("_printed"):
                step["_printed"] = True
                print(f"  {step['source']} / {step['role']}...")
                print(f"    -> {step['found']} fetched")
            elif step.get("state") == "failed" and not step.get("_printed"):
                step["_printed"] = True
                print(f"  {step['source']} / {step['role']}... FAILED")

    conn, user_id = _open_store()
    try:
        run_id = start_run(conn, user_id)
        try:
            result = run_core_execute(
                conn, user_id, run_id, config, resumes, profile,
                on_progress=_announce, enrich=_enrich)
        except Exception as exc:
            fail_run(conn, run_id, str(exc))
            raise
    finally:
        conn.close()

    print(f"\n  Total scraped: {result.scraped}")
    filtered_out_count = 0

    # ── Build the tracker rows from what the core scored ───────────────────
    cat_order = {title: i for i, title in enumerate(result.titles)}
    by_resume = {r["id"]: r for r in resumes}
    rows: list[dict] = []
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    for job in result.scored_jobs:
        intel  = job.get("_intel", {})
        filt_r = job.get("_filter", {"verdict": "PASS", "reason": "",
                                     "warn": None})
        is_filtered = filt_r["verdict"] == "REJECT"

        row: dict = {
            # Columns 1-15 — same positions as original job_tracker_updater.py
            "Search Category":    job["cat"],
            "Job Title":          job["title"],
            "Company":            job["company"],
            "Location":           job["location"],
            "Platform":           job["platform"],
            "Posting Date":       job["date"],
            "Apply Link":         job["url"],
            "Match Score":        job["match_score"],
            # Removed — was a hardcoded lookup table shown as a percentage.
            # Column kept blank so existing tracker files stay aligned.
            "Interview Chance":   "",
            "Recommended Resume": job["resume_label"],
            "Tailoring Needed":   job["tailoring"],
            "Application Status": "Filtered Out" if is_filtered else "New",
            "Date Applied":       "",
            "Follow-up Date":     "",
            "Notes":              filt_r.get("warn", "") or "",
            # Columns 16+ — new fields
            "Salary":             job.get("salary", ""),
            "Apply_Now":          "",
            "LLM_Reason":         filt_r.get("reason", "") if is_filtered else "",
            "Risk_Flags":         "",
            "Company Size":       intel.get("headcount_range", ""),
            "Company Stage":      intel.get("stage", ""),
            "Growth Score":       intel.get("growth_score", ""),
            "Intel Source":       intel.get("source", ""),
            "Loaded At":          run_ts,
            # Internal — not written to Excel
            "_score":             job["match_score"],
            "_description":       job.get("description", ""),
            "_cat_order":         cat_order.get(job["cat"], 9),
            "_resume_id":         job["resume_id"],
            "Low Growth Signal":  bool(filt_r.get("warn")),
        }
        rows.append(row)

    rows.sort(key=lambda r: (r["_cat_order"], -r["_score"]))
```

- [ ] **Step 3: Add the new imports**

At the top of `run_pipeline`, alongside the other local imports, add:

```python
    from src.store.runs import fail_run, start_run
```

- [ ] **Step 4: Delete the now-duplicated persist call**

At the end of `run_pipeline`, `_persist_and_launch(...)` is now redundant —
`run_core.execute` already persisted through `persist_run`. Delete this line:

```python
    _persist_and_launch(scored_jobs, len(all_scraped), shortlist_min, config)
```

and replace it with:

```python
    print(f"  Stored {result.kept} roles.")
```

Then delete the whole `_persist_and_launch` function (and its `# ──
Opportunity map helper ──` banner comment), which now has no callers.

- [ ] **Step 5: Verify main.py still imports and the suite is green**

Run: `python -c "import main; print('ok')"`
Expected: `ok`

Run: `python -m pytest tests/ -q`
Expected: `464 passed`

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_pipeline_titles.py
git commit -m "refactor: the terminal pipeline runs on the shared core"
```

---

## Task 7: The background worker

**Files:**
- Create: `job_hunt/src/run_worker.py`
- Test: `job_hunt/tests/test_run_worker.py`

Adds 7 tests.

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_run_worker.py`:

```python
"""Tests for src/run_worker.py.

The runner is injected so every test drives the work synchronously. Threading
is one thin wrapper and is tested only for the property that matters: that it
returns before the work is done.
"""
import threading

import pytest

from src.run_worker import run_in_background, work
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.runs import get_run, start_run
from src.store.schema import init_db


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "worker.db"
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "default")
    conn.close()
    return path


@pytest.fixture
def user_and_run(db):
    conn = connect(db)
    user_id = ensure_user(conn, "default")
    run_id = start_run(conn, user_id)
    conn.close()
    return user_id, run_id


def _read(db, run_id):
    conn = connect(db)
    try:
        return get_run(conn, run_id)
    finally:
        conn.close()


def test_a_successful_runner_leaves_the_run_alone(db, user_and_run):
    """execute() finishes the run itself; the worker must not overwrite that."""
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=3, kept=2)

    work(db, user_id, run_id, runner)

    stored = _read(db, run_id)
    assert stored["status"] == "OK"
    assert (stored["scraped"], stored["kept"]) == (3, 2)


def test_progress_from_the_runner_reaches_the_row(db, user_and_run):
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        on_progress({"stage": "scraping", "steps": [], "scraped": 7})
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=7, kept=0)

    work(db, user_id, run_id, runner)

    stored = _read(db, run_id)
    assert stored["stage"] == "scraping"
    assert stored["progress"]["scraped"] == 7


def test_a_raising_runner_marks_the_run_failed(db, user_and_run):
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        raise RuntimeError("actor rejected the input")

    work(db, user_id, run_id, runner)

    stored = _read(db, run_id)
    assert stored["status"] == "FAILED"
    assert "actor rejected the input" in stored["error"]


def test_a_raising_runner_never_leaves_the_run_running(db, user_and_run):
    """This is the lockout: a RUNNING row blocks every future run."""
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        raise RuntimeError("boom")

    work(db, user_id, run_id, runner)
    assert _read(db, run_id)["status"] != "RUNNING"


def test_the_worker_opens_its_own_connection(db, user_and_run):
    """Connections are not shareable across threads."""
    user_id, run_id = user_and_run
    handed = {}

    def runner(conn, user_id_, run_id_, on_progress):
        handed["conn"] = conn
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=0, kept=0)

    work(db, user_id, run_id, runner)
    assert handed["conn"] is not None


def test_run_in_background_returns_before_the_work_finishes(db, user_and_run):
    user_id, run_id = user_and_run
    released = threading.Event()
    started = threading.Event()

    def runner(conn, user_id_, run_id_, on_progress):
        started.set()
        released.wait(timeout=5)
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=0, kept=0)

    thread = run_in_background(db, user_id, run_id, runner)
    assert started.wait(timeout=5), "the worker should have started"
    assert _read(db, run_id)["status"] == "RUNNING"

    released.set()
    thread.join(timeout=5)
    assert _read(db, run_id)["status"] == "OK"


def test_the_background_thread_does_not_hold_the_process_open(db, user_and_run):
    user_id, run_id = user_and_run

    def runner(conn, user_id_, run_id_, on_progress):
        from src.store.runs import finish_run
        finish_run(conn, run_id_, scraped=0, kept=0)

    thread = run_in_background(db, user_id, run_id, runner)
    assert thread.daemon is True
    thread.join(timeout=5)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_run_worker.py -q`
Expected: collection error — `No module named 'src.run_worker'`

- [ ] **Step 3: Create the worker**

Create `job_hunt/src/run_worker.py`:

```python
"""Running a scrape off the request thread.

The whole of threading in this feature is here, and it is deliberately thin:
open a connection, call the runner, make sure the run row ends in a terminal
state whatever happens.
"""
import logging
import threading
from pathlib import Path

from .store.db import connect
from .store.runs import fail_run, get_run, set_progress

logger = logging.getLogger(__name__)


def default_runner(conn, user_id: int, run_id: int, on_progress):
    """Load config and hand off to run_core. Replaced wholesale in tests."""
    import yaml

    from .run_core import execute
    from .store.profile import get_profile, list_resumes

    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    resumes = list_resumes(conn, user_id, active_only=True)
    profile = get_profile(conn, user_id)
    execute(conn, user_id, run_id, config, resumes, profile,
            on_progress=on_progress)


def work(db_path: Path | str, user_id: int, run_id: int, runner=None) -> None:
    """Run one scrape to completion on the calling thread.

    Opens its own connection: SQLite connections cannot be shared across
    threads, and this is the single most likely place in the feature to
    introduce a defect. WAL and busy_timeout, already set in db.py, cover this
    writer against the poll endpoint's reads.
    """
    runner = runner or default_runner
    conn = connect(db_path)
    try:
        def on_progress(event: dict) -> None:
            set_progress(conn, run_id, event.get("stage", ""), event)

        runner(conn, user_id, run_id, on_progress)
    except Exception as exc:
        # A crashed worker must never leave the run RUNNING — that row blocks
        # every future run until the app restarts.
        logger.exception("Run %s failed", run_id)
        try:
            fail_run(conn, run_id, str(exc))
        except Exception:
            logger.exception("Could not even record the failure of run %s",
                             run_id)
    else:
        # The runner is expected to finish the run. If it returned without
        # doing so, fail it rather than leave it hanging.
        stored = get_run(conn, run_id)
        if stored and stored["status"] == "RUNNING":
            fail_run(conn, run_id, "the run ended without reporting a result")
    finally:
        conn.close()


def run_in_background(db_path: Path | str, user_id: int, run_id: int,
                      runner=None) -> threading.Thread:
    """Start `work` on a daemon thread and return immediately."""
    thread = threading.Thread(
        target=work, args=(db_path, user_id, run_id, runner),
        name=f"run-{run_id}", daemon=True)
    thread.start()
    return thread
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_worker.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/run_worker.py tests/test_run_worker.py
git commit -m "feat: run a scrape off the request thread"
```

---

## Task 8: Starting and polling a run

**Files:**
- Modify: `job_hunt/src/app.py`
- Test: `job_hunt/tests/test_run_routes.py`

Adds 12 tests.

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_run_routes.py`:

```python
"""Tests for POST /api/runs and GET /api/runs/<id>.

The runner is injected through create_app so no test scrapes anything.
"""
import json

import pytest

from src.app import create_app
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.profile import create_resume, set_profile, update_resume
from src.store.runs import finish_run, get_run, start_run
from src.store.schema import init_db


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "runs.db"
    conn = connect(path)
    init_db(conn)
    user_id = ensure_user(conn, "default")
    resume_id = create_resume(conn, user_id, label="bi",
                              orig_filename="bi.pdf", sha256="abc",
                              stored_path="resumes/1/abc.pdf",
                              extracted_text="Power BI")
    update_resume(conn, user_id, resume_id, label="bi",
                  target_roles=[{"title": "BI Developer", "aliases": []}],
                  skills=[{"name": "Power BI", "tier": "core", "aliases": []}],
                  seniority="senior")
    set_profile(conn, user_id, location="Toronto, ON", country="ca",
                work_modes=["remote"])
    conn.close()
    return path


def _client(db, tmp_path, runner=None, token="apify_test"):
    app = create_app(db_path=db, user_name="default",
                     data_root=tmp_path / "data",
                     runner=runner or (lambda *a, **k: None),
                     run_in_thread=False)
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    return _client(db, tmp_path)


def _user_id(db):
    conn = connect(db)
    try:
        return ensure_user(conn, "default")
    finally:
        conn.close()


def test_starting_a_run_returns_its_id(client):
    response = client.post("/api/runs")
    assert response.status_code == 201
    assert isinstance(response.get_json()["run_id"], int)


def test_the_run_row_exists_before_the_response_returns(client, db):
    run_id = client.post("/api/runs").get_json()["run_id"]
    conn = connect(db)
    try:
        assert get_run(conn, run_id) is not None
    finally:
        conn.close()


def test_a_second_run_while_one_is_going_is_refused(client):
    client.post("/api/runs")
    response = client.post("/api/runs")

    assert response.status_code == 409
    assert "already" in response.get_json()["error"].lower()


def test_a_run_can_start_once_the_previous_one_finished(client, db):
    run_id = client.post("/api/runs").get_json()["run_id"]
    conn = connect(db)
    try:
        finish_run(conn, run_id, scraped=1, kept=1)
    finally:
        conn.close()

    assert client.post("/api/runs").status_code == 201


def test_an_abandoned_run_is_superseded_rather_than_blocking(client, db):
    """A worker killed without marking FAILED must not lock the user out."""
    stale = client.post("/api/runs").get_json()["run_id"]
    conn = connect(db)
    try:
        conn.execute("UPDATE run SET started_at = '2020-01-01T00:00:00+00:00'"
                     " WHERE id = ?", (stale,))
    finally:
        conn.close()

    response = client.post("/api/runs")
    assert response.status_code == 201

    conn = connect(db)
    try:
        assert get_run(conn, stale)["status"] == "FAILED"
    finally:
        conn.close()


def test_starting_a_run_without_a_resume_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    path = tmp_path / "empty.db"
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "default")
    conn.close()

    response = _client(path, tmp_path).post("/api/runs")
    assert response.status_code == 400
    assert "resume" in response.get_json()["error"].lower()


def test_a_refused_run_leaves_no_row_behind(tmp_path, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_test")
    path = tmp_path / "empty.db"
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "default")
    conn.close()

    _client(path, tmp_path).post("/api/runs")

    conn = connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM run").fetchone()["n"] == 0
    finally:
        conn.close()


def test_starting_a_run_without_an_apify_token_is_refused(db, tmp_path,
                                                          monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    response = _client(db, tmp_path).post("/api/runs")

    assert response.status_code == 400
    assert "APIFY_TOKEN" in response.get_json()["error"]


def test_polling_reports_status_stage_and_progress(client, db):
    run_id = client.post("/api/runs").get_json()["run_id"]
    conn = connect(db)
    try:
        from src.store.runs import set_progress
        set_progress(conn, run_id, "scraping",
                     {"stage": "scraping", "steps": [], "scraped": 12})
    finally:
        conn.close()

    body = client.get(f"/api/runs/{run_id}").get_json()
    assert body["status"] == "RUNNING"
    assert body["stage"] == "scraping"
    assert body["progress"]["scraped"] == 12


def test_polling_an_unknown_run_is_a_404(client):
    assert client.get("/api/runs/9999").status_code == 404


def test_polling_reports_the_error_of_a_failed_run(client, db):
    run_id = client.post("/api/runs").get_json()["run_id"]
    conn = connect(db)
    try:
        from src.store.runs import fail_run
        fail_run(conn, run_id, "Apify returned 401")
    finally:
        conn.close()

    body = client.get(f"/api/runs/{run_id}").get_json()
    assert body["status"] == "FAILED"
    assert body["error"] == "Apify returned 401"


def test_no_score_or_percentage_leaks_from_the_poll_endpoint(client, db):
    run_id = client.post("/api/runs").get_json()["run_id"]
    body = json.dumps(client.get(f"/api/runs/{run_id}").get_json())

    assert "match_score" not in body
    assert "%" not in body
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_run_routes.py -q`
Expected: FAIL — `create_app() got an unexpected keyword argument 'runner'`

- [ ] **Step 3: Extend create_app's signature**

In `job_hunt/src/app.py`, change the `create_app` definition:

```python
def create_app(db_path: Path | str = DEFAULT_PATH,
               user_name: str = "default",
               shortlist_min: int = 7,
               data_root: Path | str = DEFAULT_DATA_ROOT,
               llm_factory=None,
               runner=None,
               run_in_thread: bool = True) -> Flask:
```

and add just below `build_llm = llm_factory or _default_llm`:

```python
    # Injected so tests drive a run synchronously instead of chasing a thread.
    run_runner = runner
```

- [ ] **Step 4: Add the imports**

In `job_hunt/src/app.py`, add to the import block:

```python
import os

from .run_worker import run_in_background, work
from .store.runs import active_run, get_run, is_stale, latest_ok_run
```

The route below inlines its `INSERT` rather than calling `start_run`, because
the check and the insert have to share one transaction. That is why
`start_run` is not imported here.

- [ ] **Step 5: Add the two routes**

Insert into `create_app`, after the `/api/profile` route and before
`@app.get("/profile")`:

```python
    @app.post("/api/runs")
    def start_scrape():
        conn = _conn()
        try:
            user_id = _user(conn)

            # Refuse before creating a row. A run that exists only to fail two
            # seconds later is worse than a clear message now.
            resumes = list_resumes(conn, user_id, active_only=True)
            if not resumes:
                return jsonify({"error": "Upload a resume before searching."}), 400
            if not search_titles(resumes):
                return jsonify({"error": "Your resumes name no target roles. "
                                         "Add one on the profile screen."}), 400
            if not os.environ.get("APIFY_TOKEN"):
                return jsonify({"error": "APIFY_TOKEN is not set, so no "
                                         "search can run."}), 400

            # Check and insert together: transaction() uses BEGIN IMMEDIATE,
            # so two rapid posts cannot both find no RUNNING run.
            with transaction(conn):
                existing = active_run(conn, user_id)
                if existing and not is_stale(existing["started_at"]):
                    return jsonify(
                        {"error": "A search is already running.",
                         "run_id": existing["id"]}), 409
                if existing:
                    conn.execute(
                        "UPDATE run SET status = 'FAILED', error = ?"
                        " WHERE id = ?",
                        ("abandoned — superseded by a new search",
                         existing["id"]))
                conn.execute(
                    "INSERT INTO run (user_id, started_at, status)"
                    " VALUES (?, ?, 'RUNNING')", (user_id, _utc_now()))
            run_id = conn.execute(
                "SELECT last_insert_rowid() AS i").fetchone()["i"]
        finally:
            conn.close()

        if run_in_thread:
            run_in_background(db_path, user_id, run_id, run_runner)
        else:
            work(db_path, user_id, run_id, run_runner)
        return jsonify({"run_id": run_id}), 201

    @app.get("/api/runs/<int:run_id>")
    def poll_scrape(run_id: int):
        conn = _conn()
        try:
            stored = get_run(conn, run_id)
            if stored is None:
                return jsonify({"error": "not found"}), 404
            return jsonify({"status": stored["status"],
                            "stage": stored["stage"],
                            "progress": stored["progress"],
                            "error": stored["error"]})
        finally:
            conn.close()
```

- [ ] **Step 6: Add the two helpers the routes use**

At the top of `job_hunt/src/app.py`, add these imports:

```python
from datetime import datetime, timezone

from .run_core import search_titles
from .store.db import DEFAULT_PATH, connect, transaction
```

and this helper beside `_default_llm`:

```python
def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_routes.py -q`
Expected: `12 passed`

- [ ] **Step 8: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: `483 passed`

- [ ] **Step 9: Commit**

```bash
git add src/app.py tests/test_run_routes.py
git commit -m "feat: start a scrape from the browser and poll it"
```

---

## Task 9: Recovering runs the process abandoned

**Files:**
- Modify: `job_hunt/src/app.py` (`create_app`)
- Test: `job_hunt/tests/test_run_recovery.py`

Adds 4 tests.

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_run_recovery.py`:

```python
"""Boot recovery for runs a dead process left RUNNING."""
import pytest

from src.app import create_app
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.runs import get_run, start_run
from src.store.schema import init_db


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "recovery.db"
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "default")
    conn.close()
    return path


def _orphan(db):
    conn = connect(db)
    try:
        return start_run(conn, ensure_user(conn, "default"))
    finally:
        conn.close()


def _read(db, run_id):
    conn = connect(db)
    try:
        return get_run(conn, run_id)
    finally:
        conn.close()


def test_creating_the_app_clears_a_run_left_running(db, tmp_path):
    orphan = _orphan(db)
    create_app(db_path=db, user_name="default", data_root=tmp_path / "data")

    assert _read(db, orphan)["status"] == "FAILED"


def test_the_cleared_run_says_why(db, tmp_path):
    orphan = _orphan(db)
    create_app(db_path=db, user_name="default", data_root=tmp_path / "data")

    assert "interrupted" in _read(db, orphan)["error"].lower()


def test_a_finished_run_is_untouched_at_boot(db, tmp_path):
    from src.store.runs import finish_run

    done = _orphan(db)
    conn = connect(db)
    try:
        finish_run(conn, done, scraped=5, kept=3)
    finally:
        conn.close()

    create_app(db_path=db, user_name="default", data_root=tmp_path / "data")
    assert _read(db, done)["status"] == "OK"


def test_an_ordinary_request_does_not_kill_a_live_run(db, tmp_path):
    """Recovery belongs to boot. _conn() runs init_db on every request, so
    putting this there would fail the run currently in flight."""
    app = create_app(db_path=db, user_name="default",
                     data_root=tmp_path / "data")
    app.config.update(TESTING=True)
    client = app.test_client()

    live = _orphan(db)                 # starts after boot, so it is real
    client.get("/")

    assert _read(db, live)["status"] == "RUNNING"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_run_recovery.py -q`
Expected: FAIL — the orphan is still `RUNNING`

- [ ] **Step 3: Clear orphans once, at boot**

In `job_hunt/src/app.py`, add near the end of `create_app`, immediately before
the final `return app`:

```python
    # Any RUNNING run belongs to a process that is no longer here — at boot
    # none of ours are alive yet. Without this one hard kill locks the user
    # out of ever starting another run, because POST /api/runs sees a RUNNING
    # row and refuses.
    #
    # This must stay in create_app, which runs once. init_db() is called by
    # _conn() on every single request; recovering there would mark the run
    # currently in flight as failed.
    _boot_conn = connect(db_path)
    try:
        init_db(_boot_conn)
        cleared = clear_running(_boot_conn,
                                "interrupted — the app restarted mid-run")
        if cleared:
            logger.info("Cleared %s run(s) left running by a previous process",
                        cleared)
    finally:
        _boot_conn.close()
```

Add `clear_running` to the `from .store.runs import ...` line.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_recovery.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/app.py tests/test_run_recovery.py
git commit -m "feat: recover runs a dead process left running"
```

---

## Task 10: The progress screen

**Files:**
- Create: `job_hunt/src/searching_page.py`
- Test: `job_hunt/tests/test_searching_page.py`

Follow the paper language already in `src/map_page.py` — read its `_CSS` and
copy the tokens rather than inventing new ones. Adds 8 tests.

- [ ] **Step 1: Read the existing design language**

Run: `sed -n '1,120p' src/map_page.py`

Note the colour tokens and fonts. `DESIGN.md` is the authority: background
`#0A0E1A`, surface `#0D1117`, border `#1E2A3A`, cyan `#00D4FF`, green
`#00D9A3`, amber `#F59E0B`, red `#E05C5C`, JetBrains Mono for data and labels,
Inter for prose, dark only.

- [ ] **Step 2: Write the failing tests**

Create `job_hunt/tests/test_searching_page.py`:

```python
"""Tests for the progress screen's markup."""
import re

from src.searching_page import render


def _visible(html: str) -> str:
    html = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


def test_the_run_id_is_embedded_for_polling():
    assert "42" in render(42)


def test_it_polls_the_run_endpoint():
    assert "/api/runs/42" in render(42)


def test_it_polls_every_two_seconds():
    assert "2000" in render(42)


def test_it_sends_the_reader_to_the_map_when_the_run_is_ok():
    html = render(42)
    assert "OK" in html and "'/'" in html


def test_a_failed_run_offers_a_retry():
    assert "retry" in render(42).lower()


def test_it_warns_when_progress_stops_changing():
    """A worker killed with the tab open would otherwise spin forever."""
    assert "may have stopped" in render(42).lower()


def test_no_score_or_percentage_appears():
    html = render(42)
    assert "match_score" not in html
    assert "%" not in _visible(html)


def test_the_page_uses_the_project_palette():
    assert "#0A0E1A" in render(42)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_searching_page.py -q`
Expected: collection error — `No module named 'src.searching_page'`

- [ ] **Step 4: Create the screen**

Create `job_hunt/src/searching_page.py`:

```python
"""The progress screen.

Renders every planned step from the first poll so the reader sees the whole
shape of the run immediately, rather than a list that grows.

Counts shown are only ones the run has actually produced. While scraping, the
total is unknown, so no denominator is displayed — inventing one would be the
fabricated-precision pattern this project bans.
"""

_POLL_MS = 2000

# Progress unchanged for this long means nothing is watching the worker any
# more. Detected in the page rather than the database: it costs no schema
# change, and the only reader who cares is the one looking at the screen.
_STALL_MS = 180_000

_CSS = """
:root{--bg:#0A0E1A;--surface:#0D1117;--border:#1E2A3A;--cyan:#00D4FF;
--green:#00D9A3;--amber:#F59E0B;--red:#E05C5C;--dim:#7A8899;--text:#E6EDF3}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font-family:Inter,system-ui,sans-serif;padding:48px 24px}
.wrap{max-width:640px;margin:0 auto}
h1{font-size:20px;font-weight:600;margin:0 0 4px}
.sub{color:var(--dim);font-size:14px;margin:0 0 32px}
.steps{border:1px solid var(--border);border-radius:8px;
background:var(--surface);overflow:hidden}
.step{display:flex;align-items:center;gap:12px;padding:12px 16px;
border-bottom:1px solid var(--border);
font-family:'JetBrains Mono',ui-monospace,monospace;font-size:13px}
.step:last-child{border-bottom:none}
.dot{width:8px;height:8px;border-radius:50%;background:var(--border);
flex:none}
.step[data-state=running] .dot{background:var(--cyan)}
.step[data-state=done] .dot{background:var(--green)}
.step[data-state=failed] .dot{background:var(--red)}
.name{flex:1}
.found{color:var(--dim)}
.step[data-state=failed] .found{color:var(--red)}
.note{margin-top:24px;font-size:14px;color:var(--dim);min-height:20px}
.note.bad{color:var(--amber)}
a.retry{color:var(--cyan);text-decoration:none;border-bottom:1px solid
var(--cyan)}
"""

_HTML = """<!doctype html>
<meta charset="utf-8">
<title>Searching</title>
<style>{css}</style>
<div class="wrap">
  <h1>searching</h1>
  <p class="sub">Reading Indeed and LinkedIn for the roles on your resumes.</p>
  <div class="steps" id="steps"></div>
  <p class="note" id="note"></p>
</div>
<script>
const RUN = {run_id};
const POLL = {poll_ms};
const STALL = {stall_ms};
const steps = document.getElementById('steps');
const note = document.getElementById('note');
let lastPayload = '';
let lastChange = Date.now();

function draw(list) {{
  steps.innerHTML = list.map(s => `
    <div class="step" data-state="${{s.state}}">
      <span class="dot"></span>
      <span class="name">${{s.source}} / ${{s.role}}</span>
      <span class="found">${{s.state === 'failed' ? 'failed'
        : s.state === 'pending' ? 'waiting'
        : s.found + ' found'}}</span>
    </div>`).join('');
}}

async function tick() {{
  let body;
  try {{
    const r = await fetch(`/api/runs/${{RUN}}`);
    if (!r.ok) throw new Error('gone');
    body = await r.json();
  }} catch (e) {{
    note.textContent = 'Lost contact with the app.';
    note.className = 'note bad';
    return;
  }}

  draw((body.progress && body.progress.steps) || []);

  const snapshot = JSON.stringify(body.progress || {{}});
  if (snapshot !== lastPayload) {{ lastPayload = snapshot; lastChange = Date.now(); }}

  if (body.status === 'OK') {{
    window.location = '/';
    return;
  }}
  if (body.status === 'FAILED') {{
    note.innerHTML = (body.error || 'The search failed.') +
      ' <a class="retry" href="#" onclick="again();return false">retry</a>';
    note.className = 'note bad';
    return;
  }}
  if (Date.now() - lastChange > STALL) {{
    note.innerHTML = 'This may have stopped. ' +
      '<a class="retry" href="#" onclick="again();return false">retry</a>';
    note.className = 'note bad';
  }} else {{
    const n = (body.progress && body.progress.scraped) || 0;
    note.textContent = n ? n + ' found so far' : 'starting';
    note.className = 'note';
  }}
  setTimeout(tick, POLL);
}}

async function again() {{
  const r = await fetch('/api/runs', {{method: 'POST'}});
  const body = await r.json();
  if (body.run_id) window.location = '/searching/' + body.run_id;
}}

tick();
</script>
"""


def render(run_id: int) -> str:
    return _HTML.format(css=_CSS, run_id=int(run_id),
                        poll_ms=_POLL_MS, stall_ms=_STALL_MS)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_searching_page.py -q`
Expected: `8 passed`

- [ ] **Step 6: Commit**

```bash
git add src/searching_page.py tests/test_searching_page.py
git commit -m "feat: a screen that shows the whole run from the first poll"
```

---

## Task 11: The progress route

**Files:**
- Modify: `job_hunt/src/app.py`
- Test: `job_hunt/tests/test_run_routes.py` (append)

Adds 3 tests.

- [ ] **Step 1: Write the failing tests**

Append to `job_hunt/tests/test_run_routes.py`:

```python
def test_the_progress_screen_renders_for_a_real_run(client):
    run_id = client.post("/api/runs").get_json()["run_id"]
    response = client.get(f"/searching/{run_id}")

    assert response.status_code == 200
    assert b"searching" in response.data.lower()


def test_the_progress_screen_polls_its_own_run(client):
    run_id = client.post("/api/runs").get_json()["run_id"]
    body = client.get(f"/searching/{run_id}").get_data(as_text=True)

    assert f"/api/runs/{run_id}" in body


def test_the_progress_screen_404s_for_an_unknown_run(client):
    assert client.get("/searching/9999").status_code == 404
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_run_routes.py -q -k progress_screen`
Expected: FAIL — 404 for a run that exists

- [ ] **Step 3: Add the route**

In `job_hunt/src/app.py`, add directly after the `poll_scrape` route:

```python
    @app.get("/searching/<int:run_id>")
    def searching_screen(run_id: int):
        conn = _conn()
        try:
            if get_run(conn, run_id) is None:
                return jsonify({"error": "not found"}), 404
            return render_searching(run_id)
        finally:
            conn.close()
```

Add the import:

```python
from .searching_page import render as render_searching
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_routes.py -q`
Expected: `15 passed`

- [ ] **Step 5: Commit**

```bash
git add src/app.py tests/test_run_routes.py
git commit -m "feat: serve the progress screen"
```

---

## Task 12: Where the map sends you

**Files:**
- Modify: `job_hunt/src/app.py` (`map_screen`)
- Modify: `job_hunt/src/map_page.py` (`render`)
- Test: `job_hunt/tests/test_map_routing.py`

Adds 9 tests.

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_map_routing.py`:

```python
"""What / does, depending on setup state and whether a run is going."""
import pytest

from src.app import create_app
from src.store.db import connect
from src.store.ingest import ensure_user
from src.store.profile import create_resume, set_profile, update_resume
from src.store.runs import finish_run, start_run
from src.store.schema import init_db


def _bare(tmp_path, name="bare.db"):
    path = tmp_path / name
    conn = connect(path)
    init_db(conn)
    ensure_user(conn, "default")
    conn.close()
    return path


def _ready(tmp_path, name="ready.db"):
    path = _bare(tmp_path, name)
    conn = connect(path)
    user_id = ensure_user(conn, "default")
    resume_id = create_resume(conn, user_id, label="bi",
                              orig_filename="bi.pdf", sha256="abc",
                              stored_path="resumes/1/abc.pdf",
                              extracted_text="Power BI")
    update_resume(conn, user_id, resume_id, label="bi",
                  target_roles=[{"title": "BI Developer", "aliases": []}],
                  skills=[{"name": "Power BI", "tier": "core", "aliases": []}],
                  seniority="senior")
    set_profile(conn, user_id, location="Toronto, ON", country="ca",
                work_modes=["remote"])
    conn.close()
    return path


def _client(path, tmp_path):
    app = create_app(db_path=path, user_name="default",
                     data_root=tmp_path / "data")
    app.config.update(TESTING=True)
    return app.test_client()


def test_an_unset_up_user_is_sent_to_setup(tmp_path):
    response = _client(_bare(tmp_path), tmp_path).get("/")

    assert response.status_code == 302
    assert "/setup" in response.headers["Location"]


def test_a_set_up_user_reaches_the_map(tmp_path):
    assert _client(_ready(tmp_path), tmp_path).get("/").status_code == 200


def test_a_set_up_user_with_no_roles_is_told_nothing_has_been_searched(tmp_path):
    body = _client(_ready(tmp_path), tmp_path).get("/").get_data(as_text=True)
    assert "nothing searched yet" in body.lower()


def test_the_empty_state_offers_to_start_a_search(tmp_path):
    body = _client(_ready(tmp_path), tmp_path).get("/").get_data(as_text=True)
    assert "start searching" in body.lower()


def test_the_map_offers_to_search_again(tmp_path):
    body = _client(_ready(tmp_path), tmp_path).get("/").get_data(as_text=True)
    assert "/api/runs" in body


def test_a_running_run_is_announced_on_the_map(tmp_path):
    path = _ready(tmp_path)
    conn = connect(path)
    try:
        run_id = start_run(conn, ensure_user(conn, "default"))
    finally:
        conn.close()

    body = _client(path, tmp_path).get("/").get_data(as_text=True)
    assert "searching now" in body.lower()
    assert f"/searching/{run_id}" in body


def test_viewing_the_map_mid_run_does_not_mark_that_run_seen(tmp_path):
    """Otherwise every role the run is about to store files as already seen,
    and the map's new section silently empties."""
    path = _ready(tmp_path)
    conn = connect(path)
    try:
        user_id = ensure_user(conn, "default")
        start_run(conn, user_id)
    finally:
        conn.close()

    _client(path, tmp_path).get("/")

    conn = connect(path)
    try:
        seen = conn.execute("SELECT last_seen_run_id FROM user WHERE id = ?",
                            (user_id,)).fetchone()["last_seen_run_id"]
    finally:
        conn.close()
    assert seen in (None, 0)


def test_viewing_the_map_marks_the_last_finished_run_seen(tmp_path):
    path = _ready(tmp_path)
    conn = connect(path)
    try:
        user_id = ensure_user(conn, "default")
        done = start_run(conn, user_id)
        finish_run(conn, done, scraped=1, kept=1)
    finally:
        conn.close()

    _client(path, tmp_path).get("/")

    conn = connect(path)
    try:
        seen = conn.execute("SELECT last_seen_run_id FROM user WHERE id = ?",
                            (user_id,)).fetchone()["last_seen_run_id"]
    finally:
        conn.close()
    assert seen == done


def test_the_banner_shows_no_invented_total(tmp_path):
    path = _ready(tmp_path)
    conn = connect(path)
    try:
        start_run(conn, ensure_user(conn, "default"))
    finally:
        conn.close()

    body = _client(path, tmp_path).get("/").get_data(as_text=True)
    assert " of " not in body.lower().split("searching now")[1][:60]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_map_routing.py -q`
Expected: FAIL — `/` returns 200 for an unset-up user

- [ ] **Step 3: Teach map_page to render the two new pieces**

In `job_hunt/src/map_page.py`, change the `render` signature (line 352) from:

```python
def render(maps: list[dict], meta: dict | None = None) -> str:
```

to:

```python
def render(maps: list[dict], meta: dict | None = None,
           running_run_id: int | None = None) -> str:
```

Then, immediately after the `payload = payload.replace("</", "<\\/")` line and
before the `return f"""<!DOCTYPE html>` line, insert:

```python
    # Only counts the run has actually produced. While scraping, the total is
    # unknown, so the banner never shows a denominator — inventing one would
    # be the fabricated-precision pattern this project bans.
    banner = ""
    if running_run_id:
        banner = (f'<a class="banner" href="/searching/{running_run_id}">'
                  f'searching now &middot; see progress</a>')

    empty = ""
    again = ""
    if maps:
        again = ('<div class="again">'
                 '<button class="go alt" onclick="startRun()">SEARCH AGAIN'
                 '</button></div>')
    else:
        empty = ('<div class="empty"><p>nothing searched yet</p>'
                 '<button class="go" onclick="startRun()">START SEARCHING'
                 '</button></div>')

    starter = """<script>
async function startRun(){
  const r = await fetch('/api/runs', {method:'POST'});
  const body = await r.json();
  if(body.run_id){ window.location = '/searching/' + body.run_id; }
  else { alert(body.error || 'Could not start a search.'); }
}
</script>"""
```

Now place them in the returned document. Replace this block (lines 420-423):

```
<div class="wrap"><div class="col">
{"".join(body)}
{_watch_shelf(watching)}
</div></div>
```

with:

```
<div class="wrap"><div class="col">
{banner}
{empty}
{"".join(body)}
{again}
{_watch_shelf(watching)}
</div></div>
```

and replace this line:

```
<script>{_JS.replace("__DATA__", payload)}</script>
```

with:

```
<script>{_JS.replace("__DATA__", payload)}</script>
{starter}
```

Finally add these rules to the module's `_CSS`:

```css
.banner{display:block;margin:0 0 24px;padding:10px 16px;border-radius:6px;
background:rgba(0,212,255,.08);border:1px solid #00D4FF;color:#00D4FF;
font-family:'JetBrains Mono',ui-monospace,monospace;font-size:13px;
text-decoration:none}
.empty{padding:64px 0;text-align:center;color:#7A8899}
.go{margin-top:16px;padding:10px 20px;border-radius:6px;cursor:pointer;
background:#00D4FF;color:#0A0E1A;border:none;font-weight:600;
font-family:'JetBrains Mono',ui-monospace,monospace;font-size:13px}
.go.alt{background:transparent;color:#00D4FF;border:1px solid #00D4FF}
```

- [ ] **Step 4: Rewrite the map route**

In `job_hunt/src/app.py`, replace `map_screen` entirely:

```python
    @app.get("/")
    def map_screen():
        conn = _conn()
        try:
            user_id = _user(conn)

            # Nothing to show and nothing to search for — send them to setup
            # rather than to an empty map they cannot act on.
            profile = get_profile(conn, user_id)
            resumes = list_resumes(conn, user_id, active_only=True)
            if not resumes or not profile.get("setup_complete"):
                return redirect("/setup")

            sections = map_sections(conn, user_id, shortlist_min)
            tagged = (
                [{**m, "section": "new"} for m in sections["new"]]
                + [{**m, "section": "earlier"} for m in sections["earlier"]]
                + [{**m, "section": "watching"} for m in sections["watching"]]
            )
            in_flight = active_run(conn, user_id)
            html = render_map(
                tagged,
                meta={"companies": len(sections["new"]) + len(sections["earlier"]),
                      "roles": sum(len(m["roles"]) for m in
                                   sections["new"] + sections["earlier"])},
                running_run_id=in_flight["id"] if in_flight else None)

            # Only a finished run may be marked seen. Marking the in-flight
            # run would file every role it is about to store as already seen.
            latest = latest_ok_run(conn, user_id)
            if latest:
                mark_seen(conn, user_id, latest)
            return html
        finally:
            conn.close()
```

Add `redirect` to the Flask import line:

```python
from flask import Flask, jsonify, redirect, request
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_map_routing.py -q`
Expected: `9 passed`

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -q`

Existing map tests may fail on the new `redirect` — a fixture that never
completed setup now gets a 302. Fix those fixtures by calling `set_profile`,
not by weakening the route.

Expected when done: `507 passed`

- [ ] **Step 7: Commit**

```bash
git add src/app.py src/map_page.py tests/test_map_routing.py
git commit -m "feat: the map routes on setup state and announces a live run"
```

---

## Task 13: Starting a run from setup and from the profile

**Files:**
- Modify: `job_hunt/src/setup_page.py`
- Test: `job_hunt/tests/test_setup_routes.py` (append)

Adds 4 tests.

- [ ] **Step 1: Write the failing tests**

Append to `job_hunt/tests/test_setup_routes.py`:

```python
def test_the_confirm_screen_offers_to_start_searching(client):
    resume_id = _upload(client).get_json()["resume_id"]
    body = client.get(f"/setup/confirm/{resume_id}").get_data(as_text=True)

    assert "start searching" in body.lower()


def test_the_confirm_screen_can_post_a_run(client):
    resume_id = _upload(client).get_json()["resume_id"]
    body = client.get(f"/setup/confirm/{resume_id}").get_data(as_text=True)

    assert "/api/runs" in body


def test_the_profile_screen_offers_to_search(client):
    _upload(client)
    body = client.get("/profile").get_data(as_text=True)

    assert "/api/runs" in body


def test_the_profile_screen_sends_you_to_the_progress_screen(client):
    _upload(client)
    body = client.get("/profile").get_data(as_text=True)

    assert "/searching/" in body
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_setup_routes.py -q -k "start_searching or post_a_run or profile_screen_offers or progress_screen"`
Expected: FAIL — no `/api/runs` in either page

- [ ] **Step 3: Add the shared starter to setup_page.py**

In `job_hunt/src/setup_page.py`, add this constant near the top:

```python
# Both screens start a run the same way. Kept here rather than duplicated so
# the two cannot drift apart.
_STARTER = """
<script>
async function startRun() {
  const r = await fetch('/api/runs', {method: 'POST'});
  const body = await r.json();
  if (body.run_id) { window.location = '/searching/' + body.run_id; }
  else { alert(body.error || 'Could not start a search.'); }
}
</script>
"""
```

- [ ] **Step 4: Change the confirm screen's button and what it does next**

In `job_hunt/src/setup_page.py`, in `_CONFIRM_JS`, replace line 218:

```javascript
  location.href = '/profile';
```

with:

```javascript
  out.textContent = 'Starting your first search...';
  await startRun();
```

Then in `render_confirm`, replace this line (currently line 277):

```python
        '<button type="button" id="save" class="btn-p">SAVE THIS PROFILE</button>'
```

with:

```python
        '<button type="button" id="save" class="btn-p">'
        'LOOKS RIGHT &mdash; START SEARCHING</button>'
```

And in the same function's `return _shell(...)` call, append `_STARTER` to the
body argument so `startRun` is defined on the page. Change:

```python
        body, _CONFIRM_JS, nav='<a href="/profile">ALL RESUMES &rarr;</a>')
```

to:

```python
        body + _STARTER, _CONFIRM_JS,
        nav='<a href="/profile">ALL RESUMES &rarr;</a>')
```

`_STARTER` is its own `<script>` tag, so `startRun` is a global by the time
anyone clicks — script order does not matter here.

- [ ] **Step 5: Add the button to the profile screen**

In `render_profile`, replace the `body = (...)` assignment (lines 332-338)
with:

```python
    search = ('<button class="go" onclick="startRun()">SEARCH NOW</button>'
              if resumes else "")
    body = (
        f'<div class="card"><span class="lab">YOUR RESUMES</span>{listing}'
        '<div class="foot"><a class="btn-p" href="/setup">ADD A RESUME</a>'
        f'{search}</div></div>'
        '<div class="card"><span class="lab">WHERE YOU ARE LOOKING</span>'
        f'<div class="note">{_e(where)} &middot; {_e(modes)}</div></div>'
    )
```

and change its `return _shell(...)` body argument from `body` to
`body + _STARTER`.

Then add this rule to `setup_page.py`'s `_CSS`:

```css
.go{margin-left:12px;padding:10px 20px;border-radius:6px;cursor:pointer;
background:#00D4FF;color:#0A0E1A;border:none;font-weight:600;
font-family:'JetBrains Mono',ui-monospace,monospace;font-size:13px}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_setup_routes.py -q`
Expected: all pass, 4 more than before

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: `511 passed`

- [ ] **Step 8: Commit**

```bash
git add src/setup_page.py tests/test_setup_routes.py
git commit -m "feat: finish setup and the search starts itself"
```

---

## Task 14: Guard the boundaries, then run it for real

**Files:**
- Test: `job_hunt/tests/test_run_routes.py` (append)
- Modify: `CLAUDE.md`

Adds 3 tests.

- [ ] **Step 1: Write the guard tests**

Append to `job_hunt/tests/test_run_routes.py`:

```python
def test_no_new_route_exposes_a_score_or_a_percentage(client, db):
    """The product rule: a number is for ranking, never for reading."""
    run_id = client.post("/api/runs").get_json()["run_id"]

    for path in ("/api/runs/%s" % run_id, "/searching/%s" % run_id):
        body = client.get(path).get_data(as_text=True)
        assert "match_score" not in body, path
        assert "interview_chance" not in body.lower(), path


def test_the_worker_never_writes_excel():
    """The browser run stops after scoring. Excel belongs to the terminal."""
    from pathlib import Path

    source = (Path(__file__).parent.parent / "src" / "run_core.py").read_text(
        encoding="utf-8")
    assert "excel" not in source.lower()


def test_the_core_knows_nothing_about_flask_or_threads():
    """run_core is shared by a request handler and a CLI. It stays pure."""
    from pathlib import Path

    source = (Path(__file__).parent.parent / "src" / "run_core.py").read_text(
        encoding="utf-8")
    assert "flask" not in source.lower()
    assert "threading" not in source.lower()
```

- [ ] **Step 2: Run them**

Run: `python -m pytest tests/test_run_routes.py -q`
Expected: all pass

- [ ] **Step 3: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: `514 passed`

- [ ] **Step 4: Update the project instructions**

In `CLAUDE.md`, under **Finalized UI**, replace the closing sentence
`Run it with `python main.py --serve`.` with:

```
Run it with `python main.py --serve`. Scrapes start from the browser:
`POST /api/runs` opens a run, `GET /searching/<id>` watches it, and `/`
redirects to `/setup` until a resume and a location are on file. The browser
run stops after scoring — the LLM shortlist, resume variants and the Excel
tracker still belong to `python main.py`.
```

- [ ] **Step 5: Smoke-test the real thing**

The suite cannot cover the first time a real worker thread scrapes live actors
while a browser polls it.

```bash
python main.py --serve
```

Check, in order:

1. `/` redirects to `/setup` on a database with no resume.
2. With a resume on file, `/` shows the map. If no run has ever completed, it
   reads **nothing searched yet** with a START SEARCHING button.
3. Click it. The URL becomes `/searching/<id>` and every planned step is
   listed immediately — one row per source per target role, all `waiting`.
4. Steps turn cyan then green as they complete, with real found counts. **No
   percentage and no "N of M" appears anywhere.**
5. Open `/` in a second tab while the run is going. The map renders with the
   **searching now** banner, and the run does not vanish from the new section
   when it lands — this is the `mark_seen` trap, and it is the single most
   likely thing to be wrong.
6. On completion the screen redirects to `/` and the new roles are in the
   **new** section, not filed under earlier.
7. Press SEARCH AGAIN. The second run either starts, or returns 409 if the
   first is somehow still marked running.
8. Kill the process mid-run with Ctrl-C, restart `python main.py --serve`, and
   confirm a new run can start — the orphan must have been cleared at boot.

Then confirm the terminal path still works end to end:

```bash
python main.py
```

Step 3 must still fetch non-zero from both sources, step 7 must still make LLM
shortlist decisions, and step 8 must still write the workbook. If any of those
changed, Task 6's refactor broke something the suite does not cover.

- [ ] **Step 6: Commit**

```bash
git add tests/test_run_routes.py CLAUDE.md
git commit -m "test: guard the run boundaries; document the browser run"
```

---

## What Ship 3 deliberately does not do

Leave these alone.

- **No LLM shortlist, no resume variants, no Excel in the browser run.** They
  are 90% of the terminal run's wall clock and none of them reach the map.
- **No authentication and no CSRF token.** Any page open in the browser can
  `POST /api/runs` and spend Apify credits. Same exposure as the existing
  `POST /api/resumes`; accepted knowingly because this binds to localhost.
- **No run timeout and no cancel button.** Superseding a stale run closes the
  lockout, not the spend.
- **No schema migration.** Every column this ship writes already exists.
- **No heartbeat column.** Staleness is detected in the page and by age.
- **Company enrichment stays disabled.** The `enrich` hook exists so the
  terminal path keeps its behaviour, not so this ship turns it on.
- **Roles scored before this release keep their scores.** They refresh on the
  next run that sees them.

## Open threads this ship hands to Ship 4

- `Apply_Now`, `LLM_Reason` and `Risk_Flags` live only in the workbook and the
  browser run does not produce them. Retiring Excel without deciding where
  they go silently deletes the feature.
- The terminal dedupes against the workbook; the browser run dedupes against
  the store. The two disagree about what is new until Excel goes.
- `tracker/excel.py` still carries an `Interview Chance` column, a `CAT_ORDER`
  naming the four categories Ship 2 deleted, and a stale comment on
  `Recommended Resume`. All three disappear when the module does.
