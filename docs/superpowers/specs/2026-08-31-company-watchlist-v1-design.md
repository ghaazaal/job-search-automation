# Company Watchlist v1 — implementation spec

Date: 2026-08-31
Status: proposed
Supersedes: `2026-08-31-company-watchlist-design.md`, whose review found
ten unsupported assumptions; every mechanism below is probe-verified or
explicitly marked as a decision.

## The mental model

> **Watching a company changes where we search, not what qualifies as a
> job for the user.**

This is the load-bearing sentence. A watched company's rows enter the
existing pipeline at the earliest possible point and pass through every
gate — relevance, presence, scope, scoring — unchanged. There is no
watched-jobs table, no watched scoring, no watched map. Any future change
of the shape `if watched: include = True` violates this spec.

## Pre-implementation validation (run 2026-08-31, live actor)

The prior spec's rung 2 hung on `companyId`. Validation was made blocking
because this actor has already demonstrated that a schema parameter can
be silently dead (`remote:`, Ship 7).

| Experiment | Input | Result | Verdict |
|---|---|---|---|
| E1 | `companyId: ["epam-systems"]` | 10 rows: Two Maids, ProService Hawaii, U-Haul… | not filtering |
| E2 (control) | `companyId: ["zzz-no-such-co-987654"]` | **10 rows of random companies** | **`companyId` is dead** — ignored, not erroring |
| E3 | `companyId` array of 2 | random companies | dead at any arity |
| E4 | `companyName: ["EPAM Systems", "Luxoft"]` | 23 Luxoft + 2 EPAM, **0 others** | **name arrays batch as OR, pure** |
| E0 | rows carry `companyUrl` | Andersen-the-IT-firm = `/company/andersenus`; its `companyName` is the bare, colliding "Andersen" | slug is the disambiguator `companyId` was supposed to be |

**Consequences, baked into this spec:**
- `companyId` is never used. It appears nowhere below.
- Rung 2 fetches by **batched `companyName`** (E4) and verifies at ingest
  by **exact name plus, when stored, `companyUrl` slug** (E0).
- A shared `limit` spans the whole batch (23/2 skew in E4): the LinkedIn
  watched call sends `limit = per_company × n_companies`, and the skew is
  an accepted v1 characteristic, recorded on the run row via yields.

## Objective

A user watches companies by name; every run additionally fetches those
companies' postings via the cheapest working source; the rows ride the
existing pipeline; the map shows what survives, marked as watched.

## Source resolution strategy — not authority

```
try ATS (needs domain) → else try LinkedIn (name, slug if ambiguous) → else unresolved
```

**Resolution determines the source used for ingestion; it does not
establish source authority.** When company sources later become
first-class (a company with ATS + LinkedIn + portal at once), v1's single
`resolution` reads as "the source v1 ingests from," and nothing here
needs undoing. Sigma Software is the recorded example of what v1
deliberately leaves on the table: it resolves `linkedin` (4 jobs) while
its own portal lists 66.

Resolution is **lazy**: attempted at the start of the watched step of the
next run, never inside a Flask request (an actor probe is 30s+; the POST
returns immediately with `unresolved — pending next run`). Probes per
first resolution: at most one `fabro.dev/company-career-page-jobs` call
(domain present) and one LinkedIn call. An exact-name LinkedIn probe
whose rows show more than one distinct `companyUrl` slug is **ambiguous**:
it stays `unresolved` with `resolution_note` asking the user to paste the
company's LinkedIn URL — the Andersen rule, enforced without a purity
threshold.

## Data model — migration v10

One table, three concept groups kept visually distinct so the schema does
not become an accidental blob:

```sql
CREATE TABLE watched_company (
    id                  INTEGER PRIMARY KEY,

    -- identity ---------------------------------------------------------
    user_id             INTEGER NOT NULL REFERENCES user(id),
    company_name        TEXT NOT NULL,          -- display name, user's words
    company_fingerprint TEXT NOT NULL,          -- tracker.dedup.fingerprint(name)
    domain              TEXT,                   -- enables the ATS probe

    -- resolution -------------------------------------------------------
    resolution          TEXT NOT NULL DEFAULT 'unresolved'
                        CHECK (resolution IN ('ats','linkedin','custom','unresolved')),
    resolution_note     TEXT,                   -- why unresolved, user-facing
    linkedin_name       TEXT,                   -- exact companyName to batch and match
    linkedin_slug       TEXT,                   -- from companyUrl; REQUIRED when the name is ambiguous
    resolved_at         TEXT,

    -- execution --------------------------------------------------------
    last_fetched_at     TEXT,
    last_yield_count    INTEGER,

    created_at          TEXT NOT NULL,
    UNIQUE (user_id, company_fingerprint),
    CHECK (resolution != 'linkedin'
           OR linkedin_name IS NOT NULL OR linkedin_slug IS NOT NULL)
);
```

Decisions, with reasons:
- **`company_fingerprint` is the join path** to `company` rows (for the
  card marker), because a `company` row is not guaranteed to exist before
  ingestion creates it. This inherits the documented fingerprint
  weakness — "Proxify" and "Proxify AB" fingerprint apart — accepted for
  v1; a global company identity is explicitly not this milestone.
- **`custom` is in the CHECK but unreachable in v1 code.** SQLite cannot
  extend a CHECK without a table rebuild; one inert enum value now is
  cheaper than a rebuild migration later.
- The `linkedin` invariant lives in the schema, not Python — this store's
  stated philosophy ("a status typo should be rejected by the database").
- `unresolved` is a real, shown state, never an error.

## Components

| Piece | File | Nature |
|---|---|---|
| store CRUD + resolver persistence | `src/store/watchlist.py` (new) | thin, transactional |
| resolver + both fetch rungs | `src/scrapers/watched.py` (new) | wraps `call_actor`; same `scrape()`-shaped contract as siblings |
| run integration | `src/run_core.py` | two steps — `("Watched companies", lane="ats")`, `(…, lane="linkedin")` — planned only when the watchlist is non-empty; per-step failure isolation exactly as sources have today |
| ingest filter | inside `watched.py` fetch, before rows leave it | exact `companyName` match; slug match when `linkedin_slug` stored; mismatches counted, logged, discarded |
| routes | `src/app.py`: `GET` list via setup page, `POST /api/watchlist`, `DELETE /api/watchlist/<id>` | POST returns immediately; no probe in-request |
| UI | `src/setup_page.py` watchlist section | add (name + optional domain + optional LinkedIn URL), remove, per-company: resolution, note, last yield |
| card marker | `_role_view`/`map_page` | "on your watchlist", via fingerprint match |

Batching: rung `ats` = **one** generic-actor call with every `ats`
domain; rung `linkedin` = **one** LinkedIn call with every
`linkedin_name`. Two actor calls per run for any watchlist size (plus
first-resolution probes for new rows).

Seed suggestions: a static, impersonal list (GitLab, Supabase, Wikimedia,
Zapier, Deel, Remote.com, PostHog, Buffer, Doist) rendered as one-click
adds, never pre-added. It stays in this milestone because it is the only
part with measured yield for the working profile (Supabase
"Remote, Global").

## Workflow

```
POST /api/watchlist {name, domain?, linkedin_url?}
  → row stored, resolution='unresolved' (note: "pending next run")
next run, watched step:
  → resolve any unresolved rows (≤2 probes each, results stored)
  → one ATS call for ats-rows, one LinkedIn call for linkedin-rows
  → ingest filter (exact name / slug)
  → rows join the run's job stream BEFORE dedupe
  → dedupe → gates → scope → scorer → store → map, unchanged
  → last_fetched_at / last_yield_count updated per company
```

## Expected initial yield — stated, not hidden

The six-company validation set (EPAM, SoftServe, Luxoft, Sigma, Andersen,
DataArt) is **not expected to produce visible Armenia-eligible roles
through the LinkedIn source**: measured over 30 days they posted 4 data
roles, all US-anchored, and the presence/anchor gates will rightly close
them. **This milestone validates the ingestion architecture, not the
commercial usefulness of the initial company set.** The seed-suggestion
companies are where visible yield is plausible. These are different
experiments, and conflating them is how a working feature gets judged a
failure.

## Failure states

- A rung's actor call fails → that step is `failed`; the other rung and
  all other sources are untouched.
- Resolution probes fail → row stays `unresolved` with a note; retried
  next run; never blocks the run.
- Ambiguous LinkedIn name without a slug → `unresolved` + note; never
  fetched by bare name.
- Ingest filter rejections (wrong company in the batch) → counted and
  logged, never stored.
- Empty watchlist → steps not planned; zero cost.

## Acceptance criteria

1. EPAM, SoftServe, Luxoft, Sigma resolve `linkedin`; GitLab and Supabase
   resolve `ats`; DataArt resolves `unresolved` (fact, shown to user).
2. "Andersen" without a LinkedIn URL stays `unresolved`; with
   `linkedin.com/company/andersenus` pasted it resolves and only
   `andersenus` rows survive ingest.
3. Any-size watchlist adds exactly two fetch calls per run.
4. A watched hybrid role in London is still dropped by the presence rule.
5. **A watched company bypasses no existing eligibility, geography,
   relevance, or scoring logic** — the hard invariant, tested, and the
   review gate for every future change touching this feature.
6. `python -m pytest` green from repo root and `job_hunt/`; migration v10
   applies to a populated v9 store.

## Tests

- resolver matrix: domain+ATS-hit → `ats`; no-domain+clean-name →
  `linkedin` with stored exact name; multi-slug name → `unresolved`+note;
  slug supplied → `linkedin`; probes erroring → `unresolved`, run OK.
- batching: one call per rung regardless of company count (spy fixtures).
- ingest filter: E4-shaped fixture (mixed batch) keeps only exact-name
  rows; Andersen fixture keeps only `andersenus` slug rows.
- invariant: watched rows flow through `_apply_gates`/`_apply_scope`
  unchanged (same fixtures as the presence/anchor tests, watched flag on).
- store: v10 migration, UNIQUE collision, the `linkedin` CHECK invariant,
  fingerprint join to `company`.
- routes: POST returns before any probe runs; DELETE removes fetch
  participation next run.

## Amendment 2026-09-01 — the DataArt adapter, built

The non-goal below deferred DataArt because it was believed
browser-rendered at an unknown URL. The user supplied the real URL
(dataart.team, not dataart.com) and measurement overturned every
premise: the portal is a JS shell over a PLAIN JSON API
(`/dataart-team/api/vacancies/filter-fields-page`), fetchable with one
HTTP GET, country-filterable by an id resolvable from the API's own
countries list. The adapter is `scrapers/dataart.py` — one module, no
framework; the trap the non-goal guarded against was abstractions, and
none was built. Dispatch is a dict literal keyed by fingerprint in
`watched.py`; the `custom` lane is planned only when a custom-resolved
row exists.

Measured at build time: Armenia shows 10 distinct vacancies (the page's
"68" is pagination echo), currently 0 matching the user's data titles —
the watch's value is the Monday that changes.

## Non-goals

- **Custom adapters beyond DataArt** (see Amendment). Trigger to revisit: 5–10 real
  companies measurably failing both rungs — an abstraction for n=1 is
  the trap this spec exists to avoid. DataArt's staff.am presence is an
  **unverified** lead, recorded as exactly that.
- `companyId` (dead — see validation), source authority, multiple
  concurrent sources per company, global company identity, re-detect
  endpoints (delete + re-add covers it), notifications, per-company
  scheduling, auto-discovery of companies hiring in a country.
