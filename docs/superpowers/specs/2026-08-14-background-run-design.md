# Ship 3 — It Runs Itself

Date: 2026-08-14
Status: approved, ready for an implementation plan

Ship 1 built the profile. Ship 2 made the profile drive the search and the
score. Both still require a terminal: `python main.py` is the only way to get
new roles onto the map. Ship 3 removes that requirement.

---

## What the browser run does

**Scrape, dedupe, score, store. Nothing else.**

The terminal pipeline has eight steps. Only five of them produce anything the
map can show:

| Step | Time in the 2026-08-13 live run | Where the output lands |
| --- | --- | --- |
| 1–4 read profile, read tracker, scrape, dedupe | ~15s | store → map |
| 5 company enrichment | disabled | — |
| 6 scoring | fast | store → map |
| 7 LLM shortlist (30 jobs) + role variants | **~3.5 min** | Excel and `output/` only |
| 8 save tracker | fast | Excel |

`Apply_Now`, `LLM_Reason` and `Risk_Flags` appear in exactly one place in
`src/` — `tracker/excel.py`. They never reach the store, so they never reach
the map. Step 7 is 90% of the wall clock and none of the product.

So the browser run stops after step 6. It finishes in roughly 15–30 seconds
and the map is complete. `python main.py` keeps all eight steps until Ship 4.

This is the decision the rest of the design rests on. A progress screen that
filled in within 15 seconds and then sat silent for three and a half minutes
would be the worst artifact of the alternative.

---

## Architecture

```
src/run_core.py        NEW   scrape → dedupe → score → persist, emits progress
src/run_worker.py      NEW   thread wrapper: own connection, writes progress
src/searching_page.py  NEW   the progress screen
main.py                      run_pipeline calls run_core, then LLM + Excel
src/app.py                   POST /api/runs, GET /api/runs/<id>, GET /searching/<id>
```

### The shared core

```python
run_core.execute(conn, user_id, run_id, config, resumes, profile,
                 on_progress) -> RunResult
```

`RunResult` carries what the caller needs for its own reporting: the number
scraped, the number kept, and the scored rows. `run_pipeline` uses the rows to
continue into its LLM and Excel steps; the worker ignores them.

The **caller creates the run row and passes its id in** — the endpoint so that
`POST` has something to return, `run_pipeline` via `start_run` before it
calls. The core never inserts a run; it updates the one it is given.

One implementation of scrape-and-score, three presentations of its progress:

| Caller | `on_progress` does |
| --- | --- |
| `run_pipeline` (terminal) | prints the `-> 100 fetched` lines you see today |
| `run_worker` (background) | `UPDATE run SET stage, progress` on its own connection |
| tests | appends to a list and asserts on the sequence |

`on_progress` is a plain callable taking an event dict. The core knows nothing
about threads, Flask or the `run` table.

Two behaviour changes fall out of the extraction, both deliberate:

- **The core dedupes against the store, not Excel.** It has no workbook.
  Within-batch collapsing is unchanged; cross-run dedupe comes from
  `role.url_normalised`, which already carries a `UNIQUE` constraint doing
  exactly this.
- **`sys.exit(1)` does not enter the core.** The locked-workbook exit stays in
  `run_pipeline`, where a terminal exists to read it. The core raises; the
  worker catches and marks the run `FAILED`. A `sys.exit` inside a worker
  thread would raise `SystemExit` in that thread and leave the run `RUNNING`
  forever.

Extracting the core is the riskiest task in this ship. It pulls apart
`main.py` code whose integration was verified by exactly one live run, and
re-verification costs real Apify credits. The mitigation is that the core is
pure and testable in a way the 280-line `run_pipeline` never was.

---

## The run lifecycle

```
POST /api/runs        → {run_id}   409 if one is RUNNING and under 15 min old
GET  /api/runs/<id>   → {status, stage, progress}
GET  /searching/<id>  → progress screen, polls the above every 2s
```

409 is the response to a run that is genuinely in flight. A `RUNNING` row
older than fifteen minutes is treated as abandoned and superseded rather than
blocking — see *Stale runs* below.

`run.status` already carries the three states:

| Status | Set when | Screen shows |
| --- | --- | --- |
| `RUNNING` | `POST /api/runs` inserts the row | live step list, polling |
| `OK` | core returns, persist committed | redirect to `/` |
| `FAILED` | worker catches an exception, boot cleanup, or supersede | what broke, plus retry |

The endpoint inserts the run row, not the worker — otherwise `POST` has
nothing to return and the 409 check has nothing to test. This splits today's
`persist_run`, which calls `start_run` itself at the end, into `start_run`
(endpoint) and a persist that takes an existing `run_id`.

### progress

Written before the first scrape so the screen renders the whole list from the
first poll:

```json
{"steps": [{"source": "Indeed",   "role": "BI Developer",  "state": "done",    "found": 100},
           {"source": "LinkedIn", "role": "BI Developer",  "state": "running", "found": 0},
           {"source": "Indeed",   "role": "Data Analyst",  "state": "pending", "found": 0}],
 "scraped": 100, "stage": "scraping"}
```

`state` is `pending`, `running`, `done` or `failed`. One write per step
transition and one per stage transition — not one per scored job.

### Concurrency

Check-and-insert runs inside a single `BEGIN IMMEDIATE` transaction. Two rapid
POSTs would otherwise both see no `RUNNING` row and both insert.

A partial unique index on `run(user_id) WHERE status = 'RUNNING'` is the
stronger guarantee and is deliberately **not** used: `_DDL` executes on every
`init_db`, so the index would be created before boot cleanup has had a chance
to clear orphaned rows, and a database holding two stale `RUNNING` runs would
fail to open. For a single-process local app where SQLite serializes writes,
the transaction is sufficient and carries no ordering hazard.

### Failure rules

- **One source failing does not fail the run.** That step goes `failed`, the
  others continue. A LinkedIn timeout must not discard 100 Indeed results.
- **Zero results everywhere is `OK`, not `FAILED`.** An empty search is a
  legitimate answer and the screen says so plainly.
- **The worker opens its own SQLite connection.** Connections are not
  shareable across threads. WAL and `busy_timeout`, already set in `db.py`,
  cover worker-writes against poller-reads.
- **Any exception marks the run `FAILED` with its message**, then re-raises
  into the thread to be logged. A crashed worker must never leave `RUNNING`.

### Stale runs

A worker killed without marking `FAILED` leaves the run `RUNNING`, and 409
then blocks every new run. Staleness detection on the progress screen is
client-side, so a closed tab means nothing is watching. Boot cleanup alone
would leave the user locked out until the restart they are locked into.

Two lines of defence, neither needing a schema change:

1. **`POST` supersedes** a `RUNNING` run whose `started_at` is more than 15
   minutes old — marks it `FAILED`, starts the new one. `started_at` already
   exists.
2. **Boot marks every `RUNNING` run `FAILED`** in `create_app`.

Cleanup belongs in `create_app`, which runs once per process — **not** in
`init_db`, which `_conn()` calls on every single request and which would
therefore mark a live run `FAILED` mid-scrape.

---

## Routing

| `/` when… | does |
| --- | --- |
| no active resume, or `setup_complete = 0` | redirect to `/setup` |
| setup done, no roles ever stored | map empty state — "nothing searched yet" + START SEARCHING |
| a run is `RUNNING` | map from the last `OK` run, plus a banner linking to `/searching/<id>` — **and does not mark seen** |
| otherwise | map as today, marks the latest **`OK`** run seen |

### Why "latest OK run", not "latest run"

`map_screen` currently reads `SELECT MAX(id) FROM run` and calls `mark_seen`.
That is safe today only because `persist_run` creates the run row *after* a
scrape completes, so the maximum id is always a finished run.

Ship 3 inserts the row up front. Opening `/` mid-run — which the banner
actively invites — would set `last_seen_run_id` to the in-flight run. Its
roles then land with `first_seen_run_id` equal to that same id, `map_sections`
filters new roles on `first_seen_run_id > last_seen_run_id`, and every
genuinely new role would file under "still here from earlier". The new section
would silently empty.

`mark_seen` must therefore be driven by `MAX(id) WHERE status = 'OK'`.

---

## Screens

Three entry points, all posting to the same endpoint:

- the confirm screen's button becomes **LOOKS RIGHT — START SEARCHING** and
  lands on `/searching/<id>`, so a first-time user never meets an empty map
- the map gets a persistent **SEARCH AGAIN**
- `/profile` gets one beside the resume list, where target roles are edited

The progress screen polls every two seconds, renders every step from the first
poll, redirects to `/` on `OK`, and on `FAILED` shows the message and a retry
rather than landing silently on a stale map. After roughly three minutes with
an unchanged progress payload it says the run may have stopped.

The in-flight banner reports only counts the run has actually produced —
"searching now — 100 found so far". The total is unknown while scraping, so no
denominator is shown. Inventing one would be the fabricated-precision pattern
`CLAUDE.md` bans.

Both new screens follow the existing paper language of `map_page.py` and
`activity_page.py`.

---

## No schema change

`stage`, `progress` and `error` landed in the version 2 migration during Ship
1 and have never been written. `started_at` already exists. Nothing here needs
a new column, so the schema stays at version 3.

---

## Testing

No network in the suite. The runner is injected so tests drive it
synchronously; threading stays one thin wrapper rather than a race chased
through a test suite.

- `POST` while one is `RUNNING` and under 15 minutes old → 409
- `POST` with no active resumes, or resumes with no target roles → 400
- `POST` with no `APIFY_TOKEN` → 400, and no run row is inserted
- `POST` supersedes a `RUNNING` run older than 15 minutes
- worker raises → `FAILED` carrying the message, never stuck `RUNNING`
- one source fails → run is `OK`, that step is `failed`, the other source's
  results are kept
- every step returns zero → `OK`, not `FAILED`
- orphaned `RUNNING` cleared at boot
- **ordinary requests do not clear live runs** — the `init_db` trap
- **`/` during a `RUNNING` run leaves `last_seen_run_id` untouched**
- `/` redirects when setup is incomplete; renders the empty state when setup
  is complete and no roles exist
- no `match_score` and no percentage in any response from any new route

---

## Open threads for Ship 4

Recorded here so they are not rediscovered.

**The LLM shortlist has no home after Excel.** `Apply_Now`, `LLM_Reason` and
`Risk_Flags` live only in the workbook, and the browser run does not produce
them. When Ship 4 retires Excel, a feature that currently runs against 30 jobs
per scrape disappears unless Ship 4 decides to move it into the store and onto
the map. If it moves, the per-job progress reporting deferred here comes back
with it.

**Two dedupe sources of truth.** The terminal dedupes against the workbook's
full history; the browser run dedupes against the store, which only knows what
`persist_run` wrote. The two will disagree about what is new until Excel goes.

**Rot inside `tracker/excel.py`**, all of it deleted when Excel is retired:

- `Interview Chance` is still a column — the hardcoded-percentage pattern
  `CLAUDE.md` explicitly bans
- `CAT_ORDER` hardcodes the four search categories Ship 2 deleted, so it is a
  near no-op against resume-derived titles like `BI Developer`
- `Recommended Resume` is commented "kept for backward compat; blank in new
  rows", but Ship 2 began writing a real resume label into it

---

## Out of scope, and accepted risks

- **No authentication and no CSRF token.** Any page open in the browser can
  `POST http://127.0.0.1:5000/api/runs` and spend Apify credits. This is the
  same exposure as the existing `POST /api/resumes` and consistent with the
  localhost-only, single-user decision — but this is the first endpoint that
  costs money, so the acceptance is explicit rather than inherited.
- **No overall run timeout and no cancel button.** Once started, up to four
  Apify calls at 120 seconds each proceed unattended. Superseding stale runs
  closes the lockout, not the spend.
- **The progress machinery is heavy for a 15–30 second run.** It earns its
  place only as roles and sources multiply. Accepted knowingly; a spinner
  would very nearly do today.
- Company enrichment stays disabled. `company_agent.py` and
  `company_filter.py` are untouched.
- Rescoring roles stored before this release is out of scope; they refresh on
  the next run that sees them.
