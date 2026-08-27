# Eligibility from measurement — Ship 8 design

Date: 2026-08-28
Status: proposed
Supersedes: parts 6–9 of
`2026-08-27-search-lanes-and-store-cleanup-design.md`, whose rules were
derived from eleven postings scraped by a source Ship 7 replaced.

## Why

Ship 7 landed and ran live. Run 6, against the real profile
(Yerevan / `am` / remote+hybrid, four titles), took 26.5 minutes over 24
steps and produced:

```
796 scraped -> 508 deduped -> 384 kept, 124 off-topic, 0 dropped
```

The run invalidated four things the Ship 7 spec asserted. Every number
below is from that run, not from an estimate.

| | Ship 7 estimate | Run 6 |
|---|---|---|
| off-topic share | 41% | **24%** (124 / 508) |
| remote-board rows kept | 50 | 87 |
| **open to the user's country** | 11 of 50 (22%) | **2 of 87 (2.3%)** |
| boards contributing | 10 | **4** |

Two roles out of 796. That is the honest size of this market for this
profile, and the product has to say so.

### Indeed contributed nothing, and said "done"

All four Indeed calls returned HTTP 400. `kaix/indeed-scraper` declares
`country` as an **enum of 54 Indeed country sites**; `AM` is not one,
because Indeed has no Armenia site. Verified directly against the API:

| Sent | Result |
|---|---|
| `AM` | **400** |
| `GB` | **400** |
| `UK` | 201 |
| `US` | 201 |

Two defects, not one. Armenia is genuinely unsupported — but `GB` fails
only because kaix spells the United Kingdom `UK` while `eligibility.
countries` and `user.country` store ISO codes. **Every UK user 400s on
every Indeed call**, and nothing says so.

That is the second defect. `call_actor` catches `RequestException`,
logs, and returns `[]`. `execute` sees an empty list, not an exception,
so the step is marked `done` with `found: 0` — indistinguishable from a
search that genuinely found nothing. Ship 7 made three silent failures
loud and left the loudest one in place.

### The eligibility rules were derived from the wrong sample

Ship 7's rules 6b–6d came from eleven Indeed postings hand-read by the
user. Run 6 contains 384 roles with 382 descriptions, from LinkedIn and
the remote boards. Measured against that sample, **rule 6c is wrong in
the most dangerous direction available.**

Rule 6c proposed adding `"work from anywhere"` as *open* eligibility
evidence, on the grounds that it "fired on exactly the three roles the
user marked OPEN, and nothing else". It fires on 12 roles in run 6:

| Reading | Count | Example |
|---|---|---|
| genuine eligibility | **1** | `remote (work from anywhere)` |
| **country-qualified** | **1** | `work from anywhere in the united states for most positions` |
| time-boxed perk | 4 | `work from anywhere in the world for up to 4 weeks per year` |
| culture / benefits prose | 6 | `lifeway has a strong work from anywhere (wfa) culture` |

One in twelve. And the second row is the failure that matters: rule 6c
would read a US-only posting as open to an Armenian user — the exact
outcome rules 6a and 6d exist to prevent.

Rule 6b — remove `"work from home"` — is **confirmed**. It fires on 15
roles: roughly five genuinely remote, six benefits boilerplate, and four
that state the opposite outright (`at least 4 days in the office per
week, with the flexibility to work from home 1 day a week`).

Rule 6d's closed phrases barely fire on this sample at all: `us-based` 3,
`u.s.-based` 2, `unable to sponsor` 2, `not eligible for immigration
sponsorship` 1, and **zero** for the other eleven. They are not wrong —
they are phrase-bounded and additive, so they under-claim — but they were
tuned against Indeed prose and this pipeline no longer fetches Indeed
prose for this user.

### The reach parser was built for shapes that did not arrive

`location_scope` recognises worldwide phrases, timezone bands, regions
and country names. Run 6's actual reach values:

```
33  "United States"        5  ""                     2  "Europe"
 7  "Mexico"               4  "Flexible / Remote"    2  "Canada"
 5  "USA"                  3  "Brazil"               1  "Darwen"
```

Not one `Anywhere in the World`. Not one timezone band. Those shapes come
from We Work Remotely, RemoteOK and Remotive — three of the six boards
that returned nothing this run. The parser's worldwide and timezone
branches remain **unvalidated against live data**; its country-list branch
is the one doing all the work, and it works: the reach string
`Armenia, Cyprus, Georgia, Kazakhstan, Poland, Portugal, Serbia, Spain`
resolved correctly to open.

## The finding underneath this one

Ship 7's closing section said the source was the binding constraint, not
the rules. Run 6 says it again, harder. Indeed is structurally unavailable
to this user. LinkedIn contributed 297 kept roles and **not one** of them
proves it will hire from Armenia. The remote boards contributed 87, of
which 2 do.

So the entire product, for this profile, is four job boards — and six more
that were supposed to be there and weren't.

## What we are changing

### 1. Indeed's country, and a transport failure that says so

**1a. Map ISO codes to kaix's enum, and refuse the rest before paying.**
Add `apify.indeed_countries` to `vocabulary.yaml`: ISO code → the value
kaix accepts. Diffed against `eligibility.countries` (66 codes) and
kaix's enum (54):

| | Count |
|---|---|
| map by straight upper-casing | 43 |
| **genuine spelling mismatch** | **1** — `gb` → `UK` |
| Indeed has no site at all | **22** |

The 22: Armenia, Azerbaijan, Bangladesh, Belarus, Bulgaria, Croatia,
Cyprus, Egypt, Estonia, Georgia, Kazakhstan, Kenya, Latvia, Lithuania,
Malta, Nigeria, Pakistan, Serbia, Slovakia, Slovenia, Sri Lanka,
Thailand.

So **a third of the countries this product supports cannot use Indeed**,
and one more (the UK) was failing on a spelling. That is the fact worth
writing down; the table is just where it lives.

A country absent from the table means Indeed has no site for it. The
Indeed source is then **skipped for that user**, with the step marked
`skipped` and a reason, not `done` — and never billed. This is a normal
outcome for a user in Armenia, not an error.

**1b. A non-200 must not look like an empty search.** `call_actor`
currently returns `[]` for every failure, so its callers cannot tell "the
search found nothing" from "the request was rejected". It gains a way to
signal failure — an exception, or a sentinel the scrapers translate — and
`execute` marks the step `failed`, exactly as it already does when a
scraper raises. The run still completes on the other sources; that
behaviour does not change. What changes is that the screen and the run row
stop claiming a source succeeded when it did not.

This is the same fault Ship 7 fixed three times over (a wrong actor id, a
renamed field, a config gate keyed on a display name) and missed once.

### 2. Eligibility phrases, re-derived

**2a. Rule 6c is withdrawn.** `"work from anywhere"` and
`"(from anywhere)"` are not added as open evidence. Measured precision on
384 real roles is 1/12.

**2b. Rule 6b stands.** Remove `"work from home"` from `remote_phrases`.
Confirmed on a larger sample than the one that proposed it.

**2c. Rules 6a and 6d stand, unchanged.** Never treat a location field of
`"Remote"` as evidence; keep the closed-eligibility phrase list. They
under-claim rather than over-claim, which is the correct direction, and
nothing in run 6 contradicts them.

**2d. Add a qualifier guard, which is what rule 6c was reaching for.**
Both false-positive families in the table above share one shape: the
phrase is immediately followed by something that takes the claim back.

- a place — `work from anywhere **in the united states**`
- a duration — `work from anywhere **for up to 4 weeks per year**`,
  `**for up to 30 days a year**`

So: an eligibility phrase followed directly by a country or region name,
or by a duration expression, claims **nothing**. Not closed — nothing.
Same discipline as every other conflict in this codebase. Phrase-shaped,
not a character window: match the compound (`<phrase> in <place>`,
`<phrase> for up to <n> <unit>`) rather than scanning N characters ahead,
so the rule stays as inspectable as the phrase lists it guards.

This is the identical fix already applied to bare `"anywhere"` in
`location_scope` during the Ship 7 review, where `Anywhere in the United
States` was reading as open. The same trap, in prose instead of a field.

**The guard does not rescue rule 6c, and this is worth being explicit
about.** It would kill the country-qualified case and all four time-boxed
ones — 5 of the 11 false positives. The other 6 are plain benefits prose
with no qualifier to catch (`wfa culture`, `embrace the freedom to work
from anywhere, anytime`, `work from anywhere (remote-first workplace)`).
Precision goes from 1/12 to **1/7**. Still not defensible, so 6c stays
withdrawn.

The guard earns its place elsewhere: on the closed phrases in 2c, and as
the general mechanism this codebase keeps needing. It is not a way to
keep a refuted rule alive.

### 3. Wire `scope_verdict` into ingest

It is tested, correct, and called by nothing. `role.location_scope` ships
NULL on every row. It is also the only thing that separates 2 applicable
roles from 85 that are not, so it is the highest-value wiring in this
ship.

The call belongs in **ingest**, not the scraper (which should not carry
per-user judgment) and not scoring (which runs after the row is written).
It takes the row's `location` and the user's country and writes `open`,
`closed` or `unknown` into `role.location_scope`.

The Ship 7 residual asking for a stated precedence between `role.country`
and `location_country(role.location)` **resolves itself**: `role.country`
is populated only from kaix's structured field, and run 6 set it on
**0 of 384 rows**. There is no conflict to arbitrate until Indeed
produces data again. Record that, prefer `role.country` when it is
present, and move on.

Scope applies to remote-board rows only. LinkedIn's location field is a
place, not a reach statement, and feeding it to a reach parser would
manufacture exactly the fake evidence rule 6a exists to stop.

### 4. The four findings deferred from Ship 7's review

All four are recorded in that spec's "Corrections after review" section.

**4a. Lane evidence is lost to dedupe.** Mode-lane steps run last and
`dedupe` keeps the first copy, so `_lane_mode` is discarded whenever the
plain lane already returned the posting — which is the case the lane
exists to serve. Fix: carry lane membership across the collapse rather
than dropping the challenger wholesale.

**4b. Remote boards run for users who never selected remote.** The source
is planned on the worldwide lane unconditionally, stamps every row
`work_mode: "remote"`, and an onsite-only user then has every row dropped
or flagged — after paying the slowest source in the run. Fix: plan it only
when `remote` is among the user's work modes.

**4c. `_countries_named` contradicts its docstring twice.** It does use
the bare `us` alias (`"come join us"` → United States), and word-bounding
does not stop `Ireland` matching inside `Northern Ireland`. Make the
guards real or drop the claims.

**4d. An unrecognised timezone anchor short-circuits everything after
it.** `Europe, Time zone: XYZ (+/- 3 hours)` returns unknown without ever
checking the region or country. The band branch should fall through, not
return.

### 5. Remote-board coverage

Six of ten boards contributed nothing: RemoteOK, We Work Remotely,
Working Nomads, Remotive, Hacker News, DevITjobs US. The Ship 7 residual
watches for "two consecutive failed runs, or a run under 10 rows" —
neither fired, because 133 rows arrived. The trigger was watching the
wrong thing.

**Replace it with a per-board expectation.** The actor reports
`source_board` per row; record the distinct boards seen on the run row.
A board silent across two consecutive runs is a signal, whatever the row
count. This is cheap and it is the only way we find out whether the
aggregator sweeps ten boards or advertises ten and sweeps four.

Do **not** switch actors on this evidence alone. One run, and the missing
boards may simply have had nothing for four data-role titles.

### 6. The LinkedIn fields already paid for

Unchanged from Ship 7 part 7: `contractType`, `experienceLevel`,
`applicationsCount`, `id` → `employment_type`, `applicants`,
`source_job_id`. LinkedIn is now 297 of 384 kept roles, so reading four
more of its fields is worth more than it was when this was written.

The `workType` guard stays: despite the name it carries LinkedIn's job
function ("Legal", "Health Care Provider"), and it must never reach
`work_mode`.

### 7. Say the honest number

384 roles on the map implies 384 roles worth reading. Two of them are
provably open. The map already states off-topic and hidden counts; it
should also state what eligibility verification found, in the same
register:

Run 6's actual split, from `scope_verdict` computed over the stored rows:

| | Roles |
|---|---|
| open | **2** |
| closed | 66 |
| unverified (19 board rows unparseable + 297 LinkedIn) | 316 |

```
384 ROLES · 2 OPEN · 66 NOT OPEN · 316 UNVERIFIED
```

Exact wording is a UI decision against `DESIGN.md`, not settled here. The
requirement is: a user must not have to open 384 cards to discover that
two of them will hire from their country. Unverified is not a failure —
LinkedIn publishes nothing to verify against — but it must not read as
eligible either.

### 8. Store cleanup — last, and only last

Ship 7 part 9, unchanged in substance, deliberately unchanged in
position. It decides what to drop using exactly the rules in part 2, so
it cannot run before they are settled and measured. Soft drops
(`role.dropped_at`, schema v8), the application-row guard, the
unparseable-country keep, and per-branch counts to the run log all stand
as written.

The store is now 1184 roles across six runs, of which 800 predate the
relevance gate. That is the population this migration exists for.

## Shipping order

Eight parts is more than Ship 7 carried, and they are not equally
entangled. If this runs long, it splits cleanly in two at a real seam:

- **8a — parts 1, 2, 3, 4.** Everything that changes what the pipeline
  believes: the country mapping and loud transport failure, the re-derived
  phrase rules, `scope_verdict` wired up, and the four deferred findings.
  Self-contained, and part 3 is the highest-value change in the ship.
- **8b — parts 5, 6, 7, 8.** Board coverage, the unused LinkedIn fields,
  the honest count on the map, and the store cleanup. Part 8 depends on
  part 2 having landed and been measured; parts 5–7 are additive.

Do not reorder part 8 forward under any circumstance. It deletes rows
using the rules from part 2, and Ship 7's own history is the argument:
those rules were wrong when they were written and only a live run showed
it.

## Testing

- **Country mapping**: `gb` → `UK`; `us` → `US`; `am` → not present, so
  Indeed is skipped and never called. A test asserting the skipped step is
  `skipped`, not `done`, and that `call_actor` was not invoked.
- **Transport failure**: a stubbed 400 marks the step `failed`, the run
  still completes on the other sources, and the run row records it.
  Regression test for the exact shape run 6 hit.
- **Rule 6c withdrawal**: the four measured false-positive strings —
  `work from anywhere in the united states for most positions`,
  `work from anywhere in the world for up to 4 weeks per year`,
  `work from anywhere (wfa) culture`, `embrace the freedom to work from
  anywhere, anytime` — each yields no open claim. Fixtures verbatim from
  run 6.
- **Rule 6b**: the four contradicting strings, including
  `at least 4 days in the office per week, with the flexibility to work
  from home 1 day a week`, yield no remote claim.
- **Qualifier guard**: place-qualified and duration-qualified phrases
  claim nothing; the one genuine case (`remote (work from anywhere)`)
  survives, so the guard is measured to be a guard and not a mute button.
- **`scope_verdict` wiring**: a remote-board row with reach
  `Armenia, Cyprus, Georgia, Kazakhstan, Poland` stores `open` for an `am`
  user and `closed` for a `us` one; a LinkedIn row is never scoped at all.
- **4a**: a posting returned by both the plain lane and the mode lane
  keeps its lane evidence through `dedupe`.
- **4b**: an onsite-only profile plans no remote-board step.
- **4c**: `come join us` names no country; `northern ireland` does not
  resolve to Ireland.
- **4d**: `Europe, Time zone: XYZ (+/- 3 hours)` reaches the region check.
- **Board coverage**: the run row records the distinct boards seen.
- **Migration**: each branch of `keep()`, the application-row guard, the
  unparseable-country keep, and ordering — a role rescued by a widened
  phrase must not be dropped by the same migration that widened it.
- **Live check after merge**: rerun and confirm Indeed is skipped rather
  than failed-silently, the board list is recorded, and the map's stated
  open count matches what `location_scope` wrote.

## Accepted residuals

- **Everything here rests on one run.** Run 6 is one profile, one day,
  four titles. It is a much larger sample than the eleven postings it
  replaces, and it is still one run. Re-measure after the next.
- **The worldwide and timezone-band branches of `location_scope` have
  never seen live data.** They are tested against strings from a Ship 7
  exploratory run, not from any run the product has made. Trigger: if the
  six silent boards return in a later run, re-check those branches against
  what they actually publish.
- **The qualifier guard is designed from 12 examples.** Enough to see the
  two shapes, not enough to know the window size. It ships with
  `work from anywhere` still excluded from open evidence, so a wrong
  window costs nothing until that changes.
- **Rule 6d is retained on almost no evidence.** Eight hits across 384
  roles. Phrase-bounded and additive, so the failure mode is
  under-claiming. Revisit if Indeed becomes reachable for any user.
- **`role.country` is NULL on every row**, so its precedence against
  `location_country` is decided but untested. It becomes live the first
  time a supported-country user runs Indeed.
- **Six of ten boards are unexplained.** They may have had nothing, or the
  aggregator may not sweep them. Part 5 measures it rather than assuming
  either.
- **Indeed is permanently unavailable to users in unsupported countries.**
  That is Indeed's constraint, not ours; the product's job is to say so
  plainly rather than show an empty source that looks like a failed one.

## Out of scope

- Switching the remote-board actor. Part 5 gathers the evidence; acting on
  it is a later decision.
- Adding job boards outside the aggregator (Wellfound, Arc.dev).
- Re-fetching LinkedIn postings to detect closure — still the only way to
  satisfy rule 6e for LinkedIn, still deferred.
- `skipJobId` to avoid re-scraping stored postings. Real saving,
  independent of this work, and now worth more: run 6 re-scraped 288
  duplicates out of 796.
- Per-user relevance include lists. Recorded as a Ship 7 residual with its
  own trigger; nothing in run 6 fired it.
