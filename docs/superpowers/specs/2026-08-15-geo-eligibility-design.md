# Geo-Eligibility Flagging — Ship 4 Design

Date: 2026-08-15
Status: approved (v3 — list-aware, after field testing showed postings
mostly phrase geography as eligible-country lists)

## Problem

Field testing after Ship 3 (user in Yerevan, Armenia, remote-only) surfaced
two geography failures:

1. **LinkedIn "remote" is not "remote for you".** The LinkedIn scraper
   deliberately searches `Worldwide` for a remote-only profile, so results
   include remote roles restricted to another country ("remote, must be
   UK-based"). Nothing detects that restriction: the map showed a
   Chennai-restricted role as a STRONG FIT whose reason claimed "no visa or
   clearance limits found". The scorer's constraint scan knows only
   US-specific terms (`w2 only`, `clearance`, `cpt`/`opt`) and nothing about
   geography.

2. **Indeed silently narrows to the US.** The Indeed actor rejected
   `country: "am"`; the scraper's legacy retry silently substituted
   `remote`/`us` and surfaced no signal. All 98 Indeed jobs in the test run
   came off the US board while the user believed the search covered their
   own market.

A further field observation (the reason for v3): remote postings mostly
phrase geography **positively**, as a list of eligible countries — "open to
candidates in the UK, Armenia and Poland" — or a region — "open to
candidates in EMEA". A restriction-template rule alone reads such a list
wrong: it would flag "restricted to UK" without noticing the user's country
sitting right there in the list. A country list needs list logic: *is my
country in it?*

## Decisions (made with the user)

- **Flag, don't hide.** A geo-restricted role stays on the map with a lower
  score and a stated reason, exactly like `clearance` and `w2 only` today.
  Hiding risks silently dropping real fits on a false positive.
- **One eligible country: the profile's `country` field.** No multi-country
  list. Extend later if it matters.
- **Keyword/phrase detection, not LLM.** Deterministic, free, testable, and
  consistent with the project's no-fabricated-facts rule. An LLM call per
  scraped job (hundreds per run) is not worth the cost or hallucination risk.
- **Eligibility lists are first-class** (v3). "Open to candidates in …" is
  handled as a list to scan for the user's country, never as a restriction
  template.
- **Regions are eligible-only evidence** (v3). "Open to candidates in EMEA"
  with the user's country in the region's member list marks the posting
  eligible. A region that does *not* include the user stays silent
  ("unknown") — region membership is fuzzy at the edges (whether "Europe"
  includes Armenia depends on the writer), and flagging exclusion on a
  fuzzy map would be fabricated precision. Wrong-side errors are impossible
  by construction: a miss never produces a wrong flag.
- **The Indeed fallback fix ships here too** — it is the same user complaint
  ("jobs aren't actually worldwide/for me") wearing a different hat.
- **LinkedIn's `Worldwide` cast is deliberately kept.** Under flagging it is
  the correct behavior: cast wide, mark what the user is ineligible for.
  Do not "fix" it back to a location-scoped search.

## Design

### vocabulary.yaml — new `eligibility` section, two new penalties

Country names, region membership and restriction phrasing are
market/language facts, so they belong in `vocabulary.yaml` (which must
never describe a particular person).

The shipped file names ~60 countries and full region membership — the
snippet below is abbreviated to show the shape. Coverage for a new user's
country is a one-line facts edit here, never a code change.

```yaml
eligibility:
  countries:            # code -> names as postings write them (abbreviated)
    am: [armenia]
    us: [us, usa, u.s., united states, america]
    gb: [uk, united kingdom, britain, england]
    ca: [canada]
    au: [australia]
    de: [germany]
    in: [india]
    sg: [singapore]
    # ... ~50 more; quote any code YAML 1.1 would eat ("no" — Norway)
  templates:            # restriction phrasings; {country} is the slot
    - "must be based in {country}"
    - "must reside in {country}"
    - "based in {country} only"
    - "located in {country}"
    - "authorized to work in {country}"
    - "eligible to work in {country}"
    - "work authorization in {country}"
    - "{country} citizens only"
    - "{country} residents only"
  list_phrases:         # introduce a list of eligible countries/regions
    - "open to candidates in"
    - "open to applicants in"
    - "eligible countries"
    - "we can hire in"
    - "able to hire in"
    - "available to candidates in"
    - "hiring in"
  anywhere_words: [worldwide, anywhere, globally]
  regions:              # eligible-only: membership marks the user eligible;
                        # absence stays silent, never flags exclusion
    - names: [emea]
      codes: [am, ge, gb, de, fr, nl, pl, ua]   # corporate EMEA reliably includes the Caucasus
    - names: [europe]
      codes: [gb, de, fr, nl, pl]   # deliberately no `am` — writer-dependent; silence beats a guess
    - names: [european union, eu]
      codes: [de, fr, nl, pl]
    - names: [apac, asia pacific, asia-pacific]
      codes: [au, in, sg]
    - names: [americas, north america]
      codes: [us, ca]

penalties:
  geo_restricted: 30    # a stated country restriction is the same class of blocker as clearance
  wrong_board:    10    # softer: results from Indeed's us fallback carry uncertainty, not a stated restriction
```

YAML 1.1 gotcha, noted in the file: a bare `no:` (Norway) or `on:` parses
as a boolean. Quote any such future code.

### matching.py — `geo_verdict`

```python
def geo_verdict(body: str, user_country: str, cfg: dict) -> tuple[str, str | None]
```

Returns one of four verdicts, checked in this order:

| Verdict | When |
|---|---|
| `("eligible", None)` | a list phrase's window names the user's country, an anywhere-word, or a region whose member codes include the user's country |
| `("restricted", "UK")` | a restriction template matches with a foreign country in the slot |
| `("excluded", "UK, Germany and Poland")` | list-phrase windows name known countries, none of them the user's |
| `("unknown", None)` | nothing matched, or `user_country` is unset — the check cannot run, so nothing is claimed |

Mechanics:

- **Windows**: each list-phrase occurrence opens a fixed 160-character
  window after it (no sentence-splitting — "u.s." breaks naive period
  logic). All windows are scanned for eligible evidence before anything
  else, so a list that names the user's country anywhere wins.
- **Matching** uses the same lookaround word boundaries as `has_term` —
  'us' must not fire inside 'campus'. Restriction templates allow an
  optional `the ` before the country name.
- **Display names**: a country renders as the first name in its list —
  upper-cased at ≤ 3 characters (`uk` → "UK"), title-cased otherwise
  (`armenia` → "Armenia") — however the posting happened to phrase it.
- **Excluded lists**: countries deduped by code, ordered by position in
  the text, capped at three names + " and others". Only claimed when the
  user's country is one the map knows the names of — otherwise their
  country might be in the list, just unrecognised.
- **Self-exemption**: a restriction naming the user's own country is not a
  restriction.
- First hit wins per tier; nothing stacks.

### scorer.py — geography joins `_constraints`

- `Scorer.__init__` gains `user_country: str = ""`.
- `score_job`/`best_match` gain `scraped_under: str | None = None`.
- `_constraints` acts on the verdict:
  - `restricted` → penalty `geo_restricted`, fired clause
    `"remote, but restricted to {place}"`.
  - `excluded` → penalty `geo_restricted`, fired clause
    `"remote, but open only to {places}"`.
  - `unknown` **and** `scraped_under` set and ≠ `user_country` → penalty
    `wrong_board`, fired clause
    `"found via Indeed's US board, not verified for your country"`.
    Deliberately soft wording — it states uncertainty, not a restriction
    the posting never made.
  - `eligible` → nothing fires, **including** `wrong_board`: positive
    text evidence beats board uncertainty.
- Fired clauses flow into the reason sentence through the existing
  penalties path — **zero `reason.py` changes**.
- The absence phrase ("no visa or clearance limits found") is deliberately
  **not** extended to mention location: when `user_country` is empty the geo
  check never ran, and the sentence would overclaim. Existing wording stays
  truthful in all cases.

### indeed.py — the fallback stops being silent

When the legacy `remote`/`us` retry fires **and** its payload actually
diverged from the requested country, tag each returned job:

```python
job["_scraped_under"] = "us"
```

The key is set only on divergence — a US user's fallback changes nothing and
gets no tag.

### run_core.py — explicit hand-off, single wiring point

- `execute()` passes `profile.get("country") or ""` into `Scorer(...)`.
  `Scorer` is constructed in exactly one place, so the browser run and the
  terminal CLI both get this for free.
- Before scoring each job: `scraped_under = job.pop("_scraped_under", None)`
  — popped, not read, so the transient key can never reach
  `persist_run`/`upsert_jobs` or the database. Passed explicitly:
  `scorer.best_match(title, description, resumes, scraped_under=...)`.

No schema change. No migration. No route or page changes — the map already
renders whatever the reason sentence says.

## Testing

- `geo_verdict` units: one per restriction-template shape; optional-`the`
  handling; display casing; self-country exemption; unset `user_country`
  → unknown; word-boundary safety on short names ("us"); "south america"
  must not satisfy an "america" template; list including the user →
  eligible; list excluding the user → excluded with position-ordered,
  capped display; eligible beats excluded across windows; anywhere-word →
  eligible; region including the user → eligible; region without the user
  → unknown (never excluded); unrecognised-country list → unknown;
  restriction beats an excluding list; empty config → unknown.
- `Scorer._constraints`: restricted and excluded penalties fire and land in
  `fired`; `wrong_board` fires only on `unknown`; eligible suppresses
  `wrong_board`; a text restriction silences the board flag (no double
  penalty). Mutation-tested.
- `indeed.py`: with `call_actor` mocked (empty first call, items on legacy
  retry), jobs carry `_scraped_under = "us"`; no tag when the country
  already matched or no fallback happened.
- `run_core`: the popped key never appears in `RunResult.scored_jobs`;
  the profile country demonstrably reaches the scorer (a restriction lands
  in a stored reason).
- Live smoke test against the real `vocabulary.yaml`, including an EMEA
  list (eligible for `am`) and a foreign-country list (excluded).

## Out of scope

- **Indeed zero-descriptions bug**: all 98 Indeed jobs in the test run have
  no description captured, which blocks *any* text-based scoring on them,
  geography included. Separate follow-up.
- Multi-country eligibility lists in the profile; LLM-based extraction.
- Region *exclusion* ("Europe-only" flagging a non-European user) — regions
  are eligible-only evidence by decision, see above.
- Standalone "work-from-anywhere" phrasing with no list phrase — falls
  through to "unknown", which carries no penalty and no claim.
- Detecting time-zone requirements ("must overlap 4h with PST").
- The map-cap fix (4 → expandable) already shipped separately before this
  spec.
