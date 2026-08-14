# Resume Profile — Ship 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the uploaded resume drive both what gets searched and what counts as a good fit, replacing the hardcoded keyword lists and the four hardcoded search titles.

**Architecture:** `keywords.yaml` splits — the half describing a person is deleted (it lives in resumes now), the half describing language and market technology survives as `vocabulary.yaml`. The scoring rules move into `src/scoring/matching.py` as pure, independently-tested functions; `Scorer` becomes a thin composer that scores one posting against one resume and a `best_match` that runs every active resume and keeps the winner. `main.py` reads active resumes from the store instead of a PDF path in `.env`, and the scrapers take the user's location and work modes instead of hardcoding `remote`/`us`/`Worldwide`.

**Tech Stack:** Python 3, SQLite (stdlib `sqlite3`), Flask 3, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-11-resume-profile-and-search-design.md`

**Predecessor:** `docs/superpowers/plans/2026-08-11-resume-profile-ship-1.md` (merged, PR #1)

**Working directory for every command below:** `job_hunt/`.

**Baseline before starting:** `python -m pytest tests/ -q` → `333 passed`.

---

## Read this before Task 1

**`main.py` is broken from Task 5 until Task 13.** Task 5 changes `Scorer.score_job`'s signature; `main.py` is not updated until Task 13. This is intended and mirrors how Ship 1 was built. Nothing in `tests/` imports `main.py`, so the suite stays green throughout — verify that claim yourself in Task 5 with `grep -rn "import main\|from main" tests/` (expect no matches) rather than taking it on faith.

**Three deliberate refinements to the spec, flagged rather than buried.** Each is a place where implementing the spec literally produces a worse result:

1. **The `all_tokens` title tier requires at least two significant tokens.** The spec says "every significant token of some target role appears in the title". Read literally, a target role of `BI Developer` reduces to the single significant token `developer` (`bi` is two characters, which the spec excludes), so `Frontend Developer` would score 25 of 40 on title. Requiring two tokens caps such a role at the `some_tokens` tier (15). Exact-phrase matching still gives `BI Developer` its full 40.

2. **`tailoring` is derived from the score, not the category.** The old value came from membership in the four hardcoded search categories, which no longer exist. It is written to the Excel tracker and nothing else. Deriving it from the score preserves the column without inventing a new concept.

3. **Schema version 3 renames the single existing user to `default`.** The spec removes `CANDIDATE_NAME` from `.env`, but that value is the key `ensure_user` looks the user row up by. Removing it without a migration would silently strand every company, role, and application already in the database behind a name nothing sets any more. One guarded `UPDATE`, one test.

**Where resume attribution reaches the map.** The spec asks for two things — the winning `resume_id` stored on the role, and the reason sentence naming the resume. Both are built (Tasks 8 and 6). Nothing else is needed to make the map say *"STRONG FIT with your BI Developer resume"*, because the map already renders the reason sentence beneath the band. So `queries.py` and `map_page.py` are deliberately untouched: the stored `resume_id` is the structured record, the sentence is what a person reads. Adding a second, separately-rendered attribution would put the same fact on screen twice.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `vocabulary.yaml` (create) | Language and market facts only — seniority wording, known tools, employment constraints, and the point values. Nothing personal. |
| `keywords.yaml` (delete, Task 5) | Superseded. |
| `src/scoring/matching.py` (create) | Pure matching rules: title tiers, seniority bands, skill hits, gaps, mismatch penalty. No config objects, no I/O. The part most likely to be argued with later, so it is tested on its own. |
| `src/scoring/scorer.py` (rewrite) | Composes `matching` against one resume, then `best_match` across all active resumes. Owns the point arithmetic and the band cut-offs. |
| `src/scoring/reason.py` (modify) | Names which resume matched. |
| `src/store/schema.py` (modify) | Version 3: rename the sole user to `default`. |
| `src/store/ingest.py` (modify) | Persist the winning `resume_id` on the role. |
| `src/scrapers/indeed.py`, `src/scrapers/linkedin.py` (modify) | Take `location`, `country`, `work_modes`; fall back to the legacy payload if an actor returns nothing. |
| `src/agents/resume_agent.py` (rewrite) | `parse_resume` deleted (the store holds the text now); `generate_role_variant` takes a stored resume. |
| `src/agents/tailoring_agent.py` (modify) | System prompt built from the resume instead of hardcoding one person. |
| `src/config.py` (delete, Task 13) | `apply_env_overrides` has nothing left to override. |
| `main.py` (modify) | Reads active resumes from the store; search titles are their target roles. |

Tests mirror the source: `tests/test_vocabulary.py`, `tests/test_matching.py`, `tests/test_scorer.py` (rewritten), `tests/test_scorer_evidence.py` (rewritten), `tests/test_reason.py` (extended), `tests/test_store_migration.py` (extended), `tests/test_store_ingest.py` (extended), `tests/test_scrapers.py` (extended), `tests/test_resume_agent.py` (rewritten), `tests/test_pipeline_titles.py` (new). `tests/test_config.py` is deleted in Task 13.

---

### Task 1: `vocabulary.yaml`

**Files:**
- Create: `vocabulary.yaml`
- Test: `tests/test_vocabulary.py`

`keywords.yaml` stays in place for now — Task 5 deletes it, once the scorer no longer reads it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vocabulary.py`:

```python
"""vocabulary.yaml holds language and market facts, never a person.

The whole point of the split is that nothing in here describes who is
searching. A test is the only thing that keeps a personal skill list from
creeping back in the next time someone wants to nudge a score.
"""
from pathlib import Path

import yaml

_PATH = Path(__file__).parent.parent / "vocabulary.yaml"


def _vocabulary() -> dict:
    with open(_PATH, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_it_loads():
    assert isinstance(_vocabulary(), dict)


def test_it_keeps_the_sections_the_scorer_needs():
    vocab = _vocabulary()
    assert {"stopwords", "seniority", "market_tools", "mismatch", "penalties",
            "title_scores", "seniority_scores",
            "skill_scores"} <= set(vocab)


def test_the_personal_sections_are_gone():
    """`skills` and `title_groups` described one person. They live in the
    resume now, and must not come back here."""
    vocab = _vocabulary()
    assert "skills" not in vocab
    assert "title_groups" not in vocab


def test_the_hardcoded_domain_penalties_are_gone():
    """legacy_tech and frontend_tech said React and COBOL are bad, which is
    only true for a data person. The mismatch ratio replaces them."""
    penalties = _vocabulary()["penalties"]
    assert "legacy_tech" not in penalties
    assert "frontend_tech" not in penalties


def test_the_point_values_cover_every_tier():
    vocab = _vocabulary()
    assert {"exact", "all_tokens", "some_tokens",
            "none"} == set(vocab["title_scores"])
    assert {"same", "one_apart", "far"} == set(vocab["seniority_scores"])
    assert {"core", "working", "cap"} == set(vocab["skill_scores"])


def test_the_mismatch_thresholds_are_configurable():
    mismatch = _vocabulary()["mismatch"]
    assert {"min_tools", "hard_ratio", "hard_value",
            "soft_ratio", "soft_value"} == set(mismatch)
    assert mismatch["hard_ratio"] < mismatch["soft_ratio"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_vocabulary.py -v`

Expected: FAIL — every test errors with `FileNotFoundError: ... vocabulary.yaml`.

- [ ] **Step 3: Write the implementation**

Create `vocabulary.yaml` (at `job_hunt/vocabulary.yaml`, beside the now-doomed `keywords.yaml`):

```yaml
# vocabulary.yaml — language and market facts, not personal preferences.
#
# What a person is good at lives in their resume. This file holds only what is
# true regardless of who is searching: how seniority is worded in job titles,
# which tools the market names, which employment constraints rule a posting
# out, and the point values the scorer spends.

# Words that carry no signal when comparing a target role to a job title.
# Seniority words are here on purpose: seniority is scored separately, so a
# target role of "Senior Data Engineer" should still match a "Data Engineer"
# posting on the title and let the seniority rule decide the rest.
stopwords:
  - the
  - and
  - for
  - with
  - our
  - you
  - your
  - job
  - role
  - new
  - senior
  - junior
  - staff
  - principal
  - lead
  - entry
  - intern
  - associate
  - head
  - chief

seniority:
  senior_keywords: ["senior", "sr.", "sr ", "staff", "principal", "lead",
                    "manager", "director", "head of", "vp ", "vice president"]
  junior_keywords: ["junior", "jr.", "jr ", "intern", "entry", "associate ",
                    "analyst i ", "engineer i "]
  exec_keywords:   ["vp ", "vice president", "director", "head of", "executive"]

# Technology commonly named in job posts. Two jobs: anything here that appears
# in a description but is not on the resume is reported as a gap, and the
# ratio of named-to-yours drives the mismatch penalty below.
#
# The second block is what the deleted `legacy_tech` and `frontend_tech`
# penalty lists used to name. They are market facts — these tools exist and
# get named in postings — so they belong here. Whether any of them counts
# against you is now decided by the ratio rule, not by a hardcoded verdict
# that React is bad.
market_tools:
  - snowflake
  - databricks
  - bigquery
  - redshift
  - looker
  - spark
  - kafka
  - dagster
  - prefect
  - fivetran
  - terraform
  - kubernetes
  - docker
  - scala
  - java
  - "aws"
  - "gcp"
  - azure
  - sigma
  - segment
  - snowpark
  - airbyte
  - react
  - angular
  - vue
  - ruby
  - rails
  - ios
  - android
  - php
  - salesforce
  - sharepoint
  - cobol
  - mainframe
  - coldfusion

# Fires when a posting names plenty of tooling and almost none of it is yours.
# Replaces the old hardcoded legacy_tech/frontend_tech lists, which only made
# sense for a data person — a ratio lands hard on a React posting for someone
# whose stack is dbt, and softly on the same posting for a React developer.
# The floor exists so a posting naming two tools cannot be judged on a sample
# that small.
mismatch:
  min_tools:  4
  hard_ratio: 0.25
  hard_value: 20
  soft_ratio: 0.5
  soft_value: 10

# Employment constraints. These rule a posting out whatever your skills are.
penalties:
  "w2 only":    15
  clearance:    30
  secret:       30
  cpt:          20
  opt:          20
  exec_penalty: 10

# Point values. Kept here rather than in code so the weights can be tuned
# without a commit to src/. These are seeds, not findings — validating them
# against real outcomes is what the `event` table is for.
title_scores:
  exact:       40
  all_tokens:  25
  some_tokens: 15
  none:        5

seniority_scores:
  same:      20
  one_apart: 12
  far:       4

skill_scores:
  core:    5
  working: 2
  cap:     20
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_vocabulary.py -v`

Expected: PASS, 6 tests.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `339 passed` (333 + 6). Nothing reads the new file yet.

- [ ] **Step 6: Commit**

```bash
git add vocabulary.yaml tests/test_vocabulary.py && git commit -m "feat: vocabulary.yaml, the half of keywords.yaml that is not a person"
```

---

### Task 2: Title matching

**Files:**
- Create: `src/scoring/matching.py`
- Test: `tests/test_matching.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_matching.py`:

```python
"""Tests for src/scoring/matching.py — the scoring rules, on their own.

These are the rules a future reader will argue with, so they are tested
against plain data rather than through the Scorer.
"""
from src.scoring.matching import has_term, significant, title_tier, tokens

_STOP = ["the", "and", "for", "senior", "junior", "lead", "staff"]


def _role(title, *aliases):
    return {"title": title, "aliases": list(aliases)}


# ── tokens / significant ──────────────────────────────────────────────────────

def test_tokens_lowercases_and_splits_on_punctuation():
    assert tokens("Senior Engineer, Analytics") == ["senior", "engineer",
                                                    "analytics"]


def test_tokens_keeps_symbols_that_are_part_of_a_name():
    assert tokens("C# and C++ developer") == ["c#", "and", "c++", "developer"]


def test_significant_drops_short_tokens_and_stopwords():
    assert significant("Senior BI Developer", _STOP) == ["developer"]


# ── has_term ──────────────────────────────────────────────────────────────────

def test_has_term_matches_on_word_boundaries():
    assert has_term("opt", "cpt or opt candidates")
    assert not has_term("opt", "we will optimize the query")


def test_has_term_handles_multi_word_terms():
    assert has_term("power bi", "you will build power bi dashboards")


# ── title_tier ────────────────────────────────────────────────────────────────

def test_an_exact_title_is_the_top_tier():
    assert title_tier("Senior Data Engineer",
                      [_role("Data Engineer")], _STOP) == "exact"


def test_an_alias_also_counts_as_exact():
    roles = [_role("BI Developer", "business intelligence developer")]
    assert title_tier("Business Intelligence Developer Lead",
                      roles, _STOP) == "exact"


def test_reordered_tokens_are_the_second_tier():
    """`Senior Engineer, Analytics` is the same job as `Analytics Engineer`."""
    assert title_tier("Senior Engineer, Analytics",
                      [_role("Analytics Engineer")], _STOP) == "all_tokens"


def test_a_seniority_prefix_on_the_target_role_does_not_block_a_match():
    """Seniority is scored separately, so it is a stopword here."""
    assert title_tier("Data Engineer",
                      [_role("Senior Data Engineer")], _STOP) == "all_tokens"


def test_one_shared_token_is_the_third_tier():
    assert title_tier("Data Scientist",
                      [_role("Data Engineer")], _STOP) == "some_tokens"


def test_a_single_token_target_cannot_reach_the_second_tier():
    """`BI Developer` reduces to one significant token, so `Frontend
    Developer` must not score as if the whole role matched."""
    assert title_tier("Frontend Developer",
                      [_role("BI Developer")], _STOP) == "some_tokens"


def test_nothing_in_common_is_the_floor():
    assert title_tier("Warehouse Associate",
                      [_role("Analytics Engineer")], _STOP) == "none"


def test_the_best_of_several_target_roles_wins():
    roles = [_role("Product Analyst"), _role("Data Engineer")]
    assert title_tier("Data Engineer II", roles, _STOP) == "exact"


def test_no_target_roles_is_the_floor_not_a_crash():
    assert title_tier("Data Engineer", [], _STOP) == "none"


def test_an_empty_title_is_the_floor_not_a_crash():
    assert title_tier("", [_role("Data Engineer")], _STOP) == "none"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_matching.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.scoring.matching'`.

- [ ] **Step 3: Write the implementation**

Create `src/scoring/matching.py`:

```python
"""Pure matching rules, shared by the scorer.

Every function takes plain data and returns plain data — no config objects, no
database, no LLM. The scorer composes them. They live apart from it because
these are the rules a reader will want to argue with, and an argument is
easier to settle against a unit test than against a 90-line method.
"""
import re

# Ordered, so the distance between two of them is an integer.
BANDS = ("junior", "mid", "senior", "exec")

_TOKEN_RE = re.compile(r"[a-z0-9+#]+")


def has_term(term: str, haystack: str) -> bool:
    """Word-boundary match.

    Descriptions are long enough that substring matching produces false
    positives on short tokens — 'opt' inside 'optimize', 'bi' inside
    'ambitious'. Boundaries keep multi-word terms ('power bi') working.
    """
    term = (term or "").strip()
    if not term:
        return False
    return bool(re.search(r"\b" + re.escape(term) + r"\b", haystack))


def tokens(text: str) -> list[str]:
    """Lowercased words. `+` and `#` survive so C++ and C# stay one token."""
    return _TOKEN_RE.findall((text or "").lower())


def significant(text: str, stopwords) -> list[str]:
    """Tokens worth comparing: over two characters, and not a stopword."""
    stop = set(stopwords or ())
    return [t for t in tokens(text) if len(t) > 2 and t not in stop]


def title_tier(job_title: str, target_roles: list[dict], stopwords) -> str:
    """How well a posting's title matches any of the resume's target roles.

    Returns 'exact', 'all_tokens', 'some_tokens' or 'none'. The caller turns
    that into points, so the rule and its weight stay separable.

    `all_tokens` needs at least two significant tokens to fire. Without that
    floor a target role of `BI Developer` — which reduces to the single token
    `developer`, since `bi` is too short to be significant — would let
    `Frontend Developer` score as though the whole role matched.
    """
    title = (job_title or "").lower()
    if not title:
        return "none"

    phrases: list[str] = []
    for role in target_roles or []:
        phrases.append(str(role.get("title") or ""))
        phrases.extend(str(alias) for alias in (role.get("aliases") or []))
    phrases = [p.strip().lower() for p in phrases if p and p.strip()]

    if any(has_term(phrase, title) for phrase in phrases):
        return "exact"

    present = set(tokens(title))
    best = "none"
    for phrase in phrases:
        wanted = significant(phrase, stopwords)
        if not wanted:
            continue
        if len(wanted) >= 2 and all(w in present for w in wanted):
            return "all_tokens"
        if any(w in present for w in wanted):
            best = "some_tokens"
    return best
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_matching.py -v`

Expected: PASS, 15 tests.

- [ ] **Step 5: Commit**

```bash
git add src/scoring/matching.py tests/test_matching.py && git commit -m "feat: match a posting title against the resume's target roles"
```

---

### Task 3: Seniority bands

**Files:**
- Modify: `src/scoring/matching.py`
- Test: `tests/test_matching.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_matching.py`:

```python
from src.scoring.matching import band_distance, seniority_band

_SENIORITY = {
    "senior_keywords": ["senior", "sr.", "staff", "principal", "lead",
                        "manager", "director", "head of", "vp ",
                        "vice president"],
    "junior_keywords": ["junior", "jr.", "intern", "entry", "associate "],
    "exec_keywords":   ["vp ", "vice president", "director", "head of",
                        "executive"],
}


def test_a_plain_title_reads_as_mid():
    assert seniority_band("Data Engineer", _SENIORITY) == "mid"


def test_senior_is_recognised():
    assert seniority_band("Senior Data Engineer", _SENIORITY) == "senior"


def test_junior_is_recognised():
    assert seniority_band("Junior Data Engineer", _SENIORITY) == "junior"


def test_exec_beats_senior_when_a_title_reads_as_both():
    """`Director` is in both lists. An exec title is an exec title."""
    assert seniority_band("Director of Data", _SENIORITY) == "exec"


def test_an_empty_title_reads_as_mid():
    assert seniority_band("", _SENIORITY) == "mid"


def test_the_same_band_is_no_distance():
    assert band_distance("senior", "senior") == 0


def test_neighbouring_bands_are_one_apart():
    assert band_distance("mid", "senior") == 1
    assert band_distance("senior", "mid") == 1


def test_the_ends_of_the_scale_are_far_apart():
    assert band_distance("junior", "exec") == 3


def test_an_unknown_band_is_treated_as_mid():
    """A resume saved before the seniority field existed must not crash."""
    assert band_distance("wizard", "mid") == 0
    assert band_distance(None, "senior") == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_matching.py -v`

Expected: FAIL with `ImportError: cannot import name 'band_distance' from 'src.scoring.matching'`.

- [ ] **Step 3: Write the implementation**

Append to `src/scoring/matching.py`:

```python
def seniority_band(job_title: str, seniority_cfg: dict) -> str:
    """The band a posting's title implies.

    Checked exec-first because the lists overlap — `director` and `head of`
    appear in both the senior and the exec list, and an exec title is an exec
    title.
    """
    title = (job_title or "").lower()
    if any(k in title for k in seniority_cfg.get("exec_keywords") or []):
        return "exec"
    if any(k in title for k in seniority_cfg.get("junior_keywords") or []):
        return "junior"
    if any(k in title for k in seniority_cfg.get("senior_keywords") or []):
        return "senior"
    return "mid"


def band_distance(one: str, other: str) -> int:
    """How many bands apart two seniority levels are.

    Anything unrecognised reads as `mid` rather than raising — a resume
    written before the field existed should score, not crash the run.
    """
    def _index(band) -> int:
        return BANDS.index(band) if band in BANDS else BANDS.index("mid")

    return abs(_index(one) - _index(other))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_matching.py -v`

Expected: PASS, 24 tests (15 from Task 2 plus 9 new).

- [ ] **Step 5: Commit**

```bash
git add src/scoring/matching.py tests/test_matching.py && git commit -m "feat: read a posting's seniority band and its distance from yours"
```

---

### Task 4: Skills, gaps, and the mismatch penalty

**Files:**
- Modify: `src/scoring/matching.py`
- Test: `tests/test_matching.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_matching.py`:

```python
from src.scoring.matching import (gaps, mismatch_penalty, resume_terms,
                                  skill_hits)

_SKILL_SCORES = {"core": 5, "working": 2, "cap": 20}
_MISMATCH = {"min_tools": 4, "hard_ratio": 0.25, "hard_value": 20,
             "soft_ratio": 0.5, "soft_value": 10}
_TOOLS = ["snowflake", "databricks", "spark", "kafka", "airflow", "react",
          "angular", "terraform"]


def _skill(name, tier="core", *aliases):
    return {"name": name, "tier": tier, "aliases": list(aliases)}


# ── resume_terms ──────────────────────────────────────────────────────────────

def test_resume_terms_collects_names_and_aliases_lowercased():
    skills = [_skill("Power BI", "core", "PowerBI", "DAX")]
    assert resume_terms(skills) == {"power bi", "powerbi", "dax"}


def test_resume_terms_of_nothing_is_empty():
    assert resume_terms([]) == set()


# ── skill_hits ────────────────────────────────────────────────────────────────

def test_a_named_skill_is_matched_and_scored():
    matched, points = skill_hits("we run airflow daily",
                                 [_skill("Airflow")], _SKILL_SCORES)
    assert matched == ["Airflow"]
    assert points == 5


def test_an_alias_matches_but_the_display_name_is_reported():
    """The reason sentence should read like the resume, not like the JD."""
    matched, _ = skill_hits("heavy dax work ahead",
                            [_skill("Power BI", "core", "dax")], _SKILL_SCORES)
    assert matched == ["Power BI"]


def test_a_working_skill_is_worth_less_than_a_core_one():
    _, core = skill_hits("airflow", [_skill("Airflow", "core")], _SKILL_SCORES)
    _, working = skill_hits("airflow", [_skill("Airflow", "working")],
                            _SKILL_SCORES)
    assert core > working


def test_unnamed_skills_score_nothing():
    matched, points = skill_hits("we use spreadsheets",
                                 [_skill("Airflow")], _SKILL_SCORES)
    assert matched == []
    assert points == 0


def test_the_skill_total_is_capped():
    many = [_skill(f"Tool{i}") for i in range(10)]
    body = " ".join(f"tool{i}" for i in range(10))
    _, points = skill_hits(body, many, _SKILL_SCORES)
    assert points == _SKILL_SCORES["cap"]


def test_core_skills_are_reported_before_working_ones():
    skills = [_skill("Tableau", "working"), _skill("Power BI", "core")]
    matched, _ = skill_hits("tableau and power bi", skills, _SKILL_SCORES)
    assert matched == ["Power BI", "Tableau"]


# ── gaps ──────────────────────────────────────────────────────────────────────

def test_a_tool_in_the_post_that_is_not_yours_is_a_gap():
    assert "snowflake" in gaps("we run snowflake", _TOOLS, {"airflow"})


def test_a_tool_you_have_is_not_a_gap():
    assert gaps("we run airflow", _TOOLS, {"airflow"}) == []


def test_gaps_come_from_the_description_only():
    """The title is not evidence of a tool being used."""
    assert gaps("", _TOOLS, set()) == []


# ── mismatch_penalty ──────────────────────────────────────────────────────────

def test_too_few_tools_named_is_never_a_mismatch():
    """Three tools is too small a sample to conclude anything."""
    body = "we use snowflake, spark and kafka"
    assert mismatch_penalty(body, _TOOLS, set(), _MISMATCH) == 0


def test_a_dense_post_with_none_of_your_tools_lands_hard():
    body = "react, angular, terraform and kafka experience required"
    assert mismatch_penalty(body, _TOOLS, {"airflow"},
                            _MISMATCH) == _MISMATCH["hard_value"]


def test_a_dense_post_with_some_of_your_tools_lands_softly():
    """Four named, one of them yours — a quarter, under the soft threshold."""
    body = "react, angular, terraform and airflow experience required"
    assert mismatch_penalty(body, _TOOLS, {"airflow"},
                            _MISMATCH) == _MISMATCH["soft_value"]


def test_a_post_that_is_mostly_your_tools_is_not_penalised():
    body = "snowflake, spark, kafka and airflow"
    mine = {"snowflake", "spark", "kafka"}
    assert mismatch_penalty(body, _TOOLS, mine, _MISMATCH) == 0


def test_the_same_post_lands_softly_for_someone_whose_stack_it_is():
    """The point of the ratio: a React post is only a mismatch for a
    non-React person."""
    body = "react, angular, terraform and kafka experience required"
    data_person = mismatch_penalty(body, _TOOLS, {"airflow"}, _MISMATCH)
    react_person = mismatch_penalty(body, _TOOLS,
                                    {"react", "angular", "terraform"},
                                    _MISMATCH)
    assert data_person > react_person == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_matching.py -v`

Expected: FAIL with `ImportError: cannot import name 'gaps' from 'src.scoring.matching'`.

- [ ] **Step 3: Write the implementation**

Append to `src/scoring/matching.py`:

```python
def resume_terms(skills: list[dict]) -> set[str]:
    """Every string that counts as "this person has that" — names and aliases.

    Lowercased, because everything it is compared against is lowercased.
    """
    terms: set[str] = set()
    for skill in skills or []:
        name = str(skill.get("name") or "").strip().lower()
        if name:
            terms.add(name)
        for alias in skill.get("aliases") or []:
            alias = str(alias).strip().lower()
            if alias:
                terms.add(alias)
    return terms


def skill_hits(body: str, skills: list[dict],
               scores: dict) -> tuple[list[str], int]:
    """The resume's skills that this posting names, and what they earn.

    Returns display names rather than whichever alias happened to match, so
    the reason sentence reads like the resume. Core skills are considered
    first, so the cap is spent on the strongest signals and the sentence names
    them in that order.
    """
    core_points = scores.get("core", 5)
    working_points = scores.get("working", 2)
    cap = scores.get("cap", 20)

    ordered = sorted(skills or [],
                     key=lambda s: 0 if s.get("tier") == "core" else 1)

    matched: list[str] = []
    total = 0
    for skill in ordered:
        name = str(skill.get("name") or "").strip()
        if not name:
            continue
        candidates = [name.lower()]
        candidates += [str(a).strip().lower() for a in skill.get("aliases") or []]
        if any(has_term(c, body) for c in candidates if c):
            matched.append(name)
            total = min(total + (core_points if skill.get("tier") == "core"
                                 else working_points), cap)
    return matched, total


def gaps(description: str, market_tools, mine: set[str]) -> list[str]:
    """Tools the posting names that the resume does not carry.

    Read from the description only — a title is not evidence that a tool is
    actually used on the job.
    """
    body = (description or "").lower()
    return [tool for tool in market_tools or []
            if has_term(tool, body) and tool.lower() not in mine]


def mismatch_penalty(description: str, market_tools, mine: set[str],
                     cfg: dict) -> int:
    """Points off when a posting is dense with tooling that is not yours.

    Replaces the old hardcoded legacy_tech/frontend_tech lists. Because the
    rule is a ratio against the reader's own skills, a React-heavy posting
    still lands hard for someone running dbt and lands not at all for someone
    whose resume is React — which is the whole point.
    """
    body = (description or "").lower()
    named = [tool for tool in market_tools or [] if has_term(tool, body)]
    if len(named) < cfg.get("min_tools", 4):
        # Too small a sample to conclude anything from.
        return 0

    ratio = sum(1 for tool in named if tool.lower() in mine) / len(named)
    if ratio < cfg.get("hard_ratio", 0.25):
        return cfg.get("hard_value", 20)
    if ratio < cfg.get("soft_ratio", 0.5):
        return cfg.get("soft_value", 10)
    return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_matching.py -v`

Expected: PASS, 40 tests (24 from Tasks 2-3 plus 16 new).

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `379 passed` (339 + 40).

- [ ] **Step 6: Commit**

```bash
git add src/scoring/matching.py tests/test_matching.py && git commit -m "feat: score skills, gaps and tool mismatch against a resume"
```

---

### Task 5: Rewrite the scorer against a resume

**Files:**
- Modify: `src/scoring/scorer.py` (full rewrite)
- Delete: `keywords.yaml`
- Test: `tests/test_scorer.py` (full rewrite)
- Test: `tests/test_scorer_evidence.py` (full rewrite)

The public interface changes. `score_job(title, category, salary_str, url, description)` becomes `score_job(title, description, resume)`: `category` came from the four hardcoded search titles that no longer exist, and `salary_str` and `url` were never read.

- [ ] **Step 1: Confirm nothing but `main.py` calls the old interface**

Run: `grep -rn "score_job\|Scorer(" --include=*.py . | grep -v "^./tests/"`

Expected: matches in `src/scoring/scorer.py` and `main.py` only. `main.py` is updated in Task 13 and stays broken until then; nothing in `tests/` imports it.

Run: `grep -rn "import main\|from main" tests/`

Expected: no matches. If there are any, stop and report — the plan's assumption that the suite stays green through Tasks 5-12 is wrong.

- [ ] **Step 2: Write the failing tests**

Replace the entire contents of `tests/test_scorer.py` with:

```python
"""Tests for src/scoring/scorer.py — one posting against one resume."""
from pathlib import Path

import pytest

from src.scoring.scorer import Scorer

_CONFIG = {"scoring": {"bands": {"strong": 8, "partial": 5}}}
_VOCAB = Path(__file__).parent.parent / "vocabulary.yaml"

_RESUME = {
    "id": 1,
    "label": "analytics engineer",
    "seniority": "senior",
    "target_roles": [{"title": "Analytics Engineer", "aliases": []},
                     {"title": "Data Engineer", "aliases": []}],
    "skills": [{"name": "dbt", "tier": "core", "aliases": []},
               {"name": "Airflow", "tier": "core", "aliases": []},
               {"name": "Power BI", "tier": "core", "aliases": ["dax"]},
               {"name": "Python", "tier": "working", "aliases": []},
               {"name": "SQL", "tier": "working", "aliases": []}],
}

_STRONG_JD = ("We run dbt with Airflow orchestration. You will build Power BI "
              "dashboards using Python and SQL.")


@pytest.fixture
def scorer():
    return Scorer(_CONFIG, _VOCAB)


def _score(scorer, title, description="", resume=_RESUME):
    return scorer.score_job(title, description, resume)


def test_a_matching_title_and_stack_scores_high(scorer):
    assert _score(scorer, "Senior Analytics Engineer",
                  _STRONG_JD)["match_score"] >= 8


def test_an_unrelated_title_scores_low(scorer):
    assert _score(scorer, "Warehouse Associate")["match_score"] <= 4


def test_naming_the_stack_beats_the_same_title_with_no_description(scorer):
    with_jd = _score(scorer, "Data Engineer", _STRONG_JD)["match_score"]
    without = _score(scorer, "Data Engineer")["match_score"]
    assert with_jd > without


def test_seniority_distance_costs_points(scorer):
    """The resume says senior, so a junior posting is further away."""
    same = _score(scorer, "Senior Data Engineer", _STRONG_JD)["match_score"]
    apart = _score(scorer, "Junior Data Engineer", _STRONG_JD)["match_score"]
    assert same > apart


def test_the_same_posting_scores_differently_for_a_different_resume(scorer):
    """The whole point of Ship 2: the resume is the yardstick."""
    react = {**_RESUME, "id": 2, "label": "frontend",
             "target_roles": [{"title": "Frontend Engineer", "aliases": []}],
             "skills": [{"name": "React", "tier": "core", "aliases": []}]}
    jd = "React, Angular, Terraform and Kafka experience required."
    for_data = _score(scorer, "Frontend Engineer", jd)["match_score"]
    for_react = _score(scorer, "Frontend Engineer", jd, react)["match_score"]
    assert for_react > for_data


def test_a_clearance_requirement_costs_points(scorer):
    flagged = _score(scorer, "Data Engineer",
                     _STRONG_JD + " Requires an active security clearance.")
    clean = _score(scorer, "Data Engineer", _STRONG_JD)
    assert flagged["match_score"] < clean["match_score"]


def test_a_visa_restriction_costs_points(scorer):
    flagged = _score(scorer, "Data Engineer",
                     _STRONG_JD + " We cannot sponsor CPT or OPT.")
    clean = _score(scorer, "Data Engineer", _STRONG_JD)
    assert flagged["match_score"] < clean["match_score"]


def test_common_words_do_not_fire_the_visa_penalty(scorer):
    """'optimize' must not read as 'opt'."""
    innocuous = _score(scorer, "Data Engineer",
                       _STRONG_JD + " You will optimize queries.")
    clean = _score(scorer, "Data Engineer", _STRONG_JD)
    assert innocuous["match_score"] == clean["match_score"]


def test_an_exec_posting_costs_a_non_exec_points(scorer):
    exec_role = _score(scorer, "VP of Data Engineering", _STRONG_JD)
    senior_role = _score(scorer, "Senior Data Engineer", _STRONG_JD)
    assert exec_role["match_score"] < senior_role["match_score"]


def test_an_exec_posting_does_not_penalise_an_exec(scorer):
    """The penalty is about the gap, not about the word."""
    exec_resume = {**_RESUME, "seniority": "exec"}
    penalised = _score(scorer, "VP of Data Engineering", _STRONG_JD)
    not_penalised = _score(scorer, "VP of Data Engineering", _STRONG_JD,
                           exec_resume)
    assert "executive role" in penalised["penalties"]
    assert "executive role" not in not_penalised["penalties"]


def test_the_score_stays_inside_one_to_ten(scorer):
    worst = _score(scorer, "Warehouse Associate",
                   "React Angular Terraform Kafka. Requires clearance.")
    best = _score(scorer, "Senior Analytics Engineer", _STRONG_JD)
    assert 1 <= worst["match_score"] <= 10
    assert 1 <= best["match_score"] <= 10


def test_a_description_is_optional(scorer):
    assert 1 <= _score(scorer, "Analytics Engineer")["match_score"] <= 10


def test_tailoring_is_reported(scorer):
    result = _score(scorer, "Analytics Engineer", _STRONG_JD)
    assert result["tailoring"] in ("Minor", "Moderate", "Significant", "N/A")
```

Replace the entire contents of `tests/test_scorer_evidence.py` with:

```python
"""The scorer's evidence — bands, matched skills, gaps, attribution.

The UI renders a band word and a sentence, never a number, so the scorer has
to hand back what it actually matched rather than just a total.
"""
from pathlib import Path

import pytest

from src.scoring.scorer import Scorer

_CONFIG = {"scoring": {"bands": {"strong": 8, "partial": 5}}}
_VOCAB = Path(__file__).parent.parent / "vocabulary.yaml"

_RESUME = {
    "id": 7,
    "label": "analytics engineer",
    "seniority": "senior",
    "target_roles": [{"title": "Analytics Engineer", "aliases": []}],
    "skills": [{"name": "dbt", "tier": "core", "aliases": []},
               {"name": "Airflow", "tier": "core", "aliases": []},
               {"name": "Power BI", "tier": "core", "aliases": ["dax"]}],
}

_STRONG_JD = ("We run dbt on Snowflake with Airflow orchestration. You will "
              "build Power BI dashboards.")


@pytest.fixture
def scorer():
    return Scorer(_CONFIG, _VOCAB)


# ── Bands ─────────────────────────────────────────────────────────────────────

def test_a_strong_posting_earns_strong_fit(scorer):
    result = scorer.score_job("Senior Analytics Engineer", _STRONG_JD, _RESUME)
    assert result["band"] == "STRONG FIT"


def test_a_poor_posting_earns_stretch(scorer):
    jd = "React, Angular, Terraform and Kafka components."
    result = scorer.score_job("Warehouse Associate", jd, _RESUME)
    assert result["band"] == "STRETCH"


def test_no_band_is_claimed_without_a_description(scorer):
    """Nothing was compared, so nothing may be claimed."""
    result = scorer.score_job("Analytics Engineer", "", _RESUME)
    assert result["band"] is None
    assert result["description_captured"] is False


def test_the_captured_flag_is_set_when_there_is_a_description(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert result["description_captured"] is True


# ── Matched evidence ──────────────────────────────────────────────────────────

def test_matched_skills_are_reported(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert {"dbt", "Airflow", "Power BI"} == set(result["matched"])


def test_nothing_is_reported_when_nothing_matched(scorer):
    result = scorer.score_job("Analytics Engineer", "We use spreadsheets.",
                              _RESUME)
    assert result["matched"] == []


def test_a_skill_matched_by_alias_is_reported_by_name(scorer):
    result = scorer.score_job("Analytics Engineer", "Heavy dax work.", _RESUME)
    assert result["matched"] == ["Power BI"]


def test_gaps_are_tools_in_the_post_you_do_not_have(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert "snowflake" in result["gaps"]


def test_gaps_exclude_what_you_already_matched(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert not (set(result["matched"]) & set(result["gaps"]))


def test_penalties_are_named_not_just_subtracted(scorer):
    jd = _STRONG_JD + " Applicants must hold an active security clearance."
    result = scorer.score_job("Analytics Engineer", jd, _RESUME)
    assert "clearance" in result["penalties"]


def test_a_tool_mismatch_is_named_as_a_penalty(scorer):
    jd = "React, Angular, Terraform and Kafka experience required."
    result = scorer.score_job("Analytics Engineer", jd, _RESUME)
    assert any("overlap" in p for p in result["penalties"])


def test_no_penalties_are_reported_when_none_fire(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert result["penalties"] == []


def test_the_postings_seniority_is_reported(scorer):
    senior = scorer.score_job("Senior Analytics Engineer", _STRONG_JD, _RESUME)
    junior = scorer.score_job("Junior Analytics Engineer", _STRONG_JD, _RESUME)
    assert senior["seniority"] == "senior"
    assert junior["seniority"] == "junior"


# ── Attribution ───────────────────────────────────────────────────────────────

def test_the_evidence_records_which_resume_produced_it(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert result["resume_id"] == 7
    assert result["resume_label"] == "analytics engineer"


def test_the_reason_names_the_resume(scorer):
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert "analytics engineer resume" in result["reason"]


# ── Rules carried forward ─────────────────────────────────────────────────────

def test_a_band_always_ships_with_its_sentence(scorer):
    result = scorer.score_job("Senior Analytics Engineer", _STRONG_JD, _RESUME)
    assert result["band"] and result["reason"].strip()


def test_a_reason_is_present_even_without_a_description(scorer):
    result = scorer.score_job("Analytics Engineer", "", _RESUME)
    assert result["band"] is None
    assert "without a description" in result["reason"]


def test_interview_chance_is_still_gone(scorer):
    """Fabricated precision — removed by spec rule 9, and staying removed."""
    result = scorer.score_job("Analytics Engineer", _STRONG_JD, _RESUME)
    assert "interview_chance" not in result
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_scorer.py tests/test_scorer_evidence.py -v`

Expected: FAIL — `Scorer.__init__` still expects `keywords.yaml`'s shape, so tests error with `KeyError: 'title_groups'`.

- [ ] **Step 4: Write the implementation**

Replace the entire contents of `src/scoring/scorer.py` with:

```python
"""Scores one posting against one resume.

Every rule lives in `matching`, every number in `vocabulary.yaml`. This
module's job is to compose them, hand back the evidence, and never let the
total reach a caller that renders — the band word and the reason sentence are
the only fit signals the UI may show.
"""
from pathlib import Path

import yaml

from . import matching
from .reason import compose_reason

# The most a posting can earn: 40 title + 20 seniority + 20 skills.
_MAX_RAW = 80


def _load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _tailoring(match_score: int) -> str:
    """How much rewriting a posting is likely to need.

    Used only by the Excel tracker. It used to be derived from membership in
    the four hardcoded search categories; with those gone it reads off the
    score, which is what the category was standing in for anyway.
    """
    if match_score >= 8:
        return "Minor"
    if match_score >= 6:
        return "Moderate"
    if match_score >= 4:
        return "Significant"
    return "N/A"


class Scorer:
    """Scores postings against resumes. One instance per run."""

    def __init__(self, config: dict, vocabulary_path: Path):
        self._vocab = _load(vocabulary_path)
        # Band cut-offs on the internal 1-10 score.
        self._bands = config.get("scoring", {}).get("bands",
                                                    {"strong": 8, "partial": 5})

    def score_job(self, title: str, description: str, resume: dict) -> dict:
        """Evidence for one posting judged against one resume."""
        vocab = self._vocab
        lowered = (title or "").lower()
        # Skills and constraints are stated in the body, not the title. The
        # title is folded in so a posting that arrived without a description
        # can still match something.
        body = f"{lowered}\n{(description or '').lower()}"

        tier = matching.title_tier(title, resume.get("target_roles") or [],
                                   vocab.get("stopwords") or [])
        title_score = vocab["title_scores"][tier]

        jd_band = matching.seniority_band(title, vocab.get("seniority") or {})
        my_band = resume.get("seniority") or "mid"
        distance = matching.band_distance(jd_band, my_band)
        seniority_cfg = vocab["seniority_scores"]
        seniority_score = (seniority_cfg["same"] if distance == 0
                           else seniority_cfg["one_apart"] if distance == 1
                           else seniority_cfg["far"])

        skills = resume.get("skills") or []
        matched, skill_score = matching.skill_hits(body, skills,
                                                   vocab["skill_scores"])

        mine = matching.resume_terms(skills)
        tools = vocab.get("market_tools") or []
        found_gaps = matching.gaps(description, tools, mine)
        mismatch = matching.mismatch_penalty(description, tools, mine,
                                             vocab.get("mismatch") or {})

        penalty, fired = self._constraints(body, jd_band, my_band)
        if mismatch:
            fired.append("little overlap with the tools this post names")

        raw = max(0, min(title_score + seniority_score + skill_score
                         - penalty - mismatch, _MAX_RAW))
        match_score = max(1, round(raw / (_MAX_RAW / 10)))

        # Without a description nothing was compared, so no band is claimed.
        described = bool((description or "").strip())
        if not described:
            band = None
        elif match_score >= self._bands.get("strong", 8):
            band = "STRONG FIT"
        elif match_score >= self._bands.get("partial", 5):
            band = "PARTIAL FIT"
        else:
            band = "STRETCH"

        evidence = {
            # Internal only — never rendered. Used for ranking.
            "match_score":          match_score,
            "band":                 band,
            "matched":              matched,
            "gaps":                 found_gaps,
            "penalties":            fired,
            "seniority":            jd_band,
            "description_captured": described,
            "tailoring":            _tailoring(match_score),
            "resume_id":            resume.get("id"),
            "resume_label":         resume.get("label") or "",
        }
        # A band is never handed out without its sentence.
        evidence["reason"] = compose_reason(evidence)
        return evidence

    def _constraints(self, body: str, jd_band: str,
                     my_band: str) -> tuple[int, list[str]]:
        """Employment constraints that rule a posting out whatever your stack."""
        cfg = self._vocab["penalties"]
        penalty = 0
        fired: list[str] = []

        if matching.has_term("w2 only", body):
            penalty += cfg.get("w2 only", 15)
            fired.append("w2 only")
        if matching.has_term("clearance", body) or matching.has_term("secret", body):
            penalty += cfg.get("clearance", 30)
            fired.append("clearance")
        if matching.has_term("cpt", body) or matching.has_term("opt", body):
            penalty += cfg.get("cpt", 20)
            fired.append("visa restriction")
        # An executive posting only counts against you if you are not one.
        if jd_band == "exec" and my_band != "exec":
            penalty += cfg.get("exec_penalty", 10)
            fired.append("executive role")

        return penalty, fired
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_scorer.py tests/test_scorer_evidence.py -v`

Expected: FAIL on `test_the_reason_names_the_resume` only — `reason.py` does not name the resume until Task 6. Every other test passes. If anything else fails, fix it before continuing.

- [ ] **Step 6: Delete the superseded keyword file**

```bash
git rm keywords.yaml
```

Run: `grep -rn "keywords.yaml\|KEYWORDS_PATH" --include=*.py --include=*.yaml .`

Expected: matches in `main.py` only (fixed in Task 13). If any other file still references it, fix that reference now.

- [ ] **Step 7: Commit**

```bash
git add src/scoring/scorer.py tests/test_scorer.py tests/test_scorer_evidence.py && git commit -m "feat: score a posting against a resume instead of a keyword list"
```

---

### Task 6: The reason sentence names the resume

**Files:**
- Modify: `src/scoring/reason.py`
- Test: `tests/test_reason.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reason.py`:

```python
def test_the_matched_clause_names_the_resume():
    """A person with three resumes needs to know which one this was."""
    sentence = compose_reason({
        "description_captured": True,
        "matched": ["dbt", "Airflow"],
        "seniority": "senior",
        "penalties": [],
        "resume_label": "bi developer",
    })
    assert "from your bi developer resume" in sentence


def test_an_unlabelled_resume_still_reads_as_a_sentence():
    sentence = compose_reason({
        "description_captured": True,
        "matched": ["dbt"],
        "seniority": "mid",
        "penalties": [],
    })
    assert "from your resume" in sentence


def test_the_resume_is_named_even_when_nothing_matched():
    sentence = compose_reason({
        "description_captured": True,
        "matched": [],
        "seniority": "senior",
        "penalties": [],
        "resume_label": "data engineer",
    })
    assert "your data engineer resume" in sentence
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_reason.py -v`

Expected: FAIL — `test_the_matched_clause_names_the_resume` asserts a phrase the current sentence does not contain.

- [ ] **Step 3: Write the implementation**

In `src/scoring/reason.py`, replace the block that builds the matched clause:

```python
    matched = list(evidence.get("matched") or [])[:_MAX_SKILLS]
    if matched:
        clauses.append(f"matches {_readable_list(matched)} from your resume")
```

with:

```python
    # Naming the resume is the answer to the question a person actually has
    # when several are active: which of mine got me this?
    label = str(evidence.get("resume_label") or "").strip()
    whose = f"your {label} resume" if label else "your resume"

    matched = list(evidence.get("matched") or [])[:_MAX_SKILLS]
    if matched:
        clauses.append(f"matches {_readable_list(matched)} from {whose}")
    elif label:
        clauses.append(f"nothing on {whose} was named in this posting")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_reason.py tests/test_scorer_evidence.py -v`

Expected: PASS. `test_the_reason_names_the_resume` from Task 5 now passes too.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `384 passed`. Arithmetic: 379 after Task 4, minus the 14 old `test_scorer.py` tests, minus the 15 old `test_scorer_evidence.py` tests, plus 13 new scorer tests, plus 18 new evidence tests, plus 3 new reason tests. If your number differs, count the tests in the rewritten files and reconcile before continuing — do not adjust a test to make the total match.

- [ ] **Step 6: Commit**

```bash
git add src/scoring/reason.py tests/test_reason.py && git commit -m "feat: the reason sentence says which resume matched"
```

---

### Task 7: Pick the best resume for each posting

**Files:**
- Modify: `src/scoring/scorer.py`
- Test: `tests/test_scorer.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scorer.py`:

```python
_BI_RESUME = {
    "id": 2,
    "label": "bi developer",
    "seniority": "senior",
    "target_roles": [{"title": "BI Developer", "aliases": ["bi engineer"]}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": ["dax"]},
               {"name": "SQL", "tier": "core", "aliases": []}],
}


def test_the_best_fitting_resume_wins(scorer):
    """A BI posting should be judged by the BI resume, not the AE one."""
    jd = "You will build Power BI dashboards and write SQL. Heavy dax work."
    best = scorer.best_match("Senior BI Developer", jd, [_RESUME, _BI_RESUME])
    assert best["resume_id"] == 2
    assert best["resume_label"] == "bi developer"


def test_the_other_resume_wins_for_the_other_posting(scorer):
    best = scorer.best_match("Senior Analytics Engineer", _STRONG_JD,
                             [_RESUME, _BI_RESUME])
    assert best["resume_id"] == 1


def test_a_tie_goes_to_the_earlier_resume(scorer):
    """Two identical resumes must not reshuffle the map between runs."""
    twin = {**_RESUME, "id": 99, "label": "copy"}
    best = scorer.best_match("Senior Analytics Engineer", _STRONG_JD,
                             [_RESUME, twin])
    assert best["resume_id"] == 1


def test_one_resume_behaves_like_scoring_against_it_directly(scorer):
    direct = scorer.score_job("Senior Analytics Engineer", _STRONG_JD, _RESUME)
    best = scorer.best_match("Senior Analytics Engineer", _STRONG_JD, [_RESUME])
    assert best == direct


def test_scoring_with_no_resumes_raises(scorer):
    """There is nothing to judge against, and silently scoring zero would
    fill the map with meaningless rows."""
    with pytest.raises(ValueError, match="active resume"):
        scorer.best_match("Data Engineer", _STRONG_JD, [])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_scorer.py -v`

Expected: FAIL with `AttributeError: 'Scorer' object has no attribute 'best_match'`.

- [ ] **Step 3: Write the implementation**

Append this method to the `Scorer` class in `src/scoring/scorer.py`, after `score_job` and before `_constraints`:

```python
    def best_match(self, title: str, description: str,
                   resumes: list[dict]) -> dict:
        """Score against every active resume and keep the strongest.

        Someone with a Data Engineer resume and a BI Developer resume should
        see each posting judged by whichever of the two actually fits it, and
        be told which one that was.

        Ties go to the earliest resume — `list_resumes` orders by creation, and
        `max` keeps the first of equals — so re-running a scrape cannot
        reshuffle the map for no reason.
        """
        if not resumes:
            raise ValueError("cannot score without at least one active resume")
        scored = [self.score_job(title, description, resume)
                  for resume in resumes]
        return max(scored, key=lambda evidence: evidence["match_score"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_scorer.py -v`

Expected: PASS, 18 tests (13 from Task 5 plus 5 new).

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `389 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/scoring/scorer.py tests/test_scorer.py && git commit -m "feat: judge each posting by whichever resume fits it best"
```

---

### Task 8: Persist the winning resume on the role

**Files:**
- Modify: `src/store/ingest.py`
- Test: `tests/test_store_ingest.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store_ingest.py`:

```python
def _resume_row(conn, user_id, label="ae", sha="sha-ae"):
    from src.store.profile import create_resume
    return create_resume(conn, user_id, label=label, orig_filename="cv.pdf",
                         sha256=sha, stored_path=f"resumes/{user_id}/{sha}.pdf",
                         extracted_text="dbt and Airflow")


def test_the_winning_resume_is_recorded_on_the_role(conn):
    user_id = ensure_user(conn, "G")
    resume_id = _resume_row(conn, user_id)
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id,
                [_job(url="https://x/attributed", resume_id=resume_id)])
    stored = conn.execute(
        "SELECT resume_id FROM role WHERE url = ?",
        ("https://x/attributed",)).fetchone()["resume_id"]
    assert stored == resume_id


def test_a_job_scored_without_a_resume_stores_null(conn):
    """Roles ingested before Ship 2 have no attribution and must not break."""
    user_id = ensure_user(conn, "G")
    run_id = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_id, [_job(url="https://x/plain")])
    stored = conn.execute(
        "SELECT resume_id FROM role WHERE url = ?",
        ("https://x/plain",)).fetchone()["resume_id"]
    assert stored is None


def test_re_running_a_scrape_updates_the_attribution(conn):
    """A second resume can win a posting the first one won last week."""
    user_id = ensure_user(conn, "G")
    first = _resume_row(conn, user_id, label="ae", sha="sha-ae")
    second = _resume_row(conn, user_id, label="bi", sha="sha-bi")
    run_one = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_one,
                [_job(url="https://x/moves", resume_id=first)])
    run_two = start_run(conn, user_id)
    upsert_jobs(conn, user_id, run_two,
                [_job(url="https://x/moves", resume_id=second)])
    stored = conn.execute(
        "SELECT resume_id FROM role WHERE url = ?",
        ("https://x/moves",)).fetchone()["resume_id"]
    assert stored == second
```

`tests/test_store_ingest.py` already provides the `conn` fixture, the `ensure_user`/`start_run`/`upsert_jobs` imports, and a `_job(url=..., **kw)` helper that builds a complete scored-job dict — the tests above use that helper, so nothing new needs importing.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_store_ingest.py -v`

Expected: FAIL — `test_the_winning_resume_is_recorded_on_the_role` gets `None` because `_upsert_role` never writes the column.

- [ ] **Step 3: Write the implementation**

In `src/store/ingest.py`, in `_upsert_role`, add `resume_id` to the values tuple and to both statements. The `values` tuple becomes:

```python
    values = (
        job["title"], job.get("location"), job.get("salary"),
        job.get("platform"), str(job.get("date") or ""),
        job.get("description") or "",
        1 if job.get("description_captured") else 0,
        job.get("match_score"), job.get("band"), job.get("reason"),
        json.dumps(list(job.get("matched") or [])),
        json.dumps(list(job.get("gaps") or [])),
        job.get("resume_id"),
    )
```

The `UPDATE` becomes:

```python
        conn.execute(
            """UPDATE role SET title=?, location=?, salary=?, platform=?,
                   posted_date=?, description=?, description_captured=?,
                   match_score=?, band=?, reason=?, matched=?, gaps=?,
                   resume_id=?, last_seen_run_id=?
               WHERE id=?""",
            (*values, run_id, existing["id"]))
```

The `INSERT` becomes:

```python
        conn.execute(
            """INSERT INTO role (user_id, company_id, url, url_normalised,
                   title, location, salary, platform, posted_date, description,
                   description_captured, match_score, band, reason, matched, gaps,
                   resume_id, first_seen_run_id, last_seen_run_id)
               VALUES (?,?,?,?, ?,?,?,?,?,?, ?,?,?,?,?,?, ?,?,?)""",
            (user_id, company_id, job["url"], url_n, *values, run_id, run_id))
```

Both counts are 19: four identifying columns, thirteen from `values`, and the run ids.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_store_ingest.py -v`

Expected: PASS, including the three new tests.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `392 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/store/ingest.py tests/test_store_ingest.py && git commit -m "feat: record which resume won each role"
```

---

### Task 9: Schema version 3 — keep the existing user's data reachable

**Files:**
- Modify: `src/store/schema.py`
- Test: `tests/test_store_migration.py` (append)

Ship 2 stops reading `CANDIDATE_NAME`, which is the name `ensure_user` looks the user row up by. Without this migration the first run after Ship 2 creates a *new* user called `default` and every company, role and application already stored disappears from the map.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store_migration.py`:

```python
def test_the_sole_existing_user_is_renamed_to_default(tmp_path):
    """Ship 2 stops reading CANDIDATE_NAME. Without this the user's whole
    map would be stranded behind a name nothing sets any more."""
    conn = _v1_database(tmp_path / "v1.db")
    conn.execute("UPDATE user SET name = 'Ghazal Izadi'")
    init_db(conn)
    assert conn.execute("SELECT name FROM user").fetchone()["name"] == "default"


def test_the_renamed_user_keeps_their_rows(tmp_path):
    conn = _v1_database(tmp_path / "v1.db")
    conn.execute("UPDATE user SET name = 'Ghazal Izadi'")
    init_db(conn)
    row = conn.execute(
        "SELECT u.name, COUNT(r.id) AS roles FROM user u"
        " LEFT JOIN role r ON r.user_id = u.id GROUP BY u.id").fetchone()
    assert row["name"] == "default"
    assert row["roles"] == 1


def test_several_users_are_left_alone(tmp_path):
    """The rename is a rescue for the single-user case, not a policy."""
    conn = _v1_database(tmp_path / "v1.db")
    conn.execute("UPDATE user SET name = 'Ghazal Izadi'")
    conn.execute("INSERT INTO user (name, created_at) VALUES ('Other', '2026-01-01')")
    init_db(conn)
    names = {r["name"] for r in conn.execute("SELECT name FROM user")}
    assert names == {"Ghazal Izadi", "Other"}


def test_the_rename_is_safe_to_replay(tmp_path):
    conn = _v1_database(tmp_path / "v1.db")
    conn.execute("UPDATE user SET name = 'Ghazal Izadi'")
    init_db(conn)
    init_db(conn)
    assert conn.execute("SELECT name FROM user").fetchone()["name"] == "default"
```

Also update the existing `SCHEMA_VERSION` assertions — `test_a_fresh_database_lands_on_version_two` asserts the literal `2`. Change that one assertion to `3` and rename the test to `test_a_fresh_database_lands_on_the_current_version`, asserting against `SCHEMA_VERSION` rather than a literal so it stops needing an edit per release:

```python
def test_a_fresh_database_lands_on_the_current_version(tmp_path):
    conn = connect(tmp_path / "fresh.db")
    init_db(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert {"location", "country", "work_modes",
            "setup_complete"} <= _columns(conn, "user")
    assert "resume" in _tables(conn)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_store_migration.py -v`

Expected: FAIL — the renamed user is still `Ghazal Izadi`.

- [ ] **Step 3: Write the implementation**

In `src/store/schema.py`:

Change the version:

```python
SCHEMA_VERSION = 3
```

Add the version-3 entry to `_MIGRATIONS`, after the `2:` block:

```python
    3: (
        # Ship 2 stops reading CANDIDATE_NAME from .env, but that value is the
        # key `ensure_user` looks the user row up by. Rename the sole existing
        # user rather than strand their whole map behind a name nothing sets
        # any more. Guarded to one user, so a genuinely multi-user database is
        # left alone, and idempotent, so replaying it is a no-op.
        (None, None,
         "UPDATE user SET name = 'default'"
         " WHERE (SELECT COUNT(*) FROM user) = 1"),
    ),
```

Extend the step runner to allow a data migration. Replace `_add_column_if_missing` with:

```python
def _run_step(conn: sqlite3.Connection, table: str | None,
              column: str | None, sql: str) -> None:
    """Run one migration statement.

    `column is None` marks a data migration — SQL that changes rows rather
    than shape. Those always run, so they have to be written to be safe to
    replay; the guard is in the statement, not here.

    Otherwise the statement adds a column and is skipped when the column is
    already present. `_DDL` always describes the current (post-migration)
    shape of every table, and `executescript` autocommits each statement as it
    runs, so a process killed partway through a fresh CREATE TABLE run can
    leave a table that already has every column while `user_version` still
    reads 0. Checking the column directly, instead of trusting the counter, is
    what makes replaying a migration after that kind of crash safe.
    """
    if column is None:
        conn.execute(sql)
        return
    if column not in _columns(conn, table):
        conn.execute(sql)
```

And in `init_db`, change the migration loop to call it:

```python
            for target in range(version + 1, SCHEMA_VERSION + 1):
                for table, column, sql in _MIGRATIONS.get(target, ()):
                    _run_step(conn, table, column, sql)
```

Update the `_MIGRATIONS` type annotation and the comment above it, which currently says entries are `(table, column, ddl)`:

```python
# Entries are (table, column, sql). A `column` of None marks a data migration
# that always runs; otherwise the statement adds a column and is skipped when
# that column already exists — see `_run_step`.
_MIGRATIONS: dict[int, tuple[tuple[str | None, str | None, str], ...]] = {
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_store_migration.py tests/test_store_schema.py -v`

Expected: PASS, including the four new tests.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `396 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/store/schema.py tests/test_store_migration.py && git commit -m "feat: schema version 3 renames the sole user to default"
```

---

### Task 10: Scrapers take the user's location and work modes

**Files:**
- Modify: `src/scrapers/indeed.py`
- Modify: `src/scrapers/linkedin.py`
- Test: `tests/test_scrapers.py` (append)

Both actors' input schemas are third-party and undocumented beyond the note at the top of `indeed.py`. The fallback in Step 3 is what the spec asks for: if an actor rejects the new input, log a warning and retry with the values that are known to work.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scrapers.py`:

```python
def _capture(monkeypatch, module, items):
    """Record the payload each call_actor invocation received."""
    seen = []

    def _fake(actor_id, payload, label, timeout=120):
        seen.append(payload)
        return items.pop(0) if items else []

    monkeypatch.setattr(module, "call_actor", _fake)
    return seen


# ── Indeed ────────────────────────────────────────────────────────────────────

def test_indeed_uses_the_literal_remote_location_for_a_remote_search(monkeypatch):
    seen = _capture(monkeypatch, indeed, [[_MINIMAL]])
    indeed.scrape("BI Developer", "BI Developer", "actor~id",
                  location="Toronto, ON", country="ca", work_modes=["remote"])
    assert seen[0]["location"] == "remote"
    assert seen[0]["country"] == "ca"


def test_indeed_searches_the_place_when_onsite_is_wanted(monkeypatch):
    seen = _capture(monkeypatch, indeed, [[_MINIMAL]])
    indeed.scrape("BI Developer", "BI Developer", "actor~id",
                  location="Toronto, ON", country="ca",
                  work_modes=["remote", "onsite"])
    assert seen[0]["location"] == "Toronto, ON"


def test_indeed_falls_back_when_the_actor_returns_nothing(monkeypatch):
    """An actor that rejects the new input yields an empty list, which is
    indistinguishable from no results — so retry with what used to work."""
    seen = _capture(monkeypatch, indeed, [[], [_MINIMAL]])
    jobs = indeed.scrape("BI Developer", "BI Developer", "actor~id",
                         location="Toronto, ON", country="ca",
                         work_modes=["onsite"])
    assert len(seen) == 2
    assert seen[1] == {**seen[0], "location": "remote", "country": "us"}
    assert len(jobs) == 1


def test_indeed_does_not_retry_when_it_already_used_the_legacy_values(monkeypatch):
    seen = _capture(monkeypatch, indeed, [[]])
    indeed.scrape("BI Developer", "BI Developer", "actor~id",
                  location="remote", country="us", work_modes=["remote"])
    assert len(seen) == 1


# ── LinkedIn ──────────────────────────────────────────────────────────────────

def test_linkedin_maps_work_modes_to_remote_codes(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                    location="Toronto, ON", country="ca",
                    work_modes=["hybrid", "onsite"])
    assert set(seen[0]["remote"]) == {"3", "1"}
    assert seen[0]["location"] == "Toronto, ON"


def test_linkedin_searches_worldwide_for_a_remote_only_search(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                    location="Toronto, ON", country="ca", work_modes=["remote"])
    assert seen[0]["location"] == "Worldwide"
    assert seen[0]["remote"] == ["2"]


def test_linkedin_ignores_an_unknown_work_mode(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                    location="Toronto, ON", country="ca",
                    work_modes=["telepathic"])
    assert seen[0]["remote"] == ["2"]


def test_linkedin_falls_back_when_the_actor_returns_nothing(monkeypatch):
    seen = _capture(monkeypatch, linkedin, [[], [_MINIMAL]])
    jobs = linkedin.scrape("BI Developer", "BI Developer", "actor~id",
                           location="Toronto, ON", country="ca",
                           work_modes=["onsite"])
    assert len(seen) == 2
    assert seen[1]["location"] == "Worldwide"
    assert seen[1]["remote"] == ["2"]
    assert len(jobs) == 1


def test_the_defaults_reproduce_the_old_behaviour(monkeypatch):
    """Callers that have not been updated yet must not change what they get."""
    indeed_seen = _capture(monkeypatch, indeed, [[_MINIMAL]])
    indeed.scrape("BI Developer", "BI Developer", "actor~id")
    assert indeed_seen[0]["location"] == "remote"
    assert indeed_seen[0]["country"] == "us"

    linkedin_seen = _capture(monkeypatch, linkedin, [[_MINIMAL]])
    linkedin.scrape("BI Developer", "BI Developer", "actor~id")
    assert linkedin_seen[0]["location"] == "Worldwide"
    assert linkedin_seen[0]["remote"] == ["2"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_scrapers.py -v`

Expected: FAIL with `TypeError: scrape() got an unexpected keyword argument 'location'`.

- [ ] **Step 3: Write the implementation**

Replace the body of `src/scrapers/indeed.py` below the imports with:

```python
import logging

logger = logging.getLogger(__name__)

# Actor now expects numeric strings, not human-readable text
_DATE_MAP = {1: "1", 3: "3", 7: "7", 14: "14"}

# What this scraper sent before it knew where the user lives. Kept as the
# fallback because it is the only combination confirmed to work against the
# live actor.
_LEGACY_LOCATION = "remote"
_LEGACY_COUNTRY = "us"


def _location_for(location: str, work_modes) -> str:
    """Indeed has no work-mode filter — 'remote' goes in the location box.

    A remote-only search uses the literal string the actor understands.
    Anything that includes an on-site mode has to search the actual place.
    """
    modes = {str(m).strip().lower() for m in work_modes or ()}
    if modes == {"remote"}:
        return _LEGACY_LOCATION
    return (location or "").strip() or _LEGACY_LOCATION


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120,
           location: str = _LEGACY_LOCATION,
           country: str = _LEGACY_COUNTRY,
           work_modes=("remote",)) -> list[dict]:
    payload = {
        "query":      title,
        "location":   _location_for(location, work_modes),
        "country":    (country or _LEGACY_COUNTRY).strip().lower(),
        "maxResults": jobs_per_category,
        "datePosted": _DATE_MAP.get(days_posted, "7"),
    }
    raw = call_actor(actor_id, payload, f"Indeed/{category}", run_timeout)

    # The actor's input schema is undocumented. A rejected payload comes back
    # as an empty list, indistinguishable from a genuinely empty search, so
    # the only safe response is to retry once with the values known to work.
    legacy = {**payload, "location": _LEGACY_LOCATION,
              "country": _LEGACY_COUNTRY}
    if not raw and legacy != payload:
        logger.warning(
            "Indeed returned nothing for %s with location=%r country=%r — "
            "retrying with the legacy remote/us payload",
            category, payload["location"], payload["country"])
        raw = call_actor(actor_id, legacy, f"Indeed/{category} (legacy)",
                         run_timeout)

    today = date.today().isoformat()
    jobs: list[dict] = []
    for item in raw:
        url = (item.get("jobUrl") or item.get("applyUrl")
               or item.get("url") or "")
        if not url:
            continue
        # Location may be a nested object or a plain string
        loc_raw = item.get("location") or {}
        if isinstance(loc_raw, dict):
            city    = loc_raw.get("city") or ""
            state   = loc_raw.get("state") or ""
            job_location = f"{city}, {state}".strip(", ") or "Remote, US"
        else:
            job_location = str(loc_raw) or "Remote, US"

        jobs.append({
            "cat":      category,
            "title":    item.get("title") or item.get("jobTitle") or "",
            "company":  ((item.get("employer") or {}).get("name")
                         or item.get("company") or ""),
            "location": job_location,
            "platform": "Indeed",
            "date":     normalize_date(
                item.get("datePublished") or item.get("postedAt") or today),
            "url":      url,
            "salary":   parse_salary(
                item.get("baseSalary") or item.get("salary") or {}),
            "description": extract_description(item),
        })
    return jobs
```

Keep the existing module docstring and the three import lines at the top of the file (`from datetime import date`, `from .base import call_actor, extract_description`, `from ..utils._dates import normalize_date, parse_salary`), adding `import logging` beside them.

Replace the body of `src/scrapers/linkedin.py` below the imports with:

```python
import logging

logger = logging.getLogger(__name__)

_DATE_MAP = {1: "r86400", 7: "r604800", 14: "r604800", 30: "r2592000"}

# LinkedIn's own filter codes for how a job is worked.
_REMOTE_CODES = {"onsite": "1", "remote": "2", "hybrid": "3"}

# What this scraper sent before it knew where the user lives.
_LEGACY_LOCATION = "Worldwide"
_LEGACY_REMOTE = ["2"]


def _filters_for(location: str, work_modes) -> tuple[str, list[str]]:
    """Location and remote codes for one search.

    A remote-only search is worldwide by definition. Any other combination has
    to name the place, because 'hybrid in Worldwide' is not a thing.
    """
    modes = [str(m).strip().lower() for m in work_modes or ()]
    modes = [m for m in modes if m in _REMOTE_CODES]
    if not modes:
        return _LEGACY_LOCATION, list(_LEGACY_REMOTE)
    codes = [_REMOTE_CODES[m] for m in modes]
    if modes == ["remote"]:
        return _LEGACY_LOCATION, codes
    return ((location or "").strip() or _LEGACY_LOCATION), codes


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120,
           location: str = _LEGACY_LOCATION,
           country: str = "us",
           work_modes=("remote",)) -> list[dict]:
    where, codes = _filters_for(location, work_modes)
    payload = {
        "title":      title,
        "location":   where,
        "remote":     codes,
        "datePosted": _DATE_MAP.get(days_posted, "r604800"),
        "limit":      jobs_per_category,
    }
    raw = call_actor(actor_id, payload, f"LinkedIn/{category}", run_timeout)

    # See the note in indeed.py: a rejected payload is indistinguishable from
    # an empty search, so retry once with the values known to work.
    legacy = {**payload, "location": _LEGACY_LOCATION,
              "remote": list(_LEGACY_REMOTE)}
    if not raw and legacy != payload:
        logger.warning(
            "LinkedIn returned nothing for %s with location=%r remote=%r — "
            "retrying with the legacy Worldwide/remote payload",
            category, payload["location"], payload["remote"])
        raw = call_actor(actor_id, legacy, f"LinkedIn/{category} (legacy)",
                         run_timeout)

    today = date.today().isoformat()
    jobs: list[dict] = []
    for item in raw:
        url = (item.get("jobUrl") or item.get("applyUrl")
               or item.get("url") or item.get("link") or "")
        if not url:
            continue
        job_title = (item.get("title") or item.get("jobTitle")
                     or item.get("positionName") or "")
        company_raw = item.get("company") or item.get("companyName") or ""
        company = (company_raw.get("name") if isinstance(company_raw, dict)
                   else str(company_raw))
        posted_raw = (item.get("datePublished") or item.get("postedAt")
                      or item.get("publishedAt") or item.get("listedAt") or today)
        jobs.append({
            "cat":      category,
            "title":    job_title,
            "company":  company,
            "location": item.get("location") or item.get("jobLocation") or "Remote",
            "platform": "LinkedIn",
            "date":     normalize_date(posted_raw),
            "url":      url,
            "salary":   parse_salary(
                item.get("salary") or item.get("baseSalary") or {}),
            "description": extract_description(item),
        })
    return jobs
```

`country` is accepted and ignored by the LinkedIn actor, which has no such field — it is in the signature so `main.py` can call both scrapers the same way.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_scrapers.py -v`

Expected: PASS, 21 tests (12 existing parametrised cases plus 9 new).

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `405 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/scrapers/indeed.py src/scrapers/linkedin.py tests/test_scrapers.py && git commit -m "feat: scrape where the user actually wants to work"
```

---

### Task 11: The resume agent reads from the store

**Files:**
- Modify: `src/agents/resume_agent.py`
- Test: `tests/test_resume_agent.py` (full rewrite)

`parse_resume` cached a PDF from `RESUME_PATH` into `output/resume_parsed.json`. The store holds the extracted text now, so the whole cache goes. `generate_role_variant` keeps its job but takes a stored resume instead of a config block — which also removes the hardcoded "the candidate's correct name is Ghazal Izadi" line.

- [ ] **Step 1: Write the failing test**

Replace the entire contents of `tests/test_resume_agent.py` with:

```python
"""Tests for src/agents/resume_agent.py — role-specific resume variants."""
from src.agents.resume_agent import generate_role_variant
from tests.conftest import MockLLMClient

_RESUME = {
    "id": 1,
    "label": "analytics engineer",
    "extracted_text": "Ada Lovelace — ada@example.com — dbt, Airflow, Python",
}


def test_a_variant_is_written_and_returned(tmp_path):
    path = generate_role_variant("Data Engineer", _RESUME, tmp_path,
                                 MockLLMClient("Tailored resume text"))
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "Tailored resume text"


def test_the_filename_is_safe_for_a_role_with_punctuation(tmp_path):
    path = generate_role_variant("Data Engineer / Analytics", _RESUME, tmp_path,
                                 MockLLMClient("text"))
    assert path.parent == tmp_path
    assert "/" not in path.name
    assert " " not in path.name


def test_an_existing_variant_is_reused_without_calling_the_llm(tmp_path):
    class Exploding(MockLLMClient):
        def complete(self, prompt, *, system="", max_tokens=1000):
            raise AssertionError("the cached variant should have been used")

    first = generate_role_variant("Data Engineer", _RESUME, tmp_path,
                                  MockLLMClient("first pass"))
    again = generate_role_variant("Data Engineer", _RESUME, tmp_path,
                                  Exploding("unused"))
    assert again == first
    assert again.read_text(encoding="utf-8") == "first pass"


def test_the_resume_text_reaches_the_prompt(tmp_path):
    class Capturing(MockLLMClient):
        def complete(self, prompt, *, system="", max_tokens=1000):
            self.seen = prompt
            return "text"

    llm = Capturing("text")
    generate_role_variant("Data Engineer", _RESUME, tmp_path, llm)
    assert "Ada Lovelace" in llm.seen
    assert "Data Engineer" in llm.seen


def test_no_candidate_is_hardcoded_in_the_prompt(tmp_path):
    """The prompt used to name one person. It works off the resume now."""
    class Capturing(MockLLMClient):
        def complete(self, prompt, *, system="", max_tokens=1000):
            self.seen = prompt
            return "text"

    llm = Capturing("text")
    generate_role_variant("Data Engineer", _RESUME, tmp_path, llm)
    assert "Ghazal" not in llm.seen


def test_parse_resume_is_gone():
    """The store holds the extracted text; the PDF cache was a second copy."""
    import src.agents.resume_agent as agent
    assert not hasattr(agent, "parse_resume")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_resume_agent.py -v`

Expected: FAIL with `TypeError: generate_role_variant() takes 5 positional arguments but 4 were given`, and `test_parse_resume_is_gone` failing because the function is still there.

- [ ] **Step 3: Write the implementation**

Replace the entire contents of `src/agents/resume_agent.py` with:

```python
"""Role-specific resume variants.

The canonical resume text comes from the store — it was extracted once at
upload time and does not need a second cache keyed on a PDF's md5. What is
cached here is the LLM's rewrite for one target role, which is expensive and
worth keeping.
"""
import logging
import re
from pathlib import Path

from ..llm.base import LLMClient

logger = logging.getLogger(__name__)


def _safe(role: str) -> str:
    """A filename fragment from a role title. Never used as a path itself."""
    cleaned = re.sub(r"[^\w\s-]", "_", role or "").strip()
    return re.sub(r"\s+", "_", cleaned) or "role"


def generate_role_variant(role: str, resume: dict, output_dir: Path,
                          llm: LLMClient) -> Path:
    """Rewrite the resume's highlights for one role. Cached per role."""
    out_file = Path(output_dir) / f"resume_{_safe(role)}.txt"
    if out_file.exists():
        logger.info("Role variant cached: %s", out_file)
        return out_file

    logger.info("Generating role variant: %s", role)
    prompt = (
        f"Rewrite the resume highlights below for the role '{role}'.\n"
        "Keep the candidate's own name and contact details exactly as they "
        "appear in the resume — do not invent or substitute any.\n"
        "Return plain text (no JSON, no markdown fences).\n\n"
        f"Original resume:\n{(resume.get('extracted_text') or '')[:3000]}"
    )
    out_file.write_text(llm.complete(prompt, max_tokens=1200), encoding="utf-8")
    return out_file
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_resume_agent.py -v`

Expected: PASS, 6 tests.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `407 passed` (405 minus the 4 deleted cache tests plus 6 new).

- [ ] **Step 6: Commit**

```bash
git add src/agents/resume_agent.py tests/test_resume_agent.py && git commit -m "feat: build role variants from the stored resume, not a PDF cache"
```

---

### Task 12: The tailoring prompt describes whoever is loaded

**Files:**
- Modify: `src/agents/tailoring_agent.py`
- Test: `tests/test_tailoring_prompt.py`

`_SYSTEM_PROMPT` currently hardcodes one person's name, years of experience, stack and target roles. Every cover letter written for any other user would be written for her.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tailoring_prompt.py`:

```python
"""The tailoring prompt must describe whoever's resume is loaded."""
from src.agents.tailoring_agent import build_system_prompt, tailor_job
from tests.conftest import MockLLMClient

_RESUME = {
    "label": "bi developer",
    "seniority": "senior",
    "target_roles": [{"title": "BI Developer", "aliases": []},
                     {"title": "Data Analyst", "aliases": []}],
    "skills": [{"name": "Power BI", "tier": "core", "aliases": []},
               {"name": "SQL", "tier": "core", "aliases": []},
               {"name": "Tableau", "tier": "working", "aliases": []}],
}


def test_the_prompt_names_the_resumes_skills():
    prompt = build_system_prompt(_RESUME)
    assert "Power BI" in prompt
    assert "SQL" in prompt


def test_the_prompt_names_the_resumes_target_roles():
    prompt = build_system_prompt(_RESUME)
    assert "BI Developer" in prompt
    assert "Data Analyst" in prompt


def test_the_prompt_states_the_seniority():
    assert "senior" in build_system_prompt(_RESUME)


def test_no_candidate_is_hardcoded():
    """It used to describe one person by name, whoever was using it."""
    assert "Ghazal" not in build_system_prompt(_RESUME)


def test_an_empty_resume_still_produces_a_usable_prompt():
    prompt = build_system_prompt({})
    assert "resume coach" in prompt.lower()


def test_tailor_job_uses_the_resume_derived_prompt():
    class Capturing(MockLLMClient):
        def complete(self, prompt, *, system="", max_tokens=1000):
            self.system = system
            return '{"cover_letter":"c","highlights":["a"]}'

    llm = Capturing("{}")
    tailor_job("a job description", "resume text", "BI Developer", "Acme",
               llm, resume=_RESUME)
    assert "Power BI" in llm.system
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_tailoring_prompt.py -v`

Expected: FAIL with `ImportError: cannot import name 'build_system_prompt'`.

- [ ] **Step 3: Write the implementation**

In `src/agents/tailoring_agent.py`, replace the `_SYSTEM_PROMPT` constant with a builder:

```python
def build_system_prompt(resume: dict) -> str:
    """Describe the candidate from their resume, not from a hardcoded person.

    This prompt used to name one user, her stack and her target roles, which
    quietly wrote every other user's cover letters as if they were her.
    """
    skills = [str(s.get("name") or "").strip()
              for s in resume.get("skills") or []]
    skills = [s for s in skills if s][:8]
    roles = [str(r.get("title") or "").strip()
             for r in resume.get("target_roles") or []]
    roles = [r for r in roles if r]
    seniority = str(resume.get("seniority") or "").strip()

    lines = ["You are a professional resume coach helping a candidate."]
    if seniority:
        lines.append(f"They describe themselves as {seniority} level.")
    if skills:
        lines.append(f"Their main skills are {', '.join(skills)}.")
    if roles:
        lines.append(f"Their target roles are {', '.join(roles)}.")
    lines.append("Their resume is provided. Always write in first person, "
                 "professional tone.")
    lines.append("Output strictly as JSON with no prose preamble or markdown "
                 "fences.")
    return "\n".join(lines)
```

Then change `tailor_job` to take the resume and use it:

```python
def tailor_job(job_description: str, resume_text: str,
               role_title: str, company_name: str,
               llm: LLMClient, resume: dict | None = None) -> dict | None:
    """Generate cover letter + highlights. Returns None on LLM failure."""
    prompt = (
        f"Job description:\n{job_description}\n\n"
        f"Resume text for this role:\n{resume_text[:2500]}\n\n"
        f"Target role: {role_title} at {company_name}\n\n"
        'Output JSON: {"cover_letter":"...","highlights":["...","...","..."]}'
    )
    try:
        text = llm.complete(prompt, system=build_system_prompt(resume or {}),
                            max_tokens=1500)
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            logger.error("Non-JSON response from %s for %s: %s",
                         llm.provider, company_name, text[:200])
            return None
        return json.loads(m.group())
    except json.JSONDecodeError:
        logger.error("JSON parse error from %s for %s", llm.provider, company_name)
        return None
    except Exception as e:
        logger.error("LLM tailoring failed for %s: %s", company_name, e)
        return None
```

`resume` is keyword-optional so any existing caller keeps working; `main.py` starts passing it in Task 13.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tailoring_prompt.py -v`

Expected: PASS, 6 tests.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `413 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/agents/tailoring_agent.py tests/test_tailoring_prompt.py && git commit -m "feat: write cover letters for whoever's resume is loaded"
```

---

### Task 13: The pipeline runs off the profile

**Files:**
- Modify: `main.py`
- Delete: `src/config.py`
- Delete: `tests/test_config.py`
- Modify: `config.yaml`
- Modify: `.env.example`
- Test: `tests/test_pipeline_titles.py`

This is the task that makes `main.py` work again.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_titles.py`:

```python
"""The searches a run performs come from the resumes, not from config.yaml."""
import pytest

from main import _search_titles


def _resume(*titles):
    return {"target_roles": [{"title": t, "aliases": []} for t in titles]}


def test_the_target_roles_become_the_searches():
    assert _search_titles([_resume("BI Developer", "Data Analyst")]) == [
        "BI Developer", "Data Analyst"]


def test_two_resumes_are_unioned():
    resumes = [_resume("BI Developer"), _resume("Data Engineer")]
    assert _search_titles(resumes) == ["BI Developer", "Data Engineer"]


def test_a_role_wanted_by_two_resumes_is_only_searched_once():
    resumes = [_resume("Data Engineer"), _resume("data engineer")]
    assert _search_titles(resumes) == ["Data Engineer"]


def test_blank_titles_are_dropped():
    assert _search_titles([_resume("  ", "Data Engineer")]) == ["Data Engineer"]


def test_no_resumes_means_no_searches():
    assert _search_titles([]) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pipeline_titles.py -v`

Expected: FAIL with `ImportError: cannot import name '_search_titles' from 'main'`.

- [ ] **Step 3: Rewrite the parts of `main.py` that changed**

Change the paths and add the user constant near the top, replacing the `KEYWORDS_PATH` line:

```python
_BASE = Path(__file__).resolve().parent
CONFIG_PATH     = _BASE / "config.yaml"
VOCABULARY_PATH = _BASE / "vocabulary.yaml"

# One user, no authentication — see the Identity section of the design spec.
# Schema version 3 renames any pre-existing user to this.
DEFAULT_USER = "default"
```

Replace `_load_config`:

```python
def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

Add these two helpers after `_check_deps`:

```python
def _open_store():
    """A connection with the schema present. The caller closes it."""
    from src.store.db import connect
    from src.store.ingest import ensure_user
    from src.store.schema import init_db

    conn = connect()
    init_db(conn)
    return conn, ensure_user(conn, DEFAULT_USER)


def _search_titles(resumes: list[dict]) -> list[str]:
    """Every target role across the active resumes, deduplicated.

    Two resumes that both target 'Data Engineer' must not scrape it twice.
    Order follows the resumes so a run is reproducible.
    """
    seen: set[str] = set()
    titles: list[str] = []
    for resume in resumes:
        for role in resume.get("target_roles") or []:
            title = str(role.get("title") or "").strip()
            key = title.lower()
            if title and key not in seen:
                seen.add(key)
                titles.append(title)
    return titles
```

In `run_pipeline`, replace the import block and the config reads at the top of the function:

```python
def run_pipeline(config: dict) -> None:
    from src.scrapers import indeed as indeed_scraper
    from src.scrapers import linkedin as li_scraper
    from src.scoring.scorer import Scorer
    from src.agents.resume_agent import generate_role_variant
    from src.agents.tailoring_agent import shortlist_decision
    from src.store.profile import get_profile, list_resumes
    from src.tracker import excel
    from src.llm.factory import get_client

    llm = get_client(config)
    print(f"  LLM: {llm.provider} / {llm.model}")

    output_dir = _BASE / config.get("output_dir", "output/")
    output_dir.mkdir(exist_ok=True)

    tracker_path = Path(config.get("tracker_path", "../job_tracker_ghazal.xlsx"))
    if not tracker_path.is_absolute():
        tracker_path = (_BASE / tracker_path).resolve()

    apify_cfg     = config.get("apify", {})
    search_cfg    = config.get("search", {})
    days_posted   = search_cfg.get("days_posted", 7)
    jobs_per_cat  = search_cfg.get("jobs_per_category", 50)
    run_timeout   = search_cfg.get("run_timeout", 120)
    shortlist_min = config.get("tailoring", {}).get("shortlist_score", 7)

    print("=" * 62)
    print("  Job Hunt Automation")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 62)

    # ── 1. Read the profile ────────────────────────────────────────────────
    print("\n[1/8] Reading your profile...")
    conn, user_id = _open_store()
    try:
        resumes = list_resumes(conn, user_id, active_only=True)
        profile = get_profile(conn, user_id)
    finally:
        conn.close()

    if not resumes:
        print("  ERROR: no active resume on file, so there is nothing to "
              "search for.")
        print("  Run:  python main.py --serve")
        print("  Then open http://127.0.0.1:5000/setup and upload one.")
        sys.exit(1)

    titles = _search_titles(resumes)
    if not titles:
        print("  ERROR: your resumes have no target roles between them.")
        print("  Open http://127.0.0.1:5000/profile and add at least one.")
        sys.exit(1)

    work_modes = profile["work_modes"] or ["remote"]
    print(f"  {len(resumes)} resume(s): "
          f"{', '.join(r['label'] for r in resumes)}")
    print(f"  Searching: {', '.join(titles)}")
    print(f"  Where: {profile['location'] or 'remote'} "
          f"({', '.join(work_modes)})")
```

Replace step 3, the scrape loop, so it iterates the resume-derived titles and passes the profile through:

```python
    print(f"\n[3/8] Scraping Indeed + LinkedIn (last {days_posted} days)...")
    all_scraped: list[dict] = []
    for title in titles:
        print(f"\n  Indeed / {title}...")
        jobs = indeed_scraper.scrape(
            title, title, apify_cfg.get("indeed_actor", "valig~indeed-jobs-scraper"),
            days_posted, jobs_per_cat, run_timeout,
            location=profile["location"], country=profile["country"] or "us",
            work_modes=work_modes)
        print(f"    -> {len(jobs)} fetched")
        all_scraped.extend(jobs)
        time.sleep(1)

        print(f"  LinkedIn / {title}...")
        jobs = li_scraper.scrape(
            title, title, apify_cfg.get("linkedin_actor", "valig~linkedin-jobs-scraper"),
            days_posted, jobs_per_cat, run_timeout,
            location=profile["location"], country=profile["country"] or "us",
            work_modes=work_modes)
        print(f"    -> {len(jobs)} fetched")
        all_scraped.extend(jobs)
        time.sleep(1)
```

Replace step 6's scorer setup and the scoring call:

```python
    print(f"\n[6/8] Scoring {len(new_jobs)} jobs against "
          f"{len(resumes)} resume(s)...")
    scorer = Scorer(config, VOCABULARY_PATH)
    cat_order = {title: i for i, title in enumerate(titles)}
    by_resume = {r["id"]: r for r in resumes}
    rows: list[dict] = []
    scored_jobs: list[dict] = []   # jobs + evidence, for the opportunity map

    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    for job in new_jobs:
        intel  = job["_intel"]
        filt_r = job["_filter"]
        is_filtered = filt_r["verdict"] == "REJECT"
        s = scorer.best_match(job["title"], job.get("description", ""), resumes)
        scored_jobs.append({**job, **s})
```

In the same loop, the row dict's `"Recommended Resume"` column has a value now — replace that one line:

```python
            "Recommended Resume": s["resume_label"],
```

Replace step 7's resume-text lookup so it uses the winning resume:

```python
    for row in shortlist:
        winner = by_resume.get(row["_resume_id"]) or resumes[0]
        variant_file = output_dir / f"resume_{row['Search Category'].replace(' ', '_')}.txt"
        if variant_file.exists():
            resume_text = variant_file.read_text(encoding="utf-8")
        else:
            resume_text = winner.get("extracted_text", "")
```

For that to work the row needs to carry the winning id — add one line to the row dict, next to `"_score"`:

```python
            "_resume_id":         s["resume_id"],
```

Replace the role-variant generation block:

```python
    apply_now_jobs = [r for r in rows if r.get("Apply_Now") == "yes"]
    if apply_now_jobs:
        print(f"\n  Generating resume variants for {len(apply_now_jobs)} apply-now jobs...")
        for role in {r["Search Category"] for r in apply_now_jobs}:
            try:
                generate_role_variant(role, resumes[0], output_dir, llm)
            except Exception as e:
                logger.warning("Role variant failed for %s: %s", role, e)
```

Replace the summary's `by_platform`/`by_cat` sort key, which referenced the old fixed order — it already uses `cat_order`, which is now built from `titles`, so no change is needed there. Confirm by reading it.

Replace `_persist_and_launch`'s user resolution:

```python
def _persist_and_launch(scored_jobs: list[dict], scraped: int,
                        shortlist_min: int, config: dict) -> None:
    """Write the run to the store. Rendering happens separately via _serve()."""
    from src.pipeline_store import persist_run

    conn = None
    try:
        conn, user_id = _open_store()
        persist_run(conn, user_id, scored_jobs, scraped)
        print(f"  Stored {len(scored_jobs)} roles.")
    except Exception as e:
        logger.warning("Persisting the run failed: %s", e)
    finally:
        if conn is not None:
            conn.close()
```

Replace `_serve`:

```python
def _serve(config: dict, port: int) -> None:
    """Run the local app. Binds to localhost only."""
    import webbrowser

    from src.app import create_app

    shortlist_min = config.get("tailoring", {}).get("shortlist_score", 7)
    app = create_app(user_name=DEFAULT_USER, shortlist_min=shortlist_min)
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  Opportunity map: {url}")
    print(f"  Your resumes:    http://127.0.0.1:{port}/profile")
    print("  Ctrl-C to stop.")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=port, debug=False)
```

Replace the resume-text lookup in `run_tailor`, and its `tailor_job` call, with a single block that opens the store once:

```python
    from src.store.profile import list_resumes

    conn, user_id = _open_store()
    try:
        active = list_resumes(conn, user_id, active_only=True)
    finally:
        conn.close()
    if not active:
        print("ERROR: no active resume on file. Upload one at /setup first.")
        sys.exit(1)
    resume = active[0]

    # A cached role variant is a better starting point than the raw resume,
    # because it was already rewritten for this kind of role.
    category  = row_data.get("Search Category", "")
    safe_role = category.replace(" ", "_")
    variant_file = output_dir / f"resume_{safe_role}.txt" if safe_role else None
    if variant_file and variant_file.exists():
        resume_text = variant_file.read_text(encoding="utf-8")
    else:
        resume_text = resume.get("extracted_text", "")

    result = tailor_job(
        jd_text, resume_text,
        row_data.get("Job Title", ""),
        row_data.get("Company", ""),
        llm,
        resume=resume,
    )
```

This replaces the existing block that read `output/resume_parsed.json`, which no longer exists.

Finally, delete the now-unreachable `_launch_map` function and the `run_tailor` default of `"Analytics Engineer"` for `Search Category` (replaced above with `""`).

- [ ] **Step 4: Strip the config and env files**

In `config.yaml`, delete the `resume: {}` line with its comment block, and delete `search.categories` entirely, leaving:

```yaml
search:
  days_posted: 7
  jobs_per_category: 50
  run_timeout: 120
```

Add a `scoring.bands` block so the cut-offs are configurable in the same place as the rest of scoring, replacing the now-unused `scoring.weights`:

```yaml
scoring:
  bands:
    strong: 8
    partial: 5
```

In `.env.example`, delete the `CANDIDATE_NAME`, `CANDIDATE_EMAIL`, `CANDIDATE_LINKEDIN` and `RESUME_PATH` lines, leaving only the API keys. Add one comment line where they were:

```
# Personal details are no longer set here — upload a resume at /setup instead.
```

- [ ] **Step 5: Delete the config module and its tests**

```bash
git rm src/config.py tests/test_config.py
```

Run: `grep -rn "apply_env_overrides\|src.config\|from .config" --include=*.py .`

Expected: no matches. If any remain, fix them.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline_titles.py -v`

Expected: PASS, 5 tests.

Run: `python -m pytest tests/ -q`

Expected: `412 passed` (413 minus the 6 deleted config tests plus 5 new).

- [ ] **Step 7: Check the pipeline imports cleanly**

Run: `python -c "import main; main._load_config()"`

Expected: no output, exit 0. This catches a syntax error or a stale import in a file no test imports.

- [ ] **Step 8: Commit**

```bash
git add main.py config.yaml .env.example tests/test_pipeline_titles.py && git commit -m "feat: the pipeline searches and scores from the stored profile"
```

---

### Task 14: Guard the boundaries, then run it for real

**Files:**
- Test: `tests/test_setup_routes.py` (append)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write the guard tests**

Append to `tests/test_setup_routes.py`:

```python
def test_the_scorer_never_reads_a_keyword_file(client):
    """keywords.yaml is gone. Nothing may quietly recreate it."""
    from pathlib import Path
    assert not (Path(__file__).parent.parent / "keywords.yaml").exists()


def test_no_personal_detail_survives_in_the_committed_config():
    """config.yaml is public. The four hardcoded search titles described one
    person and are now the resume's job."""
    from pathlib import Path

    import yaml

    with open(Path(__file__).parent.parent / "config.yaml",
              encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    assert "resume" not in config
    assert "categories" not in config.get("search", {})


def test_the_scoring_modules_name_no_individual():
    """Ship 2's whole point: this tool works for whoever loads a resume."""
    from pathlib import Path

    src = Path(__file__).parent.parent / "src"
    offenders = [path.name for path in src.rglob("*.py")
                 if "ghazal" in path.read_text(encoding="utf-8").lower()]
    assert offenders == []
```

- [ ] **Step 2: Run them**

Run: `python -m pytest tests/test_setup_routes.py -v -k "keyword or personal or individual"`

Expected: PASS, 3 tests. If `test_the_scoring_modules_name_no_individual` fails, it names the file — fix that file rather than the test.

- [ ] **Step 3: Run the whole suite**

Run: `python -m pytest tests/ -q`

Expected: `415 passed`.

- [ ] **Step 4: Update the project instructions**

In `CLAUDE.md`, replace the "Build order" item 2 line and add a line under "Finalized UI" recording where scoring input now comes from:

Under **Build order**, change item 2 to:

```
2. Multi-user shell — resume upload, role confirmation, location + work
   mode, per-user storage. SHIPPED (Ship 1 + Ship 2).
```

Under **Scoring**, add:

```
Scoring input comes from the user's active resumes in the store, not from a
keyword file. `vocabulary.yaml` holds only language and market facts —
seniority wording, known tools, employment constraints, point values. Nothing
in it may describe a particular person.
```

- [ ] **Step 5: Smoke-test the real thing**

This is the step the test suite cannot cover: the first time the new scorer sees real postings and the scrapers send the new payloads to the live actors.

```bash
python main.py --serve
```

Confirm `http://127.0.0.1:5000/profile` lists your resume and shows your location and work modes. Stop the server.

Then, with `APIFY_TOKEN` and your LLM key set in `job_hunt/.env`:

```bash
python main.py
```

Check, in order:
1. Step 1 prints your resume labels, the searches derived from their target roles, and your location and work modes — not the four old hardcoded titles.
2. Step 3 fetches a non-zero number of jobs from **both** Indeed and LinkedIn. If either prints `-> 0 fetched`, look for the `retrying with the legacy ... payload` warning in the log. If the retry also returned zero, the actor is rejecting something else — stop and report it rather than shipping a scraper that silently returns nothing.
3. Step 6 prints the resume count it is scoring against.
4. The map at `http://127.0.0.1:5000/` shows bands and reason sentences, and at least one reason names one of your resumes by label.
5. No bare number or percentage appears anywhere on the map.

- [ ] **Step 6: Commit**

```bash
git add tests/test_setup_routes.py CLAUDE.md && git commit -m "test: guard the profile-driven boundaries; document the split"
```

---

## What Ship 2 deliberately does not do

Leave these alone — they are Ship 3, or explicitly out of scope in the spec:

- `/` still renders the map unconditionally. Redirecting to `/setup` when setup is incomplete is Ship 3.
- No background scrape run, no `POST /api/runs`, no progress screen, no stale-run cleanup at boot. All Ship 3.
- Roles scored before this release keep their old scores and their NULL `resume_id`. Rescoring them is out of scope; they refresh on the next run that sees them.
- The scoring weights in `vocabulary.yaml` are seeds, not findings. Validating them against real outcomes is what the `event` table is for, and it needs rows first.
- No embeddings, no imported skill taxonomy. Aliases from the parse LLM cover the synonym problem.
- `src/agents/company_agent.py` and `src/filters/company_filter.py` are untouched — company enrichment is still disabled in `config.yaml`.
