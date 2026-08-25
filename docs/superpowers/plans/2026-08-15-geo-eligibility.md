# Geo-Eligibility Flagging (Ship 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flag (never hide) postings restricted to a country the user isn't in — reading eligible-country lists as lists — and stop Indeed's silent us-board fallback from passing unmarked.

**Architecture:** A new pure rule `matching.geo_verdict` reads restriction templates, eligibility-list phrases, country aliases and region membership from `vocabulary.yaml` and returns one of four verdicts: `eligible` (user's country, an anywhere-word, or a member region named in a list window — nothing fires), `restricted` (a template hit), `excluded` (a list that omits the user), `unknown` (no claim). `Scorer._constraints` turns `restricted`/`excluded` into a penalty and a fired clause exactly like `clearance` today, so the reason sentence carries it with zero `reason.py` changes. The Indeed scraper tags fallback results with a transient `_scraped_under` key; `run_core.execute` pops it (so it can never be stored) and hands it to the scorer as an explicit argument, where it becomes a softer reduced-confidence flag — fired only on `unknown`, since positive eligibility evidence beats board uncertainty.

**Tech Stack:** Python 3, pytest, PyYAML, regex via the existing `has_term` lookaround style. No new dependencies, no schema change, no UI change.

**Spec:** `docs/superpowers/specs/2026-08-15-geo-eligibility-design.md`

---

## Read this before Task 1

- Working directory for all commands: `job_hunt/` (tests import `src.*` from there). Run pytest as `python -m pytest`.
- The full suite must stay green after every task. `Scorer.__init__`, `score_job`, and `best_match` gain **keyword arguments with defaults** precisely so the ~40 existing scorer/vocabulary/run_core tests keep passing untouched.
- House test style: plain functions, docstrings state the rule being defended, fixtures over setup methods, `monkeypatch` for network. Follow `tests/test_scorer.py` and `tests/test_scrapers.py`.
- The scorer lowercases `body` before `_constraints` runs; `geo_verdict` still lowercases defensively (same choice `matching.gaps` makes).
- **Never render a score.** All flags surface only through `penalties`/`reason`.

### File map

| File | Action |
|---|---|
| `job_hunt/vocabulary.yaml` | Modify — `eligibility` section, two penalties |
| `job_hunt/tests/test_vocabulary.py` | Modify — guard the new section |
| `job_hunt/src/scoring/matching.py` | Modify — add `geo_verdict` + helpers |
| `job_hunt/tests/test_geo_verdict.py` | Create |
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
    """Country names, region membership and restriction phrasing are
    language facts, so they live here — but nothing in them may describe a
    particular person."""
    eligibility = _vocabulary()["eligibility"]
    assert {"countries", "templates", "list_phrases", "anywhere_words",
            "regions"} == set(eligibility)
    assert all("{country}" in t for t in eligibility["templates"])
    # A list phrase introduces a list — it must not carry the slot itself.
    assert all("{country}" not in p for p in eligibility["list_phrases"])
    # YAML 1.1 parses a bare `no:` (Norway) or `on:` as a boolean. Every
    # code must arrive as a string — quote any future code YAML would eat.
    assert all(isinstance(code, str) for code in eligibility["countries"])
    assert all(isinstance(names, list) and names
               for names in eligibility["countries"].values())
    for region in eligibility["regions"]:
        assert {"names", "codes"} == set(region)
        assert region["names"] and region["codes"]
        assert all(isinstance(code, str) for code in region["codes"])


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
# Geography. How postings phrase who they can hire — restriction templates,
# phrases that introduce a list of eligible countries, and region
# membership. Market/language facts only — the user's own country lives in
# their profile, never here.
#
# YAML 1.1 gotcha: a bare `no:` (Norway) or `on:` parses as a boolean.
# Quote any country code YAML would eat: `"no":`, `"on":`.
eligibility:
  countries:            # code -> names as postings write them
    am: [armenia]
    us: [us, usa, u.s., united states, america]
    gb: [uk, united kingdom, britain, england]
    ca: [canada]
    au: [australia]
    nz: [new zealand]
    de: [germany]
    fr: [france]
    nl: [netherlands, holland]
    be: [belgium]
    lu: [luxembourg]
    ie: [ireland]
    es: [spain]
    it: [italy]
    pt: [portugal]
    pl: [poland]
    cz: [czech republic, czechia]
    sk: [slovakia]
    ro: [romania]
    bg: [bulgaria]
    gr: [greece]
    hu: [hungary]
    hr: [croatia]
    si: [slovenia]
    rs: [serbia]
    ee: [estonia]
    lv: [latvia]
    lt: [lithuania]
    se: [sweden]
    dk: [denmark]
    fi: [finland]
    "no": [norway]      # quoted — a bare `no:` is YAML for False
    ch: [switzerland]
    at: [austria]
    cy: [cyprus]
    mt: [malta]
    ua: [ukraine]
    by: [belarus]
    ge: [georgia]       # also a US state; a restriction reads the same either way
    az: [azerbaijan]
    kz: [kazakhstan]
    tr: [turkey]
    il: [israel]
    ae: [uae, united arab emirates, dubai]
    sa: [saudi arabia]
    eg: [egypt]
    ng: [nigeria]
    ke: [kenya]
    za: [south africa]
    in: [india]
    pk: [pakistan]
    bd: [bangladesh]
    lk: [sri lanka]
    sg: [singapore]
    my: [malaysia]
    id: [indonesia]
    ph: [philippines]
    vn: [vietnam]
    th: [thailand]
    jp: [japan]
    kr: [south korea, korea]
    cn: [china]
    mx: [mexico]
    br: [brazil]
    ar: [argentina]
    co: [colombia]
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
  # Regions are eligible-only evidence: membership marks the user eligible;
  # absence stays silent, never flags exclusion — membership is fuzzy at
  # the edges and a wrong exclusion would be fabricated precision.
  regions:
    - names: [emea]
      # Corporate EMEA reliably includes the Caucasus.
      codes: [am, ge, az, gb, ie, de, fr, nl, be, lu, es, it, pt, pl, cz,
              sk, ro, bg, gr, hu, hr, si, rs, ee, lv, lt, se, dk, fi,
              "no", ch, at, cy, mt, ua, by, kz, tr, il, ae, sa, eg, ng,
              ke, za]
    - names: [europe]
      # Deliberately no `am`, `ge`, `az`, `tr` — whether the Caucasus or
      # Turkey is "Europe" depends on the writer. Silence beats a wrong
      # eligibility claim.
      codes: [gb, ie, de, fr, nl, be, lu, es, it, pt, pl, cz, sk, ro, bg,
              gr, hu, hr, si, rs, ee, lv, lt, se, dk, fi, "no", ch, at,
              cy, mt, ua, by]
    - names: [european union, eu]
      # The EU-27 exactly — no gb, no ch, no "no".
      codes: [ie, de, fr, nl, be, lu, es, it, pt, pl, cz, sk, ro, bg, gr,
              hu, hr, si, ee, lv, lt, se, dk, fi, at, cy, mt]
    - names: [apac, asia pacific, asia-pacific]
      codes: [au, nz, in, sg, jp, kr, cn, ph, id, vn, th, my, pk, bd, lk]
    - names: [north america]
      codes: [us, ca, mx]
    - names: [americas]
      codes: [us, ca, mx, br, ar, co]
    - names: [latam, latin america]
      codes: [mx, br, ar, co]
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

### Task 2: `matching.geo_verdict` — the pure rule

**Files:**
- Modify: `job_hunt/src/scoring/matching.py`
- Create: `job_hunt/tests/test_geo_verdict.py`

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_geo_verdict.py`:

```python
"""Tests for matching.geo_verdict — what a posting says about where it hires.

The rule is pure: body text in, (verdict, detail) out. The config is
inlined here rather than loaded from vocabulary.yaml so each test states
exactly which phrasings it exercises; test_vocabulary.py guards the real
file, and test_scorer_geo.py proves the shipped file works end to end.
"""
from src.scoring.matching import geo_verdict

_CFG = {
    "countries": {
        "am": ["armenia"],
        "us": ["us", "usa", "u.s.", "united states", "america"],
        "gb": ["uk", "united kingdom", "britain", "england"],
        "ca": ["canada"],
        "de": ["germany"],
        "pl": ["poland"],
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
    ],
    "list_phrases": [
        "open to candidates in",
        "we can hire in",
        "eligible countries",
    ],
    "anywhere_words": ["worldwide", "anywhere", "globally"],
    "regions": [
        {"names": ["emea"], "codes": ["am", "gb", "de", "pl"]},
        {"names": ["europe"], "codes": ["gb", "de", "pl"]},
    ],
}


# ── restrictions ─────────────────────────────────────────────────────────────

def test_a_stated_restriction_names_the_country():
    body = "this role is remote but you must be based in the uk."
    assert geo_verdict(body, "am", _CFG) == ("restricted", "UK")


def test_citizens_only_phrasing_fires():
    assert geo_verdict("us citizens only, no sponsorship.",
                       "am", _CFG) == ("restricted", "US")


def test_the_article_is_optional_and_long_names_resolve_to_the_short_one():
    """'the united states' must match the `united states` entry, and the
    display name is the country's first listed name — 'US', not the
    phrasing that happened to match."""
    body = "applicants must be based in the united states."
    assert geo_verdict(body, "am", _CFG) == ("restricted", "US")


def test_your_own_country_is_not_a_restriction():
    assert geo_verdict("must be based in armenia.",
                       "am", _CFG) == ("unknown", None)


def test_no_user_country_claims_nothing():
    """With no country on file the check cannot run, so it must not fire —
    a claim we cannot ground is worse than silence."""
    assert geo_verdict("must be based in the uk.", "", _CFG) == ("unknown", None)
    assert geo_verdict("must be based in the uk.", None, _CFG) == ("unknown", None)


def test_a_plain_mention_is_not_a_restriction():
    assert geo_verdict("we serve clients across the us and europe.",
                       "am", _CFG) == ("unknown", None)


def test_word_boundaries_hold_on_short_names():
    """'us' inside another word must not fire — same discipline has_term
    applies to 'opt' inside 'optimize'."""
    assert geo_verdict("the campus residents only lounge is closed.",
                       "am", _CFG) == ("unknown", None)


def test_a_nearby_country_is_not_the_named_one():
    """'south america' must not satisfy an 'america' template — the name
    must sit exactly where the template puts it."""
    assert geo_verdict("must be based in south america.",
                       "am", _CFG) == ("unknown", None)


# ── eligibility lists ────────────────────────────────────────────────────────

def test_a_list_naming_your_country_is_eligible():
    """The v3 case: a country list must be read as a list, never as a
    restriction on whichever foreign name happens to sit first."""
    body = "open to candidates in the uk, armenia and poland."
    assert geo_verdict(body, "am", _CFG) == ("eligible", None)


def test_a_list_without_your_country_is_excluded_in_text_order():
    body = "open to candidates in poland, the uk and germany."
    assert geo_verdict(body, "am", _CFG) == (
        "excluded", "Poland, UK and Germany")


def test_a_long_exclusion_list_is_capped():
    body = "open to candidates in poland, the uk, germany and canada."
    assert geo_verdict(body, "am", _CFG) == (
        "excluded", "Poland, UK, Germany and others")


def test_eligible_anywhere_in_the_body_beats_an_earlier_foreign_list():
    body = "we can hire in the uk. open to candidates in armenia."
    assert geo_verdict(body, "am", _CFG) == ("eligible", None)


def test_an_anywhere_word_is_eligible():
    assert geo_verdict("open to candidates worldwide.",
                       "am", _CFG) == ("eligible", None)


def test_a_region_that_includes_you_is_eligible():
    assert geo_verdict("open to candidates in emea.",
                       "am", _CFG) == ("eligible", None)


def test_a_region_without_you_stays_silent_never_excluded():
    """Region membership is fuzzy at the edges — eligible-only evidence.
    `europe` omits `am` in this config, and the answer is silence, not a
    flag."""
    assert geo_verdict("open to candidates in europe.",
                       "am", _CFG) == ("unknown", None)


def test_a_list_of_unrecognised_countries_stays_silent():
    assert geo_verdict("open to candidates in narnia.",
                       "am", _CFG) == ("unknown", None)


def test_a_stated_restriction_beats_an_excluding_list():
    body = "us citizens only. open to candidates in the uk."
    assert geo_verdict(body, "am", _CFG) == ("restricted", "US")


def test_empty_config_is_silent():
    assert geo_verdict("must be based in the uk.", "am", {}) == ("unknown", None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_geo_verdict.py -v`
Expected: FAIL at import — `cannot import name 'geo_verdict'`.

- [ ] **Step 3: Implement**

Append to `job_hunt/src/scoring/matching.py`:

```python
# How far past a list phrase ("open to candidates in ...") country names
# are looked for. A fixed window rather than sentence-splitting, because
# "u.s." breaks naive period logic.
_LIST_WINDOW = 160


def _display_name(name: str) -> str:
    """`uk` -> "UK", `united kingdom` -> "United Kingdom"."""
    name = (name or "").strip().lower()
    return name.upper() if len(name) <= 3 else name.title()


def _join_names(names: list[str]) -> str:
    """`[a, b, c]` -> "a, b and c"; four or more cap at three + others."""
    if len(names) == 1:
        return names[0]
    if len(names) <= 3:
        return f"{', '.join(names[:-1])} and {names[-1]}"
    return f"{', '.join(names[:3])} and others"


def _bounded(term: str) -> str:
    """The has_term lookaround pattern, reusable inside larger regexes."""
    return r"(?<!\w)" + re.escape(term) + r"(?!\w)"


def geo_verdict(body: str, user_country: str,
                cfg: dict) -> tuple[str, str | None]:
    """What a posting says about where it hires, judged for one user.

    Returns one of:
      ("eligible", None)      — a list phrase's window names the user's
                                country, an anywhere-word, or a region the
                                user's country belongs to
      ("restricted", "UK")    — a restriction template fired with a foreign
                                country in the slot
      ("excluded", "UK, ...") — list windows name known countries, none of
                                them the user's
      ("unknown", None)       — nothing matched, or `user_country` is unset:
                                the check cannot run, so nothing is claimed

    Checked in that order — positive evidence anywhere in the body settles
    it before any flag is considered. Regions are eligible-only evidence:
    a region that does not include the user yields silence, never
    exclusion, because membership is fuzzy at the edges. An "excluded"
    verdict is only claimed when the user's country is one this config
    knows the names of — otherwise it might be in the list, just
    unrecognised. Matching uses the same lookaround boundaries as
    has_term ('us' must not fire inside 'campus'); restriction templates
    allow an optional `the ` before the country name.
    """
    user_country = (user_country or "").strip().lower()
    if not user_country:
        return ("unknown", None)
    body = (body or "").lower()
    cfg = cfg or {}
    countries = {
        str(code).strip().lower():
            [str(n).strip().lower() for n in (names or []) if str(n).strip()]
        for code, names in (cfg.get("countries") or {}).items()
    }

    windows: list[str] = []
    for phrase in cfg.get("list_phrases") or []:
        phrase = str(phrase).strip().lower()
        if not phrase:
            continue
        for match in re.finditer(_bounded(phrase), body):
            windows.append(body[match.end():match.end() + _LIST_WINDOW])

    # 1. Eligible — every window is scanned before anything may flag.
    user_names = countries.get(user_country) or []
    anywhere = [str(w).strip().lower()
                for w in cfg.get("anywhere_words") or []]
    for window in windows:
        if any(has_term(name, window) for name in user_names):
            return ("eligible", None)
        if any(has_term(word, window) for word in anywhere if word):
            return ("eligible", None)
        for region in cfg.get("regions") or []:
            codes = {str(c).strip().lower()
                     for c in (region.get("codes") or [])}
            names = [str(n).strip().lower()
                     for n in (region.get("names") or [])]
            if user_country in codes and any(has_term(n, window)
                                             for n in names if n):
                return ("eligible", None)

    # 2. Restricted — a template stating where hiring is locked to.
    templates = cfg.get("templates") or []
    for code, names in countries.items():
        if code == user_country:
            continue
        for name in names:
            for template in templates:
                before, _, after = str(template).lower().partition("{country}")
                pattern = (r"(?<!\w)" + re.escape(before) + r"(?:the\s+)?"
                           + re.escape(name) + re.escape(after) + r"(?!\w)")
                if re.search(pattern, body):
                    return ("restricted", _display_name(names[0]))

    # 3. Excluded — lists that name countries, none of them the user's.
    if windows and user_names:
        hits: dict[str, int] = {}
        for index, window in enumerate(windows):
            for code, names in countries.items():
                if code == user_country or code in hits:
                    continue
                for name in names:
                    match = re.search(_bounded(name), window)
                    if match:
                        hits[code] = index * (_LIST_WINDOW + 1) + match.start()
                        break
        if hits:
            ordered = sorted(hits, key=hits.get)
            return ("excluded", _join_names(
                [_display_name(countries[code][0]) for code in ordered]))

    return ("unknown", None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_geo_verdict.py -v`
Expected: all 18 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scoring/matching.py tests/test_geo_verdict.py
git commit -m "feat: a pure rule reads where a posting can hire"
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


def test_an_excluding_list_costs_points_and_is_named():
    evidence = _scorer().score_job(
        "BI Developer", _JD + " Open to candidates in the UK and Germany.",
        _RESUME)
    assert "remote, but open only to UK and Germany" in evidence["penalties"]
    assert "open only to UK and Germany" in evidence["reason"]


def test_a_list_that_includes_you_is_not_flagged():
    """The v3 case, end to end through the shipped vocabulary: your country
    in the list means no flag of any kind."""
    evidence = _scorer().score_job(
        "BI Developer",
        _JD + " Open to candidates in the UK, Armenia and Poland.", _RESUME)
    assert not any("restricted" in p or "open only" in p
                   for p in evidence["penalties"])


def test_a_region_that_includes_you_is_not_flagged():
    """EMEA includes Armenia in the shipped vocabulary — eligible, silent."""
    evidence = _scorer().score_job(
        "BI Developer", _JD + " Open to candidates in EMEA.", _RESUME)
    assert not any("restricted" in p or "open only" in p
                   for p in evidence["penalties"])


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


def test_eligible_evidence_silences_the_board_flag():
    """Positive text evidence beats board uncertainty: a worldwide posting
    fetched via the us fallback needs no warning."""
    evidence = _scorer().score_job(
        "BI Developer", _JD + " Open to candidates worldwide.", _RESUME,
        scraped_under="us")
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
        verdict, detail = matching.geo_verdict(
            body, self._user_country, self._vocab.get("eligibility") or {})
        if verdict == "restricted":
            penalty += cfg.get("geo_restricted", 30)
            fired.append(f"remote, but restricted to {detail}")
        elif verdict == "excluded":
            penalty += cfg.get("geo_restricted", 30)
            fired.append(f"remote, but open only to {detail}")
        elif (verdict == "unknown" and scraped_under and self._user_country
              and scraped_under.strip().lower() != self._user_country):
            # The Indeed fallback searched the us board because the actor
            # rejected the user's country. That is uncertainty, not a stated
            # restriction — softer penalty, wording that claims no more than
            # we know, and never on top of anything the text did state.
            # "eligible" lands here too: positive evidence beats board
            # uncertainty, so nothing fires at all.
            penalty += cfg.get("wrong_board", 10)
            fired.append("found via Indeed's US board, "
                         "not verified for your country")
```

- [ ] **Step 4: Run the scoring tests**

Run: `python -m pytest tests/test_scorer_geo.py tests/test_scorer.py tests/test_scorer_evidence.py tests/test_reason.py -v`
Expected: all PASS — the new file green, the three existing files untouched and green (defaults preserve old behaviour).

- [ ] **Step 5: Mutation-check the verdict guard**

The board flag's protection is the `verdict == "unknown"` condition — prove the tests bite it, without git-reverting (Step 3 is still uncommitted):

1. In the board-flag `elif`, temporarily delete `verdict == "unknown" and ` from the condition.
2. Run: `python -m pytest tests/test_scorer_geo.py::test_eligible_evidence_silences_the_board_flag -v` — expected: FAIL (the board clause fired on an eligible posting).
3. Restore the deleted text by hand.
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
    ('We need Power BI and SQL. Open to candidates in the UK and Germany.', None),
    ('We need Power BI and SQL. Open to candidates in EMEA.', 'us'),
    ('We need Power BI and SQL. Open to candidates worldwide.', None),
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
- line 5 contains `remote, but open only to UK and Germany`
- line 6 contains **no** flag of any kind — EMEA includes `am`, and that eligibility also silences the board flag despite `scraped_under='us'`
- line 7 contains **no** flag of any kind

- [ ] **Step 3: Confirm nothing is uncommitted**

Run: `git status --short`
Expected: clean (only the plan doc itself, if it lives in this tree).

---

## Self-review notes (done at planning time)

- **Spec coverage:** vocabulary section incl. `list_phrases`/`anywhere_words`/`regions` → Task 1; `geo_verdict` incl. all four verdicts, window mechanics, display casing/order/cap, self-exemption, unset-country silence, eligible-only regions → Task 2; scorer wording for restricted/excluded, board flag only on `unknown`, eligible-suppresses-board, absence-phrase untouched → Task 3 (no `reason.py` task exists because the spec requires zero changes there — Task 3's reason assertions prove the clauses flow through); Indeed tagging on divergence only → Task 4; pop-not-read + single wiring point → Task 5; live smoke incl. list/region/worldwide cases → Task 6. LinkedIn `Worldwide` is deliberately untouched (spec: keep it).
- **Type consistency:** `geo_verdict(body, user_country, cfg) -> tuple[str, str | None]` used identically in Tasks 2, 3. `scraped_under: str | None = None` threaded `best_match -> score_job -> _constraints`. `_scraped_under` string key identical in Tasks 4, 5. Verdict strings `eligible`/`restricted`/`excluded`/`unknown` identical across Tasks 2, 3.
- **Existing-suite safety:** every signature change is keyword-with-default; Task 3 Step 4 and Task 6 Step 1 verify.
- **v3 note:** Task 2's config inlines regions where `europe` omits `am` on purpose — that test (`test_a_region_that_includes_you_stays_silent...`) defends the eligible-only decision, not an accident of the fixture.
