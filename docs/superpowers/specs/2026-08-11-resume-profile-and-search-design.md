# Resume Profile and Profile-Driven Search — Design

**Date:** 2026-08-11
**Status:** Approved, ready for implementation planning
**Supersedes:** the `resume:` section of `config.yaml` and the personal half of `keywords.yaml`

---

## Problem

The tool has no way to take in a resume. `RESUME_PATH` in `.env` points at one PDF
on one laptop. That PDF is parsed, and the result is used for cover-letter text
and nothing else.

What gets searched comes from four job titles typed into `config.yaml`. What
counts as a good fit comes from a skill list typed into `keywords.yaml`. Both
files describe one person. A second user gets Ghazal's search and Ghazal's
scoring.

Two lanes exist and never join:

```
RESUME LANE   RESUME_PATH -> parse_resume -> resume_parsed.json -> cover letters
SEARCH LANE   config.yaml -> Apify scrape -> Scorer(keywords.yaml) -> store -> map
```

This design joins them, and makes the resume the source of truth for both.

---

## The model

A **user** is a person. A **resume** is one tailored document. One user owns many
resumes — a Data Engineer resume, a BI Developer resume, an Analytics Engineer
resume.

| Belongs to the user | Belongs to a resume |
| --- | --- |
| location, country | label |
| work modes (remote / hybrid / onsite) | target roles, with aliases |
| watched / applied / hidden state | skills, with aliases and tier |
| every run and every role ever seen | seniority |
| | the stored PDF and its extracted text |

Where you live is not a property of a PDF. Neither is the fact that you already
applied somewhere.

**Search** is the union of every target role across the user's active resumes,
deduplicated, filtered by the user's location and work modes.

**Scoring** runs every job against every active resume and keeps the best. The
winning resume is stored on the role, so the map can say *"STRONG FIT with your
BI Developer resume"* — which is the question a person actually has when they
find a job worth applying to.

Rejected alternative: one profile per resume, switched between. That splits the
map into three, breaks companies apart when a firm is hiring for two of your
roles, and ties watched/applied state to a PDF instead of to you.

---

## Identity

One user, no authentication. The `user` table already separates people's data;
login would add *authentication*, and the app binds to `127.0.0.1`, so there is
nobody to authenticate against.

Deferred deliberately, not forgotten. Adding accounts later is a login screen
plus a session lookup replacing `ensure_user(conn, name)`. Nothing in the schema
below changes. The cost that makes it premature is not the form — it is password
hashing, session management, CSRF on every write endpoint, a reset flow needing
outbound email, then hosting, HTTPS, and custody of other people's resumes.

Revisit when the decision to host it is made.

---

## Schema

`SCHEMA_VERSION` goes 1 → 2. `init_db` is currently `CREATE TABLE IF NOT EXISTS`
only, which cannot add a column to an existing table, so this release introduces
the first real migration step.

### Migration

`init_db` reads `PRAGMA user_version`. If it is below 2, it runs the version-2
`ALTER TABLE` statements inside one transaction and sets `user_version = 2`. A
fresh database gets the full DDL and jumps straight to 2. Migrations are
forward-only; there is no downgrade path and none is wanted.

### `user` — new columns

| Column | Type | Notes |
| --- | --- | --- |
| `location` | TEXT | free text, e.g. `Toronto, ON` |
| `country` | TEXT | ISO code, drives the Indeed actor |
| `work_modes` | TEXT | comma-separated subset of `remote,hybrid,onsite` |
| `setup_complete` | INTEGER NOT NULL DEFAULT 0 | gates the `/` redirect |

Existing rows migrate with NULL location and `setup_complete = 0`. Nothing reads
the flag until Ship 3 adds the `/` redirect; until then `/setup` is reached by
typing the URL.

### `resume` — new table

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | |
| `user_id` | INTEGER NOT NULL REFERENCES user(id) | |
| `label` | TEXT NOT NULL | user-editable, e.g. `bi developer` |
| `orig_filename` | TEXT NOT NULL | display only, never used as a path |
| `sha256` | TEXT NOT NULL | content hash, also the stored filename |
| `stored_path` | TEXT NOT NULL | relative to the data root |
| `extracted_text` | TEXT NOT NULL | pdfminer output |
| `seniority` | TEXT CHECK (seniority IN ('junior','mid','senior','exec')) | |
| `skills` | TEXT NOT NULL DEFAULT '[]' | JSON |
| `target_roles` | TEXT NOT NULL DEFAULT '[]' | JSON |
| `is_active` | INTEGER NOT NULL DEFAULT 1 | inactive resumes stop driving search |
| `created_at` | TEXT NOT NULL | |

`UNIQUE (user_id, label)` and `UNIQUE (user_id, sha256)`. The second stops the
same file being uploaded twice under two labels.

JSON columns rather than child tables, matching the existing `role.matched` and
`role.gaps` precedent. Both fields are read whole and written whole by the
confirm screen; normalising them buys a query nobody has asked for yet.

```json
skills:       [{"name": "Power BI", "tier": "core",
                "aliases": ["powerbi", "pbi", "dax", "power query"]}]
target_roles: [{"title": "BI Developer",
                "aliases": ["business intelligence developer", "bi engineer"]}]
```

`tier` is `core` or `working`. Core skills are worth more; the parse LLM assigns
the tier and the user can change it.

### `role` — new column

| Column | Type | Notes |
| --- | --- | --- |
| `resume_id` | INTEGER REFERENCES resume(id) | which resume won the scoring |

Nullable. Roles scored before this release keep NULL and render without resume
attribution.

### `run` — new columns

| Column | Type | Notes |
| --- | --- | --- |
| `stage` | TEXT | `scraping`, `scoring`, `storing` |
| `progress` | TEXT NOT NULL DEFAULT '{}' | JSON, what the poll endpoint reads |
| `error` | TEXT | the message shown when `status = 'FAILED'` |

`run.status` already carries `RUNNING`/`OK`/`FAILED`. No change there.

`progress` holds one entry per source-and-role pair, in the order they will be
attempted, so the screen can render the whole list from the first poll:

```json
{"steps": [{"source": "Indeed",   "role": "BI Developer", "state": "done",    "found": 50},
           {"source": "LinkedIn", "role": "BI Developer", "state": "running", "found": 0},
           {"source": "Indeed",   "role": "Data Engineer","state": "pending", "found": 0}],
 "scraped": 50}
```

`state` is `pending`, `running`, `done` or `failed`. A single source failing is
recorded on its step and does not fail the run — a LinkedIn actor timeout should
not throw away the Indeed results.

---

## What happens to `keywords.yaml`

It splits. The half describing a person moves into resumes. The half describing
language and known technology survives, renamed `vocabulary.yaml` to stop it
accumulating personal data again.

| Section today | Fate |
| --- | --- |
| `title_groups`, `title_scores` | **deleted** — target roles are the titles now |
| `skills` (dbt: 4, sql: 3 …) | **deleted** — comes from the resume, with tiers |
| `seniority` keywords | kept — `senior`, `staff`, `intern` is language, not preference |
| `market_tools` | kept — a dictionary of known technology, used to find gaps |
| `penalties: w2 only, clearance, cpt/opt` | kept — employment constraints |
| `penalties: legacy_tech, frontend_tech` | **replaced** — see below |
| `penalties: exec_penalty` | kept, but fires against the resume's seniority |

`legacy_tech` and `frontend_tech` were hardcoded lists saying React and COBOL are
bad. That is only true for a data person. They are replaced by a **mismatch
penalty**: when the JD names many tools from `market_tools` and almost none are
in the resume's skills, the score drops. Same effect for Ghazal, no hardcoded
domain, and it works for a user whose skills *are* React.

---

## Scoring

Same five-part shape as today, sourced differently. Scored once per active
resume; the highest score wins and its `resume_id` is recorded.

| Part | Rule | Points |
| --- | --- | --- |
| title | the job title contains a target role or one of its aliases, whole-word | 40 |
| | every significant token of some target role appears in the title, in any order — `Senior Engineer, Analytics` against `Analytics Engineer`. Tokens of one and two characters and the stopword set in `vocabulary.yaml` do not count as significant | 25 |
| | at least one significant token matches | 15 |
| | nothing matches | 5 |
| seniority | the JD's band equals the resume's | 20 |
| | one band apart | 12 |
| | two or more apart | 4 |
| skills | each `core` skill or alias found in the JD | 5, capped at 20 |
| | each `working` skill or alias found in the JD | 2, within the same cap |
| constraints | `vocabulary.yaml` penalties — clearance, W2-only, visa, exec | negative, unchanged from today |
| mismatch | see below | up to −20 |

Bands run `junior` < `mid` < `senior` < `exec`, so the distance between them is
an integer. The JD's band is read with the existing `vocabulary.yaml` seniority
keywords; the resume's band is the value the user confirmed.

**Mismatch penalty.** Let `named` be the count of distinct `market_tools` found
in the JD, and `mine` the count of those that are also in this resume's skills or
aliases. When `named >= 4` and `mine / named < 0.25`, subtract 20. When
`named >= 4` and `mine / named < 0.5`, subtract 10. Otherwise subtract nothing.
The floor of four exists so a JD naming two tools cannot be penalised on a
sample size that small. Both thresholds live in `vocabulary.yaml`.

This replaces the hardcoded `legacy_tech` and `frontend_tech` lists. A React-heavy
JD still lands hard for Ghazal, because none of those tools are hers — but it
lands softly for a user whose resume is React, which is the point.

The weights above are seeds, not findings. They reproduce roughly what the
current scorer does so the change is not simultaneously a re-tuning. Validating
them against real outcomes is what the `event` log is for, and is out of scope.

Matching stays word-boundary regex, extended to iterate aliases. This is the
reason the explicit-match core is kept rather than replaced with embeddings:
`CLAUDE.md` requires every recommendation to be explained from evidence the
scorer actually matched. Cosine similarity produces a number and nothing to say.

The rules from the existing specs carry forward unchanged:

- the numeric score is internal, used for ranking only
- the reason sentence is composed from the scorer's breakdown, never invented
- no band may be claimed when no description was captured
- no `match_score` and no bare percentage may reach any rendered page or JSON response

The reason sentence gains one clause: which resume matched.

Existing scored roles keep their old scores until the next run. They were scored
against a keyword list that no longer exists; rescoring them is out of scope.

---

## Screens and routes

```
GET  /                      no active resume -> /setup ; else the map
GET  /setup                 upload form
POST /api/resumes           store file, extract text, LLM parse -> {resume_id}
GET  /setup/confirm/<id>    the confirm screen
POST /api/resumes/<id>      save edited label, roles, skills, seniority
DELETE /api/resumes/<id>    remove a resume and its file
POST /api/profile           location, country, work modes -> sets setup_complete
POST /api/runs              start a scrape -> {run_id}   409 if one is RUNNING
GET  /api/runs/<id>         {status, stage, progress}
GET  /searching/<run_id>    progress screen, polls the above
GET  /profile               add, relabel, deactivate, delete resumes
```

### Upload

PDF only — `pdfminer` is the only extractor present, so anything else is
rejected with a message saying so rather than failing later in parsing. Hard cap
5 MB. Stored at `data/resumes/<user_id>/<sha256>.pdf`; the client's filename is
kept for display and never used to build a path.

### Confirm screen

Shows the parse result and takes the two things a resume cannot state:

```
WE READ YOUR RESUME AS...

  Label          [ bi developer            ]
  Target roles   [BI Developer x] [BI Analyst x]  + add
  Your skills    [Power BI *x] [SQL *x] [DAX x]   + add     * = core
  Seniority      ( ) junior  ( ) mid  (o) senior  ( ) exec

  Where          [ Toronto, ON             ]
  Work mode      [x] remote  [x] hybrid  [ ] onsite

              [ LOOKS RIGHT - START SEARCHING ]
```

Everything is editable, because the whole scoring model rests on this being
right. Location and work mode are asked once, on the first resume; later uploads
skip that block.

### Progress screen

Polls `GET /api/runs/<id>` every 2 seconds and renders per-source, per-role
counts. On `OK` it redirects to the map; on `FAILED` it shows what failed and
offers a retry, and does not silently land on an empty map.

Both new screens follow the existing paper design language used by `map_page.py`
and `activity_page.py`.

---

## The background run

`POST /api/runs` starts a `threading.Thread` and returns immediately with the
`run_id`. One run per user at a time — if a `RUNNING` run exists, the endpoint
returns 409 rather than scraping twice.

**The worker opens its own SQLite connection.** Connections are not shareable
across threads, and this is the most likely place in the whole feature to
introduce a defect. WAL and `busy_timeout`, already set in `db.py`, handle the
overlap between the worker writing progress and the poll endpoint reading it.

The worker writes `stage` and `progress` after each scrape call, then reuses the
existing `persist_run`. Any exception marks the run `FAILED` with the message and
re-raises into the thread, where it is logged. A crashed worker must never leave
a run stuck in `RUNNING`.

Interrupted runs — the process dies mid-scrape — are handled at startup: any
`RUNNING` run belonging to a previous process is marked `FAILED` when the app
boots. Without this, a hard kill locks the user out of ever starting another run.

---

## Consequences in `main.py`

- `run_pipeline` and `run_tailor` stop reading `RESUME_PATH` from `.env` and read
  the active resumes from the store.
- `CANDIDATE_NAME`, `CANDIDATE_EMAIL`, `CANDIDATE_LINKEDIN` and `RESUME_PATH`
  leave `.env`; the `resume:` block and `search.categories` leave `config.yaml`.
  `src/config.py`'s `apply_env_overrides` goes with them.
- `python main.py` with no arguments and no resume on file serves the app at
  `/setup` instead of scraping. There is nothing to scrape for.
- The scrapers gain `location`, `country` and `work_modes` parameters, replacing
  the hardcoded `"remote"`/`"us"` in `indeed.py` and `"Worldwide"` plus
  `remote: ["2"]` in `linkedin.py`:

  | | Indeed actor | LinkedIn actor |
  | --- | --- | --- |
  | remote only | `location: "remote"`, `country` | `location: "Worldwide"`, `remote: ["2"]` |
  | onsite or hybrid only | `location`, `country` | `location`, `remote: ["1"]` and/or `["3"]` |
  | remote plus others | `location`, `country` | `location`, `remote` carrying each code |

  LinkedIn's `remote` codes are `1` onsite, `2` remote, `3` hybrid. Both actors'
  input schemas are third-party and undocumented beyond the notes in
  `indeed.py`; the implementation plan must verify this mapping against a live
  run before the scrapers are switched over, and fall back to today's hardcoded
  values with a logged warning if an actor rejects the input.

Consequences land across ships: the scraper parameters and the `config.yaml`
removals belong to Ship 2, the `main.py` routing change to Ship 3.

---

## Testing

No network in the suite. A fake LLM client returns a canned parse; a fake scraper
returns canned jobs; time is injected where day counts matter.

The background thread is tested by injecting the runner, so the test drives it
synchronously. Threading is left as one thin wrapper rather than a race condition
chased through a test suite.

Specific cases worth naming because they are the ones that will break:

- migrating a version-1 database with existing users, roles and runs
- a second resume upload skipping the location block
- the same file uploaded twice, rejected by `UNIQUE (user_id, sha256)`
- a non-PDF and a 6 MB PDF, both rejected with their own message
- `POST /api/runs` while one is `RUNNING`, returning 409
- a worker that raises, leaving the run `FAILED` rather than `RUNNING`
- a `RUNNING` run from a previous process, cleared at boot
- a job matching two resumes, attributed to the higher-scoring one
- `Senior BI Developer` matching via an alias rather than falling to the floor
- no `match_score` and no percentage in any response from any new route

---

## Ships

**Ship 1 — the profile exists.** Migration to version 2, upload, extract, LLM
parse, confirm screen, `/profile`. Search and scoring still run off
`config.yaml` and `keywords.yaml`. Nothing changes on the map, and `/` still
goes straight to it — the new screens are reached by URL until Ship 3.

**Ship 2 — the profile drives everything.** `vocabulary.yaml` split, scorer
rewritten against resumes, scrapers take location and work modes, resume
attribution reaches the reason sentence and the map.

**Ship 3 — it runs itself.** Background run, progress screen, `/` routing on
setup state, stale-run cleanup at boot.

Ship 1 is inert on its own and that is intended — it is the migration and the
data, landed before anything depends on it. Ship 2 is where the tool starts
working for a second person. Ship 3 removes the terminal.

---

## Out of scope

- Resume tailoring per job. Named as a future goal; the model here supports it —
  a tailored output can become a new `resume` row — but nothing is built for it.
- Embeddings or semantic matching. A dependency and a per-job cost, buying
  ranking that cannot be explained in a sentence.
- Importing a skill taxonomy (ESCO, O\*NET, Lightcast). Aliases from the parse
  LLM cover the synonym problem at upload time without a 14,000-row import.
- Validating scoring weights against outcomes. The `event` table was built as the
  training data for this. It needs rows first.
- Rescoring roles stored before this release.
- Authentication, hosting, multi-tenancy.
