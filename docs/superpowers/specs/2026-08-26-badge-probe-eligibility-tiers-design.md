# Badge Probes + Eligibility Tiers — Ship 6 Design

Date: 2026-08-26
Status: approved

## Problem

The user's product judgment, verbatim: "If we show the user a position
that they can't apply, what is the point in using us." Field case: an
Anaplan posting in Salford, UK — Hybrid badge on LinkedIn — rendered as a
clean STRONG FIT, because:

1. **The badge never reaches us.** Diagnostics against four LinkedIn
   actors (valig, curious_coder, memo23, lntb — real 3-item validation
   calls, not READMEs) proved the workplace-type badge is absent from
   every actor's per-item output. Structural cause: guest (logged-out)
   job pages do not show the badge; one actor's own docs admit it.
   memo23's sample even returned the exact Salford posting with
   `workplaceType: null`. lntb's `workModel` field is an echo of the
   requested search filter (empty when unfiltered), not scraped truth.
2. **Most postings state nothing in text** (121 of 163 in run 3 had no
   mode words), and today's silence renders as "no visa or clearance
   limits found" — unchecked masquerading as fine.
3. **The text we do scan is mangled at the source**: valig's plain
   `description` field is pre-flattened with no separators
   ("…Manilawork setup & shift: Onsitewhy join…"), which defeats
   word-boundary matching — while a clean `descriptionHtml` sits unused
   in the same item. This produced a real wrong drop in Ship 5
   (the "RemoteTravel" case).

But the diagnostics also proved the recovery path: **LinkedIn's search
filter respects the badge server-side.** A hybrid-filtered search
returned exactly the badge-hybrid postings — the Salford Anaplan card
among them. Set membership in a filtered search IS badge evidence.

## Decisions (made with the user)

- **Geo/mode match is the product's spine.** All three pillars approved:
  text unmangling, verified/unverified tiers with ranking, and the badge
  probe lane (accepting ~+8 actor calls per run, ~50% more LinkedIn
  volume).
- **No actor switch.** No candidate delivers the badge per-item; valig
  stays (known shape, tests pin it).
- **Unverified is said and outranked, not hidden**: cards without
  positive eligibility evidence read "location eligibility not verified"
  and rank below verified ones. Flag-never-hide holds; Ship 5's bounded
  drop rule is unchanged.
- **Badge-vs-text conflicts claim nothing** — LinkedIn badges are
  poster-selected and our own data measured ~19% mislabeling, so a probe
  hit plus contradicting text evidence resolves to no claim, same
  discipline as every other conflict.

## Design

### A. Unmangled descriptions

`extract_description` (`scrapers/base.py`) prefers HTML-shaped fields:
`_DESCRIPTION_KEYS` reordered to `(descriptionHtml, description,
descriptionText, jobDescription, jobDescriptionText, snippet)`, and the
Indeed dict-unwrap prefers `html` over `text`. Tag-flattening inserts a
space per tag, so HTML input always yields separated text; plain input
passes through unchanged. This single change makes "Work setup & shift:
Onsite" and "Location: Remote" matchable where today they arrive fused
to their neighbors.

`vocabulary.yaml` `work_mode` gains the JD-header idiom family (exact
entries fixed in the plan, phrase-only rule unchanged):
"work setup & shift: onsite" / ": hybrid" / ": remote", and
"work setup: onsite" / ": hybrid" / ": remote".

### B. The badge probe lane

Per role, per run, LinkedIn only: two additional searches with the
actor's own workplace filter — `remote: ["3"]` (hybrid) and
`remote: ["1"]` (on-site) — same title, same `jobs_per_category` cap.
Probe results are **evidence, not candidates**: they are never scored or
stored. Their `url_normalised` values form two sets; any job from the
real lanes whose URL appears in a probe set carries badge evidence
(`hybrid` or `onsite`).

- Badge evidence enters the existing Ship 5 ladder as the mode when text
  said nothing: badge-hybrid + parsed foreign country → dropped (the
  Anaplan kill shot); badge + user's country/city → kept clean; badge +
  unplaceable → flagged.
- Text evidence and badge evidence disagreeing → no claim (see
  Decisions).
- Coverage is bounded by the cap (top-N per filter) — a miss is
  silence, never a wrong claim.
- Probe steps appear in `plan_steps`/progress with their own lane labels
  (e.g. "LinkedIn · probe hybrid") so the searching screen stays honest
  about what runs. `RunResult` gains probe-hit counts for reporting.

### C. Verified/unverified tiers

A role is **verified-eligible** when positive evidence exists that the
user can take it: geo verdict `eligible` (list/region/worldwide), or the
posting's location parses to the user's country, or the profile-city
rung matched. Everything else — including a clean-looking posting with
no geography at all — is **unverified**.

- Stored: `role.eligibility_verified INTEGER NOT NULL DEFAULT 0`
  (schema v5, forward-only, old rows honestly 0).
- **Sentence** (`reason.py` changes this ship, deliberately): the
  absence clause "no visa or clearance limits found" is replaced by
  tier-aware wording — verified keeps a positive clause (e.g. "open to
  your location"), unverified reads "location eligibility not
  verified". No fabricated claims in either direction.
- **Ranking**: within each map section, verified-eligible companies
  outrank unverified ones before the internal score applies
  (`queries.py` `_group` sort key gains the tier). The internal score
  itself is unchanged and still never rendered.
- The map card shows nothing numeric — the sentence carries the tier.

## Testing

- `extract_description`: html-preference on valig-shaped items (flat
  plain + clean html → separated text); Indeed dict html-first;
  plain-only items unchanged; the run-together regression body from
  Ship 5's review now yields matchable text.
- Header-idiom phrases: unit per phrase + false-positive guards.
- Probe sets: pure logic tested with injected scrapers — probe URLs
  never stored, badge evidence applied only on URL match, conflicts
  claim nothing, cap respected; ladder integration per rung (the
  Salford shape: badge-hybrid + gb + am user → dropped and counted).
- Tiers: verified flag stored per the three positive-evidence paths and
  0 otherwise; reason wording both ways; ranking places a verified
  PARTIAL FIT company above an unverified STRONG FIT one within the
  same section; migration v5 defaults old rows to 0.
- Live smoke after merge: rerun; confirm the Salford-class card is
  dropped or flagged, probe steps visible, unverified cards reworded
  and ranked below verified.

## Accepted residuals (reviewed, kept — with triggers)

- **Probe recall is unmeasured** (top-50 worldwide window per filter).
  `RunResult.badge_hits` counts badge-filled-silence; read it after the
  first live runs to turn recall from a guess into a number.
- **The reverse leak is unmeasured**: the hybrid filter may also leak
  genuinely-remote postings, and a badge-only foreign "hybrid" with
  silent text is dropped. The user's explicit product stance ("drop
  them") plus the recorded-and-visible drop (run.dropped, the map's
  HIDDEN note) carries this. Trigger to revisit: if live-run badge drops
  appear, spot-check a sample against the live postings; a confirmed
  reverse leak routes badge-only modes to the flag path instead.
- A probe or local search that finds nothing is now indistinguishable
  from an actor-rejected payload (`allow_fallback=False` trades that
  signal away deliberately — silence over a wrong answer).

## Out of scope

- Logged-in/cookie-based LinkedIn scraping (ToS and brittleness — not
  worth the badge).
- Probing Indeed (its badge equivalent is attribute tags already in
  scope of text evidence; revisit only with field data).
- Multi-country profiles, region exclusion, and all previously accepted
  residuals from Ships 4–5.
