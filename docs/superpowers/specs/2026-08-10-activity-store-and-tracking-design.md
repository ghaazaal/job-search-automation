# Activity store and application tracking — design

## Goal

Give the product a memory. Today the pipeline scrapes, renders a page, and
forgets. Nothing records which companies were seen, which roles the user saved
or applied to, or what came of it. This design adds a durable store, a local
application the user's clicks write into, and a second screen showing what they
have in flight.

## Why now

Three separate problems share one cause:

1. The opportunity map shows only the current run. A user who does not open it
   for three days loses those days.
2. `WATCH` and `HIDE` render as buttons but persist nothing.
3. The scoring weights in `keywords.yaml` have never been checked against
   reality, because outcomes are not recorded. This is the load-bearing one —
   every ranking decision in the product rests on weights nobody has validated.

## Scope

**In:** SQLite store, a local Flask application, role-level status tracking, an
activity screen, run history, and a one-time import of the existing Excel
tracker.

**Out:** hosted deployment, accounts and login, automated status detection from
email, people-in-context hints, and outcome-driven re-weighting of the scorer.
The last is deliberately deferred — this design captures the data that makes it
possible later, and stops there.

## Architecture

```
scrape → score → SQLite (source of truth) → Flask (localhost) → two screens
                     ^                                              |
                     +------------- user clicks --------------------+
```

`python main.py` scrapes and writes to SQLite, then serves the app.
`python main.py --serve` skips the scrape and serves what is already stored.

Excel stops being the database and becomes an export. This removes the
`PermissionError` when the file is open, and the hyperlink-based row identity
that made `read_existing` fragile.

Flask is chosen over FastAPI: the app serves server-rendered pages and a handful
of JSON endpoints, needs no async, and Flask adds one dependency rather than
three.

### Modules

| Module | Responsibility |
|---|---|
| `src/store/schema.py` | DDL and migrations. Owns the schema version. |
| `src/store/db.py` | Connection handling, pragmas, transaction helper. |
| `src/store/roles.py` | Upsert roles and companies from a scrape run. |
| `src/store/tracking.py` | Status transitions and the event log. |
| `src/store/queries.py` | Read models for the two screens. |
| `src/app.py` | Flask routes. No SQL — calls the store. |
| `src/map_page.py` | Existing renderer, fed from `queries`. |
| `src/activity_page.py` | New renderer for the activity screen. |

`src/tracker/db.py` and `src/tracker/cache.py` are folded into `src/store/`.
The dead `outcomes` table in `tracker/db.py` is dropped; it was never written to.

## Data model

Six tables. Every row carries `user_id` from the first migration so ship 2
(multi-user) needs no schema change.

```sql
CREATE TABLE user (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT,
    last_seen_run_id INTEGER,   -- no FK: would make user and run circular
    created_at      TEXT NOT NULL
);

CREATE TABLE run (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES user(id),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL CHECK (status IN ('RUNNING','OK','FAILED')),
    scraped     INTEGER NOT NULL DEFAULT 0,
    kept        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE company (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES user(id),
    name          TEXT NOT NULL,
    fingerprint   TEXT NOT NULL,
    user_state    TEXT NOT NULL DEFAULT 'NONE'
                  CHECK (user_state IN ('NONE','WATCH','HIDDEN')),
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    UNIQUE (user_id, fingerprint)
);

CREATE TABLE role (
    id                   INTEGER PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES user(id),
    company_id           INTEGER NOT NULL REFERENCES company(id),
    title                TEXT NOT NULL,
    url                  TEXT NOT NULL,
    url_normalised       TEXT NOT NULL,
    location             TEXT,
    salary               TEXT,
    platform             TEXT,
    posted_date          TEXT,
    description          TEXT,
    description_captured INTEGER NOT NULL DEFAULT 0,
    match_score          INTEGER,
    band                 TEXT CHECK (band IN ('STRONG FIT','PARTIAL FIT','STRETCH')),
    reason               TEXT,
    matched              TEXT NOT NULL DEFAULT '[]',
    gaps                 TEXT NOT NULL DEFAULT '[]',
    first_seen_run_id    INTEGER NOT NULL REFERENCES run(id),
    last_seen_run_id     INTEGER NOT NULL REFERENCES run(id),
    UNIQUE (user_id, url_normalised)
);

CREATE TABLE application (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES user(id),
    role_id    INTEGER NOT NULL UNIQUE REFERENCES role(id),
    status     TEXT NOT NULL CHECK (status IN
                 ('SAVED','APPLIED','INTERVIEWING','OFFER',
                  'REJECTED','CLOSED','HIDDEN')),
    applied_at TEXT,
    updated_at TEXT NOT NULL,
    notes      TEXT
);

CREATE TABLE event (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES user(id),
    role_id     INTEGER REFERENCES role(id),
    company_id  INTEGER REFERENCES company(id),
    kind        TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT,
    at          TEXT NOT NULL
);
```

### Modelling decisions

**`application` rows are created lazily.** A role the user has never touched has
no `application` row and reads as `NEW`. Queries use a `LEFT JOIN` and coalesce
to `'NEW'`. This keeps "the user's relationship with this role" out of the
scrape path entirely — a run never writes to `application`.

**`NEW` is therefore not a stored status.** It is the absence of one. This is
why it does not appear in the `CHECK` constraint.

**Company display state is derived, never stored.** `company.user_state` records
only what the user chose (`WATCH`, `HIDDEN`, or nothing). Whether a company shows
as `ACT_NOW` or `DISCOVER` is computed at render time from its roles' scores
against the shortlist threshold. Storing it would let it go stale the moment a
role is added or the threshold changes.

**`event` is append-only.** Nothing updates or deletes it. It is both the user's
history and the dataset that will eventually let the scoring weights be tested
against outcomes.

**`match_score` is stored but never served.** `queries` omits it from every read
model that reaches a renderer, matching the rule that no numeric score reaches
the interface.

## ACID and concurrency

The scraper and the web app write to the same file, so these are requirements,
not defaults.

**Every connection sets:**

```sql
PRAGMA foreign_keys = ON;    -- off by default; declared FKs are ignored without it
PRAGMA journal_mode = WAL;   -- readers never block on the writer
PRAGMA busy_timeout = 5000;  -- wait rather than fail on a brief lock
PRAGMA synchronous = FULL;   -- a committed status change survives power loss
```

`foreign_keys` is per-connection and must be set every time. `journal_mode` is
persisted in the file but is set idempotently anyway.

**Atomicity.** A run writes its `run` row, companies and roles inside a
transaction per batch of 50 roles, not one transaction for the whole scrape. A
crash mid-run leaves whole batches, and `run.status` stays `RUNNING`, which the
UI reports as an incomplete run rather than presenting it as complete.

**Consistency.** Enforced in the schema, not in application code: foreign keys
on every relationship, `CHECK` constraints on both status vocabularies, and
`UNIQUE (user_id, url_normalised)` making deduplication a database guarantee
rather than a hope.

**Isolation.** A status change and its `event` row are written in one
transaction. The current status and the history can never disagree. Write
transactions are short by construction — the long work (Apify calls, LLM calls)
happens outside any transaction.

**Durability.** `synchronous = FULL`. A re-scrape can reconstruct roles; it can
never reconstruct the fact that the user got an offer.

If this becomes a hosted multi-user product, the move is Postgres — same schema,
same guarantees, real concurrent writers. Nothing in this design depends on
SQLite specifics beyond the pragmas.

## State machines

**Role**

```
(no row = NEW) → SAVED → APPLIED → INTERVIEWING → OFFER
```

`REJECTED`, `CLOSED` and `HIDDEN` are reachable from any state. Every transition
writes an `event` row. Backwards moves are allowed — the user may correct a
mis-click — and are recorded like any other move.

**Company**

`NONE` ↔ `WATCH`, and either → `HIDDEN`. Set only by the user.

## Screens

### Map — what to do today

Three sections, in order:

1. **New since your last visit** — roles whose `first_seen_run_id` is greater
   than the user's `last_seen_run_id`.
2. **Still here from earlier** — roles seen in older runs, not new, with no
   `application` row, whose company is not hidden. This is what a user who
   skipped three days comes back to.
3. **Keeping an eye on** — companies with `user_state = 'WATCH'` that have no
   role in sections 1 or 2. A watched company with a live role appears as a
   normal card; the shelf is for companies with nothing open, matching the
   handoff's rule that a watch entry carries no role.

Roles with an `application` row do not appear on the map, in any section. Once
the user has acted on something it belongs to the activity screen, and hidden
roles are simply the case of that with no column to show them in.

`user.last_seen_run_id` is updated when the map is rendered, so "new" means new
since the last time the user actually looked, not since the last scrape.

### Activity — what you have in flight

Four columns: `SAVED`, `APPLIED`, `INTERVIEWING`, `OFFER`, each with a count and
oldest-first ordering, so the thing waiting longest is at the top. `REJECTED` and
`CLOSED` live in a collapsed section below. `HIDDEN` is not shown.

Each card carries company, role title, current status, days in that status, and
its dated event log.

## Trust rules

These extend the rules in the MVP spec and are binding.

- Never render "still open". The product knows only when a role was last seen in
  a run. Copy is "last seen 3d ago".
- A role absent from recent runs is not marked closed. Disappearing from a job
  board is not evidence of anything.
- The `NO DESCRIPTION CAPTURED` state survives storage — `description_captured`
  is persisted, and a stored role with no description still renders the
  "not checked yet" block rather than a band.
- No numeric score in any response body, including JSON endpoints.

## HTTP interface

| Method | Path | Does |
|---|---|---|
| GET | `/` | Map screen |
| GET | `/activity` | Activity screen |
| POST | `/api/roles/<id>/status` | Set status, write event |
| POST | `/api/companies/<id>/state` | Watch, unwatch or hide |
| GET | `/api/export.xlsx` | Excel export of the current state |

State-changing endpoints accept JSON, return the updated read model, and are the
only paths that write. They validate the target status against the same
vocabulary as the `CHECK` constraint, so an invalid value is rejected before it
reaches SQLite.

The app binds to `127.0.0.1` only.

## Migrating the existing tracker

A one-time `python main.py --import-tracker` reads
`job_tracker_ghazal.xlsx` and creates a synthetic run holding its 273 rows.
Existing `Application Status` values map as: `Applied` → `APPLIED`,
`Interview` → `INTERVIEWING`, `Rejected` → `REJECTED`, `Ignored` and
`Filtered Out` → `HIDDEN`, `New` and `Tailored` → no application row. Imported
roles have `description_captured = 0`, because those rows predate description
capture, and so render as "not checked yet" rather than claiming a fit.

## Testing

- **Pragmas are verified, not assumed.** A test asserts a fresh connection
  reports `foreign_keys = 1` and `journal_mode = wal`.
- **Constraints are tested by violating them.** Inserting an invalid status, a
  duplicate `url_normalised`, or a role pointing at a missing company must raise.
- **Atomicity is tested by failure.** A batch that raises partway leaves no rows
  from that batch.
- **Status and event cannot diverge.** After any transition the current status
  equals the `to_status` of the latest event for that role.
- **Read models carry no score.** A test asserts `match_score` appears in no read
  model or response body.
- Existing renderer and scorer tests continue to pass unchanged.

## Acceptance criteria

1. `python main.py` scrapes into SQLite and serves the map at `127.0.0.1`.
2. Clicking WATCH, HIDE, SAVE or a status change persists across a restart.
3. A role saved on Monday appears in the activity screen on Friday with its
   status and the number of days it has held it.
4. A role first seen on Monday and untouched appears under "still here from
   earlier" on Friday, labelled with when it was last seen.
5. Marking a role APPLIED removes it from the map and places it in the activity
   screen's applied column.
6. The event log for a role that went saved → applied → interviewing shows three
   dated rows.
7. A fresh connection reports `foreign_keys = 1` and `journal_mode = wal`.
8. An invalid status is rejected by the database, not only by the application.
9. No numeric score appears in any rendered page or JSON response.
10. `--import-tracker` loads the existing 273 rows without inventing fit data.

## Sequencing

1. Store: schema, pragmas, transactions, upsert from a run. No UI.
2. Import the existing tracker. Proves the schema against real data.
3. Flask app serving the existing map from the store, read-only.
4. Write endpoints, then wire the map's buttons.
5. Activity screen.

Each step ends with a working system.
