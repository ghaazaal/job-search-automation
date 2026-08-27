# Search lanes, relevance, and store cleanup — design

Date: 2026-08-27
Status: proposed
Supersedes: the probe mechanism from
`2026-08-26-badge-probe-eligibility-tiers-design.md`

## Why

Two independent faults, both found by live measurement.

**The LinkedIn probes never worked.** The `remote:` key the scrapers send
is not a parameter valig accepts; Apify drops unknown keys silently, so
both probe lanes ran the same unfiltered search. Same search, 25 results:

| What was sent | Hybrid set vs on-site set |
|---|---|
| `remote: ["3"]` / `["1"]` (shipped code) | 9 job IDs in **both** |
| `urlParam f_WT=3` / `=1` / `=2` / `=1,3` | `f_WT=3` ≡ `f_WT=2`; `f_WT=1` ≡ `f_WT=1,3` |
| `keywords: "hybrid …"` / `"remote …"` | **0** job IDs in both |

Overlapping URLs are claimed by `probe hybrid`, re-claimed by
`probe onsite`, hit the conflict branch and collapse to `""`. 400 probe
results produced 7 verified roles, all of them page-2 ranking jitter.

**41% of the store is the wrong job.** 325 of 800 stored roles are not
data roles at all — Nurse Practitioner, Travel Advisor, Fleet Parking
Specialist, SAT Test Prep Tutor. 269 came from Indeed. The scorer rates
them 1–4 out of 10; nothing stops them being stored.

Read together: the pipeline stores the wrong jobs, then reasons carefully
about whether those wrong jobs are eligible.

## The real funnel

Applying a relevance gate first, against the current profile (Yerevan,
Armenia, remote only):

| Gate | Roles |
|---|---|
| wrong job entirely | **325** |
| data role, abroad, not remote | 418 |
| data role, in Armenia | 22 |
| data role, remote, no description | 23 |
| data role, remote, provably closed | 4 |
| **data role, remote, unclear** | **8** |
| **proven open to Armenia** | **0** |

Not one job in 800 proves it will hire from Armenia. That is the number
this ship has to move.

## What we are changing

### 1. Relevance gate — new, and first

A role is stored only if its title names a role the user searches for.
Keyword-in-title is not enough: it matched "Quantitative **Analyst**",
"Urban **Data** Platforms", "**Data** Center & Edge Infrastructure".

- Match against whole role phrases (`data analyst`, `analytics engineer`,
  `bi developer`, `business intelligence`, `data engineer`,
  `product analyst`, `data scientist`), word-bounded.
- Maintain an exclusion list for the traps measured above:
  `data center`, `data centre`, `data entry`, `quantitative analyst`,
  `infrastructure`.
- Roles failing the gate are not stored at all. They are counted on the
  run row so the drop is visible, never silent.

All three sources also filter server-side, which is cheaper than
filtering after paying per result:

- **Indeed**: `title:"Data Analyst"` — **one title per search**. Measured:
  a single title returns 15/15 on-target; combining titles with `or`
  collapses to 11/20, and `-intern` is ignored inside a combined query.
  So run one Indeed search per role title.
- **LinkedIn**: valig's `titleInclude` / `titleExclude`, already paid for
  and currently unused.
- **Remote boards** (part 3): `searchTerms` matches titles by default.

Server-side filtering reduces what we pay for; it does not replace the
gate. All three still leaked the "Data Center" trap in testing.

### 2. Fix the Indeed search

Today's payload puts the work mode in the location box:

```
query = "data analytics",  location = "remote"
```

Indeed then returns the string "Remote" in each item's location field —
our own query reflected back. Four of the eleven roles reviewed by hand
were admitted on that basis alone, and one of those actually reads
"Remote (United States)".

Replace with Indeed's real attribute filter:

```
keyword  = title:"Data Analyst"     # one title per search
location = <the user's country or region>
country  = <ISO>
remote   = "remote"                 # kaix's Indeed remote filter
```

Measured: 20/20 results came back with publisher-stated
`workArrangement.locationType = "Remote"` and real city locations, not
the echoed string.

This requires the `kaix/indeed-scraper` swap, which therefore moves into
this ship rather than the next one. It also brings `signals.isExpired`,
`dates.validThrough`, 90% salary coverage and structured
`location.country`, at $0.05/1K versus the current $0.10/1K.

### 3. Add remote job boards as a fourth source

Indeed and LinkedIn carry almost nothing this user can take. Measured
against the same profile:

| Source | Jobs | Open to Armenia |
|---|---|---|
| LinkedIn + Indeed | 800 | **0** (0%) |
| Remote boards | 50 | **11** (22%) |

One run of `flash_scraper/remote-job-aggregator` returned more applicable
roles than four full LinkedIn/Indeed runs produced in total. It sweeps
ten public boards (RemoteOK, We Work Remotely, Working Nomads, Remotive,
Jobicy, Himalayas, The Muse, DevITjobs US/UK, HN "Who is hiring?") into
one deduplicated feed at $0.002/job — cheaper than the current LinkedIn
actor.

Two properties make it a better fit than either incumbent:

**Eligibility is a published field, not prose.** Observed location values:

```
"Anywhere in the World"
"Europe, North America, Latin America, APAC"
"Time zone: CET (+/- 3 hours)"
"United States"
```

These boards state reach as a field because being borderless is their
product. Most of the phrase-mining in parts 6 and 8 is unnecessary here —
parse the location field directly, and fall back to text rules only when
it is empty.

Add a `location_scope` parser recognising: `anywhere in the world` /
`worldwide` / `any` → open; a region or country list → membership test
against the user's country; a timezone band (`CET (+/- N hours)`) →
compare against the user's UTC offset. Yerevan is UTC+4 and CET+3 is
UTC+4, so the Proxify posting qualifies exactly — timezone bands must be
computed, not treated as unknown.

**`searchTerms` matches job titles**, so the relevance gate from part 1
is enforced server-side before we pay per row.

Integration rules:
- The source is **allowed to fail**. It has 14 users and no ratings, one
  board (Jobicy) failed mid-run during testing, and a run took 5 minutes
  versus 20 seconds for valig. If it errors or returns nothing, the run
  continues on the other sources and the run row records the failure.
- It does **not** replace LinkedIn or Indeed. Those still carry the 22
  local Armenian roles and everything hybrid.
- The relevance gate still applies: 6 of the 50 test rows were the same
  "Data Center" trap (Mechanical and Electrical Engineers at data
  centres).

If it proves unreliable, `get_anything/remote-jobs-aggregator` and
`hyperbach/remote-jobs-feed` cover the same boards;
`hyperbach` additionally retains postings after they close, which would
also satisfy rule 6e for non-Indeed sources.

### 4. Delete the probe mechanism

- Remove `probes` from `plan_steps` and the `probe` branch in the run
  loop (`run_core.py`).
- Remove `probe_badges`, the badge-vs-text reconciliation, and
  `RunResult.badge_hits`.
- Remove the `remote` argument from `linkedin.scrape` and `_filters_for`.
- Remove `search.probes` from `config.yaml`.

Nothing downstream loses information, because the mechanism never
produced any.

### 5. LinkedIn keyword lanes

A user may tick any subset of remote/hybrid/onsite at setup
(`profile.WORK_MODES`), so lanes are derived, never hardcoded:

```
lanes = [m for m in profile.work_modes if m in ("remote", "hybrid")]
```

| User ticked | Keyword lanes run |
|---|---|
| remote | `"remote <role>"` |
| remote + hybrid | `"remote <role>"`, `"hybrid <role>"` |
| hybrid + onsite | `"hybrid <role>"` |
| onsite only | *none* — local lane only |

**No on-site lane.** Measured precision: remote 5/5, hybrid 3/4,
on-site 1/3. On-site fails because companies advertise "remote" and
"hybrid" as selling points but rarely write "this job is on-site" —
there is no word to match. It also overlapped the hybrid lane on 3 of 23
IDs, where remote and hybrid overlapped on 0.

On-site is inferred by elimination. A user who ticks on-site is served
entirely by the local lane, which already searches their actual place
with every work mode.

Lane membership is **evidence, not proof** — Bedrock Robotics landed in
the hybrid lane with no work-mode statement at all. It enters the
existing tier system below a stated fact:

| Lane says | `work_mode()` says | Result |
|---|---|---|
| remote | remote | verified, full-confidence wording |
| remote | *silent* | stored, reduced-confidence, ranks below verified |
| remote | hybrid | conflict — claim nothing, as today |

### 6. Eligibility rules, from hand-reviewed postings

Eleven remote data roles were read by the user. Three were open; eight
were not. Each rule below traces to a specific one.

**6a. Never treat a location field of "Remote" as evidence.** It is the
query reflected back. Admitted jobs 1, 5, 6, 7 — including one reading
"Remote (United States)". Applies to all 297 stored Indeed rows.

**6b. Remove `"work from home"` from `remote_phrases`.** It fired on 4
wrong roles and 3 right ones. Job 11 is the clearest failure — standard
UK flexible-working boilerplate:

> "you may work from home or another suitable location that meets
> business needs"

**6c. Add `"(from anywhere)"` and `"work from anywhere"` as open
evidence.** Fired on exactly the three roles the user marked OPEN, and
nothing else.

**6d. Add closed-eligibility phrases**, all observed verbatim:
`remote (united states)`, `remote - united states`,
`remote, united states`, `fully remote / u.s.-based`, `u.s.-based`,
`us-based`, `remote within the united states`, `u.s.-based only`,
`authorized to work in the us`, `will not sponsor`, `unable to sponsor`,
`no visa sponsorship`, `not eligible for immigration sponsorship`,
`must reside in one of the following states`, `w2 only`, `1099/c2c only`.

**6e. Drop closed postings.** Job 4 reads "No longer accepting
applications" and that text is not in our stored description, so it
cannot be detected today. Indeed via `kaix` supplies `signals.isExpired`
and `dates.validThrough`. LinkedIn supplies nothing, so a LinkedIn role
can only be checked by re-fetching its page — deferred, and recorded as
a residual.

All additions remain phrases, never bare words.

### 7. Read the fields already paid for

valig returns 20 fields; `linkedin.py` reads 8.

| Field | Coverage | Use |
|---|---|---|
| `contractType` | 20/20 | employment type — captured nowhere today |
| `experienceLevel` | 20/20, "Not Applicable" ×14 | seniority, publisher-stated |
| `applicationsCount` | 20/20 | competition ("Over 200" vs "first 25") |
| `id` | 20/20 | stable key, no URL normalisation |

Add `employment_type`, `applicants`, `source_job_id` to `role`.

Do **not** map valig's `workType` to work mode. Despite the name it
carries LinkedIn's *job function* — measured values include
"Information Technology", "Legal", "Health Care Provider".
`cheap_scraper` has the identical misnaming.

### 8. Widen the work-mode phrase list

Of 479 stored LinkedIn roles with a description but no work mode, 122
mention a work-mode word: 66 are missed wordings, 53 correctly ignored
(`hybrid cloud`), 3 conflicts. The conflict rule is not the problem.

Add to `hybrid_phrases`: `hybrid –`, `hybrid -`, `hybrid |`,
`location: hybrid`, `days a week in office`, `office N days per week`.
Add to `remote_phrases`: `remote eligible`, `performed remotely`.

The 66 is an upper bound from a broad regex — spot-check 20 first.

### 9. Re-evaluate and drop stored roles

Runs per user, against that user's own country and selected modes.
One-off for existing rows; new rows are filtered at scrape time.

Order matters — the widened list and new eligibility rules must run
before anything is dropped:

1. Apply the relevance gate (part 1).
2. Re-run `work_mode()` with the widened list, ignoring any location
   field of "Remote" (rule 6a).
3. Re-run `location_country()` and `geo_verdict()` with the new
   eligibility phrases (rules 6c, 6d).
4. Apply the keep test.

```
keep(role, user):
    if not relevant_title(role.title):     return False
    if role.expired:                       return False
    country = location_country(role.location)
    if country == user.country:            return True
    if country is None and not remote_claim(role):
                                           return True   # unknown -> keep + flag
    if remote_claim(role):
        if closed_elsewhere(role):         return False
        return "remote" in user.work_modes
    return False
```

Guard rails:
- Roles with any `application` row are never dropped. A job the user has
  acted on stays, whatever the rules say.
- Drops are soft: add `role.dropped_at` (nullable TEXT, schema migration
  v6) and exclude from the map rather than `DELETE`.
- The migration reports counts per branch to the run log.
- A role whose country cannot be parsed is kept and flagged. Silence
  about *location* is still silence.

## Testing

- **Relevance gate**: the measured traps as fixtures — "Quantitative
  Analyst", "Urban Data Platforms", "Data Center & Edge Infrastructure",
  "Fleet Parking Specialist" all rejected; the user's four real titles
  all accepted.
- **Indeed payload**: asserts `location` is never the string "remote"
  and that `remote="remote"` is sent instead; one search per title.
- **Rule 6a**: a role whose only remote evidence is `location == "Remote"`
  makes no remote claim.
- **Rule 6b**: the UK boilerplate sentence yields no work mode.
- **Rules 6c/6d**: one test per phrase, plus false-positive guards
  (`hybrid cloud`, `remote teams`).
- **`workType` guard**: a test asserting `workType` never reaches
  `work_mode`, with the real measured values as fixtures. This is the
  trap most likely to be reintroduced.
- **`location_scope` parser**: the four measured shapes as fixtures —
  `"Anywhere in the World"` → open; `"United States"` → closed for an
  `am` user; `"Europe, North America, Latin America, APAC"` → membership
  test; `"Time zone: CET (+/- 3 hours)"` → open for UTC+4, closed for
  UTC-5. Empty or unparseable falls through to the text rules and claims
  nothing on its own.
- **Fourth source fails safe**: with the aggregator erroring or returning
  zero rows, the run still completes on the other sources and the run row
  records the failure.
- **Probe removal**: `plan_steps` emits only worldwide and local lanes.
- **Lane construction**: parameterised over all seven non-empty work-mode
  selections.
- **Migration**: each branch of `keep()`, the application-row guard, the
  unparseable-country keep, and ordering (a role rescued by the widened
  list is not dropped).
- **Live check after merge**: rerun; confirm no probe steps, both keyword
  lanes present, off-target titles counted and not stored, and the map's
  kept-count matches the migration's reported keep.

## Accepted residuals

- **The aggregator is unproven.** 14 users, no ratings, published days
  ago, one board failed mid-run, 5 minutes per run against valig's 20
  seconds. The fail-safe integration carries this. Trigger: two
  consecutive failed runs, or a run under 10 rows, moves us to
  `get_anything/remote-jobs-aggregator` or `hyperbach/remote-jobs-feed`.
- **"Anywhere in the World" is We Work Remotely's tag, not the
  employer's words.** We have not verified that those nine postings
  honour it. Trigger: spot-check five against their apply pages before
  the tier promotes them to verified; until then they are evidence, not
  proof, and rank with the reduced-confidence tier.
- **The 22% figure comes from one 50-row run on one day.** It could as
  easily be 10% or 35%. Re-measure after the first scheduled run.
- **LinkedIn expiry is undetectable.** Rule 6e covers Indeed only.
  Detecting a closed LinkedIn posting needs a per-job re-fetch. Trigger:
  if users report applying to closed roles, add the fetch.
- **Lane precision is measured on one search, one location, one day** —
  remote 5/5, hybrid 3/4, on-site 1/3, n small. Re-measure across the
  user's four real titles before trusting the hybrid lane at 75%.
- **Hybrid-lane false positives are known and unfixed** (Bedrock
  Robotics). The reduced-confidence tier carries them. Trigger: if
  hybrid-lane roles with silent descriptions exceed ~30% of the lane,
  demote the lane to evidence-only.
- **The eligibility rules come from 11 hand-reviewed postings.** Small.
  They are additive and phrase-bounded, so a wrong one under-claims
  rather than over-claims, but they need re-checking against a larger
  sample after the first clean run.
- **`role.country` and `role.location` are two country signals with no
  stated precedence.** Ship 7 added `role.country` (structured, lowercase
  ISO, from kaix's `location.country`). `location_country()` still
  derives its own guess from the free-text `location` and nothing yet
  says which wins when both exist. This matters directly to part 9's
  cleanup, whose `keep()` test calls `location_country(role.location)` —
  it should prefer `role.country` where present, since that is the
  publisher's structured answer and the text parse is a heuristic that
  cannot tell "Chennai, IN" from "Gary, IN". Decide the precedence
  explicitly in Ship 8 rather than leaving two sources of truth.

- **The relevance gate is a fixed data-professional list, not per-user.**
  `vocabulary.yaml`'s `roles.include` names the market's data-role titles.
  That satisfies the vocabulary rule (market facts, not a person), and the
  scorer still judges per-user fit from the resumes. But a user whose
  resumes target a different profession would have every genuine posting
  rejected as off-topic, and the run would look empty rather than
  misconfigured. `search_titles()` already extracts each user's own
  `target_roles` from their resumes, so a per-user include list is
  reachable — the open question is whether it is *better*, since a user
  listing "Data Analyst" would then stop matching "Business Intelligence
  Analyst", losing the market synonyms the fixed list provides.
  Trigger to revisit: the first non-data user, or any run where the
  off-topic count approaches the scraped count.

- **The relevance exclusion list is hand-maintained** and will drift as
  new trap titles appear. Trigger: review it whenever an off-target role
  reaches the map.
- **LinkedIn does not publish workplace type to logged-out clients.**
  Confirmed three ways: direct scrape of the guest endpoint (criteria are
  exactly Seniority level, Employment type, Job function, Industries),
  `cheap_scraper`'s own documentation, and valig and `cheap_scraper`
  returning an identical four-field set. No vendor can sell this.

## Corrections after review

Three faults found reviewing the implementation, all fixed on the branch.

### The "worldwide" lane was not worldwide

`execute` passed the profile's own location to the lane named worldwide.
Deleting LinkedIn's `_filters_for` (part 4) removed the last thing that
made the two lanes differ, so they sent identical payloads:

```
Indeed   worldwide  location="Yerevan, Armenia" country=AM fromDays=7
Indeed   local      location="Yerevan, Armenia" country=AM fromDays=7
LinkedIn worldwide  location="Yerevan, Armenia"
LinkedIn local      location="Yerevan, Armenia"
```

For LinkedIn this held for every user with a location set; for Indeed
whenever `_remote_filter` returned "" for both lanes, which is any
multi-mode selection. Two billed searches per title per source for one
question, `scraped` double-counted, and no reach past the user's own
country — in a ship whose entire premise is that this user's country
carries nothing.

**Fixed two ways.** The worldwide lane now sends `_LANE_WORLDWIDE`, the
same value the mode lanes already used. And Indeed is dropped from the
worldwide lane entirely (`_LOCAL_ONLY`): kaix is country-scoped by
construction, so its worldwide lane could only ever have been the local
one wearing a different name. Nothing measurable is lost — for a US user
the local lane already *is* the US board, and for a user outside it that
board returned zero eligible roles across 800. Worldwide reach is the
LinkedIn mode lanes and the remote boards, which are the sources that
carry it.

### The bare word "anywhere" claimed the whole world

`location_scope.worldwide` listed `"anywhere"` alongside the certain
phrases, and that list is checked first and returns "open" outright.
Measured against the real vocabulary with `user_country="am"`:

| Reach field | Was | Now |
|---|---|---|
| `Anywhere in the World` | open | open |
| `Anywhere in the United States` | **open** | closed |
| `Anywhere in the US` | **open** | closed |
| `Anywhere in Europe` | **open** | unknown |
| `Anywhere` | open | open |

The first two are precisely the US-only postings rule 6d exists to
exclude. The third contradicted `eligibility.regions`, which deliberately
leaves the Caucasus out of "Europe" — and which this parser's own
docstring says it defers to.

The bare word still has to be read: Remotive and Jobicy publish it alone.
So it moves to `worldwide_unqualified` and is checked **last**, after a
named country or region has had its say. A qualified "anywhere" defers to
its qualifier; "Anywhere in Europe" stays unknown, since region absence
never claims exclusion either.

### The test suite would not collect from the repo root

`test_location_scope.py` and `test_relevance.py` read `vocabulary.yaml`
by cwd-relative path at module level, so `pytest job_hunt/tests` from the
repo root raised `FileNotFoundError` during collection and ran nothing at
all. Both now use `Path(__file__).parent.parent`, as every sibling does.
`test_work_mode.py` had the same read inside a test body — pre-existing,
one line, fixed alongside so the suite passes from either directory.

### Deferred to Ship 8

Four further findings from the same review, none of which change what a
user sees today:

- Mode-lane evidence is lost to dedupe whenever the plain lane returned
  the same posting first — which is the case the lane exists to serve.
- Remote boards are planned for users who never selected remote; every
  row they return is then dropped or flagged.
- `_countries_named` contradicts its docstring twice: it does use the
  bare `us` alias, and word-bounding does not stop `Ireland` matching
  inside `Northern Ireland`.
- An unrecognised timezone anchor returns "unknown" before the region and
  country checks can answer.

## The finding underneath all of this

The rules above are worth having, but they were never the binding
constraint. The source was.

Of 800 roles scraped from Indeed and LinkedIn, **zero** prove they will
hire from Armenia. The only three the user judged open were all
BairesDev — one Latin American outsourcing firm hiring globally, whose
stored locations read "São Paulo", "Lima", "Veracruz" because that is the
recruiter's office, not the job's. Three jobs, one employer, is not a job
market.

One 50-row run against the remote boards returned 11. Same user, same
titles, same day.

That is why part 3 exists, and why it matters more than parts 6–9. No
amount of phrase-tuning extracts eligible roles from a source that does
not carry them. Expect the map to be small either way: a realistic count
for this profile is tens of roles, not hundreds, and the product should
say so plainly rather than pad the map with roles that will not hire.

## Out of scope

- Switching the LinkedIn actor. `cheap_scraper` returns the same four
  criteria fields as valig at 1.75× the price with a 150-result floor.
- Logged-in LinkedIn scraping, self-hosted guest-API scraping, and
  third-party AI-inferred work arrangement (`fantastic-jobs`).
- `skipJobId` to avoid re-scraping stored postings. Real saving,
  independent of this work.
- Wellfound, Arc.dev and other boards not covered by the aggregator.
  Evaluate only if part 3's eleven boards prove too thin.
