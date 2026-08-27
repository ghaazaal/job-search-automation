# Remote-first sourcing for small-country users — Ship 8 design

Date: 2026-08-28
Status: proposed
Supersedes: parts 6–9 of
`2026-08-27-search-lanes-and-store-cleanup-design.md`, whose rules were
derived from eleven postings scraped by a source this ship removes.

## The persona, stated

Earlier ships built for "a job-seeking data professional". Run 6 forced a
sharper statement, and it is the reason this spec exists:

> **A data professional living in a country the big job boards do not
> serve, who needs roles they can actually be hired into from there.**

Not "someone who wants remote work". Someone for whom remote work is the
only category that exists, because the local market is small and the
large markets will not hire across a border. Armenia is the working
example; the persona is every country in the same position.

This changes what the product is. It is not a job board aggregator that
happens to filter for remote. It is an eligibility engine, and its
sources are worth keeping only insofar as they carry roles that pass it.

## Why

Ship 7 landed and ran live. Run 6 (Yerevan / `am` / remote+hybrid, four
titles) took 26.5 minutes over 24 steps:

```
796 scraped -> 508 deduped -> 384 kept, 124 off-topic, 0 dropped
```

Broken down by source, against the only question that matters:

| Source | Steps | Roles kept | **Provably open** |
|---|---|---|---|
| Indeed | 4 | 0 — every call HTTP 400 | — |
| LinkedIn | 16 | 297 | **0** |
| Remote boards | 4 | 87 | **2** |

Two-thirds of the run went to a source that produced nothing eligible.

### Indeed cannot serve this persona at all

All four Indeed calls returned HTTP 400. `kaix/indeed-scraper` declares
`country` as an enum of 54 Indeed country sites. Verified against the
live API: `AM` → 400, `GB` → 400, `UK` → 201, `US` → 201.

Diffing that enum against `eligibility.countries` (66 codes):

| | Count |
|---|---|
| map by straight upper-casing | 43 |
| genuine spelling mismatch | 1 — `gb` → `UK` |
| **Indeed has no site at all** | **22** |

The 22: Armenia, Azerbaijan, Bangladesh, Belarus, Bulgaria, Croatia,
Cyprus, Egypt, Estonia, Georgia, Kazakhstan, Kenya, Latvia, Lithuania,
Malta, Nigeria, Pakistan, Serbia, Slovakia, Slovenia, Sri Lanka,
Thailand.

Indeed is organised as one site per country. That is precisely the shape
this persona is not: a third of the countries the product supports have
no Indeed at all, and for the rest Indeed answers "what is hiring *in*
this country", which is the local question, not the one being asked.

`call_actor` also swallowed the 400 and returned `[]`, so each step read
`done, found: 0` — indistinguishable from a search that found nothing.
That is the same silent-failure shape Ship 7 fixed three times and missed
once, and it is why this took a live run to notice.

### LinkedIn produced 297 roles and nothing verifiable

Running `geo_verdict` over the 297 stored LinkedIn descriptions:

| Verdict | Roles |
|---|---|
| unknown | 286 |
| restricted | 8 |
| eligible | 3 |

All three "eligible" roles are false positives, from the **already-
shipped** `anywhere_words` window rule:

```
"work from anywhere in the world for up to 4 weeks per year"     — holiday perk
"embrace the freedom to work from anywhere ... for up to 30 days" — holiday perk
"work together in real time from anywhere in the world"           — Figma's marketing copy
```

The third is not about employment at all; it is a sentence about the
product the company sells. LinkedIn's true count is **0 of 297**.

`unknown` means unmeasured, not ineligible — many genuinely remote-first
employers never state reach in prose. But unverifiable is what the
product can act on, and 286 unverifiable roles is what LinkedIn costs
16 of 24 steps to produce.

### Prose mining does not work. Published fields do.

| Mechanism | Real finds | False positives |
|---|---|---|
| mining prose (`geo_verdict`) | **0** | 3 |
| reading a reach field (`location_scope`) | **2** | 0 known |

Across 384 roles with 382 descriptions, mining prose for eligibility
found nothing and manufactured three claims. The only mechanism that
found anything reads a field the board publishes on purpose.

This is the finding the whole ship turns on. Ship 7 said the source was
the binding constraint rather than the rules; run 6 says the *shape of
the evidence* is, and only one source shape carries it.

### The rules were derived from the wrong sample

Ship 7's rule 6c proposed `"work from anywhere"` as open evidence, from
three hand-read postings. It fires on 12 roles in run 6:

| Reading | Count | Example |
|---|---|---|
| genuine eligibility | **1** | `remote (work from anywhere)` |
| country-qualified | 1 | `work from anywhere in the united states for most positions` |
| time-boxed perk | 4 | `work from anywhere in the world for up to 4 weeks per year` |
| culture / benefits prose | 6 | `lifeway has a strong work from anywhere (wfa) culture` |

One in twelve, and the second row would read a US-only posting as open to
an Armenian user — the outcome rules 6a and 6d exist to prevent.

Rule 6b (remove `"work from home"`) is **confirmed** on the larger
sample: 15 hits, roughly five genuinely remote, six boilerplate, and four
stating the opposite outright (`at least 4 days in the office per week,
with the flexibility to work from home 1 day a week`).

### The reach parser was built for shapes that did not arrive

Run 6's actual reach values:

```
33  "United States"        5  ""                     2  "Europe"
 7  "Mexico"               4  "Flexible / Remote"    2  "Canada"
 5  "USA"                  3  "Brazil"               1  "Darwen"
```

Not one `Anywhere in the World`, not one timezone band. Those come from
We Work Remotely, RemoteOK and Remotive — three of the **six boards that
returned nothing this run**. `location_scope`'s worldwide and
timezone-band branches remain unvalidated against live data; its
country-list branch did all the work and did it correctly, resolving
`Armenia, Cyprus, Georgia, Kazakhstan, Poland, Portugal, Serbia, Spain`
to open.

## What we are changing

### 1. Remove Indeed

Not "skip when unsupported" — remove. Delete `scrapers/indeed.py`, its
entry in `SOURCES`, `apify.indeed_actor`, and its tests.

It cannot serve 22 of 66 supported countries, and for the rest it answers
the local question that the LinkedIn local lane already covers. Keeping
it as a conditionally-skipped source means maintaining a country-mapping
table, a skip path, and a scraper, for a source this persona never uses.

The country findings above are recorded **in this spec** rather than in
code, so nothing is lost if Indeed is ever reintroduced for a
big-country user. Git keeps the implementation.

### 2. Demote LinkedIn to the local and mode lanes

LinkedIn stays, at two-thirds of its current cost. Its plain worldwide
lane goes; the local and mode lanes remain.

| Lane | Steps (4 titles) | Keep? | Why |
|---|---|---|---|
| plain worldwide | 4 | **no** | The mode lanes ask the same worldwide question with better precision — Ship 7 measured remote 5/5 and hybrid 3/4 against an unfiltered lane's noise. |
| local | 4 | **yes** | 63 roles in run 6, all in the user's own country. A hybrid role in Yerevan *is* a role workable from Armenia. This lane serves the persona directly. |
| mode remote / hybrid | 8 | **yes** | The worldwide reach, mode-worded. |

`_LOCAL_ONLY` survives with its membership changed from `("Indeed",)` to
`("LinkedIn",)` — the constant already means "no plain worldwide lane",
and mode lanes are constructed separately, so they are unaffected.

Run shape: 24 steps → **16**. Remote boards worldwide (4), LinkedIn local
(4), LinkedIn mode (8).

### 3. Fix the shipped `anywhere_words` false positives

This is a live bug, not a rejected proposal. `geo_verdict`'s
anywhere-word window rule produced all three of LinkedIn's false
"eligible" verdicts.

Both failing families share one shape — the phrase is followed directly
by something that takes the claim back:

- a place — `work from anywhere **in the united states**`
- a duration — `**for up to 4 weeks per year**`, `**for up to 30 days a
  year**`

So: an anywhere-word or eligibility phrase followed directly by a country
or region name, or by a duration expression, claims **nothing**. Not
closed — nothing. Phrase-shaped, matching the compound (`<phrase> in
<place>`, `<phrase> for up to <n> <unit>`) rather than scanning N
characters ahead, so the rule stays as inspectable as the phrase lists it
guards.

This is the same fix already applied to bare `"anywhere"` in
`location_scope` during the Ship 7 review, where `Anywhere in the United
States` read as open. The same trap, in prose instead of a field.

The Figma case (`work together in real time from anywhere in the world`)
is **not** caught by this guard and is recorded as a residual. It is
marketing copy about a product, and no phrase rule separates it from an
eligibility statement.

### 4. Eligibility phrases, re-derived

- **Rule 6c is withdrawn.** Measured precision 1/12. With the part-3
  guard it reaches 1/7 — the guard kills the country-qualified and
  time-boxed cases but not the six plain-prose ones. Still not
  defensible, so the rule stays out rather than being propped up.
- **Rule 6b stands** — remove `"work from home"` from `remote_phrases`.
- **Rules 6a and 6d stand unchanged.** Never treat a location field of
  `"Remote"` as evidence; keep the closed-eligibility phrases. They fire
  8 times across 384 roles — thin, but phrase-bounded and additive, so
  they under-claim, which is the correct direction.

### 5. Wire `scope_verdict` into ingest

Tested, correct, called by nothing; `role.location_scope` is NULL on
every row. It is also the only mechanism in the product that has ever
found this user an eligible role, so it is the highest-value change here.

The call belongs in **ingest** — not the scraper, which should not carry
per-user judgment, and not scoring, which runs after the row is written.
It takes the row's `location` and the user's country and writes `open`,
`closed` or `unknown`.

**Remote-board rows only.** LinkedIn's location field is a place, not a
reach statement; feeding it to a reach parser manufactures exactly the
fake evidence rule 6a exists to stop.

Ship 7's residual asking for precedence between `role.country` and
`location_country(role.location)` **dissolves**: `role.country` came only
from Indeed's structured field, and Indeed is gone. Drop the column's
only writer along with it; the residual is closed, not deferred.

### 6. Board breadth — the actual growth path

With Indeed gone and LinkedIn demoted, the remote boards are the product.
Run 6 got **4 of 10 advertised boards**: himalayas 65, jobicy 15, muse 5,
devitjobs_uk 2. Silent: RemoteOK, We Work Remotely, Working Nomads,
Remotive, Hacker News, DevITjobs US.

Ship 7's residual watched for "two consecutive failed runs, or a run
under 10 rows". Neither fired — 133 rows arrived. The trigger watched
the wrong thing.

**6a. Record which boards were seen.** The actor reports `source_board`
per row; persist the distinct set on the run row. A board silent across
two consecutive runs is the signal, whatever the row count. This is the
only way to learn whether the aggregator sweeps ten boards or advertises
ten and sweeps four.

**6b. Evaluate sources outside the aggregator.** Previously out of scope;
now the growth path. Candidates in order of fit to the persona — boards
that publish reach as a field and hire across borders: Wellfound,
Arc.dev, and the direct APIs of the four silent boards that have them
(RemoteOK and Remotive both publish public JSON feeds, which removes the
aggregator as a single point of failure for them).

Evaluate, do not adopt blind. The measure is roles-open-to-a-small-country
per run, not rows per run. Run 6's own numbers are the baseline: 87 rows,
2 open.

### 7. The map shows the roles that are actually open

Run 6's split, from `scope_verdict` over the stored rows:

| | Roles |
|---|---|
| open | **2** |
| closed | 66 |
| unverified (19 unparseable board rows + 297 LinkedIn) | 316 |

The map currently renders all 384, which tells the user there are 384
roles worth reading. There are two.

**The map shows verified-open roles.** Everything else is not rendered.

**And says so, always.** Hidden is never silent — the same rule the
product already follows for drops (`N HIDDEN (ON-SITE ELSEWHERE)`). The
header states what was found and what is not shown:

```
2 OPEN · 66 NOT OPEN · 316 UNVERIFIED · 124 OFF-TOPIC
```

Exact wording and layout is a `DESIGN.md` decision, not settled here. The
requirement is that a user can see, without opening anything, both how
many roles they can act on and how much was set aside on their behalf.

This is a deliberate, user-approved narrowing of the flag-never-hide
rule, and it should be recorded in `CLAUDE.md` as the second such
exception alongside the on-site-elsewhere drop.

### 8. The four findings deferred from Ship 7's review

Recorded in that spec's "Corrections after review" section.

- **8a.** Mode-lane evidence is lost to `dedupe` when the plain lane
  returned the posting first. Note part 2 removes LinkedIn's plain
  worldwide lane, which removes the main collision source — but the local
  lane can still collide, so the fix stands.
- **8b.** Remote boards are planned for users who never selected remote,
  then have every row dropped or flagged. Plan the source only when
  `remote` is among the user's work modes.
- **8c.** `_countries_named` contradicts its docstring twice: it does use
  the bare `us` alias (`"come join us"` → United States), and
  word-bounding does not stop `Ireland` matching inside `Northern
  Ireland`.
- **8d.** An unrecognised timezone anchor returns unknown before the
  region and country checks run.

### 9. Store cleanup — last, and only last

Ship 7 part 9, unchanged in substance and deliberately unchanged in
position. Soft drops (`role.dropped_at`, schema v8), the application-row
guard, the unparseable-country keep, per-branch counts to the run log.

It decides what to drop using exactly the rules in parts 3–5, so it
cannot run before those are settled and measured. Ship 7's own history is
the argument: those rules were wrong when written, and only a live run
showed it.

The store is 1184 roles across six runs, 800 of which predate the
relevance gate. That is the population this migration exists for.

## Shipping order

Nine parts, splitting at a real seam:

- **8a — parts 1, 2, 3, 4, 5.** Everything that changes what the pipeline
  fetches and believes: Indeed out, LinkedIn demoted, the live
  anywhere-window bug fixed, the phrase rules corrected, `scope_verdict`
  wired up. Self-contained, and it is the whole persona re-scope.
- **8b — parts 6, 7, 8, 9.** Board breadth, the map, the deferred
  findings, the cleanup.

Part 7 (the map) may be worth pulling forward into 8a: it is the only
part the user sees, and after part 5 the data behind it exists.

Part 9 never moves forward.

## Testing

- **Indeed removal**: `SOURCES` names two sources; `_default_scrapers`
  matches; no import of `scrapers.indeed` survives; `plan_steps` for a
  located profile emits Remote-boards-worldwide, LinkedIn-local and
  LinkedIn-mode steps only.
- **Lane shape**: 4 titles, remote+hybrid → 16 steps, and no LinkedIn
  step on the plain worldwide lane.
- **Part 3 guard**: the three measured live false positives —
  `work from anywhere in the world for up to 4 weeks per year`,
  `embrace the freedom to work from anywhere in the world for up to 30
  days a year`, `work from anywhere in the united states for most
  positions` — each yields no eligibility claim. Fixtures verbatim from
  run 6. Plus a guard-is-not-a-mute-button case: `remote (work from
  anywhere)` still claims what it claimed before.
- **Rule 6b**: `at least 4 days in the office per week, with the
  flexibility to work from home 1 day a week` yields no remote claim.
- **`scope_verdict` wiring**: a board row with reach `Armenia, Cyprus,
  Georgia, Kazakhstan, Poland` stores `open` for an `am` user and
  `closed` for a `us` one; a LinkedIn row is never scoped at all.
- **Map**: a fixture with 2 open, 66 closed and 316 unverified renders 2
  cards and states all four counts; a run with 0 open renders the counts
  and an explicit empty state, not a blank page.
- **8a**: a posting returned by both the local and a mode lane keeps its
  lane evidence through `dedupe`.
- **8b**: an onsite-only profile plans no remote-board step.
- **8c**: `come join us` names no country; `northern ireland` does not
  resolve to Ireland.
- **8d**: `Europe, Time zone: XYZ (+/- 3 hours)` reaches the region check.
- **Board coverage**: the run row records the distinct boards seen.
- **Migration**: each branch of `keep()`, the application-row guard, the
  unparseable-country keep, and ordering — a role rescued by a widened
  phrase must not be dropped by the migration that widened it.
- **Live check after merge**: rerun and confirm 16 steps, the board list
  recorded, and the map's stated open count matching what
  `location_scope` wrote.

## Accepted residuals

- **Everything here rests on one run.** Run 6 is one profile, one day,
  four titles — a far larger sample than the eleven postings it replaces,
  and still one run. Re-measure after the next.
- **The map may show zero roles.** On run 6 it shows two. That is the
  honest answer for this profile and this source set, and part 6 is the
  response — but the product must read as "we checked and found two", not
  as broken. The empty state carries this and is explicitly tested.
- **Marketing copy is indistinguishable from eligibility prose.** The
  Figma sentence (`work together in real time from anywhere in the
  world`) defeats the part-3 guard and any phrase rule we could write.
  Prose mining is now a supporting mechanism rather than the primary one,
  which bounds the damage. Trigger: if a false `open` reaches the map,
  drop prose-derived eligibility to evidence-only.
- **`unknown` is unmeasured, not ineligible.** 286 LinkedIn roles are set
  aside on the strength of what they do not say. Some are certainly open.
  The product's answer is that it will not claim what it cannot show, and
  the counts make the size of that set visible.
- **`location_scope`'s worldwide and timezone branches have never seen
  live data.** They are tested against strings from a Ship 7 exploratory
  run, not from any run the product has made. Trigger: if the six silent
  boards return, re-check both branches against what they publish.
- **Six of ten boards are unexplained.** They may have had nothing for
  four data-role titles, or the aggregator may not sweep them. Part 6a
  measures rather than assumes.
- **Indeed is removed, not disabled.** A big-country user loses a source
  they could have used. Accepted: the persona above is the one being
  built for, and the local lane still answers their local question via
  LinkedIn. Trigger: a user in a supported country asking for it.
- **Rule 6d is retained on 8 hits across 384 roles.** Thin. Phrase-bounded
  and additive, so it under-claims.

## Out of scope

- Re-fetching LinkedIn postings to detect closure — still the only way to
  satisfy rule 6e for LinkedIn, still deferred.
- The unused LinkedIn fields (`contractType`, `experienceLevel`,
  `applicationsCount`, `id`). Ship 7 part 7, **demoted out of this ship**:
  LinkedIn is now a supporting source, and four more of its fields do not
  move the number this ship is about. The `workType` guard stays wherever
  the fields eventually land — despite the name it carries job function
  ("Legal", "Health Care Provider") and must never reach `work_mode`.
- `skipJobId` to avoid re-scraping stored postings. Independent, and now
  worth more: run 6 re-scraped 288 duplicates of 796.
- Per-user relevance include lists. Ship 7 residual, trigger unfired.
- Switching the remote-board aggregator. Part 6a gathers the evidence.
