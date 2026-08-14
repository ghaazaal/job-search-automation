# Geo-Eligibility Flagging (Ship 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flag (never hide) postings restricted to a country the user isn't in, and stop Indeed's silent us-board fallback from passing unmarked.

**Architecture:** A new pure rule `matching.geo_restriction` reads phrase templates and country aliases from `vocabulary.yaml`; `Scorer._constraints` turns a hit into a penalty and a fired clause exactly like `clearance` today, so the reason sentence carries it with zero `reason.py` changes. The Indeed scraper tags fallback results with a transient `_scraped_under` key; `run_core.execute` pops it (so it can never be stored) and hands it to the scorer as an explicit argument, where it becomes a softer reduced-confidence flag.

**Tech Stack:** Python 3, pytest, PyYAML, regex via the existing `has_term` lookaround style. No new dependencies, no schema change, no UI change.

**Spec:** `docs/superpowers/specs/2026-08-15-geo-eligibility-design.md`

---

## Read this before Task 1

- Working directory for all commands: `job_hunt/` (tests import `src.*` from there). Run pytest as `python -m pytest`.
- The full suite must stay green after every task. `Scorer.__init__`, `score_job`, and `best_match` gain **keyword arguments with defaults** precisely so the ~40 existing scorer/vocabulary/run_core tests keep passing untouched.
- House test style: plain functions, docstrings state the rule being defended, fixtures over setup methods, `monkeypatch` for network. Follow `tests/test_scorer.py` and `tests/test_scrapers.py`.
- The scorer lowercases `body` before `_constraints` runs; `geo_restriction` still lowercases defensively (same choice `matching.gaps` makes).
- **Never render a score.** All flags surface only through `penalties`/`reason`.

### File map

| File | Action |
|---|---|
| `job_hunt/vocabulary.yaml` | Modify — `eligibility` section, two penalties |
| `job_hunt/tests/test_vocabulary.py` | Modify — guard the new section |
| `job_hunt/src/scoring/matching.py` | Modify — add `geo_restriction` + `_display_name` |
| `job_hunt/tests/test_geo_restriction.py` | Create |
| `job_hunt/src/scoring/scorer.py` | Modify — `user_country`, `scraped_under`, `_constraints` |
| `job_hunt/tests/test_scorer_geo.py` | Create |
| `job_hunt/src/scrapers/indeed.py` | Modify — tag fallback results |
| `job_hunt/tests/test_scrapers.py` | Modify — three tagging tests |
| `job_hunt/src/run_core.py` | Modify — pop the tag, pass country + tag to scorer |
| `job_hunt/tests/test_run_core_execute.py` | Modify — wiring guards |

---

### Task 1: vocabulary.yaml — eligibility facts and two penalty weights

**Files:**
- Modify: `job_hunt/vocabulary.yaml`
- Test: `job_hunt/tests/test_vocabulary.py`

- [ ] **Step 1: Write the failing tests**

Append to `job_hunt/tests/test_vocabulary.py`:

```python
def test_the_eligibility_section_holds_market_facts():
    """Country names and restriction phrasing are language facts, so they
    live here — but nothing in them may describe a particular person."""
    eligibility = _vocabulary()["eligibility"]
    assert {"countries", "templates"} == set(eligibility)
    assert all("{country}" in t for t in eligibility["templates"])
    # YAML 1.1 parses a bare `no:` (Norway) as boolean False. Every code
    # must arrive as a string — quote any future code YAML would eat.
    assert all(isinstance(code, str) for code in eligibility["countries"])
    assert all(isinstance(names, list) and names
               for names in eligibility["countries"].values())


def test_the_geo_penalties_are_configured():
    penalties = _vocabulary()["penalties"]
    assert penalties["geo_restricted"] == penalties["clearance"]
    assert penalties["wrong_board"] < penalties["geo_restricted"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vocabulary.py -v`
Expected: the two new tests FAIL with `KeyError: 'eligibility'` / `KeyError: 'geo_restricted'`; the six existing ones still pass.

- [ ] **Step 3: Add the section and the weights**

In `job_hunt/vocabulary.yaml`, extend the `penalties` block:

```yaml
# Employment constraints. These rule a posting out whatever your skills are.
penalties:
  "w2 only":      15
  clearance:      30
  secret:         30
  cpt:            20
  opt:            20
  exec_penalty:   10
  geo_restricted: 30   # a stated country restriction is the same class of blocker as clearance
  wrong_board:    10   # softer: results from Indeed's us fallback carry uncertainty, not a stated restriction
```

Then append at the end of the file:

```yaml
# Geography. How postings phrase a country restriction, and the names each
# country goes by in them. Market/language facts only — the user's own
# country lives in their profile, never here.
#
# YAML 1.1 gotcha: a bare `no:` (Norway) parses as boolean False. Quote any
# country code YAML would eat: `"no":`, `"on":`.
eligibility:
  countries:            # code -> names as postings write them
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vocabulary.py -v`
Expected: all 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add vocabulary.yaml tests/test_vocabulary.py
git commit -m "feat: vocabulary learns how postings phrase a country restriction"
```

---

### Task 2: `matching.geo_restriction` — the pure rule

**Files:**
- Modify: `job_hunt/src/scoring/matching.py`
- Create: `job_hunt/tests/test_geo_restriction.py`

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_geo_restriction.py`:

```python
"""Tests for matching.geo_restriction — the country a posting locks hiring to.

The rule is pure: body text in, display name (or None) out. The config is
inlined here rather than loaded from vocabulary.yaml so each test states
exactly which templates it exercises; test_vocabulary.py guards the real file.
"""
from src.scoring.matching import geo_restriction

_CFG = {
    "countries": {
        "am": ["armenia"],
        "us": ["us", "usa", "u.s.", "united states", "america"],
        "gb": ["uk", "united kingdom", "britain", "england"],
        "ca": ["canada"],
    },
    "templates": [
        "must be based in {country}",
        "must reside in {country}",
        "based in {country} only",
        "located in {country}",
        "authorized to work in {country}",
        "eligible to work in {country}",
        "work authorization in {country}",
        "{country} citizens only",
        "{country} residents only",
        "open to candidates in {country}",
    ],
}


def test_a_stated_restriction_names_the_country():
    body = "this role is remote but you must be based in the uk."
    assert geo_restriction(body, "am", _CFG) == "UK"


def test_citizens_only_phrasing_fires():
    assert geo_restriction("us citizens only, no sponsorship.",
                           "am", _CFG) == "US"


def test_the_article_is_optional_and_long_names_resolve_to_the_short_one():
    """'the united states' must match the `united states` entry, and the
    display name is the country's first listed name — 'US', not the
    phrasing that happened to match."""
    body = "applicants must be based in the united states."
    assert geo_restriction(body, "am", _CFG) == "US"


def test_display_casing():
    """`uk` -> UK (short codes upper-cased), `canada` -> Canada (title-cased)."""
    assert geo_restriction("must be based in the united kingdom.",
                           "am", _CFG) == "UK"
    assert geo_restriction("open to candidates in canada.",
                           "am", _CFG) == "Canada"


def test_your_own_country_is_not_a_restriction():
    assert geo_restriction("must be based in armenia.", "am", _CFG) is None


def test_no_user_country_claims_nothing():
    """With no country on file the check cannot run, so it must not fire —
    a claim we cannot ground is worse than silence."""
    assert geo_restriction("must be based in the uk.", "", _CFG) is None
    assert geo_restriction("must be based in the uk.", None, _CFG) is None


def test_a_plain_mention_is_not_a_restriction():
    assert geo_restriction("we serve clients across the us and europe.",
                           "am", _CFG) is None


def test_word_boundaries_hold_on_short_names():
    """'us' inside another word must not fire — same discipline has_term
    applies to 'opt' inside 'optimize'."""
    assert geo_restriction("the campus residents only lounge is closed.",
                           "am", _CFG) is None


def test_a_nearby_country_is_not_the_named_one():
    """'south america' must not satisfy an 'america' template — the name
    must sit exactly where the template puts it."""
    assert geo_restriction("must be based in south america.",
                           "am", _CFG) is None


def test_multiple_restrictions_yield_one_name():
    body = "must be based in the uk. us citizens only."
    assert geo_restriction(body, "am", _CFG) in {"UK", "US"}


def test_empty_config_is_silent():
    assert geo_restriction("must be based in the uk.", "am", {}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_geo_restriction.py -v`
Expected: FAIL at import — `cannot import name 'geo_restriction'`.

- [ ] **Step 3: Implement**

Append to `job_hunt/src/scoring/matching.py`:

```python
def _display_name(name: str) -> str:
    """`uk` -> "UK", `united kingdom` -> "United Kingdom"."""
    name = (name or "").strip().lower()
    return name.upper() if len(name) <= 3 else name.title()


def geo_restriction(body: str, user_country: str, cfg: dict) -> str | None:
    """The country a posting restricts hiring to, when it is not yours.

    Templates come from vocabulary.yaml with `{country}` as the substitution
    point. An optional `the ` may precede the country name, so "must be
    based in the united states" matches the `united states` entry. Matching
    uses the same lookaround boundaries as has_term, for the same reason:
    'us' must not fire inside 'campus'.

    Returns the display name of the restricting country — the first name in
    its list, however the posting happened to phrase it — or None when
    nothing matches, when `user_country` is unset (the check cannot run, so
    nothing may be claimed), or when the restriction names the user's own
    country. First hit wins; multiple restrictions do not stack.
    """
    user_country = (user_country or "").strip().lower()
    if not user_country:
        return None
    body = (body or "").lower()
    countries = (cfg or {}).get("countries") or {}
    templates = (cfg or {}).get("templates") or []
    for code, names in countries.items():
        if str(code).strip().lower() == user_country:
            continue
        for name in names or []:
            name = str(name).strip().lower()
            if not name:
                continue
            for template in templates:
                before, _, after = str(template).lower().partition("{country}")
                pattern = (r"(?<!\w)" + re.escape(before)
                           + r"(?:the\s+)?" + re.escape(name)
                           + re.escape(after) + r"(?!\w)")
                if re.search(pattern, body):
                    return _display_name(str(names[0]))
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_geo_restriction.py -v`
Expected: all 11 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scoring/matching.py tests/test_geo_restriction.py
git commit -m "feat: a pure rule reads a posting's country restriction"
```

---

### Task 3: Scorer — geography joins the constraint scan

**Files:**
- Modify: `job_hunt/src/scoring/scorer.py`
- Create: `job_hunt/tests/test_scorer_geo.py`

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_scorer_geo.py`:

```python
"""Tests for the geography constraints in Scorer._constraints.

Uses the real vocabulary.yaml — these are also the integration proof that
the shipped templates survive the scorer's lowercasing and land in the
reason sentence.
"""
from pathlib import Path

from src.scoring.scorer import Scorer

_CONFIG = {"scoring": {"bands": {"strong": 8, "partial": 5}}}
_VOCAB = Path(__file__).parent.parent / "vocabulary.yaml"

_RESUME = {
    "id": 1,
    "label": "bi",
    "seniority": "senior",
    "target_roles": [{"title": "BI Developer", "aliases": []}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": []},
               {"name": "SQL", "tier": "working", "aliases": []}],
}

_JD = "We need Power BI and SQL dashboards."

_BOARD_CLAUSE = "found via Indeed's US board, not verified for your country"


def _scorer(country="am"):
    return Scorer(_CONFIG, _VOCAB, user_country=country)


def test_a_foreign_restriction_costs_points_and_is_named():
    restricted = _scorer().score_job(
        "BI Developer", _JD + " Must be based in the UK.", _RESUME)
    free = _scorer().score_job("BI Developer", _JD, _RESUME)
    assert restricted["match_score"] < free["match_score"]
    assert "remote, but restricted to UK" in restricted["penalties"]
    assert "restricted to UK" in restricted["reason"]


def test_your_own_country_is_not_flagged():
    evidence = _scorer().score_job(
        "BI Developer", _JD + " Must be based in Armenia.", _RESUME)
    assert not any("restricted" in p for p in evidence["penalties"])


def test_no_country_on_file_claims_nothing():
    """A scorer built without a country must not fire geography at all —
    existing callers and tests keep their exact behaviour."""
    evidence = Scorer(_CONFIG, _VOCAB).score_job(
        "BI Developer", _JD + " Must be based in the UK.", _RESUME)
    assert not any("restricted" in p for p in evidence["penalties"])


def test_the_fallback_board_is_a_softer_flag():
    flagged = _scorer().score_job("BI Developer", _JD, _RESUME,
                                  scraped_under="us")
    clean = _scorer().score_job("BI Developer", _JD, _RESUME)
    assert _BOARD_CLAUSE in flagged["penalties"]
    assert flagged["match_score"] <= clean["match_score"]


def test_a_text_restriction_silences_the_board_flag():
    """Both present -> only the stated restriction fires. No double penalty,
    and the sentence states the stronger fact."""
    evidence = _scorer().score_job(
        "BI Developer", _JD + " US citizens only.", _RESUME,
        scraped_under="us")
    assert "remote, but restricted to US" in evidence["penalties"]
    assert _BOARD_CLAUSE not in evidence["penalties"]


def test_your_own_board_is_not_flagged():
    evidence = _scorer(country="us").score_job(
        "BI Developer", _JD, _RESUME, scraped_under="us")
    assert _BOARD_CLAUSE not in evidence["penalties"]


def test_best_match_passes_the_board_through():
    evidence = _scorer().best_match("BI Developer", _JD, [_RESUME],
                                    scraped_under="us")
    assert _BOARD_CLAUSE in evidence["penalties"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scorer_geo.py -v`
Expected: FAIL — `Scorer.__init__() got an unexpected keyword argument 'user_country'`.

- [ ] **Step 3: Implement**

In `job_hunt/src/scoring/scorer.py`, make four edits.

`__init__` (replace the whole method):

```python
    def __init__(self, config: dict, vocabulary_path: Path,
                 user_country: str = ""):
        self._vocab = _load(vocabulary_path)
        # Band cut-offs on the internal 1-10 score.
        self._bands = config.get("scoring", {}).get("bands",
                                                    {"strong": 8, "partial": 5})
        # Where the user can be hired. Empty means unknown, and unknown
        # means the geography checks stay silent rather than guess.
        self._user_country = (user_country or "").strip().lower()
```

`score_job` signature and the `_constraints` call:

```python
    def score_job(self, title: str, description: str, resume: dict,
                  scraped_under: str | None = None) -> dict:
```

```python
        penalty, fired = self._constraints(body, jd_band, my_band,
                                           scraped_under)
```

`best_match` signature and the inner call:

```python
    def best_match(self, title: str, description: str,
                   resumes: list[dict],
                   scraped_under: str | None = None) -> dict:
```

```python
        scored = [self.score_job(title, description, resume,
                                 scraped_under=scraped_under)
                  for resume in resumes]
```

`_constraints` — new signature, and the geography block inserted after the cpt/opt check, before the exec check:

```python
    def _constraints(self, body: str, jd_band: str, my_band: str,
                     scraped_under: str | None = None) -> tuple[int, list[str]]:
```

```python
        place = matching.geo_restriction(
            body, self._user_country, self._vocab.get("eligibility") or {})
        if place:
            penalty += cfg.get("geo_restricted", 30)
            fired.append(f"remote, but restricted to {place}")
        elif (scraped_under and self._user_country
              and scraped_under.strip().lower() != self._user_country):
            # The Indeed fallback searched the us board because the actor
            # rejected the user's country. That is uncertainty, not a stated
            # restriction — softer penalty, wording that claims no more than
            # we know, and never on top of a restriction the text did state.
            penalty += cfg.get("wrong_board", 10)
            fired.append("found via Indeed's US board, "
                         "not verified for your country")
```

- [ ] **Step 4: Run the scoring tests**

Run: `python -m pytest tests/test_scorer_geo.py tests/test_scorer.py tests/test_scorer_evidence.py tests/test_reason.py -v`
Expected: all PASS — the new file green, the three existing files untouched and green (defaults preserve old behaviour).

- [ ] **Step 5: Mutation-check the double-penalty guard**

Prove the guard test bites, without git-reverting (Step 3 is still uncommitted):

1. In the new `_constraints` block, change `elif` to `if` (one word).
2. Run: `python -m pytest tests/test_scorer_geo.py::test_a_text_restriction_silences_the_board_flag -v` — expected: FAIL (both clauses fired).
3. Change `if` back to `elif` by hand.
4. Re-run Step 4's command — expected: all PASS again.
5. `git diff src/scoring/scorer.py` — confirm only Step 3's intended edits remain.

- [ ] **Step 6: Commit**

```bash
git add src/scoring/scorer.py tests/test_scorer_geo.py
git commit -m "feat: the scorer flags postings the user cannot legally take"
```

---

### Task 4: Indeed — the fallback stops being silent

**Files:**
- Modify: `job_hunt/src/scrapers/indeed.py`
- Test: `job_hunt/tests/test_scrapers.py`

- [ ] **Step 1: Write the failing tests**

Append to the Indeed section of `job_hunt/tests/test_scrapers.py` (uses the existing `_capture` helper and `_MINIMAL` item):

```python
def test_indeed_tags_fallback_results_with_the_board_they_came_from(monkeypatch):
    """When the actor rejects the user's country and the retry lands on the
    us board, every job must say so — the scorer turns the tag into a
    reduced-confidence flag."""
    _capture(monkeypatch, indeed, [[], [_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Yerevan, Armenia", country="am",
                         work_modes=["remote"])
    assert jobs[0]["_scraped_under"] == "us"


def test_indeed_does_not_tag_when_the_country_already_matched(monkeypatch):
    """A retry that only changed the location searched the same country —
    nothing to warn about."""
    _capture(monkeypatch, indeed, [[], [_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Austin, TX", country="us",
                         work_modes=["onsite"])
    assert "_scraped_under" not in jobs[0]


def test_indeed_does_not_tag_without_a_fallback(monkeypatch):
    _capture(monkeypatch, indeed, [[_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Yerevan, Armenia", country="am",
                         work_modes=["remote"])
    assert "_scraped_under" not in jobs[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scrapers.py -v -k indeed`
Expected: the first new test FAILS with `KeyError: '_scraped_under'`; the other two already pass (they pin current behaviour so the implementation cannot over-tag).

- [ ] **Step 3: Implement**

In `job_hunt/src/scrapers/indeed.py`, track whether the retry fired — replace the retry block:

```python
    # The actor's input schema is undocumented. A rejected payload comes back
    # as an empty list, indistinguishable from a genuinely empty search, so
    # the only safe response is to retry once with the values known to work.
    fellback = False
    legacy = {**payload, "location": _LEGACY_LOCATION,
              "country": _LEGACY_COUNTRY}
    if not raw and legacy != payload:
        logger.warning(
            "Indeed returned nothing for %s with location=%r country=%r — "
            "retrying with the legacy remote/us payload",
            category, payload["location"], payload["country"])
        raw = call_actor(actor_id, legacy, f"Indeed/{category} (legacy)",
                         run_timeout)
        fellback = True
```

And just before `return jobs` at the end of `scrape`:

```python
    if fellback and payload["country"] != _LEGACY_COUNTRY:
        # These jobs came off the us board, not the one that was asked for.
        # Transient by design: run_core pops the key before anything is
        # scored or stored; the scorer receives it as an explicit argument.
        for job in jobs:
            job["_scraped_under"] = _LEGACY_COUNTRY
    return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scrapers.py -v`
Expected: all PASS, including the five pre-existing Indeed fallback tests.

- [ ] **Step 5: Commit**

```bash
git add src/scrapers/indeed.py tests/test_scrapers.py
git commit -m "feat: Indeed's us-board fallback marks the jobs it fetched"
```

---

### Task 5: run_core — the explicit hand-off

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_run_core_execute.py`

- [ ] **Step 1: Write the failing tests**

Append to `job_hunt/tests/test_run_core_execute.py` (uses the existing `conn`/`user`/`resume` fixtures, `_job`, `_scrapers`, `_CONFIG`, `_PROFILE` — note `_PROFILE["country"]` is `"ca"`):

```python
def test_a_foreign_restriction_reaches_the_stored_reason(conn, user, resume):
    """The profile's country must arrive at the scorer — this is the wiring
    guard for the single Scorer construction site."""
    job = _job("https://x/9")
    job["description"] += " Must be based in the UK."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert "restricted to UK" in result.scored_jobs[0]["reason"]


def test_the_fallback_tag_becomes_a_flag_and_never_reaches_the_store(conn, user, resume):
    tagged = {**_job("https://x/8"), "_scraped_under": "us"}
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[tagged]))
    evidence = result.scored_jobs[0]
    assert "not verified for your country" in evidence["reason"]
    # Popped, not read: the transient key must be gone from what the
    # LLM/Excel steps and persist_run receive.
    assert "_scraped_under" not in evidence
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_core_execute.py -v`
Expected: the two new tests FAIL (no restriction clause in the reason; `_scraped_under` still present); the fourteen existing tests still pass.

- [ ] **Step 3: Implement**

In `job_hunt/src/run_core.py`, replace the scoring block (currently the `report("scoring")` line through the `scored_jobs = [...]` comprehension):

```python
    report("scoring")
    scorer = Scorer(config, VOCABULARY_PATH,
                    user_country=profile.get("country") or "")
    scored_jobs = []
    for job in new_jobs:
        # Set by the Indeed scraper when its us-board fallback fired.
        # Popped — not read — so the transient key can never reach
        # persist_run, the store, or the terminal path's later steps.
        scraped_under = job.pop("_scraped_under", None)
        scored_jobs.append(
            {**job, **scorer.best_match(job["title"],
                                        job.get("description", ""),
                                        resumes,
                                        scraped_under=scraped_under)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_core_execute.py -v`
Expected: all 16 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/run_core.py tests/test_run_core_execute.py
git commit -m "feat: runs judge geography against the profile's country"
```

---

### Task 6: Full suite, live smoke test

**Files:** none created — verification only.

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest -q`
Expected: everything passes. Any failure in a file this plan did not touch is a regression — stop and fix before proceeding.

- [ ] **Step 2: Live smoke test against the real vocabulary and a real profile shape**

Run from `job_hunt/`:

```bash
python -c "
from pathlib import Path
from src.scoring.scorer import Scorer
resume = {'id': 1, 'label': 'cv', 'seniority': 'senior',
          'target_roles': [{'title': 'BI Developer', 'aliases': []}],
          'skills': [{'name': 'Power BI', 'tier': 'core', 'aliases': []},
                     {'name': 'SQL', 'tier': 'working', 'aliases': []}]}
s = Scorer({'scoring': {'bands': {'strong': 8, 'partial': 5}}},
           Path('vocabulary.yaml'), user_country='am')
for jd, tag in [
    ('We need Power BI and SQL. Must be based in the UK.', None),
    ('We need Power BI and SQL. US citizens only.', None),
    ('We need Power BI and SQL.', 'us'),
    ('We need Power BI and SQL. Must be based in Armenia.', None),
]:
    e = s.score_job('BI Developer', jd, resume, scraped_under=tag)
    print(e['band'], '|', e['reason'])
"
```

Expected output shape (bands may vary with penalties; the reasons must):
- line 1 contains `remote, but restricted to UK`
- line 2 contains `remote, but restricted to US`
- line 3 contains `found via Indeed's US board, not verified for your country`
- line 4 contains **no** restriction clause

- [ ] **Step 3: Confirm nothing is uncommitted**

Run: `git status --short`
Expected: clean (only the plan doc itself, if it lives in this tree).

---

## Self-review notes (done at planning time)

- **Spec coverage:** vocabulary section → Task 1; `geo_restriction` incl. display casing, self-exemption, unset-country silence → Task 2; scorer penalties, wording, no-double-penalty, absence-phrase untouched → Task 3 (no `reason.py` task exists because the spec requires zero changes there — Task 3's reason assertions prove the clause flows through); Indeed tagging on divergence only → Task 4; pop-not-read + single wiring point → Task 5; live smoke → Task 6. LinkedIn `Worldwide` is deliberately untouched (spec: keep it).
- **Type consistency:** `geo_restriction(body, user_country, cfg) -> str | None` used identically in Tasks 2, 3. `scraped_under: str | None = None` threaded `best_match -> score_job -> _constraints`. `_scraped_under` string key identical in Tasks 4, 5.
- **Existing-suite safety:** every signature change is keyword-with-default; Task 3 Step 4 and Task 6 Step 1 verify.
