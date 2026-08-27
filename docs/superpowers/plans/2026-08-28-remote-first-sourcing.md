# Remote-First Sourcing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-shape the pipeline around a user in a country the big job boards do not serve, so the map shows the roles they can actually be hired into and says plainly what it set aside.

**Architecture:** Three moves. Cut the sources that carry nothing eligible (Indeed out, LinkedIn's plain worldwide lane out). Fix the eligibility rules that were wrong — two live false-positive faults in `eligible_phrases`, plus four findings deferred from Ship 7's review. Then wire `scope_verdict` — the only mechanism that has ever found this user an eligible role — into the run, record what it found on the run row, and make the map render it.

**Tech Stack:** Python 3.13, pytest, SQLite, Apify actors via `requests`, Flask.

**Scope:** Parts 1–8 of `docs/superpowers/specs/2026-08-28-eligibility-from-measurement-design.md`. Part 9 (store cleanup) is **not** in this plan: the spec requires it to run after parts 3–5 are settled *and measured against a live run*, and that run has not happened yet. Part 6b (evaluating boards outside the aggregator) is research, not code, and is a follow-up.

Run all commands from `job_hunt/`. The full suite is `python -m pytest tests -q` and is green at **760 passing** before this plan starts.

---

## File structure

**Delete:**
- `job_hunt/src/scrapers/indeed.py` — the source being removed.

**Modify:**
- `job_hunt/src/run_core.py` — `SOURCES`, `_LOCAL_ONLY`, `_default_scrapers`, `plan_steps`, `_apply_gates`, new `_apply_scope`, boards collection.
- `job_hunt/src/scoring/matching.py` — `geo_verdict`'s `eligible_phrases` loop gains a duration guard.
- `job_hunt/src/scoring/location_scope.py` — `_countries_named` guards, timezone fall-through.
- `job_hunt/src/scoring/scorer.py` — remove the now-dead `scraped_under` path.
- `job_hunt/src/tracker/dedup.py` — lane evidence survives a collapse.
- `job_hunt/src/store/schema.py` — migration v8 for `run.boards`.
- `job_hunt/src/store/runs.py`, `job_hunt/src/pipeline_store.py` — carry `boards`.
- `job_hunt/src/store/queries.py` — map filters on `location_scope`; new `eligibility_counts`.
- `job_hunt/src/map_page.py`, `job_hunt/src/app.py` — the header counts.
- `job_hunt/vocabulary.yaml` — `eligible_phrases`, `remote_phrases`.
- `job_hunt/config.yaml`, `job_hunt/main.py`, `job_hunt/src/searching_page.py` — source names shown to the user.

**Tests:** `test_run_core_steps.py`, `test_run_core_execute.py`, `test_scrapers.py`, `test_geo_verdict.py`, `test_location_scope.py`, `test_dedup.py`, `test_store_runs.py`, `test_store_migration.py`, `test_map_page.py`, `test_map_routing.py`, `test_scorer_geo.py`, `test_eligibility_tier.py`, `test_pipeline_store.py`, `test_pipeline_announce.py`.

---

### Task 1: Re-shape the source plan

Indeed is removed and LinkedIn loses its plain worldwide lane, in one change — they are the same decision about what the run asks. `_LOCAL_ONLY` already means "this source gets no plain worldwide lane"; only its membership changes.

Run shape for 4 titles / remote+hybrid goes from 24 steps to 16: Remote boards worldwide (4), LinkedIn local (4), LinkedIn mode (8).

**Files:**
- Delete: `job_hunt/src/scrapers/indeed.py`
- Modify: `job_hunt/src/run_core.py`, `job_hunt/config.yaml`, `job_hunt/main.py:195`, `job_hunt/src/searching_page.py:73`
- Test: `job_hunt/tests/test_run_core_steps.py`, `job_hunt/tests/test_run_core_execute.py`, `job_hunt/tests/test_scrapers.py`

- [ ] **Step 1: Write the failing tests**

Add to `job_hunt/tests/test_run_core_steps.py`:

```python
def test_indeed_is_not_a_source():
    """Indeed is organised one site per country: 22 of the 66 countries
    this product supports have no Indeed at all, and for the rest it
    answers the local question the LinkedIn local lane already covers."""
    assert "Indeed" not in {name for name, _, _ in SOURCES}


def test_linkedin_gets_no_plain_worldwide_lane():
    """The mode lanes ask the same worldwide question with better
    precision (measured remote 5/5, hybrid 3/4 against an unfiltered
    lane). The local lane stays: a hybrid role in the user's own city is
    a role they can work."""
    steps = plan_steps(["Data Analyst"], local=True, mode_lanes=("remote",))
    worldwide = {s["source"] for s in steps if s["lane"] == "worldwide"}
    assert worldwide == {"Remote boards"}
    assert "LinkedIn" in {s["source"] for s in steps if s["lane"] == "local"}
    assert "LinkedIn" in {s["source"] for s in steps
                          if s["lane"].startswith("mode ")}


def test_the_whole_plan_for_a_remote_and_hybrid_user():
    """4 titles: 4 board lanes + 4 LinkedIn local + 8 LinkedIn mode."""
    titles = ["BI Developer", "Data Analyst", "data engineer", "data analytics"]
    steps = plan_steps(titles, local=True, mode_lanes=("remote", "hybrid"))
    assert len(steps) == 16
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_run_core_steps.py -k "indeed_is_not or plain_worldwide or whole_plan" -v`
Expected: FAIL — `Indeed` is still in `SOURCES`, so the worldwide set is `{"Indeed", "LinkedIn", "Remote boards"}` and the plan is 24 steps.

- [ ] **Step 3: Remove Indeed from the source list**

In `job_hunt/src/run_core.py`, replace the `SOURCES` block:

```python
# (display name, config key for the actor id, default actor id)
SOURCES = (
    ("LinkedIn",      "linkedin_actor",      "valig~linkedin-jobs-scraper"),
    ("Remote boards", "remote_boards_actor",
     "flash_scraper~remote-job-aggregator"),
)
```

and `_default_scrapers`:

```python
def _default_scrapers() -> dict:
    from .scrapers import linkedin, remote_boards
    return {"LinkedIn": linkedin.scrape,
            "Remote boards": remote_boards.scrape}
```

- [ ] **Step 4: Point `_LOCAL_ONLY` at LinkedIn**

In `job_hunt/src/run_core.py`, replace the whole `_LOCAL_ONLY` block:

```python
# Sources with no plain worldwide lane.
#
# This was Indeed, which is gone. It is now LinkedIn, for a different
# reason: its plain worldwide lane asks the same question the mode lanes
# ask, and asks it worse. Measured lane precision was remote 5/5 and
# hybrid 3/4 against an unfiltered lane that returns whatever LinkedIn's
# relevance matcher likes; run 6 spent 4 of 24 steps on it and the roles
# it added were indistinguishable from the mode lanes' own.
#
# The LOCAL lane stays, and is not affected by this constant. It found 63
# roles in the user's own country in run 6, and for a user in a small
# country a hybrid role in their own city is a role they can actually
# work — which is the whole question this product asks.
_LOCAL_ONLY = ("LinkedIn",)
```

- [ ] **Step 5: Delete the scraper and its config**

```bash
git rm job_hunt/src/scrapers/indeed.py
```

In `job_hunt/config.yaml`, delete the `indeed_actor` line so the block reads:

```yaml
apify:
  linkedin_actor:       "valig~linkedin-jobs-scraper"
  remote_boards_actor:  "flash_scraper~remote-job-aggregator"
  company_actor:        "curious_coder~linkedin-company-scraper"
```

In `job_hunt/main.py:195`, replace the print with:

```python
    print(f"\n[2/7] Scraping LinkedIn + Remote boards "
          f"(last {days_posted} days)...")
```

In `job_hunt/src/searching_page.py:73`, replace the line with:

```html
<div class="sub">Reading LinkedIn and Remote boards for the roles on your resumes.</div>
```

- [ ] **Step 6: Delete Indeed's scraper tests**

In `job_hunt/tests/test_scrapers.py`, delete every test that imports or parametrises `src.scrapers.indeed`. Keep the LinkedIn and remote-board tests untouched.

Run: `python -m pytest tests/test_scrapers.py -q`
Expected: PASS, with the Indeed cases gone.

- [ ] **Step 7: Update the step-count expectations that encoded three sources**

These tests assert counts that change. Update each to the new plan shape:

- `test_run_core_steps.py::test_every_title_is_planned_against_every_source` — with two sources and both lanes, each title is planned against `{"LinkedIn", "Remote boards"}`.
- `test_run_core_steps.py::test_steps_are_grouped_by_role_so_the_screen_reads_in_order` — worldwide-only now means one step per role (Remote boards).
- `test_run_core_steps.py::test_a_location_adds_a_local_lane` — 1 worldwide + 1 local = 2.
- `test_run_core_steps.py::test_without_a_location_the_plan_is_worldwide_only` — 1 step, Remote boards.
- `test_run_core_steps.py::test_indeed_is_never_planned_on_the_worldwide_lane` — **delete**; Task 1's own tests supersede it.
- `test_run_core_steps.py::test_plan_steps_only_plans_the_given_sources` — swap `only_indeed` for `only_linkedin`, keep `local=True`.
- `test_run_core_execute.py::test_the_first_event_already_lists_every_step` — 1 worldwide + 1 local + 1 mode lane = 3.
- `test_run_core_execute.py::test_duplicates_within_one_scrape_collapse` — LinkedIn's 2 lanes (local + mode) plus Remote boards' 1 = 3.
- `test_run_core_execute.py::test_no_location_means_no_local_lane` — Remote boards worldwide + 1 mode lane = 2.
- `test_run_core_execute.py::test_the_worldwide_lane_searches_worldwide_not_the_users_own_city` — **rewrite**: LinkedIn's only un-prefixed call is now the local one, so assert `[c["location"] for c in linkedin if c["title"] == "BI Developer"] == [_PROFILE["location"]]` and that Remote boards was called with `"Worldwide"`.
- Any `_scrapers(indeed_jobs=...)` call — change the fixture to `linkedin_jobs=` or `remote_boards_jobs=` and drop the `indeed_jobs` parameter from the `_scrapers` helper.
- `test_run_core_execute.py::test_a_failed_source_is_marked_on_its_step` — the expected dict loses its `"Indeed"` key.

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest tests -q`
Expected: PASS. Investigate any failure rather than adjusting the assertion — a surprise here means a source reference was missed.

- [ ] **Step 9: Commit**

```bash
git add -A job_hunt/
git commit -m "feat: the run asks only the sources that carry eligible roles

Indeed is removed. It is organised one site per country: 22 of the 66
countries this product supports have no Indeed site at all, and for the
rest it answers what is hiring IN a country, which is the local question
the LinkedIn local lane already covers. Run 6 proved it in the bluntest
way available - all four calls returned HTTP 400, because kaix declares
country as an enum of 54 sites and Armenia is not one.

LinkedIn loses its plain worldwide lane. The mode lanes ask the same
question with better precision. Its local lane stays: it found 63 roles
in the user's own country in run 6, and for a user in a small country a
hybrid role in their own city is a role they can work.

24 steps to 16."
```

---

### Task 2: Remove the `scraped_under` path

`scrapers/indeed.py` was the only writer of `_scraped_under`; the scorer's reduced-confidence branch for it is now unreachable. Ship 7 deleted the probe mechanism for exactly this reason — an inert mechanism that still looks live is worse than no mechanism.

**Files:**
- Modify: `job_hunt/src/run_core.py`, `job_hunt/src/scoring/scorer.py`
- Test: `job_hunt/tests/test_scorer_geo.py`, `job_hunt/tests/test_eligibility_tier.py`, `job_hunt/tests/test_run_core_execute.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_scorer_geo.py`:

```python
def test_the_scorer_takes_no_scraped_under_argument():
    """Indeed's us-board fallback was its only writer, and Indeed is gone.

    An inert parameter that still looks live is the pattern Ship 7 deleted
    the probe mechanism to avoid.
    """
    import inspect

    from src.scoring.scorer import Scorer
    assert "scraped_under" not in inspect.signature(
        Scorer.best_match).parameters
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_scorer_geo.py -k scraped_under -v`
Expected: FAIL — the parameter is still there.

- [ ] **Step 3: Remove it from the scorer**

In `job_hunt/src/scoring/scorer.py`, delete the `scraped_under` parameter from all three signatures (lines around 58, 142, 166), remove it from the internal call sites (around 92, 158), and delete the branch at lines 198–212 in full — the `elif (verdict == "unknown" and scraped_under and ...)` clause and the `fired.append("found via Indeed's US board, ...")` inside it.

- [ ] **Step 4: Remove it from the caller**

In `job_hunt/src/run_core.py`, in the scoring loop, delete the `scraped_under` local and its argument:

```python
    for job in new_jobs:
        mode_mismatch = job.pop("_mode_mismatch", None)
        local_ok = job.pop("_local_ok", False)
        scored_jobs.append(
            {**job, **scorer.best_match(job["title"],
                                        job.get("description", ""),
                                        resumes,
                                        mode_mismatch=mode_mismatch,
                                        local_evidence=local_ok)})
```

- [ ] **Step 5: Delete the tests that exercised the removed branch**

In `job_hunt/tests/test_scorer_geo.py`, `test_eligibility_tier.py` and `test_run_core_execute.py`, delete every test whose subject is the us-board fallback wording. Grep to find them:

Run: `grep -rn "scraped_under" tests/`
Expected after deletion: only the new Task 2 test remains.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A job_hunt/
git commit -m "refactor: drop the scraped_under path with the source that fed it

Indeed's us-board fallback was the only writer of _scraped_under, so the
scorer's reduced-confidence branch for it is unreachable. Removing it
rather than leaving an inert parameter that reads as live."
```

---

### Task 3: `eligible_phrases` — drop the bare phrase

First of two live faults. `anywhere in the world` sits in `eligible_phrases` bare, and members of that list return eligible on a `has_term` with no window and no corroboration. So it fires inside any sentence containing those five words — including Figma's `work together in real time from anywhere in the world`, which is marketing copy about the product they sell.

`candidates from anywhere in the world` is already in the list and carries the actual claim.

**Files:**
- Modify: `job_hunt/vocabulary.yaml`
- Test: `job_hunt/tests/test_geo_verdict.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_geo_verdict.py`. This test uses the real vocabulary because the point is the shipped config, not an inlined fixture:

```python
def test_a_sentence_that_merely_contains_the_words_claims_nothing():
    """Verbatim from run 6: Figma describing the product they sell.

    `anywhere in the world` was in eligible_phrases bare, and that list
    returns eligible on a bare has_term with no window at all.
    """
    from pathlib import Path

    import yaml
    cfg = yaml.safe_load(
        (Path(__file__).parent.parent / "vocabulary.yaml")
        .read_text(encoding="utf-8"))["eligibility"]
    body = ("empowers teams to streamline workflows, move faster, and "
            "work together in real time from anywhere in the world.")
    assert geo_verdict(body, "am", cfg) == ("unknown", None)


def test_the_real_worldwide_statements_still_claim_eligible():
    """The guard must not mute the phrases that carry an actual claim."""
    from pathlib import Path

    import yaml
    cfg = yaml.safe_load(
        (Path(__file__).parent.parent / "vocabulary.yaml")
        .read_text(encoding="utf-8"))["eligibility"]
    for body in ("we are open to candidates worldwide.",
                 "we hire candidates from anywhere in the world."):
        assert geo_verdict(body, "am", cfg) == ("eligible", None), body
```

- [ ] **Step 2: Run to verify the first fails**

Run: `python -m pytest tests/test_geo_verdict.py -k "merely_contains or real_worldwide" -v`
Expected: `test_a_sentence_that_merely_contains_the_words_claims_nothing` FAILS with `('eligible', None) != ('unknown', None)`; `test_the_real_worldwide_statements_still_claim_eligible` PASSES already.

- [ ] **Step 3: Remove the bare phrase**

In `job_hunt/vocabulary.yaml`, under `eligibility.eligible_phrases`, delete the `- "anywhere in the world"` entry and add the reason above the list:

```yaml
  # Standalone worldwide statements. A member of this list returns
  # eligible on a bare match - no window, no corroboration - so only
  # phrases that ARE a claim belong here.
  #
  # "anywhere in the world" was in this list bare and is not a claim, it
  # is five words: it fired inside "work together in real time from
  # anywhere in the world", a live LinkedIn row where the sentence is
  # about the product the company sells. "candidates from anywhere in the
  # world" below carries the claim that one was standing in for.
  eligible_phrases:
    - "open to candidates worldwide"
    - "open to applicants worldwide"
    - "candidates from anywhere in the world"
    - "work from anywhere in the world"
```

- [ ] **Step 4: Run to verify both pass**

Run: `python -m pytest tests/test_geo_verdict.py -k "merely_contains or real_worldwide" -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A job_hunt/
git commit -m "fix: 'anywhere in the world' is five words, not a claim

It sat in eligible_phrases bare, and members of that list return eligible
on a bare has_term with no window and no corroboration - so it fired
inside any sentence containing those words. Run 6 has the case: a
LinkedIn row where Figma describes teams working together in real time
from anywhere in the world, which is about the product they sell.

'candidates from anywhere in the world' stays and carries the claim."
```

---

### Task 4: `eligible_phrases` — a duration takes the claim back

Second fault. `work from anywhere in the world` is specific enough to belong in the list, but two live rows narrow it with a *duration* rather than a country — a case the list's own comment ("only phrases a following country cannot grammatically narrow") did not anticipate.

```
work from anywhere in the world for up to 4 weeks per year
work from anywhere in the world for up to 30 days a year
```

Both are holiday perks. This is the same fix already applied to bare `"anywhere"` in `location_scope` during the Ship 7 review — the trap in prose instead of a field.

**Files:**
- Modify: `job_hunt/src/scoring/matching.py`
- Test: `job_hunt/tests/test_geo_verdict.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_geo_verdict.py`:

```python
_ELIGIBLE_CFG = {
    "countries": {"am": ["armenia"], "us": ["us", "united states"]},
    "eligible_phrases": ["work from anywhere in the world"],
}


@pytest.mark.parametrize("body", [
    "work from anywhere in the world for up to 4 weeks per year.",
    "embrace the freedom to work from anywhere in the world for up to "
    "30 days a year.",
    "work from anywhere in the world for 5 days a month.",
])
def test_a_duration_after_the_phrase_claims_nothing(body):
    """Both verbatim from run 6, plus the un-hedged shape.

    A holiday perk is not an eligibility statement.
    """
    assert geo_verdict(body, "am", _ELIGIBLE_CFG) == ("unknown", None)


def test_the_phrase_without_a_duration_still_claims_eligible():
    """The guard is a guard, not a mute button."""
    body = "this role is fully remote - work from anywhere in the world."
    assert geo_verdict(body, "am", _ELIGIBLE_CFG) == ("eligible", None)


def test_one_qualified_mention_does_not_mute_an_unqualified_one():
    """A body can say it twice, once as a perk and once as a fact."""
    body = ("work from anywhere in the world for up to 4 weeks per year. "
            "this role is remote: work from anywhere in the world.")
    assert geo_verdict(body, "am", _ELIGIBLE_CFG) == ("eligible", None)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_geo_verdict.py -k "duration or without_a_duration or qualified_mention" -v`
Expected: the three `test_a_duration_after_the_phrase_claims_nothing` cases FAIL with `('eligible', None)`; the other two PASS.

- [ ] **Step 3: Add the duration pattern**

In `job_hunt/src/scoring/matching.py`, next to the other module-level patterns (near `_LIST_WINDOW`), add:

```python
# A duration immediately after an eligibility phrase takes the claim back:
# "work from anywhere in the world FOR UP TO 4 WEEKS PER YEAR" is a
# holiday perk, not a statement about who the employer will hire. Both
# live examples came from run 6. Anchored at the phrase's own end rather
# than scanned over a character window, so the rule stays as inspectable
# as the phrase list it guards. Digits only: every observed instance
# writes the number as a numeral.
_DURATION_AFTER = re.compile(
    r"\s*for\s+(?:up\s+to\s+)?\d+\s+(?:day|week|month)s?\b")
```

- [ ] **Step 4: Apply it in the `eligible_phrases` loop**

In `geo_verdict`, replace the standalone-phrase loop:

```python
    # Standalone worldwide statements ("open to candidates worldwide") open
    # no list window — the phrase itself is the evidence. Only phrases a
    # following country cannot grammatically narrow belong in this list.
    #
    # A following DURATION narrows them just as effectively, which that
    # rule did not anticipate: run 6 had two rows offering "work from
    # anywhere in the world for up to 4 weeks per year". Every occurrence
    # is checked, not just the first, so a body that states the fact once
    # and offers the perk once still claims what it states.
    for phrase in cfg.get("eligible_phrases") or []:
        phrase = str(phrase).strip().lower()
        if not phrase:
            continue
        for match in re.finditer(bounded(phrase), body):
            if not _DURATION_AFTER.match(body, match.end()):
                return ("eligible", None)
```

- [ ] **Step 5: Run to verify all five pass**

Run: `python -m pytest tests/test_geo_verdict.py -k "duration or without_a_duration or qualified_mention" -v`
Expected: PASS.

- [ ] **Step 6: Verify against the live rows this came from**

Run:

```bash
python -c "
import sys, yaml; sys.path.insert(0,'.')
from src.store.db import connect
from src.scoring.matching import geo_verdict
cfg = yaml.safe_load(open('vocabulary.yaml', encoding='utf-8'))['eligibility']
rows = connect().execute('SELECT description FROM role WHERE last_seen_run_id = 6').fetchall()
n = sum(1 for r in rows if geo_verdict((r['description'] or '').lower(), 'am', cfg)[0] == 'eligible')
print('LinkedIn+boards rows reading eligible:', n)
"
```

Expected: `0`. It was 3 before Tasks 3 and 4, and all three were false.

- [ ] **Step 7: Run the full suite and commit**

Run: `python -m pytest tests -q`
Expected: PASS.

```bash
git add -A job_hunt/
git commit -m "fix: a duration after an eligibility phrase takes the claim back

'work from anywhere in the world for up to 4 weeks per year' is a holiday
perk. Two live rows in run 6 read as eligible on it. The eligible_phrases
comment already said only phrases a following country cannot narrow
belong in that list; a following duration narrows them just as well.

Anchored at the phrase's own end rather than scanned over a window, and
every occurrence is checked, so a body that states the fact once and
offers the perk once still claims what it states.

Run 6's rows now yield 0 eligible, from 3 - all three of which were
false."
```

---

### Task 5: Rule 6b — `"work from home"` is not remote evidence

Ship 7's spec proposed this from one posting. Run 6 confirms it on 15: roughly five genuinely remote, six benefits boilerplate, and four stating the opposite outright.

**Files:**
- Modify: `job_hunt/vocabulary.yaml:313`
- Test: `job_hunt/tests/test_work_mode.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_work_mode.py`:

```python
def test_work_from_home_is_not_remote_evidence():
    """Verbatim from run 6, and it says the opposite of remote."""
    from pathlib import Path

    import yaml
    cfg = yaml.safe_load(
        (Path(__file__).parent.parent / "vocabulary.yaml")
        .read_text(encoding="utf-8"))["work_mode"]
    body = ("at least 4 days in the office per week, with the flexibility "
            "to work from home 1 day a week.")
    assert work_mode(body, cfg) != "remote"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_work_mode.py -k work_from_home -v`
Expected: FAIL — returns `"remote"`.

- [ ] **Step 3: Remove the phrase**

In `job_hunt/vocabulary.yaml`, delete line 313 (`    - "work from home"`) from `work_mode.remote_phrases` and add above the list:

```yaml
    # "work from home" is deliberately absent. Measured on 384 live roles
    # it fires 15 times: about five genuinely remote, six benefits
    # boilerplate ("reimbursement for work from home equipment"), and
    # four saying the opposite outright ("at least 4 days in the office
    # per week, with the flexibility to work from home 1 day a week").
```

- [ ] **Step 4: Run to verify it passes, then the full suite**

Run: `python -m pytest tests/test_work_mode.py -k work_from_home -v`
Expected: PASS.

Run: `python -m pytest tests -q`
Expected: PASS. If another test asserted `"work from home"` yields remote, delete it — it encoded the behaviour being removed.

- [ ] **Step 5: Commit**

```bash
git add -A job_hunt/
git commit -m "fix: 'work from home' is not evidence of a remote role

15 hits across 384 live roles: about five genuinely remote, six benefits
boilerplate, and four stating the opposite - 'at least 4 days in the
office per week, with the flexibility to work from home 1 day a week'."
```

---

### Task 6: `_countries_named` — make the docstring's guards real

Ship 7 review finding 8c. The docstring claims two guards the code does not implement.

**Files:**
- Modify: `job_hunt/src/scoring/location_scope.py`
- Test: `job_hunt/tests/test_location_scope.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_location_scope.py`:

```python
def test_the_pronoun_us_names_no_country():
    """A reach field is short, but 'us' is still a pronoun."""
    assert scope_verdict("Remote - come join us", "am", CFG, GEO) == "unknown"


def test_northern_ireland_is_not_ireland():
    """Word-bounding stops 'Irelander', not a preceding word."""
    assert scope_verdict("Northern Ireland", "am", CFG, GEO) != "closed"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_location_scope.py -k "pronoun or northern" -v`
Expected: both FAIL — `"come join us"` resolves to the United States and returns `closed`; `"Northern Ireland"` resolves to Ireland and returns `closed`.

- [ ] **Step 3: Implement the guards**

In `job_hunt/src/scoring/location_scope.py`, replace `_countries_named` in full:

```python
# Aliases too ambiguous to trust in a short reach field. "us" is the
# pronoun far more often than the country in the one live example we have
# ("Remote - come join us"), and the country has three unambiguous
# aliases left. Sourced from the eligibility table's own list so there is
# one definition of "ambiguous" in the product.
_ALIAS_PREFIX_TRAPS = ("northern",)


def _countries_named(text: str, geo_cfg: dict) -> set[str]:
    """Every country code the text names, word-bounded.

    Two guards the previous docstring claimed and the code did not have.

    `eligibility.ambiguous_names` is honoured: a reach field is short and
    enumerative, which makes a bare two-letter token likelier to be a
    country code than elsewhere — but "Remote - come join us" is a live
    counter-example, and the alias costs nothing since "usa", "u.s." and
    "united states" remain.

    And word-bounding does not stop a preceding word: `\\bireland\\b`
    matches inside "Northern Ireland", which is a different place. An
    alias preceded by a trap word does not count.
    """
    ambiguous = {str(n).strip().lower()
                 for n in (geo_cfg.get("ambiguous_names") or [])}
    found: set[str] = set()
    for code, aliases in (geo_cfg.get("countries") or {}).items():
        for alias in aliases or ():
            alias = str(alias).strip().lower()
            if not alias or alias in ambiguous:
                continue
            match = re.search(bounded(alias), text)
            if not match:
                continue
            before = text[:match.start()].rstrip()
            if any(before.endswith(trap) for trap in _ALIAS_PREFIX_TRAPS):
                continue
            found.add(str(code).strip().lower())
            break
    return found
```

- [ ] **Step 4: Run to verify, then the full suite**

Run: `python -m pytest tests/test_location_scope.py -q`
Expected: PASS, including the existing country-list tests — `us` is still named by `usa`, `u.s.` and `united states`.

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A job_hunt/
git commit -m "fix: _countries_named honours the guards its docstring claimed

It said the bare 'us' alias was deliberately unused and that word
bounding stopped 'Ireland' matching inside 'Northern Ireland'. Neither
was true: 'Remote - come join us' resolved to the United States, and
'Northern Ireland' to Ireland, both returning closed to every other
country."
```

---

### Task 7: An unknown timezone anchor must not silence the field

Ship 7 review finding 8d. The band branch returns `unknown` outright when it cannot read the anchor, skipping the region and country checks that could still have answered.

**Files:**
- Modify: `job_hunt/src/scoring/location_scope.py`
- Test: `job_hunt/tests/test_location_scope.py`

- [ ] **Step 1: Write the failing test**

```python
def test_an_unreadable_timezone_band_still_lets_the_rest_answer():
    """timezone_anchors lists six zones; a board writing IST, AEST or BST
    must not take the country list down with it."""
    assert scope_verdict("Armenia, Poland (+/- 3 hours)",
                         "am", CFG, GEO) == "open"


def test_an_unreadable_band_with_nothing_else_still_claims_nothing():
    assert scope_verdict("Time zone: XYZ (+/- 3 hours)",
                         "am", CFG, GEO) == "unknown"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_location_scope.py -k timezone_band -v`
Expected: the first FAILS with `'unknown' != 'open'`; the second PASSES.

- [ ] **Step 3: Fall through instead of returning**

In `job_hunt/src/scoring/location_scope.py`, replace the band branch:

```python
    band = _BAND_RE.search(text)
    if band:
        anchors = {str(k).lower(): int(v)
                   for k, v in (cfg.get("timezone_anchors") or {}).items()}
        offsets = {str(k).lower(): int(v)
                   for k, v in (cfg.get("country_utc_offset") or {}).items()}
        anchor, span = band.group(1).lower(), int(band.group(2))
        if anchor in anchors and user in offsets:
            centre = anchors[anchor]
            return ("open" if abs(offsets[user] - centre) <= span
                    else "closed")
        # Anchor or user offset unknown: this branch has nothing to say,
        # so it says nothing and lets the region and country checks below
        # try. Returning "unknown" here took the whole field down —
        # `timezone_anchors` lists six zones, and a board writing IST or
        # AEST would have silenced any country list in the same string.
```

- [ ] **Step 4: Run to verify, then the full suite**

Run: `python -m pytest tests/test_location_scope.py -q`
Expected: PASS.

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A job_hunt/
git commit -m "fix: an unreadable timezone band no longer silences the field

timezone_anchors lists six zones. A board writing IST, AEST or BST hit
the band branch, failed to resolve it, and returned unknown before the
region and country checks could run - taking any country list in the
same string down with it."
```

---

### Task 8: Remote boards only when the user wants remote

Ship 7 review finding 8b. The source is planned unconditionally, stamps every row `work_mode: "remote"`, and an onsite-only user then has every row dropped or flagged — after paying for the slowest source in the run (a 420-second floor).

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_run_core_steps.py`, `job_hunt/tests/test_run_core_execute.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_run_core_steps.py`:

```python
def test_an_onsite_only_user_gets_no_remote_board_step():
    """Every row the boards return is stamped remote, so an onsite-only
    user has all of them dropped or flagged - after paying for the
    slowest source in the run."""
    steps = plan_steps(["Data Analyst"], local=True, mode_lanes=(),
                       wants_remote=False)
    assert "Remote boards" not in {s["source"] for s in steps}


def test_a_remote_user_still_gets_the_remote_board_step():
    steps = plan_steps(["Data Analyst"], local=True, mode_lanes=("remote",),
                       wants_remote=True)
    assert "Remote boards" in {s["source"] for s in steps}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_run_core_steps.py -k remote_board_step -v`
Expected: FAIL — `plan_steps` takes no `wants_remote` argument.

- [ ] **Step 3: Add the parameter**

In `job_hunt/src/run_core.py`, change the `plan_steps` signature and the comprehension:

```python
def plan_steps(titles: list[str], sources=SOURCES, local: bool = False,
               mode_lanes: tuple = (), wants_remote: bool = True) -> list[dict]:
```

and inside, before the comprehension:

```python
    # The remote boards carry nothing but remote work — `remote_boards.
    # scrape` stamps every row "remote" because that is what those boards
    # are. A user who did not tick remote would have every row dropped or
    # flagged by the work-mode policy, after paying for the slowest source
    # in the run (a 420-second floor against LinkedIn's 20 seconds).
    if not wants_remote:
        sources = tuple(s for s in sources if s[0] not in _WORLDWIDE_ONLY)
```

- [ ] **Step 4: Pass it from `execute`**

In `job_hunt/src/run_core.py`, in `execute`, where `steps` is built:

```python
    steps = plan_steps(titles, sources=sources,
                      local=bool((profile.get("location") or "").strip()),
                      mode_lanes=mode_lanes,
                      wants_remote="remote" in {str(m).strip().lower()
                                                for m in work_modes})
```

- [ ] **Step 5: Add the execute-level test**

Add to `job_hunt/tests/test_run_core_execute.py`:

```python
def test_an_onsite_only_profile_never_calls_the_remote_boards(conn, user,
                                                              resume):
    profile = {**_PROFILE, "work_modes": ["onsite"]}
    called = []

    def boards(*args, **kwargs):
        called.append(args)
        return []

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], profile,
            scrapers={"LinkedIn": lambda *a, **k: [],
                      "Remote boards": boards})
    assert called == []
```

- [ ] **Step 6: Run to verify, then the full suite**

Run: `python -m pytest tests/test_run_core_steps.py tests/test_run_core_execute.py -q`
Expected: PASS.

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A job_hunt/
git commit -m "fix: the remote boards are not searched for onsite-only users

Every row they return is stamped remote, because that is what those
boards are. A user who did not tick remote had all of them dropped or
flagged by the work-mode policy - after paying for the slowest source in
the run, which carries a 420-second floor."
```

---

### Task 9: Lane evidence survives a dedupe collapse

Ship 7 review finding 8a. Mode-lane steps run last and `dedupe` keeps the first copy, so `_lane_mode` is discarded whenever an earlier lane returned the same posting — which is exactly the posting the lane exists to serve. Task 1 removed LinkedIn's plain worldwide lane, which removed the main collision source, but the local lane still collides.

**Files:**
- Modify: `job_hunt/src/tracker/dedup.py`
- Test: `job_hunt/tests/test_dedup.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_dedup.py`:

```python
def test_a_collapse_keeps_the_challengers_lane_evidence():
    """The mode lanes run last, so their copy is always the challenger.

    Lane membership is the only work-mode evidence a silent posting has,
    and dropping the challenger wholesale threw it away for exactly the
    postings the lane exists to serve.
    """
    incumbent = {"url": "https://x/1", "company": "Acme",
                 "title": "Data Analyst", "description": "body"}
    challenger = {"url": "https://x/1?src=lane", "company": "Acme",
                  "title": "Data Analyst", "description": "body",
                  "_lane_mode": "remote"}

    kept = dedupe([incumbent, challenger])

    assert len(kept) == 1
    assert kept[0]["_lane_mode"] == "remote"


def test_a_collapse_does_not_invent_lane_evidence():
    incumbent = {"url": "https://x/2", "company": "Acme",
                 "title": "Data Engineer", "description": "body"}
    challenger = {"url": "https://x/2?src=other", "company": "Acme",
                  "title": "Data Engineer", "description": "body"}

    kept = dedupe([incumbent, challenger])

    assert "_lane_mode" not in kept[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_dedup.py -k lane_evidence -v`
Expected: `test_a_collapse_keeps_the_challengers_lane_evidence` FAILS with `KeyError: '_lane_mode'`.

- [ ] **Step 3: Carry the evidence across the collapse**

In `job_hunt/src/tracker/dedup.py`, replace the collision branch inside `dedupe`:

```python
        if fp in kept:
            # Same posting, second source: upgrade only if it adds a body.
            incumbent = kept[fp]
            if not incumbent.get("description") and job.get("description"):
                kept[fp] = job
            # Lane membership survives the collapse either way. A mode
            # lane runs after the plain lanes, so its copy is always the
            # challenger — and for a posting whose own text says nothing
            # about work mode, the lane is the only evidence there is.
            # Dropping the challenger wholesale discarded it for exactly
            # the postings the lane exists to serve. Never overwritten:
            # if both copies carry a lane, the first one recorded stands,
            # the same way a conflict claims nothing elsewhere.
            lane = job.get("_lane_mode") or incumbent.get("_lane_mode")
            if lane:
                kept[fp].setdefault("_lane_mode", lane)
            continue
```

- [ ] **Step 4: Run to verify, then the full suite**

Run: `python -m pytest tests/test_dedup.py -q`
Expected: PASS.

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A job_hunt/
git commit -m "fix: lane membership survives a dedupe collapse

Mode-lane steps run last, so their copy is always the challenger, and
dedupe dropped the challenger wholesale. For a posting whose own text
says nothing about work mode the lane is the only evidence there is -
so the collapse threw it away for exactly the postings the lane exists
to serve."
```

---

### Task 10: Wire `scope_verdict` into the run

`location_scope.scope_verdict` is tested, correct, and called by nothing; `role.location_scope` is NULL on every row. It is also the only mechanism in the product that has ever found this user an eligible role.

**Deviation from the spec, recorded here:** the spec says the call belongs in ingest. It does not — `store/ingest.py` is a pure writer with neither the vocabulary nor the user's profile, and giving it both would make it load YAML and read the user table to write one column. `run_core` has both already and annotates jobs in exactly this way (`_local_ok`, `_mode_mismatch`). The call goes in a dedicated `_apply_scope` there, and `_upsert_role` writes `job.get("location_scope")`, which it already reads.

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_run_core_execute.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_run_core_execute.py`:

```python
def test_a_board_row_gets_its_reach_judged(conn, user, resume):
    """The reach field is the only eligibility evidence that has ever
    worked. Verbatim from run 6, on a profile whose country is in it."""
    from src.run_core import _apply_scope

    vocab = {
        "location_scope": {"worldwide": ["anywhere in the world"]},
        "eligibility": {"countries": {"am": ["armenia"], "pl": ["poland"]},
                        "regions": []},
    }
    jobs = [
        {"title": "Analytics Engineer", "source_board": "himalayas",
         "location": "Armenia, Cyprus, Georgia, Kazakhstan, Poland"},
        {"title": "Data Analyst", "source_board": "jobicy",
         "location": "Poland"},
        {"title": "Data Engineer", "platform": "LinkedIn",
         "location": "Yerevan, Armenia"},
    ]
    _apply_scope(jobs, vocab, {"country": "am"})

    assert jobs[0]["location_scope"] == "open"
    assert jobs[1]["location_scope"] == "closed"
    # A LinkedIn location is a place, not a reach statement. Judging it
    # would manufacture the fake evidence rule 6a exists to stop.
    assert "location_scope" not in jobs[2]


def test_the_scope_reaches_the_store(conn, user, resume):
    board_job = {**_job("https://x/scope1"), "platform": "Himalayas",
                 "source_board": "himalayas",
                 "location": "Anywhere in the World"}
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers=_scrapers(remote_boards_jobs=[board_job]))

    row = conn.execute(
        "SELECT location_scope FROM role WHERE url = ?",
        ("https://x/scope1",)).fetchone()
    assert row["location_scope"] == "open"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_run_core_execute.py -k "reach_judged or scope_reaches" -v`
Expected: FAIL — `cannot import name '_apply_scope'`.

- [ ] **Step 3: Write `_apply_scope`**

In `job_hunt/src/run_core.py`, add after `_apply_gates`:

```python
def _apply_scope(jobs: list[dict], vocab: dict, profile: dict) -> None:
    """Judge each remote-board row's published reach, in place.

    Remote boards state who they will hire as a FIELD, because being
    borderless is their product. Run 6 measured what that is worth: across
    384 roles, mining prose for eligibility found nothing and manufactured
    three claims, while reading this field found two and manufactured
    none.

    Board rows only. A LinkedIn `location` is a place, not a reach
    statement — feeding it to a reach parser would manufacture exactly the
    fake evidence rule 6a exists to stop. Rows without a `source_board`
    are left untouched, and an untouched row stores NULL, which the map
    reads as unverified rather than as closed.
    """
    from .scoring.location_scope import scope_verdict

    country = (profile.get("country") or "").strip().lower()
    scope_cfg = vocab.get("location_scope") or {}
    geo_cfg = vocab.get("eligibility") or {}
    for job in jobs:
        if not job.get("source_board"):
            continue
        job["location_scope"] = scope_verdict(
            job.get("location") or "", country, scope_cfg, geo_cfg)
```

- [ ] **Step 4: Call it from `execute`**

In `job_hunt/src/run_core.py`, immediately after the `_apply_gates` call:

```python
    new_jobs, offtopic_total, dropped_total = _apply_gates(
        new_jobs, vocab, profile, work_modes)
    _apply_scope(new_jobs, vocab, profile)
```

- [ ] **Step 5: Run to verify, then the full suite**

Run: `python -m pytest tests/test_run_core_execute.py -k "reach_judged or scope_reaches" -v`
Expected: PASS.

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A job_hunt/
git commit -m "feat: a board row's published reach is judged and stored

scope_verdict was tested, correct, and called by nothing;
role.location_scope was NULL on every row. It is also the only mechanism
in this product that has ever found this user an eligible role - across
384 roles in run 6, mining prose found nothing and manufactured three
claims, while reading the reach field found two and manufactured none.

Board rows only: a LinkedIn location is a place, not a reach statement,
and judging it would manufacture the fake evidence rule 6a exists to
stop. Untouched rows store NULL, which the map reads as unverified.

Lives in run_core rather than ingest, which the spec suggested: ingest is
a pure writer with neither the vocabulary nor the profile, and run_core
already annotates jobs this way."
```

---

### Task 11: Record which boards a run actually saw

The aggregator advertises ten boards. Run 6 returned four. Ship 7's residual watched for "two consecutive failed runs, or a run under 10 rows"; neither fired, because 133 rows arrived — from a quarter of the sources. The trigger watched the wrong thing.

**Files:**
- Modify: `job_hunt/src/store/schema.py`, `job_hunt/src/store/runs.py`, `job_hunt/src/pipeline_store.py`, `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_store_migration.py`, `job_hunt/tests/test_store_runs.py`, `job_hunt/tests/test_run_core_execute.py`

- [ ] **Step 1: Write the failing tests**

Add to `job_hunt/tests/test_store_migration.py`:

```python
def test_migration_v8_adds_the_boards_column(tmp_path):
    conn = connect(tmp_path / "v8.db")
    init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(run)")}
    assert "boards" in cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
    conn.close()
```

Add to `job_hunt/tests/test_store_runs.py`:

```python
def test_finish_run_records_the_boards_seen(conn):
    user_id = ensure_user(conn, "default")
    run_id = start_run(conn, user_id)
    finish_run(conn, run_id, scraped=10, kept=5,
               boards=["himalayas", "jobicy"])
    assert get_run(conn, run_id)["boards"] == ["himalayas", "jobicy"]


def test_a_run_that_saw_no_boards_records_an_empty_list(conn):
    user_id = ensure_user(conn, "default")
    run_id = start_run(conn, user_id)
    finish_run(conn, run_id, scraped=0, kept=0)
    assert get_run(conn, run_id)["boards"] == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_store_migration.py tests/test_store_runs.py -k "v8 or boards" -v`
Expected: FAIL — no `boards` column, `user_version` is 7.

- [ ] **Step 3: Add the column**

In `job_hunt/src/store/schema.py`, bump the version and extend the DDL and migrations:

```python
SCHEMA_VERSION = 8
```

In the `run` table DDL, after `offtopic`:

```sql
    boards      TEXT NOT NULL DEFAULT '[]',
```

And add to `_MIGRATIONS`:

```python
    8: (
        # Which of the aggregator's ten boards actually returned rows.
        # Run 6 got four and nothing noticed, because the residual watched
        # row count and 133 rows arrived. A board silent across two
        # consecutive runs is the signal; the row count is not.
        ("run", "boards",
         "ALTER TABLE run ADD COLUMN boards TEXT NOT NULL DEFAULT '[]'"),
    ),
```

- [ ] **Step 4: Carry it through `runs.py`**

In `job_hunt/src/store/runs.py`, add `import json` at the top if absent, then change `finish_run`:

```python
def finish_run(conn: sqlite3.Connection, run_id: int,
               scraped: int, kept: int, ok: bool = True,
               dropped: int = 0, offtopic: int = 0,
               boards: list[str] | None = None) -> None:
    with transaction(conn):
        conn.execute(
            """UPDATE run SET status = ?, finished_at = ?, scraped = ?,
               kept = ?, dropped = ?, offtopic = ?, boards = ?
             WHERE id = ?""",
            ("OK" if ok else "FAILED", _now(), scraped, kept, dropped,
             offtopic, json.dumps(sorted(boards or [])), run_id))
```

and in `get_run`, add `boards` to the SELECT column list and to the returned dict:

```python
        "boards":   json.loads(row["boards"] or "[]"),
```

- [ ] **Step 5: Carry it through `pipeline_store.py`**

```python
def persist_run(conn: sqlite3.Connection, user_id: int, run_id: int,
                scored_jobs: list[dict], scraped: int,
                dropped: int = 0, offtopic: int = 0,
                boards: list[str] | None = None) -> int:
```

and pass `boards=boards` to both `finish_run` calls in that function.

- [ ] **Step 6: Collect the boards in `execute`**

In `job_hunt/src/run_core.py`, after the scrape loop finishes and before `persist_run`:

```python
    # The aggregator advertises ten boards and returned four in run 6.
    # Recorded per run so a board going quiet is visible; the row count
    # is not the signal, because 133 rows arrived from those four.
    boards_seen = sorted({str(job["source_board"]) for job in all_scraped
                          if job.get("source_board")})
```

and pass it on:

```python
    persist_run(conn, user_id, run_id, scored_jobs, scraped_total,
               dropped=dropped_total, offtopic=offtopic_total,
               boards=boards_seen)
```

- [ ] **Step 7: Add the end-to-end test**

Add to `job_hunt/tests/test_run_core_execute.py`:

```python
def test_the_run_row_records_which_boards_returned_rows(conn, user, resume):
    rows = [{**_job("https://x/b1"), "source_board": "himalayas"},
            {**_job("https://x/b2", company="Other"),
             "source_board": "jobicy"}]
    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers=_scrapers(remote_boards_jobs=rows))

    assert get_run(conn, run_id)["boards"] == ["himalayas", "jobicy"]
```

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add -A job_hunt/
git commit -m "feat: the run row records which boards actually returned rows

The aggregator advertises ten. Run 6 got four - himalayas, jobicy, muse
and devitjobs_uk - and nothing noticed, because the Ship 7 residual
watched row count and 133 rows arrived. A board silent across two
consecutive runs is the signal; the row count is not.

Schema v8."
```

---

### Task 12: The map shows the roles that are actually open

Run 6's map renders 384 roles. Two of them are provably open. This is the user-facing point of the whole ship.

Hiding is never silent — the header states what was set aside, the same way the on-site-elsewhere drop already does.

**Files:**
- Modify: `job_hunt/src/store/queries.py`, `job_hunt/src/map_page.py`, `job_hunt/src/app.py`
- Test: `job_hunt/tests/test_map_routing.py`, `job_hunt/tests/test_map_page.py`

- [ ] **Step 1: Write the failing tests**

Add to `job_hunt/tests/test_map_routing.py`:

```python
def test_the_map_lists_only_roles_proven_open(conn, user):
    """384 rendered roles told the user there were 384 worth reading.
    Two were open."""
    _store_role(conn, user, url="https://x/open", location_scope="open")
    _store_role(conn, user, url="https://x/closed", location_scope="closed")
    _store_role(conn, user, url="https://x/null", location_scope=None)

    sections = map_sections(conn, user, 7)
    urls = {r["url"] for m in sections["new"] + sections["earlier"]
            for r in m["roles"]}
    assert urls == {"https://x/open"}


def test_the_counts_account_for_every_role(conn, user):
    _store_role(conn, user, url="https://x/o", location_scope="open")
    _store_role(conn, user, url="https://x/c1", location_scope="closed")
    _store_role(conn, user, url="https://x/c2", location_scope="closed")
    _store_role(conn, user, url="https://x/u", location_scope=None)

    assert eligibility_counts(conn, user) == {
        "open": 1, "closed": 2, "unverified": 1}
```

Add to `job_hunt/tests/test_map_page.py`:

```python
def test_the_header_states_what_was_set_aside():
    html = render([], meta={"companies": 0, "roles": 0,
                            "open": 2, "closed": 66, "unverified": 316,
                            "offtopic": 124})
    assert "2 OPEN" in html
    assert "66 NOT OPEN" in html
    assert "316 UNVERIFIED" in html
    assert "124 OFF-TOPIC" in html


def test_an_empty_map_reads_as_checked_not_broken():
    """Zero open roles is an answer. It must not render as a blank page."""
    html = render([], meta={"companies": 0, "roles": 0,
                            "open": 0, "closed": 87, "unverified": 297})
    assert "0 OPEN" in html
    assert "87 NOT OPEN" in html
```

`_store_role` is a helper in `test_map_routing.py`; extend its signature with `location_scope=None` and write the column through to `role`.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_map_routing.py tests/test_map_page.py -k "proven_open or counts_account or set_aside or checked_not_broken" -v`
Expected: FAIL — `eligibility_counts` does not exist and the map lists all three roles.

- [ ] **Step 3: Filter the map query**

In `job_hunt/src/store/queries.py`, add the filter to `_OPEN_ROLES`:

```python
_OPEN_ROLES = """
SELECT r.* FROM role r
  JOIN company c ON c.id = r.company_id
  LEFT JOIN application a ON a.role_id = r.id
 WHERE r.user_id = ?
   AND a.id IS NULL
   AND c.user_state != 'HIDDEN'
   AND r.location_scope = 'open'
   AND r.first_seen_run_id {op} ?
"""
```

- [ ] **Step 4: Add the counts query**

In `job_hunt/src/store/queries.py`, add beside `map_sections`:

```python
def eligibility_counts(conn: sqlite3.Connection, user_id: int) -> dict:
    """How every stored role divides on the only question that matters.

    `unverified` is NULL `location_scope` — a row nothing could judge,
    which is every LinkedIn row (its location is a place, not a reach
    statement) and every board row whose reach field was unparseable.
    Unverified is not eligible and not ineligible; the map states its size
    rather than implying either.
    """
    rows = conn.execute(
        """SELECT COALESCE(location_scope, 'unverified') AS verdict,
                  COUNT(*) AS n
             FROM role r
             JOIN company c ON c.id = r.company_id
            WHERE r.user_id = ? AND c.user_state != 'HIDDEN'
            GROUP BY verdict""", (user_id,)).fetchall()
    counts = {row["verdict"]: row["n"] for row in rows}
    return {"open": counts.get("open", 0),
            "closed": counts.get("closed", 0),
            "unverified": (counts.get("unverified", 0)
                           + counts.get("unknown", 0))}
```

- [ ] **Step 5: Render the counts**

In `job_hunt/src/map_page.py`, replace the `meta_2` block:

```python
    # Hiding is never silent. The map now lists only roles proven open to
    # this user, which is a deliberate, user-approved narrowing of
    # flag-never-hide — so the header carries the full account of what was
    # set aside and why. Run 6's honest split was 2 open, 66 not open,
    # 316 unverified: rendering all 384 told the reader there were 384
    # worth opening.
    meta_2 = f"SCRAPED {_e(scraped)}"
    meta_2 = f"{meta_2} &middot; {meta.get('open') or 0} OPEN"
    meta_2 = f"{meta_2} &middot; {meta.get('closed') or 0} NOT OPEN"
    meta_2 = f"{meta_2} &middot; {meta.get('unverified') or 0} UNVERIFIED"

    hidden = meta.get("hidden") or 0
    if hidden:
        meta_2 = f"{meta_2} &middot; {hidden} HIDDEN (ON-SITE ELSEWHERE)"

    # A relevance-gate rejection is a different fact from a hidden-elsewhere
    # posting — wrong place vs. not this job at all — so it earns its own
    # clause rather than folding into the count above.
    offtopic = meta.get("offtopic") or 0
    if offtopic:
        meta_2 = f"{meta_2} &middot; {offtopic} OFF-TOPIC (NOT A TARGET ROLE)"
```

Note the open/closed/unverified clauses are unconditional: `0 OPEN` is the answer when it is the answer, and suppressing it would make an empty map read as broken.

- [ ] **Step 6: Pass them from the route**

In `job_hunt/src/app.py`, import `eligibility_counts` alongside `map_sections`, then in the map route:

```python
            counts = eligibility_counts(conn, user_id)

            html = render_map(
                tagged,
                meta={"companies": len(sections["new"]) + len(sections["earlier"]),
                      "roles": sum(len(m["roles"]) for m in
                                   sections["new"] + sections["earlier"]),
                      "hidden": hidden, "offtopic": offtopic, **counts},
                running_run_id=in_flight["id"] if in_flight else None)
```

- [ ] **Step 7: Run to verify, then the full suite**

Run: `python -m pytest tests/test_map_routing.py tests/test_map_page.py -q`
Expected: PASS.

Run: `python -m pytest tests -q`
Expected: PASS. Existing map tests that stored roles without a `location_scope` will now find an empty map — update each to store `location_scope="open"` where the test's subject is the map listing a role, since that is what "a role the user should see" now means.

- [ ] **Step 8: Commit**

```bash
git add -A job_hunt/
git commit -m "feat: the map lists the roles that are actually open, and says what it set aside

Run 6 rendered 384 roles. Two were provably open to this user. 384 cards
told the reader there were 384 worth opening.

The map now lists roles whose published reach proves them open, and the
header carries the whole account - open, not open, unverified, off-topic.
Unverified is neither eligible nor ineligible: it is every LinkedIn row,
whose location is a place rather than a reach statement, and the map
states the size of that set rather than implying either reading.

A deliberate, user-approved narrowing of flag-never-hide - the second,
alongside the on-site-elsewhere drop. Hidden, never silent."
```

---

### Task 13: Record the narrowing in CLAUDE.md

`CLAUDE.md` states flag-never-hide with "ONE user-approved exception". There are now two.

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the geography section**

In `CLAUDE.md`, replace the flag-never-hide bullet with:

```markdown
- Flag-never-hide, with TWO user-approved exceptions, both counted and
  both stated on the map, never silent:
  1. A posting stating a work mode the user did not search for, in a
     confidently-parsed foreign country, is dropped — stated as
     "N HIDDEN (ON-SITE ELSEWHERE)".
  2. The map lists only roles whose published reach proves them open to
     the user. Everything else is counted in the header as NOT OPEN or
     UNVERIFIED. Run 6 measured why: of 384 stored roles, 2 were provably
     open, and rendering all 384 told the reader there were 384 worth
     opening.
```

- [ ] **Step 2: Update the sources sentence**

In `CLAUDE.md`, the Project section says the product "Scrapes Indeed + LinkedIn via Apify". Replace with:

```markdown
Scrapes LinkedIn and ten remote job boards via Apify, scores listings
against the job description, and presents company-centred opportunity
maps rather than a flat job list. AI layer: resume parsing, tailoring,
cover letters.

Indeed was removed in Ship 8: it is organised one site per country, 22 of
the 66 countries this product supports have no Indeed site, and run 6
returned HTTP 400 on every call for an Armenian user. See
`docs/superpowers/specs/2026-08-28-eligibility-from-measurement-design.md`.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md catches up with Ship 8

Two user-approved exceptions to flag-never-hide now, not one, and the
source list no longer names Indeed."
```

---

### Task 14: Verify the whole ship against the stored run

No new scrape. Run 6's rows are already in the store, so the eligibility changes can be checked against real data before anything is spent.

- [ ] **Step 1: Confirm the prose false positives are gone**

Run:

```bash
python -c "
import sys, yaml; sys.path.insert(0,'.')
from src.store.db import connect
from src.scoring.matching import geo_verdict
cfg = yaml.safe_load(open('vocabulary.yaml', encoding='utf-8'))['eligibility']
rows = connect().execute('SELECT description FROM role WHERE last_seen_run_id = 6').fetchall()
from collections import Counter
print(Counter(geo_verdict((r['description'] or '').lower(), 'am', cfg)[0] for r in rows))
"
```

Expected: `eligible` is **0**, down from 3. `restricted` stays at 8.

- [ ] **Step 2: Confirm the reach parser finds the two known roles**

Run:

```bash
python -c "
import sys, yaml; sys.path.insert(0,'.')
from collections import Counter
from src.store.db import connect
from src.scoring.location_scope import scope_verdict
V = yaml.safe_load(open('vocabulary.yaml', encoding='utf-8'))
rows = connect().execute(
    'SELECT title, location FROM role WHERE last_seen_run_id = 6 AND source_board IS NOT NULL').fetchall()
c = Counter()
for r in rows:
    v = scope_verdict(r['location'] or '', 'am', V['location_scope'], V['eligibility'])
    c[v] += 1
    if v == 'open':
        print('OPEN:', r['title'][:60], '|', repr(r['location']))
print(dict(c))
"
```

Expected: the two known roles — `Engineering Manager - Data Platform` (reach `Anywhere`) and `Analytics Engineer (Payments & Finance Data)` (reach `Armenia, Cyprus, ...`) — and a total of 87.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest tests -q`
Expected: PASS, from either `job_hunt/` or the repo root.

- [ ] **Step 4: Confirm the plan shape without spending anything**

Run:

```bash
python -c "
import sys; sys.path.insert(0,'.')
from src.run_core import plan_steps
steps = plan_steps(['BI Developer','Data Analyst','data engineer','data analytics'],
                   local=True, mode_lanes=('remote','hybrid'))
print(len(steps), 'steps')
for s in steps: print(' ', s['source'], '|', s['lane'], '|', s['role'])
"
```

Expected: **16 steps** — 4 Remote-boards worldwide, 4 LinkedIn local, 8 LinkedIn mode. No Indeed.

- [ ] **Step 5: Open a PR**

```bash
git push -u origin ship-8-remote-first-sourcing
gh pr create --base master --title "Ship 8: remote-first sourcing for small-country users" --body "..."
```

The PR body should carry run 6's measured table (source → steps → roles → provably open), the two `eligible_phrases` faults with their live examples, and the before/after of Step 1 and Step 2 above.

---

## Not in this plan

- **Spec part 9, the store cleanup.** It decides what to drop using exactly the rules in Tasks 3–5 and 10, and the spec requires those to be measured against a live run first. The store holds 1184 roles, 800 of which predate the relevance gate; dropping them on rules that have only been checked against stored text would repeat the mistake Ship 7 made. Do it after the next live run.
- **Spec part 6b, boards outside the aggregator.** Research — evaluate Wellfound, Arc.dev, and the public JSON feeds RemoteOK and Remotive publish. Task 11 gathers the evidence that should drive it.
- **The unused LinkedIn fields.** Demoted out of the ship by the spec: LinkedIn is a supporting source now.
