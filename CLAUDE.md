# Job Search Automation — Claude Code Instructions

## Project
Career opportunity mapping product for job-seeking data professionals
(Analytics Engineer, Data Engineer, Data Analyst, Product Analyst).
Ghazal is both the author and a user — build for multiple users, not just her.

Built for a specific person: **a data professional living in a country
the big job boards do not serve, who needs roles they can actually be
hired into from there.** Not "someone who wants remote work" — someone
for whom remote work is the only category that exists.

Scrapes LinkedIn and ten remote job boards via Apify, scores listings
against the job description, and presents company-centred opportunity
maps rather than a flat job list. AI layer: resume parsing, tailoring,
cover letters.

Indeed was removed in Ship 8: it is organised one site per country, 22 of
the 66 countries this product supports have no Indeed site, and run 6
returned HTTP 400 on every call for an Armenian user. See
`docs/superpowers/specs/2026-08-28-eligibility-from-measurement-design.md`.

Dev environment: Windows 11, Python + PowerShell.

Design spec: `docs/superpowers/specs/2026-08-09-career-opportunity-map-mvp-design.md`

### Build order
Phase 1 is three independent features. Ship them in sequence, not together:
1. The map — company entity, ACT_NOW/WATCH/DISCOVER, ranking, evidence.
   Runs on existing scrape data. Single user is fine here.
2. Multi-user shell — resume upload, role confirmation, location + work
   mode, per-user storage. SHIPPED (Ship 1 + Ship 2).
3. People-in-context hints — only if phase 1 gets real use.

## Scoring
Never show a bare number to the user. Every recommendation is explained in
one sentence built from evidence the scorer actually matched — named skills,
seniority band, penalties that fired, location/work-mode fit.

- The numeric score is internal, used for ranking only.
- The reason sentence is composed from the scorer's breakdown. The LLM may
  phrase it; it must not invent the facts.
- Never state a skill-level match when no job description was captured —
  use reduced-confidence wording instead.
- Do not present fabricated precision. `interview_chance` was a hardcoded
  lookup table rendered as a percentage; do not reintroduce that pattern.

Scoring input comes from the user's active resumes in the store, not from a
keyword file. `vocabulary.yaml` holds only language and market facts —
seniority wording, known tools, employment constraints, geography and
work-mode phrasings, point values. Nothing in it may describe a particular
person.

Geography and work mode (Ships 4–6; specs in `docs/superpowers/specs/` are
the authority, including their correction notes and accepted residuals):

- Every claim needs evidence; silence is the default. Phrase rules are
  word-bounded and phrase-only; conflicting evidence claims nothing.
- Flag-never-hide, with TWO user-approved exceptions. Both are counted
  and both are stated on the map — hidden, never silent:
  1. A posting the user cannot physically attend, in a confidently-parsed
     foreign country, is dropped — stated as "N HIDDEN (ON-SITE
     ELSEWHERE)". Two ways to qualify: the posting states a mode the user
     did not search for, OR it states hybrid/on-site, which require being
     there whatever the user ticked. Ticking "hybrid" means hybrid NEAR
     ME; reading it as hybrid-anywhere put 211 of 594 listed roles on the
     live map that the user could not attend — hybrid posts in London,
     Bengaluru and Sydney. Remote is exempt: being elsewhere is the point,
     and reach evidence decides it, not geography. An unparseable location
     still claims nothing and is flagged, not dropped.
  2. The map hides roles a posting's own words rule out, counted in the
     header as NOT OPEN. It does NOT hide the unverified: those were never
     judged rather than judged and rejected, so they are listed, ranked
     below proven-open ones, and say so on the card. Ship 8 hid them too
     and that was wrong — it buried 1055 LinkedIn roles the user could see
     on LinkedIn itself behind a bare number.
  Roles first seen before the relevance gate existed (runs 1-4) are
  soft-dropped via `role.dropped_at` — excluded from map and counts, never
  DELETEd, and never dropped if the user has an application row for them.
- LinkedIn's workplace badge is guest-invisible. Ship 7 deleted the probe
  mechanism (it never filtered anything) and replaced it with keyword mode
  lanes; Ship 8 dropped LinkedIn's plain worldwide lane, since the mode
  lanes ask the same question better. Its local lane stays — a hybrid role
  in the user's own city is one they can work. The local and mode lanes
  never use the scrapers' legacy fallback — silence stays silent.
- Eligibility evidence comes from a published reach field, not from prose.
  Measured over 384 live roles: prose mining found 0 real matches and
  manufactured 3; the reach field found 2 and manufactured none.
- But a board's reach TAG is not the employer's word, and loses to the
  posting's own text. We Work Remotely tagged a US-only Doximity role
  "Anywhere in the World"; Faire the same, while enumerating the eleven US
  states it would hire in. A restriction in the description overrides the
  field; a silent description leaves the field standing, because most
  postings are silent and the field is then all there is. This is NOT the
  usual conflict-claims-nothing rule — the two sources are not of equal
  standing.
- A posting anchored to a foreign country is not this user's, whatever
  mode it claims: "remote" on a posting whose location says Canada means
  remote FROM Canada. This is the weakest rung of the ladder, so a reach
  field or a description stating wider hiring still beats it, and an
  unreadable location claims nothing. Place knowledge comes from offline
  reference datasets (pycountry, geonamescache — 249 countries, 34k
  cities) wrapped by `src/scoring/geo.py`, which answers MEMBERSHIP, not
  resolution: "is this place the user's?" Eligibility never needs to know
  WHICH Dublin a posting means — every Dublin is equally not-Armenia — so
  ambiguity is only fatal when a candidate IS the user's own country, and
  then the answer is silence. Reference data does not belong in
  `vocabulary.yaml`; that file keeps only judgment (phrases, aliases,
  weights).
- Watching a company (Ship 10, `watched_company` table) changes WHERE we
  search, not what qualifies as a job for the user. Watched rows pass
  every gate; `if watched: include = True` is a spec violation
  (`2026-08-31-company-watchlist-v1-design.md`). Resolution (ats /
  linkedin / unresolved) is a source strategy, never authority; the
  LinkedIn actor's `companyId` is dead - batch by exact `companyName`
  and verify the `companyUrl` slug. The one custom adapter is DataArt
  (`scrapers/dataart.py`, their careers JSON API on dataart.team - found
  by the user, no browser needed); a second custom company earns its own
  file, and only 5-10 earn a shared shape.
- Every role stores `eligibility_verified`; unverified cards say
  "location eligibility not verified" and rank below verified ones.
- The first alias in a `vocabulary.yaml` country list IS the display name
  rendered in reason sentences — reordering it is a product change.

## Design System
Always read `DESIGN.md` before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.

Key tokens from DESIGN.md:
- Background: `#0A0E1A`, Surface: `#0D1117`, Border: `#1E2A3A`
- Cyan: `#00D4FF` (primary interactive), Green: `#00D9A3` (approve), Amber: `#F59E0B` (partial), Red: `#E05C5C` (skip)
- Fonts: JetBrains Mono (data/labels/scores) + Inter (body/descriptions)
- Dark mode only — no light mode toggle

## Finalized UI
The job-list dashboard (`job_hunt/src/dashboard.py`, the `JOBS`-array HTML
file) is retired — superseded by the company-centred opportunity map.

The live product is a local Flask app (`job_hunt/src/app.py`):
`GET /` renders the opportunity map (`job_hunt/src/map_page.py`), `GET
/activity` renders the in-flight application board
(`job_hunt/src/activity_page.py`), both reading from the SQLite store
(`job_hunt/src/store/`). Run it with `python main.py --serve`. Scrapes
start from the browser: `POST /api/runs` opens a run, `GET
/searching/<id>` watches it, and `/` redirects to `/setup` until a resume
and a location are on file. The browser run stops after scoring — the LLM
shortlist, resume variants and the Excel tracker still belong to `python
main.py`.
