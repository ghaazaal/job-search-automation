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

Both actors also filter server-side, which is cheaper than filtering
after paying per result:

- **Indeed**: `title:"Data Analyst"` — **one title per search**. Measured:
  a single title returns 15/15 on-target; combining titles with `or`
  collapses to 11/20, and `-intern` is ignored inside a combined query.
  So run one Indeed search per role title.
- **LinkedIn**: valig's `titleInclude` / `titleExclude`, already paid for
  and currently unused.

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

### 3. Delete the probe mechanism

- Remove `probes` from `plan_steps` and the `probe` branch in the run
  loop (`run_core.py`).
- Remove `probe_badges`, the badge-vs-text reconciliation, and
  `RunResult.badge_hits`.
- Remove the `remote` argument from `linkedin.scrape` and `_filters_for`.
- Remove `search.probes` from `config.yaml`.

Nothing downstream loses information, because the mechanism never
produced any.

### 4. LinkedIn keyword lanes

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

### 5. Eligibility rules, from hand-reviewed postings

Eleven remote data roles were read by the user. Three were open; eight
were not. Each rule below traces to a specific one.

**5a. Never treat a location field of "Remote" as evidence.** It is the
query reflected back. Admitted jobs 1, 5, 6, 7 — including one reading
"Remote (United States)". Applies to all 297 stored Indeed rows.

**5b. Remove `"work from home"` from `remote_phrases`.** It fired on 4
wrong roles and 3 right ones. Job 11 is the clearest failure — standard
UK flexible-working boilerplate:

> "you may work from home or another suitable location that meets
> business needs"

**5c. Add `"(from anywhere)"` and `"work from anywhere"` as open
evidence.** Fired on exactly the three roles the user marked OPEN, and
nothing else.

**5d. Add closed-eligibility phrases**, all observed verbatim:
`remote (united states)`, `remote - united states`,
`remote, united states`, `fully remote / u.s.-based`, `u.s.-based`,
`us-based`, `remote within the united states`, `u.s.-based only`,
`authorized to work in the us`, `will not sponsor`, `unable to sponsor`,
`no visa sponsorship`, `not eligible for immigration sponsorship`,
`must reside in one of the following states`, `w2 only`, `1099/c2c only`.

**5e. Drop closed postings.** Job 4 reads "No longer accepting
applications" and that text is not in our stored description, so it
cannot be detected today. Indeed via `kaix` supplies `signals.isExpired`
and `dates.validThrough`. LinkedIn supplies nothing, so a LinkedIn role
can only be checked by re-fetching its page — deferred, and recorded as
a residual.

All additions remain phrases, never bare words.

### 6. Read the fields already paid for

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

### 7. Widen the work-mode phrase list

Of 479 stored LinkedIn roles with a description but no work mode, 122
mention a work-mode word: 66 are missed wordings, 53 correctly ignored
(`hybrid cloud`), 3 conflicts. The conflict rule is not the problem.

Add to `hybrid_phrases`: `hybrid –`, `hybrid -`, `hybrid |`,
`location: hybrid`, `days a week in office`, `office N days per week`.
Add to `remote_phrases`: `remote eligible`, `performed remotely`.

The 66 is an upper bound from a broad regex — spot-check 20 first.

### 8. Re-evaluate and drop stored roles

Runs per user, against that user's own country and selected modes.
One-off for existing rows; new rows are filtered at scrape time.

Order matters — the widened list and new eligibility rules must run
before anything is dropped:

1. Apply the relevance gate (part 1).
2. Re-run `work_mode()` with the widened list, ignoring any location
   field of "Remote" (rule 5a).
3. Re-run `location_country()` and `geo_verdict()` with the new
   eligibility phrases (rules 5c, 5d).
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
- **Rule 5a**: a role whose only remote evidence is `location == "Remote"`
  makes no remote claim.
- **Rule 5b**: the UK boilerplate sentence yields no work mode.
- **Rules 5c/5d**: one test per phrase, plus false-positive guards
  (`hybrid cloud`, `remote teams`).
- **`workType` guard**: a test asserting `workType` never reaches
  `work_mode`, with the real measured values as fixtures. This is the
  trap most likely to be reintroduced.
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

- **LinkedIn expiry is undetectable.** Rule 5e covers Indeed only.
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
- **The relevance exclusion list is hand-maintained** and will drift as
  new trap titles appear. Trigger: review it whenever an off-target role
  reaches the map.
- **LinkedIn does not publish workplace type to logged-out clients.**
  Confirmed three ways: direct scrape of the guest endpoint (criteria are
  exactly Seniority level, Employment type, Job function, Industries),
  `cheap_scraper`'s own documentation, and valig and `cheap_scraper`
  returning an identical four-field set. No vendor can sell this.

## The question this ship does not answer

Even with every rule above, the honest count of Armenia-eligible roles in
800 scraped jobs may be closer to 10 than 300. The three that were open
were all BairesDev — a Latin American outsourcing firm hiring globally,
whose stored locations read "São Paulo", "Lima", "Veracruz" because that
is the recruiter's office, not the job's.

If that pattern holds, the supply for a remote-seeking user outside the
US and EU is not on the Indeed and LinkedIn boards we search, and the
product should say so plainly rather than show a map of roles that will
not hire them. Decide after the first clean run produces a real number.

## Out of scope

- Switching the LinkedIn actor. `cheap_scraper` returns the same four
  criteria fields as valig at 1.75× the price with a 150-result floor.
- Logged-in LinkedIn scraping, self-hosted guest-API scraping, and
  third-party AI-inferred work arrangement (`fantastic-jobs`).
- `skipJobId` to avoid re-scraping stored postings. Real saving,
  independent of this work.
- Adding job boards that serve non-US remote supply. Raised by the
  section above; needs its own investigation.
