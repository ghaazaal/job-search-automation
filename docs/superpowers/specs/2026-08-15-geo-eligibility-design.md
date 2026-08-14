# Geo-Eligibility Flagging — Ship 4 Design

Date: 2026-08-15
Status: approved

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

## Decisions (made with the user)

- **Flag, don't hide.** A geo-restricted role stays on the map with a lower
  score and a stated reason, exactly like `clearance` and `w2 only` today.
  Hiding risks silently dropping real fits on a false positive.
- **One eligible country: the profile's `country` field.** No multi-country
  list, no region buckets. Extend later if it matters.
- **Keyword/phrase detection, not LLM.** Deterministic, free, testable, and
  consistent with the project's no-fabricated-facts rule. An LLM call per
  scraped job (hundreds per run) is not worth the cost or hallucination risk.
- **The Indeed fallback fix ships here too** — it is the same user complaint
  ("jobs aren't actually worldwide/for me") wearing a different hat.
- **LinkedIn's `Worldwide` cast is deliberately kept.** Under flagging it is
  the correct behavior: cast wide, mark what the user is ineligible for.
  Do not "fix" it back to a location-scoped search.

## Design

### vocabulary.yaml — new `eligibility` section, two new penalties

Country names and restriction phrasing are market/language facts, so they
belong in `vocabulary.yaml` (which must never describe a particular person).

```yaml
eligibility:
  countries:            # code → names as postings write them
    am: [armenia]
    us: [us, usa, u.s., united states, america]
    gb: [uk, united kingdom, britain, england]
    ca: [canada]
    au: [australia]
    de: [germany]
    in: [india]
    sg: [singapore]
  templates:            # {country} is the substitution point
    - "must be based in {country}"
    - "must reside in {country}"
    - "based in {country} only"
    - "located in {country}"
    - "authorized to work in {country}"
    - "eligible to work in {country}"
    - "work authorization in {country}"
    - "{country} citizens only"
    - "{country} residents only"
    - "open to candidates in {country}"

penalties:
  geo_restricted: 30    # same class of blocker as clearance
  wrong_board:    10    # softer: uncertainty, not a stated restriction
```

### matching.py — `geo_restriction`

```python
def geo_restriction(body: str, user_country: str, cfg: dict) -> str | None
```

- Expands each template × each country name; an optional `the ` is allowed
  before the country name ("must be based in the United States").
- Word-boundary matching via the existing `has_term` machinery — no
  substring false positives.
- Returns the offending country's **display name** — the first name in its
  list, upper-cased when it is 3 characters or fewer (`uk` → "UK",
  `us` → "US"), title-cased otherwise (`armenia` → "Armenia") — or `None`
  when:
  - no template matches,
  - `user_country` is unset — the check cannot run, so nothing is claimed,
  - the restriction names the user's own country (an Armenia-restricted
    posting is fine for an Armenia-based user).
- First hit wins; multiple restrictions do not stack.

### scorer.py — geography joins `_constraints`

- `Scorer.__init__` gains `user_country: str = ""`.
- `score_job`/`best_match` gain `scraped_under: str | None = None`.
- `_constraints` additions, in order:
  1. `geo_restriction(...)` hit → penalty `geo_restricted`, fired clause
     `"remote, but restricted to {place}"`.
  2. Else, `scraped_under` set and ≠ `user_country` → penalty
     `wrong_board`, fired clause
     `"found via Indeed's US board, not verified for your country"`.
     The wording is deliberately soft — it states uncertainty, not a
     restriction the posting never made. Never fires when a text
     restriction already fired (no double penalty).
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

- `geo_restriction` units: one per template shape; optional-`the` handling;
  false-positive guards ("clients across the US" must not fire
  "must be based in the US"); self-country exemption; unset `user_country`
  returns `None`; word-boundary safety on short names ("us").
- `Scorer._constraints`: geo penalty fires and lands in `fired`;
  `wrong_board` fires only when `scraped_under` differs and no text
  restriction fired; both-present → only `geo_restricted`, no double
  penalty. Mutation-tested (revert the fix, watch the test fail, restore).
- `indeed.py`: with `call_actor` mocked (empty first call, items on legacy
  retry), jobs carry `_scraped_under = "us"`; no tag when the original
  payload already was `remote`/`us`.
- `run_core`: the popped key never appears in what `persist_run` receives;
  `Scorer` receives the profile country (wiring guard).
- Live smoke test against the real profile and stored run after merge.

## Out of scope

- **Indeed zero-descriptions bug**: all 98 Indeed jobs in the test run have
  no description captured, which blocks *any* text-based scoring on them,
  geography included. Separate follow-up.
- Multi-country eligibility lists, region buckets (EMEA/APAC), LLM-based
  extraction.
- Detecting time-zone requirements ("must overlap 4h with PST").
- The map-cap fix (4 → expandable) already shipped separately before this
  spec.
