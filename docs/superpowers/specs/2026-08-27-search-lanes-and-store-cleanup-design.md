# Search lanes and store cleanup — design

Date: 2026-08-27
Status: proposed
Supersedes: the probe mechanism from
`2026-08-26-badge-probe-eligibility-tiers-design.md`

## Why

Ship 6 added probe searches to recover LinkedIn's workplace badge. Live
measurement shows they never worked. The `remote:` key the scrapers send
is not a parameter valig accepts — Apify drops unknown keys silently, so
both probe lanes run the same unfiltered search.

Evidence, same search, 25 results per run:

| What was sent | Hybrid set vs on-site set |
|---|---|
| `remote: ["3"]` / `["1"]` (shipped code) | 9 job IDs in **both** |
| `urlParam f_WT=3` / `=1` / `=2` / `=1,3` | `f_WT=3` ≡ `f_WT=2`; `f_WT=1` ≡ `f_WT=1,3` |
| `keywords: "hybrid …"` / `"remote …"` | **0** job IDs in both |

A job has exactly one workplace type, so a working filter yields zero
overlap. Both parameter routes are ignored. Only the search words reach
LinkedIn.

This also explains run 4's badge yield: overlapping URLs get claimed by
`probe hybrid`, re-claimed by `probe onsite`, hit the conflict branch and
collapse to `""`. 400 probe results produced 7 verified roles. The 7 are
page-2 ranking jitter, not badges.

## What we are changing

Five parts. Parts 1–4 are the pipeline; part 5 is a one-off cleanup of
what is already stored.

### 1. Delete the probe mechanism

- Remove `probes` from `plan_steps` and the `probe` branch in the run
  loop (`run_core.py`).
- Remove `probe_badges`, the badge-vs-text reconciliation, and
  `RunResult.badge_hits`.
- Remove the `remote` argument from `linkedin.scrape` and
  `_filters_for`. It has never done anything.
- Remove `search.probes` from `config.yaml`.

Nothing downstream loses information, because the mechanism never
produced any.

### 2. Replace with keyword lanes

Per role, run a LinkedIn search per selected work mode, with the mode in
the search words. A user may tick any subset of remote/hybrid/onsite at
setup (`profile.WORK_MODES`), so lanes are derived, never hardcoded:

```
lanes = [m for m in profile.work_modes if m in ("remote", "hybrid")]
```

| User ticked | Keyword lanes run |
|---|---|
| remote | `"remote <role>"` |
| remote + hybrid | `"remote <role>"`, `"hybrid <role>"` |
| hybrid + onsite | `"hybrid <role>"` |
| onsite only | *none* — local lane only |

**No on-site lane.** Measured precision:

| Lane | Correct on manual read |
|---|---|
| remote | 5/5 (100%) |
| hybrid | 3/4 (75%) |
| on-site | 1/3 (33%) |

On-site fails because companies advertise "remote" and "hybrid" as
selling points but rarely write "this job is on-site" — there is no word
for LinkedIn to match, so the lane returns noise. It also overlapped the
hybrid lane on 3 of 23 IDs, while remote/hybrid overlapped on 0.

On-site is inferred by elimination: a role in neither lane, in the user's
own country, is treated as on-site-or-unknown and follows the existing
flag path. A user who ticks on-site is served entirely by the local lane,
which already searches their actual place with every work mode — that is
what it was built for and it is unchanged.

Lane membership is **evidence, not proof**. LinkedIn is matching text, so
a posting that merely mentions "remote" can land in the remote lane —
Bedrock Robotics landed in the hybrid lane with no work-mode statement at
all. Lane membership therefore enters the existing tier system as a
weaker signal than a stated fact:

| Lane says | `work_mode()` says | Result |
|---|---|---|
| remote | remote | verified, full-confidence wording |
| remote | *silent* | stored, reduced-confidence wording, ranks below verified |
| remote | hybrid | conflict — claim nothing, as today |

Cost: 2 mode lanes × N roles, versus today's 1 worldwide + 1 local + 2
probes. Fewer searches than now.

Keep the local lane. It is the only way target-country on-site and hybrid
roles arrive at all, and its purpose is unchanged.

### 3. Read the fields we already pay for

valig returns 20 fields; `linkedin.py` reads 8. Four of the discarded
ones close known gaps, at zero extra cost:

| Field | Coverage in test | Use |
|---|---|---|
| `contractType` | 20/20 | employment type — not captured anywhere today |
| `experienceLevel` | 20/20, but "Not Applicable" ×14 | seniority, publisher-stated |
| `applicationsCount` | 20/20 | competition signal ("Over 200 applicants" vs "Be among the first 25") |
| `id` | 20/20 | stable key, no URL normalisation needed |

Add `employment_type`, `applicants` and `source_job_id` columns to
`role`. `experienceLevel` is stored but only used when it is not
"Not Applicable".

Do **not** map valig's `workType` to work mode. Despite the name it
carries LinkedIn's *job function* — measured values include
"Information Technology", "Engineering", "Legal", "Health Care Provider".
`cheap_scraper` has the identical misnaming. Store it as `job_function`
or not at all.

### 4. Widen the work-mode phrase list

Of 479 stored LinkedIn roles that have a full description but no work
mode, 122 mention a work-mode word. Splitting them:

| Cause | Count |
|---|---|
| phrase list has no entry for the wording | **66** |
| correctly ignored (`hybrid cloud`, `remote teams`) | 53 |
| conflict rule forced `None` | 3 |

The conflict rule is not the problem. The list is missing common
wordings, clustered in one idiom:

```
Location: Hybrid – Reading/London
Senior BI Developer | Competitive Salary | Hybrid – Glasgow
This role is based in the Richmond office 4 days per week
```

Add to `hybrid_phrases`: `hybrid –`, `hybrid -`, `hybrid |`,
`location: hybrid`, `days a week in office`, `office 4 days per week`
(and the 2/3/5-day variants). Add to `remote_phrases`: `remote eligible`,
`performed remotely`.

All remain phrases, never bare words — the rule that keeps "hybrid cloud"
out is unchanged.

The 66 is an upper bound from a broad regex. Spot-check a sample of 20
before trusting the number.

### 5. Re-evaluate and drop stored roles

The store holds 800 roles. It contains 115 roles in India, 60 in the UK,
55 in Singapore, 14 in Australia, 11 in Brazil — none of them reachable
by the user they were stored for.

This runs per user, against that user's own country and selected work
modes. It is a one-off migration for existing rows; new rows are filtered
at scrape time by the lanes in part 2.

Run **in this order** — step 3 must follow step 1, because the widened
phrase list will reclassify some roles as remote and save them from being
dropped:

1. Re-run `work_mode()` over every stored description with the widened
   list; update `role.work_mode`.
2. Re-run `location_country()` over every stored location.
3. Apply the keep test below.

The rule is stated as a **keep** test, evaluated against the user's own
selected modes — never against a hardcoded "remote". A foreign role is
reachable only if it is remote, because nobody commutes across a border.

```
keep(role, user):
    country = location_country(role.location)
    if country == user.country:            return True   # home country, any mode
    if country is None and not literal_remote(role):
                                           return True   # unknown -> keep + flag
    if literal_remote(role) or role.work_mode == "remote":
        return "remote" in user.work_modes
    return False                                          # foreign, not remote
```

Counts for the current profile (Armenia, remote only):

| Outcome | Roles |
|---|---|
| foreign, not remote → **drop** | **404** |
| remote role, user wants remote → keep | 303 |
| home country → keep | 51 |
| country unknown → keep + flag | 42 |

The same rule under other selections, same 800 rows:

| User ticks | Keep | Drop |
|---|---|---|
| remote | 396 | 404 |
| remote + hybrid + onsite | 396 | 404 |
| hybrid + onsite | 93 | 707 |
| onsite only | 93 | 707 |

The hybrid/onsite figures are not a bug: the store was filled by
remote-oriented searches, so a user wanting only local work legitimately
has almost nothing in it. Their first run after this ship refills it via
the local lane.

The third branch is a deliberate change to the flag-never-hide
discipline: it drops roles that never stated a work mode, purely because
they sit in a confidently-parsed foreign country. The justification is
that a Chennai posting silent on work mode is not reachable from Yerevan
by any mode the user selected. This is the user's explicit product call,
recorded here.

Guard rails:
- Roles with any `application` row are never dropped, whatever the rule
  says. A job the user has acted on stays.
- Drops are soft: add a new `role.dropped_at` column (nullable TEXT,
  schema migration v6), set it, and exclude those rows from the map
  rather than `DELETE`. Reversible if the rule proves wrong.
- The migration reports counts per rule and writes them to the run log.
- Roles whose country cannot be parsed are kept and flagged, not dropped.
  Silence about *location* is still silence.

## Testing

- **Probe removal**: existing probe tests deleted; a test asserts
  `plan_steps` emits only worldwide and local lanes.
- **Lane construction**: unit test that a role produces exactly the
  remote and hybrid keyword lanes, and no on-site lane.
- **Lane-to-tier mapping**: table test for the three rows in part 2 —
  agree, silent, conflict.
- **`workType` guard**: a test asserting `workType` never reaches
  `work_mode`, with the real measured values as fixtures. This is the
  trap most likely to be reintroduced later.
- **Phrase additions**: one test per new phrase, plus false-positive
  guards (`hybrid cloud`, `remote teams`, `hybrid approach`).
- **Migration**: fixture store exercising each branch of `keep()`, the
  application-row guard, the unparseable-country keep, and ordering
  (a role rescued by the widened list is not dropped). Parameterised
  over all seven non-empty work-mode selections, asserting that a
  foreign non-remote role is dropped for every one of them and that a
  foreign remote role survives exactly when `remote` is ticked.
- **Live check after merge**: rerun; confirm probe steps are gone, both
  keyword lanes appear, and the map's kept-count matches the migration's
  reported keep.

## Accepted residuals

- **Lane precision is measured on one search, one location, one day.**
  Remote 5/5, hybrid 3/4, on-site 1/3, n small. Re-measure across the
  user's four real roles before trusting the hybrid lane at 75%.
- **Hybrid lane false positives are known and unfixed** (Bedrock
  Robotics). The reduced-confidence tier carries them. Trigger to
  revisit: if hybrid-lane roles with silent descriptions exceed ~30% of
  the lane, demote the lane to evidence-only.
- **The foreign-and-not-remote drop is unverified against ground truth.**
  We have not confirmed that the 404 dropped roles are genuinely
  unreachable. Trigger: spot-check 20 of them against the live postings;
  if more than 2 are genuinely remote, that branch moves to the flag path
  instead of dropping. Run this check *after* the widened phrase list,
  since some will reclassify to remote and never reach the branch.
- **`"United States"` as LinkedIn's nationwide-remote location shape** is
  inferred from 16/25 vs 0/25, not documented behaviour. Not relied on
  in any rule here, noted for future use.
- LinkedIn does not publish workplace type to logged-out clients at all.
  Confirmed three ways: direct scrape of the guest endpoint (criteria
  list is exactly Seniority level, Employment type, Job function,
  Industries), `cheap_scraper`'s own documentation, and the fact that
  valig and `cheap_scraper` return an identical four-field set. No vendor
  can sell this. Do not revisit without a login-based approach, which
  stays out of scope.

## Out of scope

- Swapping the Indeed actor. `kaix/indeed-scraper` returns publisher-
  stated `workArrangement.locationType` (9/20 populated, genuinely
  distinguishing In-person/Hybrid/Remote), 90% salary coverage and
  structured `location.country`, at $0.05/1K versus the current
  $0.10/1K. Strictly better and cheaper, but it is a separate change
  with its own field mapping and migration. Next ship.
- Switching the LinkedIn actor. Measured: `cheap_scraper` returns the
  same four criteria fields as valig at 1.75× the price with a
  150-result floor. No reason to move.
- Logged-in LinkedIn scraping, self-hosted guest-API scraping, and
  third-party AI-inferred work arrangement (`fantastic-jobs`). The first
  two carry ToS and maintenance cost for no gain; the third imports
  another party's guess as a fact.
- `skipJobId` to avoid re-scraping stored postings. Real saving, but
  independent of this work.
