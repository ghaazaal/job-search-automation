# Work-Mode Truth + the Local Lane — Ship 5 Design

Date: 2026-08-26
Status: approved

## Problem

Field data from run 2 (post-Ship-4, user in Yerevan, remote-only profile,
600 scraped / 271 new):

1. **The remote filter is requested but never verified.** Of 172 LinkedIn
   jobs returned under workplace-type `Remote`: 26 say "hybrid" in their
   own text, 7 say "on-site", only 16 say "remote", 131 say nothing. At
   least ~19% are explicitly not remote — poster mislabeling plus a loose
   actor filter — and nothing in the pipeline reads the description to
   check. Foreign on-site jobs reach the map as clean fits.
2. **No work-mode data is stored.** `role` has only a raw `location`
   string. The scrapers receive mode evidence (descriptions, Indeed
   attribute tags) and drop it. The map cannot show or filter by mode.
3. **Local jobs never arrive.** Both search casts are remote-only; a
   Yerevan hybrid job shows up only by accident, though it is exactly what
   the user wants ("Yerevan + worldwide remote").
4. **Indeed is unscoreable.** ~200 jobs across two runs with zero
   descriptions (aggregator redirect links). A third of every scrape is
   unreadable cards.
5. **The Indeed actor ignores the volume cap** — asked for 50 per role, it
   returns ~100.

## Decisions (made with the user)

- **Drop foreign on-site/hybrid; keep local ones.** A posting whose own
  text states a mode the user did not ask for, located in a country that
  is not theirs, is dropped — never stored. The same posting in the
  user's own country is kept with no penalty ("Yerevan hybrid — bring
  it"). This is a deliberate, user-approved exception to Ship 4's
  flag-never-hide rule, bounded by requiring BOTH an explicit mode phrase
  AND a confidently-parsed foreign country.
- **Unparseable location → flag, not drop.** Without knowing where the
  job is, a silent drop cannot be justified; the posting stays with a
  penalty and a stated reason.
- **No mode word → no claim.** Same discipline as geography.
- **Add the local lane.** Each run searches every role twice per source:
  the worldwide-remote cast (unchanged) plus the profile's location with
  all work modes. Driven by the profile; no location on file → lane
  skipped. Actor calls per run double (8 → 16).
- **Indeed: diagnose, else disable.** One cheap diagnostic call to
  inspect raw actor output; if descriptions exist under an unmapped
  field, map it. If genuinely absent, ship a `search.sources` config gate
  with Indeed off by default.
- **Volume: keep 50, enforce it client-side.**
- Everything generalizes to any user via `profile.work_modes` and
  `profile.country` — nothing hardcodes this user's preferences.

## Design

### vocabulary.yaml — new `work_mode` section, one penalty, US states

Phrases only — never bare words. Bare "hybrid" fires on "hybrid cloud"
(common in data-job postings); bare "remote" fires on "remote teams";
bare "on-site" fires on "on-site gym". Every phrase must be role-anchored.

```yaml
work_mode:
  remote_phrases:   [fully remote, 100% remote, remote position, remote role,
                     remote-first, work remotely, work from home]
  hybrid_phrases:   [hybrid work, hybrid role, hybrid model, hybrid working,
                     hybrid position, hybrid schedule,
                     days per week in the office, days a week in the office,
                     in-office days]
  onsite_phrases:   [on-site role, onsite role, on-site position,
                     onsite position, in-office role, must work onsite,
                     onsite work required]
  # Reviewed out for reproduced false positives: "no remote work"
  # (...experience required), "office-based" (...clients), "hybrid model"
  # (ML term), "in-office days" (...are optional), "on-site only" (...gym
  # access). Added: remote-only, work from anywhere, telecommute.

penalties:
  mode_mismatch: 15   # says hybrid/on-site, user searched remote-only,
                      # and the place could not be parsed

eligibility:
  us_states: [al, ak, az, ar, ca, co, ct, de, fl, ga, hi, id, il, in, ia,
              ks, ky, la, me, md, ma, mi, mn, ms, mo, mt, ne, nv, nh, nj,
              nm, ny, nc, nd, oh, ok, or, pa, ri, sc, sd, tn, tx, ut, vt,
              va, wa, wv, wi, wy, dc]   # for location parsing: "New York, NY" -> us
```

(Quote any YAML-boolean collisions; `in` and `on` are safe as list items,
but verify at implementation time.)

### matching.py — two new pure rules

```python
def work_mode(body: str, cfg: dict) -> str | None
```
Scans title+description text (lowercased) for the three phrase lists via
the existing `has_term` boundaries. Exactly one category matched → that
mode. Zero or more than one ("remote or hybrid") → `None`, no claim.
Accepted miss, documented: a title tag like "Data Analyst (Hybrid)" with
no body phrase stays `None` — bare-word matching is the greater evil.

```python
def location_country(location: str, cfg: dict) -> str | None
```
Parses a stored location string ("Bengaluru, Karnataka, India") against
`eligibility.countries` names, word-bounded, **rightmost match wins**
(locations end with the country: "Georgia, US" → us). Bare "us" is
allowed here — a location string is not prose, so the pronoun hazard does
not apply. Hardened during implementation review (probed against all 549
real stored locations):

- A country alias that is also a US state name ("georgia") is **silent
  both ways** — "Atlanta, Georgia" must not parse as the country, and
  the accepted cost is "Tbilisi, Georgia" parsing as nothing.
- The 2-letter `us_states` fallback is **anchored to the final
  comma-segment** with an optional ZIP ("Austin, TX 78701" → us) —
  "La Paz", "Or Yehuda" and diacritic fragments no longer read as us.
- An ambiguous code stays silent even there: "San Francisco, CA" and
  "Chennai, IN" are structurally identical, so both are `None` — a safe
  silence beats a coin-flip that can delete a real job.
- `us_state_names` (full names) covers suffix-free US formats:
  "Austin, Texas" → us.
- **A tail that independently says "us" outranks a country-named city**:
  "Holland, MI" is Michigan, not the Netherlands; "Poland, OH" is Ohio.
  ("New England" → gb stays an accepted minor: its tail is the whole
  string.)
- "Remote" → `None`; and in the run_core ladder a location of literally
  "Remote" **vetoes** a stray prose mode phrase entirely — conflicting
  evidence claims nothing (no drop, no flag, no stored mode).

### run_core.py — the policy ladder and the local lane

**Policy** (between dedupe/enrich and scoring, in the one shared path;
`user_modes = profile.get("work_modes")`, `user_country` as in Ship 4):

| Posting's text says | Location country | Action |
|---|---|---|
| mode ∉ user_modes | known, ≠ user's | **dropped** — not scored, not stored; counted |
| mode ∉ user_modes | = user's | kept, no penalty; mode stored |
| mode ∉ user_modes | unparseable, or user country unset | kept + `mode_mismatch` penalty via the scorer, clause `"says hybrid, you searched remote-only"` (mode and modes interpolated) |
| mode ∈ user_modes, or `None` | any | current behavior; mode stored when detected |

The scorer stays location-ignorant: run_core computes `(mode,
loc_country)` once per job, decides drop / keep-clean / keep-flag, and
passes a `mode_mismatch: str | None` argument through `best_match` →
`score_job` → `_constraints`, exactly like `scraped_under`. `RunResult`
gains `dropped: int`; the progress payload carries it.

**Local lane:** `plan_steps` produces steps per (title × source × lane).
Lane "worldwide" runs exactly today's calls. Lane "local" calls each
scraper with `location=profile["location"]` and
`work_modes=("remote", "hybrid", "onsite")` — the existing
`_filters_for`/`_location_for` logic then searches the actual place with
all modes. Lane skipped entirely when the profile has no location. The
step's display source reads "LinkedIn · local" so the progress screen
needs no changes. Dedupe already collapses cross-lane duplicates.

### Storage and map

- `role.work_mode TEXT NULL` — added via the existing schema-migration
  pattern; backfill is NULL (old rows honestly unknown).
- `_role_view` exposes it; the map card's meta line and drawer meta
  prepend the mode when present: `HYBRID · YEREVAN · POSTED 2D`.
  DESIGN.md tokens; no new UI surfaces.

### Indeed: diagnose, else disable

A diagnosis task early in the plan: one actor call, `maxResults` ~5,
dump raw item keys and sample values.
- **Branch found:** descriptions exist under an unmapped key → add it to
  `_DESCRIPTION_KEYS` in `scrapers/base.py`, prove with the run's own
  output, Indeed stays enabled.
- **Branch absent:** new config gate —

```yaml
search:
  sources:
    indeed:   false   # off: two runs, zero descriptions — unscoreable
    linkedin: true
```

  `run_core` filters `SOURCES` by the gate (missing key → enabled, so
  existing configs keep working). The plan encodes both branches; the
  implementer executes whichever the diagnosis proves.

### Volume

Each scraper truncates its mapped jobs to `jobs_per_category` before
returning (`jobs[:jobs_per_category]`) — Indeed's 100-for-50 overshoot
ends at the client boundary regardless of actor behavior.

## Testing

- `work_mode` units: each phrase category; false-positive guards
  ("hybrid cloud", "remote teams", "on-site gym" → None); conflict →
  None; empty cfg → None.
- `location_country` units: country-name hit; rightmost-wins ("Georgia,
  US" → us); US state codes ("New York, NY" → us); "Remote" → None;
  unknown → None.
- Policy ladder through `run_core.execute` (integration, real scorer):
  one test per row — foreign hybrid dropped (and `dropped` counted, not
  stored); local hybrid kept unpenalized; unparseable-location hybrid
  kept with the clause in the stored reason; no-mode-word untouched.
  Mutation-checked against the drop condition.
- Local lane: `plan_steps` doubles with a location on file, doesn't
  without; the local scrape call receives the profile location and all
  three modes (captured via injected scrapers); lane label in steps.
- Scorer: `mode_mismatch` clause + penalty fires only when passed;
  keyword-default keeps all existing tests green.
- Migration: old DB gains the column; old rows NULL; map renders NULL
  mode with no chip.
- Config gate: indeed off → no Indeed steps planned; missing key →
  both sources run.
- Volume: scraper returns ≤ cap when the actor overshoots.
- Live smoke after merge: rerun, verify dropped count > 0, a local-lane
  step visible, and no foreign on-site cards in the new section.

## Out of scope

- Multi-city local lanes, commute radius.
- Work-mode preference UI changes (the profile's existing checkboxes
  stay the source of truth).
- Title-tag mode detection ("(Hybrid)" in titles) — accepted miss.
- Ship 4's documented geo residuals.
- Replacement Indeed actor research (only if the disable branch lands
  and Indeed is missed later).
