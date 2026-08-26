# Work-Mode Truth + the Local Lane (Ship 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop foreign on-site/hybrid postings, keep local ones, store and show each job's work mode, add a local search lane per role, diagnose-or-disable Indeed, and enforce the volume cap.

**Architecture:** Two new pure rules in `matching.py` — `work_mode` (phrase-only mode detection) and `location_country` (location-string parsing) — feed a policy ladder in `run_core.execute`, the one shared path: confirmed-foreign mode mismatches are dropped before scoring (counted in `RunResult.dropped`), local ones kept clean, unplaceable ones flagged via a transient `_mode_mismatch` key the scorer receives as an explicit argument (the Ship 4 `_scraped_under` pattern). A `work_mode` column (schema v4) flows to the map card. `plan_steps` gains lanes: every role searches worldwide-remote plus the profile's location with all modes. A `search.sources` config gate can switch a scraper off; both scrapers truncate to the volume cap.

**Tech Stack:** Python 3, pytest, PyYAML, sqlite (forward-only migrations). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-26-work-mode-local-lane-design.md`

---

## Read this before Task 1

- Working directory for all commands: `job_hunt/`. Run pytest as `python -m pytest`. Full-suite baseline at branch start: **571 passed**.
- The full suite must stay green after every task; every signature change is keyword-with-default.
- House test style: plain functions, docstrings state the defended rule, `monkeypatch` for network, mutation-check fixes (revert → expected failure → restore → green).
- **Phrases only, never bare words** for mode detection — "hybrid cloud", "remote teams", "on-site gym" are the false positives the rule must survive.
- **Never render a score.** New flags surface only through `penalties`/`reason`; the dropped count surfaces only as an honest number in progress.
- Two known integration landmines this plan already accounts for — do not "fix" them differently: `main.py`'s `_announce` dedups printed steps by `(source, role)`, which collides once lanes duplicate those pairs (Task 6 fixes the key); `tests/test_run_core_execute.py`'s `test_the_first_event_already_lists_every_step` asserts 2 steps, which becomes 4 when the profile has a location (Task 6 updates it).

### File map

| File | Action |
|---|---|
| `job_hunt/vocabulary.yaml` | Modify — `work_mode` section, `mode_mismatch` penalty, `eligibility.us_states` |
| `job_hunt/tests/test_vocabulary.py` | Modify — guard the new sections |
| `job_hunt/src/scoring/matching.py` | Modify — add `work_mode`, `location_country` |
| `job_hunt/tests/test_work_mode.py` | Create |
| `job_hunt/src/store/schema.py` | Modify — v4: `role.work_mode` |
| `job_hunt/src/store/ingest.py` | Modify — write `work_mode` |
| `job_hunt/src/store/queries.py` | Modify — expose `work_mode` |
| `job_hunt/tests/test_store_migration.py` | Modify — v4 tests |
| `job_hunt/tests/test_store_ingest.py` | Modify — round-trip test |
| `job_hunt/src/scoring/scorer.py` | Modify — `user_modes`, `mode_mismatch` |
| `job_hunt/tests/test_scorer_mode.py` | Create |
| `job_hunt/src/run_core.py` | Modify — policy ladder, lanes, sources gate |
| `job_hunt/tests/test_run_core_execute.py` | Modify — ladder + lane + gate tests |
| `job_hunt/tests/test_run_core_steps.py` | Modify — `plan_steps` lane tests |
| `job_hunt/src/searching_page.py` | Modify — lane label in step row |
| `job_hunt/tests/test_searching_page.py` | Modify — lane snippet test |
| `job_hunt/main.py` | Modify — `_announce` dedup key gains lane |
| `job_hunt/tests/test_pipeline_announce.py` | Modify — lane-collision test |
| `job_hunt/src/scrapers/indeed.py`, `linkedin.py` | Modify — cap truncation |
| `job_hunt/tests/test_scrapers.py` | Modify — cap tests |
| `job_hunt/src/scrapers/base.py` | Modify only on the found-branch of Task 9 |
| `job_hunt/config.yaml` | Modify only on the absent-branch of Task 9 |
| `job_hunt/src/map_page.py` | Modify — mode in `_role_meta` |
| `job_hunt/tests/test_map_page.py` | Modify — chip test |

---

### Task 1: vocabulary — mode phrases, penalty, US states

**Files:**
- Modify: `job_hunt/vocabulary.yaml`
- Test: `job_hunt/tests/test_vocabulary.py`

- [ ] **Step 1: Write the failing tests**

Append to `job_hunt/tests/test_vocabulary.py`:

```python
def test_the_work_mode_section_holds_role_anchored_phrases():
    """Phrases only, never bare words — bare 'hybrid' fires on 'hybrid
    cloud', bare 'remote' on 'remote teams', bare 'on-site' on 'on-site
    gym'. Single-word entries are how those false positives creep back."""
    work_mode = _vocabulary()["work_mode"]
    assert {"remote_phrases", "hybrid_phrases",
            "onsite_phrases"} == set(work_mode)
    for phrases in work_mode.values():
        assert phrases
        assert all(" " in p or "-" in p for p in phrases), \
            "single bare words are banned here"


def test_the_mode_mismatch_penalty_is_configured():
    penalties = _vocabulary()["penalties"]
    assert 0 < penalties["mode_mismatch"] < penalties["geo_restricted"]


def test_us_states_are_two_letter_strings():
    """`in` (Indiana) is not a YAML boolean, but `on`/`no`/`off` would be —
    none of them are US states, and this guard keeps every entry a
    2-letter string if that ever changes."""
    states = _vocabulary()["eligibility"]["us_states"]
    assert states
    assert all(isinstance(s, str) and len(s) == 2 for s in states)
    assert "ny" in states and "dc" in states
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vocabulary.py -v`
Expected: the three new tests FAIL with `KeyError: 'work_mode'` / `KeyError: 'mode_mismatch'` / `KeyError: 'us_states'`; the ten existing ones still pass.

Note: `test_the_eligibility_section_holds_market_facts` asserts the exact key-set of `eligibility` — adding `us_states` will break it until Step 3 also updates that assertion. Update it in this step: add `"us_states"` to the expected set in that test.

- [ ] **Step 3: Add the data**

In `job_hunt/vocabulary.yaml`, add to the `penalties` block:

```yaml
  mode_mismatch:  15   # says hybrid/on-site, the user searched remote-only, and the place could not be parsed
```

Inside the `eligibility` section (after `ambiguous_names`):

```yaml
  # For parsing stored location strings ("New York, NY" -> us). Two-letter
  # state codes; none collide with YAML booleans today, and the guard test
  # keeps it that way.
  us_states: [al, ak, az, ar, ca, co, ct, de, fl, ga, hi, id, il, in, ia,
              ks, ky, la, me, md, ma, mi, mn, ms, mo, mt, ne, nv, nh, nj,
              nm, ny, nc, nd, oh, ok, or, pa, ri, sc, sd, tn, tx, ut, vt,
              va, wa, wv, wi, wy, dc]
  # Full state names for suffix-free US formats ("Austin, Texas").
  # `georgia` is deliberately ambiguous with the country — handled in code.
  us_state_names: [alabama, alaska, arizona, arkansas, california, colorado,
                   connecticut, delaware, florida, georgia, hawaii, idaho,
                   illinois, indiana, iowa, kansas, kentucky, louisiana,
                   maine, maryland, massachusetts, michigan, minnesota,
                   mississippi, missouri, montana, nebraska, nevada,
                   "new hampshire", "new jersey", "new mexico", "new york",
                   "north carolina", "north dakota", ohio, oklahoma, oregon,
                   pennsylvania, "rhode island", "south carolina",
                   "south dakota", tennessee, texas, utah, vermont,
                   virginia, washington, "west virginia", wisconsin, wyoming]
```

At the end of the file:

```yaml
# How postings phrase the way a role is worked. Phrases only, never bare
# words: bare "hybrid" fires on "hybrid cloud", bare "remote" on "remote
# teams", bare "on-site" on "on-site gym". Every entry must be
# role-anchored. Language facts only — whether a mode suits the user
# lives in their profile.
# Reviewed out: "no remote work" (…experience required), "office-based"
# (…clients), "hybrid model" (ML term), "in-office days" (…are optional).
work_mode:
  remote_phrases:
    - "fully remote"
    - "100% remote"
    - "remote position"
    - "remote role"
    - "remote-first"
    - "remote-only"
    - "work remotely"
    - "work from home"
    - "work from anywhere"
    - "telecommute"
  hybrid_phrases:
    - "hybrid work"
    - "hybrid role"
    - "hybrid working"
    - "hybrid position"
    - "hybrid schedule"
    - "days per week in the office"
    - "days a week in the office"
  onsite_phrases:
    - "on-site role"
    - "onsite role"
    - "on-site position"
    - "onsite position"
    - "in-office role"
    - "must work onsite"
    - "onsite work required"
```

> **Correction found during Task 1 code review** (probed with the consumer's
> own regex against realistic JD text): four given phrases had reproduced
> false positives and were removed — "no remote work" ("…experience
> required"), "office-based" ("…clients"), "hybrid model" (ML vocabulary:
> "a hybrid model combining ARIMA…" — this product's own audience),
> "in-office days" ("…are completely optional"). Three clean role-anchored
> phrases added: "remote-only", "must work onsite", "onsite work required".
> The review's other Critical — nine `us_states` codes are also country
> ISO codes ("Chennai, IN", "Toronto, CA") — is fixed in Task 2's
> `location_country` rule, not the data: an ambiguous token claims
> nothing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vocabulary.py -v`
Expected: all 11 PASS.

- [ ] **Step 5: Commit**

```bash
git add vocabulary.yaml tests/test_vocabulary.py
git commit -m "feat: vocabulary learns how postings phrase the way a role is worked"
```

---

### Task 2: `matching.work_mode` + `matching.location_country`

**Files:**
- Modify: `job_hunt/src/scoring/matching.py`
- Create: `job_hunt/tests/test_work_mode.py`

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_work_mode.py`:

```python
"""Tests for matching.work_mode and matching.location_country.

Both are pure: text in, fact out. Configs are inlined so each test states
what it exercises; test_vocabulary.py guards the real file.
"""
from src.scoring.matching import location_country, work_mode

_MODE_CFG = {
    "remote_phrases": ["fully remote", "remote position", "work from home"],
    "hybrid_phrases": ["hybrid work", "hybrid role",
                       "days a week in the office"],
    "onsite_phrases": ["on-site role", "onsite work required",
                       "must work onsite"],
}

_LOC_CFG = {
    "countries": {
        "am": ["armenia"],
        "us": ["us", "usa", "u.s.", "united states"],
        "gb": ["uk", "united kingdom", "britain", "england"],
        "ge": ["georgia"],
        "in": ["india"],
    },
    "us_states": ["ny", "wa", "ga", "tx", "in"],
}


# ── work_mode ────────────────────────────────────────────────────────────────

def test_each_phrase_category_is_detected():
    assert work_mode("this is a fully remote team.", _MODE_CFG) == "remote"
    assert work_mode("hybrid work, 2 days a week in the office.",
                     _MODE_CFG) == "hybrid"
    assert work_mode("onsite work required for this analyst position.",
                     _MODE_CFG) == "onsite"


def test_bare_words_never_fire():
    """'hybrid cloud', 'remote teams', 'on-site gym' are the false
    positives phrase-only matching exists to survive."""
    assert work_mode("experience with hybrid cloud required.",
                     _MODE_CFG) is None
    assert work_mode("you will manage remote teams.", _MODE_CFG) is None
    assert work_mode("perks include an on-site gym.", _MODE_CFG) is None


def test_conflicting_evidence_claims_nothing():
    body = "remote position or hybrid work, your choice."
    assert work_mode(body, _MODE_CFG) is None


def test_no_mode_word_claims_nothing():
    assert work_mode("we need power bi and sql.", _MODE_CFG) is None


def test_empty_config_is_silent():
    assert work_mode("fully remote.", {}) is None


def test_case_is_irrelevant():
    assert work_mode("This is a FULLY REMOTE role.", _MODE_CFG) == "remote"


# ── location_country ─────────────────────────────────────────────────────────

def test_a_country_name_resolves():
    assert location_country("Bengaluru, Karnataka, India", _LOC_CFG) == "in"


def test_the_rightmost_country_wins():
    """Locations end with the country: 'Georgia, US' is the state,
    'Tbilisi, Georgia' is the country."""
    assert location_country("Georgia, US", _LOC_CFG) == "us"
    assert location_country("Tbilisi, Georgia", _LOC_CFG) == "ge"


def test_a_us_state_code_resolves_to_us():
    assert location_country("New York, NY", _LOC_CFG) == "us"
    assert location_country("Seattle, WA", _LOC_CFG) == "us"


def test_remote_and_unknown_stay_none():
    assert location_country("Remote", _LOC_CFG) is None
    assert location_country("Narnia", _LOC_CFG) is None
    assert location_country("", _LOC_CFG) is None
    assert location_country(None, _LOC_CFG) is None


def test_a_state_code_inside_a_word_does_not_fire():
    """'ny' must not fire inside 'company' — word boundaries hold."""
    assert location_country("Acme Company HQ", _LOC_CFG) is None


def test_a_state_code_that_is_also_a_country_code_claims_nothing():
    """'Chennai, IN' abbreviates India; 'Gary, IN' abbreviates Indiana.
    The bare token cannot tell them apart, so it must claim nothing —
    a wrong 'us' here corrupts the drop decision."""
    assert location_country("Chennai, IN", _LOC_CFG) is None
    assert location_country("Gary, IN", _LOC_CFG) is None


def test_empty_location_config_is_silent():
    assert location_country("New York, NY", {}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_work_mode.py -v`
Expected: FAIL at import — `cannot import name 'work_mode'`.

- [ ] **Step 3: Implement**

Append to `job_hunt/src/scoring/matching.py`:

```python
def work_mode(body: str, cfg: dict) -> str | None:
    """How a posting says the role is worked, if it says so at all.

    Phrase lists come from vocabulary.yaml — phrases only, never bare
    words, because bare "hybrid" fires on "hybrid cloud" and bare
    "remote" on "remote teams". Exactly one category matching yields its
    mode; zero or conflicting evidence ("remote or hybrid") yields None,
    the same no-claim discipline geo_verdict follows. A title tag like
    "(Hybrid)" with no body phrase is an accepted miss — bare-word
    matching is the greater evil.
    """
    body = (body or "").lower()
    cfg = cfg or {}
    found = [mode for mode, key in (("remote", "remote_phrases"),
                                    ("hybrid", "hybrid_phrases"),
                                    ("onsite", "onsite_phrases"))
             if any(has_term(str(p).strip().lower(), body)
                    for p in cfg.get(key) or [] if str(p).strip())]
    return found[0] if len(found) == 1 else None


def location_country(location: str, cfg: dict) -> str | None:
    """The country a stored location string names, if it names one.

    Country names are matched word-bounded and the RIGHTMOST match wins —
    locations end with the country ("Georgia, US" is the state,
    "Tbilisi, Georgia" the country). Bare "us" is allowed here: a
    location string is not prose, so the pronoun hazard geo_verdict
    guards against does not apply. With no country name, any token that
    is a 2-letter code in `us_states` resolves to "us" — UNLESS that token
    is also a country ISO code ("Chennai, IN" abbreviates India, "Gary,
    IN" Indiana; the token cannot tell them apart, so it claims nothing).
    Anything else — including "Remote" — is None: no claim.
    """
    location = (location or "").lower()
    if not location:
        return None
    cfg = cfg or {}
    best: tuple[int, str] | None = None
    for code, names in (cfg.get("countries") or {}).items():
        for name in names or []:
            name = str(name).strip().lower()
            if not name:
                continue
            for match in re.finditer(_bounded(name), location):
                if best is None or match.start() > best[0]:
                    best = (match.start(), str(code).strip().lower())
    if best:
        return best[1]
    states = {str(s).strip().lower() for s in cfg.get("us_states") or []}
    codes = {str(c).strip().lower() for c in cfg.get("countries") or {}}
    for token in re.findall(r"(?<![a-z])[a-z]{2}(?![a-z])", location):
        if token in states and token not in codes:
            return "us"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_work_mode.py tests/test_matching.py tests/test_geo_verdict.py -v`
Expected: all PASS (13 new + existing untouched — two same-named
tests would shadow each other, hence the distinct empty-config names).

> **Correction found during Task 2 code review** (probed against all 549
> real stored locations — the shipped `matching.py` and test file are the
> authority over this task's inline blocks, which predate it):
> - **"georgia" is ambiguous both directions** ("Atlanta, Georgia" parsed
>   as the country `ge` on Indeed's suffix-free `city, state` format — a
>   drop-path corruption). Country aliases that are also US state names
>   are skipped by the country scan AND the state fallback: silence both
>   ways, including the accepted loss of "Tbilisi, Georgia".
> - **The state-code fallback is tail-anchored** with an optional ZIP:
>   "La Paz", "Or Yehuda", "Al Ain" and diacritic fragments ("iaşi" →
>   "ia") no longer resolve to `us`. An ambiguous code stays silent even
>   in `city, CODE` form — "San Francisco, CA" and "Chennai, IN" are
>   structurally identical, so both are None: a safe silence beats a
>   coin-flip that can delete a real job (accepted, pinned by test).
> - **`eligibility.us_state_names`** added (full names): "Austin, Texas"
>   → us.
> - **Phrases**: "on-site only"/"onsite only" removed ("on-site only gym
>   access"); "work from anywhere"/"telecommute" added — a thin remote
>   list next to a rich hybrid list is what turns boilerplate into drops.
> - **`work_mode` precompiles one alternation per category** (lru_cache) —
>   ~5.2ms/job measured, ~5× saved.
> - Task 5's ladder gained the Remote-location veto (see its code block):
>   a location field of literally "Remote" beats a stray prose phrase.

- [ ] **Step 5: Commit**

```bash
git add src/scoring/matching.py tests/test_work_mode.py
git commit -m "feat: pure rules read a posting's work mode and a location's country"
```

---

### Task 3: schema v4 — `role.work_mode`, stored and exposed

**Files:**
- Modify: `job_hunt/src/store/schema.py`, `job_hunt/src/store/ingest.py`, `job_hunt/src/store/queries.py`
- Test: `job_hunt/tests/test_store_migration.py`, `job_hunt/tests/test_store_ingest.py`

- [ ] **Step 1: Write the failing tests**

Append to `job_hunt/tests/test_store_migration.py`:

```python
def test_version_four_adds_work_mode_and_old_rows_stay_honest(tmp_path):
    """Old rows were scraped before mode detection existed — NULL, never a
    guessed backfill."""
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    assert "work_mode" in _columns(conn, "role")
    assert conn.execute(
        "SELECT work_mode FROM role").fetchone()["work_mode"] is None
```

Append to `job_hunt/tests/test_store_ingest.py` (follow that file's existing fixture style — read it first; it inserts via `upsert_jobs` with a conn fixture):

```python
def test_work_mode_round_trips(conn):
    job = {"title": "BI Developer", "company": "Acme",
           "url": "https://x/wm1", "location": "Yerevan, Armenia",
           "platform": "LinkedIn", "date": "2026-08-26",
           "description": "hybrid work", "description_captured": True,
           "work_mode": "hybrid", "match_score": 5, "band": "PARTIAL FIT",
           "reason": "r", "matched": [], "gaps": []}
    run_id = start_run(conn, 1)
    upsert_jobs(conn, 1, run_id, [job])
    assert conn.execute("SELECT work_mode FROM role WHERE url = ?",
                        ("https://x/wm1",)).fetchone()["work_mode"] == "hybrid"


def test_a_job_without_a_mode_stores_null(conn):
    job = {"title": "BI Developer", "company": "Acme",
           "url": "https://x/wm2", "description": "", "matched": [], "gaps": []}
    run_id = start_run(conn, 1)
    upsert_jobs(conn, 1, run_id, [job])
    assert conn.execute("SELECT work_mode FROM role WHERE url = ?",
                        ("https://x/wm2",)).fetchone()["work_mode"] is None
```

Adjust the two tests' fixture usage to whatever `test_store_ingest.py` actually provides (`conn`, user id, `start_run` import) — the assertions are the contract, the plumbing follows the file's existing style.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_store_migration.py tests/test_store_ingest.py -v`
Expected: new tests FAIL (`no such column: work_mode`); existing ones pass.

- [ ] **Step 3: Implement**

In `job_hunt/src/store/schema.py`:
1. `SCHEMA_VERSION = 4`
2. In `_DDL`'s `role` table, after the `posted_date` line add: `    work_mode            TEXT,`
3. Add to `_MIGRATIONS`:

```python
    4: (
        ("role", "work_mode", "ALTER TABLE role ADD COLUMN work_mode TEXT"),
    ),
```

In `job_hunt/src/store/ingest.py`, `_upsert_role`: add `job.get("work_mode")` to the `values` tuple right after the `posted_date` element (`str(job.get("date") or "")`), and add `work_mode` at the matching position in BOTH the UPDATE column list and the INSERT column list, with one more placeholder in each. Count placeholders carefully — the INSERT's VALUES groups must total the new column count.

In `job_hunt/src/store/queries.py`, `_role_view`: add `"work_mode": row["work_mode"],` after the `"platform"` entry.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_store_migration.py tests/test_store_ingest.py tests/test_store_queries.py tests/test_map_routing.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/store/schema.py src/store/ingest.py src/store/queries.py tests/test_store_migration.py tests/test_store_ingest.py
git commit -m "feat: roles remember how the posting said the role is worked"
```

---

### Task 4: scorer — the mode-mismatch flag

**Files:**
- Modify: `job_hunt/src/scoring/scorer.py`
- Create: `job_hunt/tests/test_scorer_mode.py`

- [ ] **Step 1: Write the failing tests**

Create `job_hunt/tests/test_scorer_mode.py`:

```python
"""Tests for the mode-mismatch flag in Scorer._constraints.

The scorer does not decide mode policy — run_core does, and passes
`mode_mismatch` only for the keep-and-flag rung of the ladder (mode the
user did not ask for, location unparseable). The scorer's job is the
penalty and the sentence.
"""
from pathlib import Path

from src.scoring.scorer import Scorer

_CONFIG = {"scoring": {"bands": {"strong": 8, "partial": 5}}}
_VOCAB = Path(__file__).parent.parent / "vocabulary.yaml"

_RESUME = {
    "id": 1, "label": "bi", "seniority": "senior",
    "target_roles": [{"title": "BI Developer", "aliases": []}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": []},
               {"name": "SQL", "tier": "working", "aliases": []}],
}

_JD = "We need Power BI and SQL dashboards."


def _scorer():
    return Scorer(_CONFIG, _VOCAB, user_country="am",
                  user_modes=("remote",))


def test_the_flag_costs_points_and_is_named():
    flagged = _scorer().score_job("BI Developer", _JD, _RESUME,
                                  mode_mismatch="hybrid")
    clean = _scorer().score_job("BI Developer", _JD, _RESUME)
    assert flagged["match_score"] <= clean["match_score"]
    assert "says hybrid, you searched remote-only" in flagged["penalties"]
    assert "says hybrid" in flagged["reason"]


def test_no_flag_without_the_argument():
    evidence = _scorer().score_job(
        "BI Developer", _JD + " Hybrid work, 2 days a week in the office.",
        _RESUME)
    assert not any("says hybrid" in p for p in evidence["penalties"])


def test_the_sentence_names_every_searched_mode():
    scorer = Scorer(_CONFIG, _VOCAB, user_country="am",
                    user_modes=("remote", "hybrid"))
    evidence = scorer.score_job("BI Developer", _JD, _RESUME,
                                mode_mismatch="onsite")
    assert "says onsite, you searched remote/hybrid-only" in evidence["penalties"]


def test_best_match_passes_the_flag_through():
    evidence = _scorer().best_match("BI Developer", _JD, [_RESUME],
                                    mode_mismatch="onsite")
    assert any("says onsite" in p for p in evidence["penalties"])
```

The second test pins the division of labor: the scorer itself must NOT
run mode detection — a description saying "hybrid" produces no flag
unless run_core passed one.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scorer_mode.py -v`
Expected: FAIL — `Scorer.__init__() got an unexpected keyword argument 'user_modes'`.

- [ ] **Step 3: Implement**

In `job_hunt/src/scoring/scorer.py`:

`__init__` gains a second keyword (after `user_country`):

```python
    def __init__(self, config: dict, vocabulary_path: Path,
                 user_country: str = "", user_modes: tuple = ()):
```

and in the body:

```python
        # What the user searched for. Only used to word the mode-mismatch
        # clause — the policy decision lives in run_core.
        self._user_modes = tuple(str(m).strip().lower()
                                 for m in user_modes if str(m).strip())
```

`score_job` and `best_match` each gain `mode_mismatch: str | None = None`, threaded exactly like `scraped_under` (best_match passes it to every score_job call; score_job passes it to `_constraints`).

`_constraints` — new parameter `mode_mismatch: str | None = None`, and a new additive check after the geography block, before the exec check:

```python
        if mode_mismatch:
            # run_core sends this only for the keep-and-flag rung of the
            # policy ladder: the posting states a mode the user did not
            # search for and its location could not be placed. Confirmed
            # foreign ones were dropped before scoring; local ones were
            # kept clean.
            searched = "/".join(self._user_modes) or "remote"
            penalty += cfg.get("mode_mismatch", 15)
            fired.append(f"says {mode_mismatch}, "
                         f"you searched {searched}-only")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scorer_mode.py tests/test_scorer.py tests/test_scorer_evidence.py tests/test_scorer_geo.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scoring/scorer.py tests/test_scorer_mode.py
git commit -m "feat: the scorer words the mode-mismatch flag run_core decides"
```

---

### Task 5: run_core — the policy ladder

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_run_core_execute.py`

- [ ] **Step 1: Write the failing tests**

Append to `job_hunt/tests/test_run_core_execute.py` (`_PROFILE` is `location "Toronto, ON"`, `country "ca"`, `work_modes ["remote"]`; `_job(...)` builds a job with location "Toronto, ON" and description "We need Power BI and SQL."):

```python
def test_a_foreign_onsite_job_is_dropped_not_stored(conn, user, resume):
    job = _job("https://x/20")
    job["location"] = "Bengaluru, Karnataka, India"
    job["description"] += " Onsite work required."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.dropped == 1
    assert result.kept == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM role").fetchone()["n"] == 0


def test_a_local_hybrid_job_is_kept_without_penalty(conn, user, resume):
    """'Yerevan hybrid — bring it': a mode mismatch in the user's own
    country is workable in person."""
    job = _job("https://x/21")
    job["location"] = "Toronto, Ontario, Canada"
    job["description"] += " Hybrid work, 2 days a week in the office."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.dropped == 0
    assert result.kept == 1
    evidence = result.scored_jobs[0]
    assert evidence["work_mode"] == "hybrid"
    assert "says hybrid" not in evidence["reason"]


def test_an_unplaceable_mode_mismatch_is_flagged_not_dropped(conn, user, resume):
    job = _job("https://x/22")
    job["location"] = "Jakarta Metropolitan Area"
    job["description"] += " Hybrid work, 2 days a week in the office."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.kept == 1
    evidence = result.scored_jobs[0]
    assert "says hybrid, you searched remote-only" in evidence["reason"]
    assert "_mode_mismatch" not in evidence


def test_a_remote_tagged_location_vetoes_a_stray_prose_phrase(conn, user, resume):
    """The location field says Remote (actor-tagged) while the prose says
    hybrid — conflicting evidence claims nothing: kept, unflagged, no
    stored mode. 36% of real stored locations are literally 'Remote', and
    they are exactly where the phrase list is blindest."""
    job = _job("https://x/25")
    job["location"] = "Remote"
    job["description"] += " Hybrid work, 2 days a week in the office."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    assert result.kept == 1
    evidence = result.scored_jobs[0]
    assert "says hybrid" not in evidence["reason"]
    assert evidence.get("work_mode") is None


def test_a_job_with_no_mode_word_is_untouched(conn, user, resume):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/23")]))
    assert result.dropped == 0
    assert result.kept == 1
    assert result.scored_jobs[0].get("work_mode") is None


def test_the_dropped_count_reaches_progress(conn, user, resume):
    seen = []
    job = _job("https://x/24")
    job["location"] = "Bengaluru, Karnataka, India"
    job["description"] += " Onsite work required."
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append,
            scrapers=_scrapers(indeed_jobs=[job]))
    assert seen[-1]["dropped"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_core_execute.py -v`
Expected: the five new tests FAIL (`RunResult` has no `dropped`; jobs stored that should drop); the fourteen existing ones still pass.

- [ ] **Step 3: Implement**

In `job_hunt/src/run_core.py`:

1. `RunResult` gains `dropped: int = 0`.
2. `execute`'s lazy imports gain `work_mode` and `location_country` (extend the existing `from .scoring...` imports) plus `import yaml` alongside them.
3. Initialize `dropped_total = 0` next to `scraped_total`, and extend `report()`'s payload with `"dropped": dropped_total`.
4. Between the enrich hook and `report("scoring")`, insert the ladder:

```python
    # Work-mode policy. The one user-approved exception to flag-never-
    # hide: a posting that states a mode the user did not search for,
    # located in a country that is not theirs, is dropped — bounded by
    # requiring BOTH the explicit phrase AND a confidently-parsed
    # country. Local ones are workable in person and kept clean;
    # unplaceable ones are flagged, because a silent drop cannot be
    # justified without knowing where the job is.
    with open(VOCABULARY_PATH, encoding="utf-8") as handle:
        vocab = yaml.safe_load(handle)
    mode_cfg = vocab.get("work_mode") or {}
    loc_cfg = vocab.get("eligibility") or {}
    user_modes = tuple(str(m).strip().lower()
                       for m in (profile.get("work_modes") or [])
                       if str(m).strip())
    user_country = (profile.get("country") or "").strip().lower()

    kept_jobs = []
    for job in new_jobs:
        mode = work_mode(f"{job.get('title') or ''}\n"
                         f"{job.get('description') or ''}", mode_cfg)
        if mode:
            job["work_mode"] = mode
        if mode and user_modes and mode not in user_modes:
            raw_location = (job.get("location") or "").strip().lower()
            if raw_location == "remote":
                # The location field says remote (actor-tagged) while the
                # prose says otherwise — conflicting evidence, so claim
                # nothing: no drop, no flag, no stored mode.
                job.pop("work_mode", None)
                kept_jobs.append(job)
                continue
            place = location_country(job.get("location") or "", loc_cfg)
            if place and user_country and place != user_country:
                dropped_total += 1
                continue
            if not (place and user_country):
                job["_mode_mismatch"] = mode
        kept_jobs.append(job)
    new_jobs = kept_jobs
```

5. In the scoring loop, pop the new transient key next to the existing one and pass it through:

```python
        scraped_under = job.pop("_scraped_under", None)
        mode_mismatch = job.pop("_mode_mismatch", None)
        scored_jobs.append(
            {**job, **scorer.best_match(job["title"],
                                        job.get("description", ""),
                                        resumes,
                                        scraped_under=scraped_under,
                                        mode_mismatch=mode_mismatch)})
```

6. `Scorer(...)` construction gains `user_modes=user_modes`.
7. `RunResult(...)` at the end gains `dropped=dropped_total`.

Note `dropped_total` is assigned inside `execute` before `report` is ever called with it — keep the `report` closure reading it as a plain closed-over name only if it is initialized BEFORE `report` is defined; otherwise use the same pattern `scraped_total` uses.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_core_execute.py -v`
Expected: all 20 PASS.

- [ ] **Step 5: Mutation-check the drop boundary**

1. In the ladder, change `place != user_country` to `True` (drop whenever a foreign OR local place parses).
2. Run `python -m pytest tests/test_run_core_execute.py::test_a_local_hybrid_job_is_kept_without_penalty -v` — expected FAIL.
3. Restore; re-run Step 4's command — all PASS; `git diff` shows only intended edits.

- [ ] **Step 6: Commit**

```bash
git add src/run_core.py tests/test_run_core_execute.py
git commit -m "feat: runs drop foreign on-site jobs and keep the local ones"
```

---

### Task 6: run_core — the local lane (and the two landmines)

**Files:**
- Modify: `job_hunt/src/run_core.py`, `job_hunt/src/searching_page.py`, `job_hunt/main.py`
- Test: `job_hunt/tests/test_run_core_steps.py`, `job_hunt/tests/test_run_core_execute.py`, `job_hunt/tests/test_searching_page.py`, `job_hunt/tests/test_pipeline_announce.py`

- [ ] **Step 1: Write the failing tests**

Append to `job_hunt/tests/test_run_core_steps.py` (read the file first and match its import style):

```python
def test_a_location_doubles_the_plan_with_a_local_lane():
    steps = plan_steps(["BI Developer"], local=True)
    assert len(steps) == 4
    assert [s["lane"] for s in steps] == ["worldwide", "worldwide",
                                          "local", "local"]


def test_without_a_location_the_plan_is_worldwide_only():
    steps = plan_steps(["BI Developer"])
    assert len(steps) == 2
    assert all(s["lane"] == "worldwide" for s in steps)
```

In `job_hunt/tests/test_run_core_execute.py`, UPDATE the existing `test_the_first_event_already_lists_every_step`: `_PROFILE` carries a location, so the plan now has a local lane — the assertion becomes `assert len(seen[0]["steps"]) == 4      # one role, two sources, two lanes`. Then append:

```python
def test_the_local_lane_searches_the_actual_place_with_all_modes(conn, user, resume):
    calls = []

    def spy(category, title, actor_id, *args, **kwargs):
        calls.append({"location": kwargs.get("location"),
                      "work_modes": tuple(kwargs.get("work_modes") or ())})
        return []

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers={"Indeed": spy, "LinkedIn": spy})

    local = [c for c in calls
             if c["work_modes"] == ("remote", "hybrid", "onsite")]
    assert len(local) == 2          # one per source
    assert all(c["location"] == "Toronto, ON" for c in local)


def test_no_location_means_no_local_lane(conn, user, resume):
    profile = {**_PROFILE, "location": ""}
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], profile,
            on_progress=seen.append, scrapers=_scrapers())
    assert len(seen[0]["steps"]) == 2
```

Append to `job_hunt/tests/test_searching_page.py`:

```python
def test_the_step_row_can_label_the_local_lane():
    """The page appends ' · local' from the step's lane field — the
    source name itself stays clean for the scraper lookup."""
    html = render(7)
    assert "s.lane === 'local'" in html
```

Append to `job_hunt/tests/test_pipeline_announce.py` (read the file first; it tests `_announce`/`_announce_step` with printed_steps):

```python
def test_the_same_source_and_role_in_both_lanes_both_print(capsys):
    """The dedup key must include the lane, or the local step is silently
    swallowed as a duplicate of the worldwide one."""
    printed = set()
    step_w = {"source": "Indeed", "role": "BI Developer",
              "lane": "worldwide", "state": "done", "found": 3}
    step_l = {"source": "Indeed", "role": "BI Developer",
              "lane": "local", "state": "done", "found": 1}
    _announce_step(step_w, printed)
    _announce_step(step_l, printed)
    out = capsys.readouterr().out
    assert out.count("Indeed") == 2
```

Adapt the announce test's helper name/signature to what `main.py` actually defines (read it first) — the contract is: two steps differing only by lane both print.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_core_steps.py tests/test_run_core_execute.py tests/test_searching_page.py tests/test_pipeline_announce.py -v`
Expected: new tests FAIL (`plan_steps` has no `local` kwarg / no `lane` key; step counts wrong); the updated 2→4 test FAILS until implementation.

- [ ] **Step 3: Implement**

In `job_hunt/src/run_core.py`:

`plan_steps` (keyword defaults preserve every existing caller):

```python
def plan_steps(titles: list[str], sources=SOURCES,
               local: bool = False) -> list[dict]:
    """The whole scrape, listed before any of it runs.

    Grouped by role, worldwide lane before local, which is the order they
    actually run in. The local lane searches the profile's actual place
    with every work mode — it exists so target-country on-site/hybrid
    jobs arrive at all instead of by accident.
    """
    lanes = ("worldwide",) + (("local",) if local else ())
    return [{"source": name, "role": title, "lane": lane,
             "state": "pending", "found": 0}
            for title in titles
            for lane in lanes
            for name, _, _ in sources]
```

In `execute`: build `steps = plan_steps(titles, local=bool((profile.get("location") or "").strip()))`, and in the scrape loop derive per-lane arguments:

```python
        if step["lane"] == "local":
            lane_location = (profile.get("location") or "").strip()
            lane_modes = ("remote", "hybrid", "onsite")
        else:
            lane_location = location
            lane_modes = work_modes
```

and pass `location=lane_location, work_modes=lane_modes` in the scraper call (country unchanged).

In `job_hunt/src/searching_page.py`, in `draw()`'s template row, change the name span to:

```
      <span class="name">${{esc(s.source)}}${{s.lane === 'local' ? ' · local' : ''}} / ${{esc(s.role)}}</span>
```

(Keep the doubled-brace `.format` escaping exactly as the surrounding lines do.)

In `job_hunt/main.py`: find the printed-steps dedup (a `printed_steps: set` keyed by `(source, role)` from Ship 3) and extend the key to `(step["source"], step["role"], step.get("lane", "worldwide"))`. Also make the printed line itself include the lane when local (e.g. `Indeed · local / BI Developer...`), matching the existing print format.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_core_steps.py tests/test_run_core_execute.py tests/test_searching_page.py tests/test_pipeline_announce.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/run_core.py src/searching_page.py main.py tests/test_run_core_steps.py tests/test_run_core_execute.py tests/test_searching_page.py tests/test_pipeline_announce.py
git commit -m "feat: every role also searches the user's own place, all modes"
```

---

### Task 7: the sources gate

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_run_core_execute.py`

- [ ] **Step 1: Write the failing tests**

Append to `job_hunt/tests/test_run_core_execute.py`:

```python
def test_a_disabled_source_is_never_planned_or_called(conn, user, resume):
    config = {**_CONFIG,
              "search": {**_CONFIG["search"], "sources": {"indeed": False}}}
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)
        return []

    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, config, [resume], _PROFILE,
            on_progress=seen.append,
            scrapers={"Indeed": spy, "LinkedIn": spy})

    sources = {s["source"] for s in seen[0]["steps"]}
    assert sources == {"LinkedIn"}


def test_a_missing_sources_key_enables_everything(conn, user, resume):
    seen = []
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            on_progress=seen.append, scrapers=_scrapers())
    assert {s["source"] for s in seen[0]["steps"]} == {"Indeed", "LinkedIn"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_core_execute.py -v -k source`
Expected: the disabled-source test FAILS (Indeed steps still planned); the missing-key test already passes (pins current behavior).

- [ ] **Step 3: Implement**

In `execute`, before building steps:

```python
    # A source can be switched off in config.yaml (search.sources).
    # Missing key means enabled, so existing configs keep working.
    gates = (config.get("search", {}) or {}).get("sources") or {}
    sources = tuple(entry for entry in SOURCES
                    if gates.get(entry[0].lower(), True))
```

Use `sources` for `plan_steps(titles, sources=sources, local=...)` and for the actor-key lookup inside the loop (replace the `SOURCES` reference there).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_core_execute.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/run_core.py tests/test_run_core_execute.py
git commit -m "feat: config can switch a scrape source off"
```

---

### Task 8: volume — enforce the cap client-side

**Files:**
- Modify: `job_hunt/src/scrapers/indeed.py`, `job_hunt/src/scrapers/linkedin.py`
- Test: `job_hunt/tests/test_scrapers.py`

- [ ] **Step 1: Write the failing tests**

Append to `job_hunt/tests/test_scrapers.py`:

```python
@pytest.mark.parametrize("module", [indeed, linkedin])
def test_an_actor_overshoot_is_truncated_to_the_cap(module, monkeypatch):
    """The Indeed actor returns ~100 when asked for 50. The cap is
    enforced at the client boundary regardless of actor behavior."""
    items = [{**_MINIMAL, "jobUrl": f"https://example.com/j{i}"}
             for i in range(100)]
    _patch(monkeypatch, module, items)
    jobs = module.scrape("Data Analyst", "Data Analyst", "actor~id",
                         jobs_per_category=50)
    assert len(jobs) == 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scrapers.py -v -k truncated`
Expected: both parametrizations FAIL with 100 != 50.

- [ ] **Step 3: Implement**

In each scraper's `scrape`, immediately after the `jobs` list is fully built and BEFORE Indeed's `_scraped_under` tag block / LinkedIn's `return`:

```python
    # Actors overshoot (Indeed returns ~100 for maxResults=50). The cap
    # is a promise to the user about volume and cost, so it is enforced
    # here, not trusted to the actor.
    jobs = jobs[:jobs_per_category]
```

(Indeed: the tag loop then runs on the truncated list, which is correct — only jobs that survive the cap are tagged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scrapers.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scrapers/indeed.py src/scrapers/linkedin.py tests/test_scrapers.py
git commit -m "fix: the volume cap is enforced where the actor ignores it"
```

---

### Task 9: Indeed — diagnose, then one branch

**Files:**
- Investigate first; then EITHER modify `job_hunt/src/scrapers/base.py` (+ `tests/test_scrapers.py`) OR modify `job_hunt/config.yaml` (+ `tests/test_vocabulary.py` untouched; the gate from Task 7 already has tests).

- [ ] **Step 1: Diagnose**

Write a throwaway script `diag_indeed.py` in the scratchpad (NOT the repo):

```python
import json, os, sys

import requests

token = os.environ.get("APIFY_TOKEN", "")
if not token:
    sys.exit("APIFY_TOKEN not set")
url = ("https://api.apify.com/v2/acts/valig~indeed-jobs-scraper/"
       "run-sync-get-dataset-items")
payload = {"query": "data analyst", "location": "remote", "country": "am",
           "maxResults": 3, "datePosted": "7"}
resp = requests.post(url, json=payload, params={"token": token, "timeout": 90},
                     timeout=120)
resp.raise_for_status()
items = resp.json()
print("items:", len(items))
for item in items[:3]:
    print("== keys ==")
    for key in sorted(item):
        value = item[key]
        text = json.dumps(value, ensure_ascii=False)[:120]
        print(f"  {key}: {text}")
    print("== long string fields ==")
    for key, value in item.items():
        if isinstance(value, str) and len(value) > 200:
            print(f"  {key} ({len(value)} chars): {value[:200]!r}")
```

Run it via PowerShell so the token (a Windows user env var) is inherited:

```
powershell -Command "$env:APIFY_TOKEN=[Environment]::GetEnvironmentVariable('APIFY_TOKEN','User'); python <scratchpad-path>\diag_indeed.py"
```

Decide from the output: does ANY field carry the posting body (a long
string, or an HTML body, under a key `_DESCRIPTION_KEYS` in
`src/scrapers/base.py` does not list)?

- [ ] **Step 2a (FOUND branch): map the field**

1. Add the key to `_DESCRIPTION_KEYS` in `job_hunt/src/scrapers/base.py` (order matters — put it after `description` but before `snippet`).
2. Append to `tests/test_scrapers.py` a variant of the existing alternate-keys test parametrized with the new key for the `indeed` module, asserting `job["description"]` carries the text.
3. Run `python -m pytest tests/test_scrapers.py -v` — all pass.
4. Commit: `git commit -m "fix: Indeed descriptions live under <key> — map it"`

- [ ] **Step 2b (ABSENT branch): ship with Indeed off**

1. In `job_hunt/config.yaml`, under `search:` add:

```yaml
  # Two full runs returned zero Indeed descriptions — every job an
  # unscoreable card. Off until the actor (or a replacement) proves it
  # can deliver text. Flip to true to re-enable.
  sources:
    indeed:   false
    linkedin: true
```

2. Run `python -m pytest -q` — the gate's behavior is already covered by Task 7's tests; the full suite must stay green (config.yaml is not loaded by unit tests).
3. Commit: `git commit -m "feat: Indeed ships disabled until it can deliver descriptions"`

- [ ] **Step 3: Report which branch ran and why** — include the diagnostic output's key list in the report (not in the repo).

---

### Task 10: the map shows the mode

**Files:**
- Modify: `job_hunt/src/map_page.py`
- Test: `job_hunt/tests/test_map_page.py`

- [ ] **Step 1: Write the failing test**

Append to `job_hunt/tests/test_map_page.py` (match the file's existing `_map()`/`_role()` fixture helpers — read them first):

```python
def test_the_role_meta_leads_with_the_work_mode():
    m = _map()
    m["roles"][0]["work_mode"] = "hybrid"
    m["roles"][0]["location"] = "Yerevan, Armenia"
    html = render([m])
    assert "HYBRID · YEREVAN, ARMENIA" in html


def test_no_mode_means_no_chip():
    html = render([_map()])
    assert "HYBRID" not in html and "ONSITE" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_map_page.py -v`
Expected: the first new test FAILS; the second passes (pins current output).

- [ ] **Step 3: Implement**

In `job_hunt/src/map_page.py`, `_role_meta`, prepend the mode to the bits list:

```python
def _role_meta(role: dict) -> str:
    bits = [role.get("work_mode") or "",
            role.get("location") or "",
            f"POSTED {_days_ago(role.get('date'))}"
            if _days_ago(role.get("date")) else "", role.get("salary") or ""]
    if not role.get("description_captured"):
        bits.append("NO DESCRIPTION CAPTURED")
    return " · ".join(b for b in bits if b).upper()
```

The drawer payload uses `_role_meta` already — no other change.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_map_page.py tests/test_map_routing.py -v`
Expected: all PASS (including the page's no-percentage guard).

- [ ] **Step 5: Commit**

```bash
git add src/map_page.py tests/test_map_page.py
git commit -m "feat: the map card names the work mode the posting stated"
```

---

### Task 11: full suite, live smoke

**Files:** none — verification only.

- [ ] **Step 1: Full suite**

Run: `python -m pytest -q`
Expected: everything passes (~605+, exact count from the run). Any failure in an untouched file is a regression — stop and fix.

- [ ] **Step 2: Live smoke of the ladder against the real vocabulary**

From `job_hunt/`:

```bash
python -c "
from pathlib import Path
import yaml
from src.scoring.matching import location_country, work_mode
vocab = yaml.safe_load(open('vocabulary.yaml', encoding='utf-8'))
mode_cfg, loc_cfg = vocab['work_mode'], vocab['eligibility']
for text, loc in [
    ('Onsite work required.', 'Bengaluru, Karnataka, India'),
    ('Hybrid work, 2 days a week in the office.', 'Yerevan, Armenia'),
    ('Hybrid work, 2 days a week in the office.', 'Remote'),
    ('Experience with hybrid cloud required.', 'Singapore, Singapore'),
    ('This is a fully remote role.', 'New York, NY'),
]:
    print(work_mode(text, mode_cfg), '|', location_country(loc, loc_cfg), '|', text[:45])
"
```

Expected lines: `onsite | in`, `hybrid | am`, `hybrid | None`, `None | sg` (hybrid cloud claims nothing), `remote | us`.

- [ ] **Step 3: `git status --short`** — clean.

---

## Self-review notes (done at planning time)

- **Spec coverage:** vocabulary → Task 1; pure rules incl. rightmost-wins, state codes, bare-word guards → Task 2; schema v4 + ingest + `_role_view`, NULL backfill → Task 3; scorer flag + wording with every searched mode → Task 4; policy ladder all four rungs + dropped count in RunResult and progress → Task 5; local lane incl. skip-without-location, per-lane scrape args, page label, `_announce` key → Task 6; sources gate with missing-key default → Task 7; cap enforcement both scrapers, tag-after-truncate order → Task 8; Indeed both branches → Task 9; map chip + NULL renders nothing → Task 10; smoke → Task 11.
- **Placeholder scan:** Task 9 is genuinely two-branched — that is the spec's own design, with complete steps per branch, not a TBD. Task 2 Step 3 shows a rejected comprehension beside the required loop, explicitly marked which to ship.
- **Type consistency:** `work_mode(body, cfg) -> str|None` and `location_country(location, cfg) -> str|None` identical in Tasks 2/5/11; `mode_mismatch: str|None = None` threaded `best_match -> score_job -> _constraints` (Tasks 4, 5); transient `_mode_mismatch` set in Task 5's ladder and popped in the same task's scoring loop; `lane` key values `"worldwide"|"local"` identical in Tasks 6 (steps, page, announce); gate keys are lowercased display names ("indeed", "linkedin") in Tasks 7, 9.
- **Existing-suite safety:** every signature keyword-defaulted; the two known breakages (`_announce` dedup, step-count 2→4) are named in the preamble and fixed inside Task 6 where they fire, not discovered mid-task.
