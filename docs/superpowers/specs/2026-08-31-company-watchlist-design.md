# Company watchlist — Ship 10 design

Date: 2026-08-31
Status: proposed

## Why

The map answers "what is open to me this week?" A user also has the
inverse question: "the companies I know hire people like me — what do
THEY have open?" DataArt and EPAM employ from Armenia whether or not this
week's boards say anything, and their openings are worth hearing about
the Monday they appear.

Run 9 (the first scheduled weekly run) sharpened the need: a whole week
of the boards produced **zero new open roles**. The eligible pool
measures ~18 postings a month; being early to a watched company's posting
is worth more than another source of the same boards.

## The resolution ladder (the user's design)

Companies publish jobs in one of three ways, so each watched company gets
a `resolution`, detected once and stored:

| Rung | Who | Mechanism | Cost |
|---|---|---|---|
| 1. `ats` | Remote-first product companies (GitLab, Supabase, Wikimedia…) | `fabro.dev/company-career-page-jobs` resolves Greenhouse/Lever/Ashby/Workable/SmartRecruiters/Recruitee/Rippling from a domain | $0.002/job, proven: 15 data roles from 10 companies |
| 2. `linkedin` | Companies that post to LinkedIn (EPAM, SoftServe, Luxoft, Sigma) | `companyName`/`companyId` filter on the LinkedIn actor we already run — proven honoured and pure | marginal |
| 3. `custom` | Companies on bespoke portals that skip LinkedIn (DataArt) | one adapter per company, browser-rendered | the expensive rung, entered last |

Measured resolution of the user's six, all live-probed 2026-08-28/31:

| Company | ATS? | LinkedIn 30d | Resolution |
|---|---|---|---|
| EPAM Systems | no | 25/25 pure | `linkedin` |
| SoftServe | no | 25/25 pure | `linkedin` |
| Luxoft | no | 25/25 pure | `linkedin` |
| Sigma Software | no | 4/4 pure | `linkedin` (also reaches us via WWR) |
| Andersen | no | ambiguous — "Andersen" returns Andersen Corporation (windows manufacturer) 10/15 | `linkedin` **by `companyId`**, never by name |
| DataArt | no | **0 rows under every plausible name** | `custom` — the only one |

The ladder is checked in order at watch time, and the answer is stored,
not re-derived per run. A company's resolution can be re-detected on
demand (they migrate ATSes).

## What we are building

### 1. The watchlist, per user

`watch_company(user_id, name, domain)` → detect resolution → store.
A table, not vocabulary.yaml: which companies a user watches is about a
person, and nothing about a person may enter the vocabulary.

```sql
CREATE TABLE watched_company (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES user(id),
    name         TEXT NOT NULL,      -- display name
    domain       TEXT,               -- for the ats rung
    resolution   TEXT NOT NULL CHECK (resolution IN
                     ('ats','linkedin','custom','unresolved')),
    linkedin_name TEXT,              -- exact companyName, when it differs
    linkedin_id   TEXT,              -- companyId, for ambiguous names
    created_at   TEXT NOT NULL
);
```

Schema v10. `unresolved` is a real state, shown to the user — a company
we could not place on any rung is a fact, not an error.

### 2. A third source in the run: "Watched companies"

One step per run (not per company): rung-1 companies go to the generic
actor in a single call (`companies: [domains]`), rung-2 companies go to
the LinkedIn actor in a single call (`companyName: [names]` /
`companyId`), rung-3 adapters run individually. Rows flow through the
same gates as everything else — relevance, presence, scope. A watched
company's role in a foreign country with no reach evidence is still
foreign; watching a company is a reason to LOOK, not a reason to believe.

The source is allowed to fail per rung, like the boards: one rung
erroring must not take the others down.

Roles from a watched company are marked on the card ("on your watchlist")
and the company map keeps its WATCH state visible. No score inflation:
the watchlist changes what we fetch, never what a role is worth.

### 3. Setup page: manage the list

The existing `/setup` flow gains a watchlist section: add by name +
domain, remove, see each company's resolution and last yield. Seed
suggestions (a static, impersonal list of remote-first companies known to
hire globally — GitLab, Supabase, Wikimedia, Zapier, Deel, Remote.com,
PostHog, Buffer, Doist) are offered, never pre-added.

### 4. The DataArt adapter — the one custom rung

DataArt posts nowhere else, and it is the user's strongest known
Armenia-hirer. Their careers site is JS-rendered, so the adapter needs a
rendering fetch (Apify `apify/rag-web-browser` or a cheap Playwright
actor) — pick at implementation time, whichever reads
`dataart.com/career` reliably. The adapter contract is the same
`scrape()` shape the other sources use, so run_core needs no special
casing beyond the rung dispatch.

If the adapter proves flaky, the fallback recorded here: DataArt also
lists on staff.am (Armenia's local board) — check there before building
anything heavier.

## Testing

- resolution detection: ats hit → `ats`; LinkedIn purity ≥ threshold →
  `linkedin`; ambiguous name with an id → `linkedin` with `linkedin_id`;
  nothing → `unresolved`.
- the run step: one call per rung, not per company; a failing rung leaves
  the others' rows intact; watched rows pass through relevance, presence
  and scope gates unchanged.
- watchlist rows never enter vocabulary.yaml (structure test).
- Andersen fixture: `companyName: ["Andersen"]` rows from Andersen
  Corporation are rejected by the purity check.
- migration v10.

## Out of scope

- Auto-discovering "companies that hire in <country>" (research, later).
- Custom adapters beyond DataArt — each is its own decision, entered only
  after rungs 1–2 measurably fail for that company.
- Notification/email on new watched-company roles; the Monday map is the
  notification for now.
