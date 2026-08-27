# Sourcing, Relevance and Lanes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the pipeline fetching the wrong jobs, and start it fetching jobs the user can actually be hired for.

**Architecture:** Five changes to the scrape half of the run. Delete the probe mechanism (proven inert). Add a title relevance gate so off-target roles are never stored. Replace LinkedIn's dead `remote` parameter with keyword lanes that genuinely partition results. Swap the Indeed actor to `kaix` so the work mode comes from a publisher-stated field instead of our own query echoed back. Add remote job boards as a fourth source, where eligibility is a published field rather than prose.

**Tech Stack:** Python 3.13, pytest, SQLite, Apify actors via `requests`.

**Test conventions — read before the first task.** This project's tests
run from the `job_hunt/` directory, not the repo root:

- Run them as `cd job_hunt && python -m pytest tests/ -q`. From the repo
  root, `test_work_mode.py` fails on a relative `open("vocabulary.yaml")`.
- Import as `from src.run_core import ...`, never `from job_hunt.src...`.
- Open the vocabulary as `open("vocabulary.yaml", encoding="utf-8")`.
- `git add` paths in the commit steps are repo-root relative, so run git
  commands from the repo root.

Baseline before any work: **669 passed** from `job_hunt/`.

**Scope:** This is Ship 7, covering parts 1–5 of
`docs/superpowers/specs/2026-08-27-search-lanes-and-store-cleanup-design.md`.
Parts 6–9 (eligibility rules, unused LinkedIn fields, work-mode phrase
widening, store-cleanup migration) are Ship 8 and depend on this landing
first — they need the new sources producing data before their rules can
be measured against anything real.

---

## File structure

**Create:**
- `job_hunt/src/scoring/relevance.py` — the title gate. One question: is this title a role we search for?
- `job_hunt/src/scrapers/remote_boards.py` — the fourth source. Wraps `flash_scraper~remote-job-aggregator`.
- `job_hunt/src/scoring/location_scope.py` — parses the reach field remote boards publish (`Anywhere in the World`, region lists, timezone bands).
- `job_hunt/tests/test_relevance.py`
- `job_hunt/tests/test_remote_boards.py`
- `job_hunt/tests/test_location_scope.py`

**Modify:**
- `job_hunt/vocabulary.yaml` — add a `roles:` section (include/exclude title phrases) and a `location_scope:` section (region membership).
- `job_hunt/src/run_core.py` — delete probes, add the relevance gate, add mode lanes, register the fourth source.
- `job_hunt/src/scrapers/linkedin.py` — delete the dead `remote` parameter.
- `job_hunt/src/scrapers/indeed.py` — swap to the `kaix` payload and field shape.
- `job_hunt/src/store/schema.py` — migration v6 for the new columns.
- `job_hunt/config.yaml` — actor ids, drop `search.probes`.

**Delete:**
- `job_hunt/tests/test_eligibility_tier.py` probe cases only (the tier tests themselves stay).

---

### Task 1: Delete the probe mechanism

The `remote` key sent to valig is not a parameter it accepts. Apify drops unknown keys silently, so both probe lanes ran the same unfiltered search; overlapping URLs were claimed by one probe, re-claimed by the other, and collapsed to `""`. Deleting this removes ~50 lines and loses no information.

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Modify: `job_hunt/src/scrapers/linkedin.py`
- Modify: `job_hunt/config.yaml`
- Test: `job_hunt/tests/test_run_core_steps.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_run_core_steps.py`:

```python
def test_plan_steps_emits_no_probe_lanes():
    """Probes never filtered anything - valig has no `remote` parameter."""
    steps = plan_steps(["Data Analyst"], local=True)
    lanes = {step["lane"] for step in steps}
    assert lanes == {"worldwide", "local"}
    assert not any(step["lane"].startswith("probe") for step in steps)


def test_plan_steps_takes_no_probes_argument():
    import inspect
    assert "probes" not in inspect.signature(plan_steps).parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd job_hunt && python -m pytest tests/test_run_core_steps.py -k probe -v`
Expected: FAIL — `plan_steps` still accepts `probes` and emits probe lanes.

- [ ] **Step 3: Remove probes from `plan_steps`**

In `job_hunt/src/run_core.py`, replace the whole `plan_steps` function with:

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

- [ ] **Step 4: Remove the probe branch from the run loop**

In `job_hunt/src/run_core.py`, delete the entire `if step["lane"].startswith("probe"):` block (from that line through its `continue`).

Delete the `probe_badges: dict[str, str] = {}` line and the `probes_on = ...` line.

Change the `plan_steps` call to:

```python
    steps = plan_steps(titles, sources=sources,
                      local=bool((profile.get("location") or "").strip()))
```

- [ ] **Step 5: Simplify the mode reconciliation**

In `job_hunt/src/run_core.py`, replace the badge reconciliation block inside the `for job in new_jobs:` loop. Find the block starting `text_mode = work_mode(` and ending `job["work_mode"] = mode`, and replace it with:

```python
        mode = work_mode(f"{job.get('title') or ''}\n"
                         f"{job.get('description') or ''}", mode_cfg)
        if mode:
            job["work_mode"] = mode
```

Delete the `badge_hits = 0` line and the `badge_hits=badge_hits` argument from the `RunResult(...)` return.

- [ ] **Step 6: Remove `badge_hits` from `RunResult`**

In `job_hunt/src/run_core.py`, delete the `badge_hits: int = 0` field from the `RunResult` dataclass.

- [ ] **Step 7: Remove the dead `remote` parameter from the LinkedIn scraper**

In `job_hunt/src/scrapers/linkedin.py`, delete `_REMOTE_CODES`, `_LEGACY_REMOTE`, and the whole `_filters_for` function. Replace the `payload` construction in `scrape` with:

```python
    where = (location or "").strip() or _LEGACY_LOCATION
    payload = {
        "title":      title,
        "location":   where,
        "datePosted": _DATE_MAP.get(days_posted, "r604800"),
        "limit":      jobs_per_category,
    }
```

Update the legacy-retry block to drop the `remote` key:

```python
    legacy = {**payload, "location": _LEGACY_LOCATION}
    if allow_fallback and not raw and legacy != payload:
        logger.warning(
            "LinkedIn returned nothing for %s with location=%r — "
            "retrying with the legacy Worldwide payload",
            category, payload["location"])
        raw = call_actor(actor_id, legacy, f"LinkedIn/{category} (legacy)",
                         run_timeout)
```

- [ ] **Step 8: Drop the config key**

In `job_hunt/config.yaml`, remove any `probes:` line under `search:`. If none exists, no change.

- [ ] **Step 9: Delete probe tests**

Remove any test in `job_hunt/tests/test_eligibility_tier.py` and `job_hunt/tests/test_run_core_execute.py` whose name contains `probe` or `badge`. Keep every other test in those files.

- [ ] **Step 10: Run the whole suite**

Run: `cd job_hunt && python -m pytest tests/ -q`
Expected: PASS. If a test fails on `badge_hits` or a probe lane, it is one the previous step should have removed.

- [ ] **Step 11: Commit**

```bash
git add job_hunt/src/run_core.py job_hunt/src/scrapers/linkedin.py job_hunt/config.yaml job_hunt/tests/
git commit -m "refactor: delete the probe mechanism, which never filtered anything"
```

---

### Task 2: Role relevance vocabulary and matcher

41% of the store is not a data role. A bare-word test is what let them in: `data` matched "Data Center & Edge Infrastructure Lead" and "Urban Data Platforms"; `analyst` matched "Quantitative Analyst".

**Files:**
- Create: `job_hunt/src/scoring/relevance.py`
- Modify: `job_hunt/vocabulary.yaml`
- Test: `job_hunt/tests/test_relevance.py`

- [ ] **Step 1: Write the failing test**

Create `job_hunt/tests/test_relevance.py`:

```python
"""The title gate. Every trap here reached the live map before it existed."""
import pytest
import yaml

from src.scoring.relevance import is_target_role

CFG = yaml.safe_load(
    open("vocabulary.yaml", encoding="utf-8"))["roles"]


@pytest.mark.parametrize("title", [
    "Data Analyst",
    "Senior Data Engineer",
    "BI Developer",
    "Analytics Engineer - AI Trainer",
    "Data Analyst II - Marketing & Customer Analytics",
    "Principal Business Intelligence Analyst",
    "Senior Power BI Data Analyst - Remote Work",
])
def test_real_roles_pass(title):
    assert is_target_role(title, CFG) is True


@pytest.mark.parametrize("title", [
    "Quantitative Analyst",
    "Cloud, Data Center & Edge Infrastructure Lead",
    "Urban Data Platforms, Digital Twins & AI Governance",
    "Senior Mechanical Engineer - Data Centers",
    "Electrical Engineer, Data Centers - Remote (U.S.)",
    "Nurse Practitioner - Telehealth HRT part time",
    "Fleet Parking Specialist",
    "Travel Advisor",
    "Online SAT Test Prep Expert Tutor",
    "Territory Sales Manager",
])
def test_traps_are_rejected(title):
    assert is_target_role(title, CFG) is False


def test_exclusion_beats_inclusion():
    """A data-centre job is a data-centre job however it is titled."""
    assert is_target_role("Data Engineer, Data Center Operations", CFG) is False


def test_empty_title_is_not_relevant():
    assert is_target_role("", CFG) is False
    assert is_target_role(None, CFG) is False


def test_no_include_list_accepts_everything_not_excluded():
    """An unconfigured gate must not silently reject the whole run."""
    assert is_target_role("Anything At All", {"include": [], "exclude": []}) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd job_hunt && python -m pytest tests/test_relevance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.scoring.relevance'`

- [ ] **Step 3: Add the vocabulary section**

Append to `job_hunt/vocabulary.yaml`:

```yaml
# Which titles name a data role at all. Title-only, phrases only, never
# bare words: a bare "data" matched "Data Center & Edge Infrastructure
# Lead" and "Urban Data Platforms"; a bare "analyst" matched
# "Quantitative Analyst". All three reached the live map.
#
# These are market facts — the names these roles go by. Nothing here
# describes a particular person; which of them a given user searches for
# comes from their resumes.
roles:
  include:
    - "data analyst"
    - "data engineer"
    - "data analytics"
    - "data scientist"
    - "analytics engineer"
    - "business intelligence"
    - "bi developer"
    - "bi analyst"
    - "bi engineer"
    - "power bi"
    - "product analyst"
    - "analytics manager"
    - "data warehouse"
    - "etl developer"
    - "reporting analyst"
    - "insights analyst"
    - "data platform"
  exclude:
    # Traps that pass an include phrase but are not the job.
    - "data center"
    - "data centre"
    - "data entry"
    - "data protection"
    - "clinical data"
    - "flight data"
```

- [ ] **Step 4: Write the matcher**

Create `job_hunt/src/scoring/relevance.py`:

```python
"""Is this posting one of the roles the user searches for?

Title only. The description is not consulted: an ad for a nurse can
mention "data" a dozen times, and 41% of the store arrived that way.

Phrases only, word-bounded, same discipline as `work_mode` — a bare-word
test is what admitted "Data Center & Edge Infrastructure Lead".
"""
import re
from functools import lru_cache


@lru_cache(maxsize=None)
def _patterns(phrases: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    """One compiled, bounded pattern per phrase, cached per phrase-tuple.

    Called once per scraped job, so the compile cost is paid once per
    run rather than once per job. `cfg` arrives as lists (unhashable),
    so callers pass an already-lowered tuple as the cache key.
    """
    return tuple(re.compile(r"(?<!\w)" + re.escape(p) + r"(?!\w)")
                 for p in phrases)


def _phrases(cfg: dict, key: str) -> tuple[str, ...]:
    return tuple(sorted({str(p).strip().lower()
                         for p in cfg.get(key) or [] if str(p).strip()}))


def is_target_role(title: str, cfg: dict) -> bool:
    """True when the title names a searched-for role and no trap phrase.

    Exclusions are checked first and win outright: "Data Engineer, Data
    Center Operations" matches an include phrase and is still a
    data-centre job.

    An empty include list accepts everything not excluded, so a
    misconfigured vocabulary degrades to today's behaviour rather than
    rejecting an entire run.
    """
    text = (title or "").strip().lower()
    if not text:
        return False
    cfg = cfg or {}

    exclude = _phrases(cfg, "exclude")
    if exclude and any(p.search(text) for p in _patterns(exclude)):
        return False

    include = _phrases(cfg, "include")
    if not include:
        return True
    return any(p.search(text) for p in _patterns(include))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd job_hunt && python -m pytest tests/test_relevance.py -v`
Expected: PASS, 21 tests.

- [ ] **Step 6: Commit**

```bash
git add job_hunt/src/scoring/relevance.py job_hunt/tests/test_relevance.py job_hunt/vocabulary.yaml
git commit -m "feat: title relevance gate, phrase-bounded like work_mode"
```

---

### Task 3: Wire the relevance gate into the run

The gate runs immediately after dedupe and before the work-mode policy, so an off-target role never costs a company-enrichment lookup or a scoring pass. Rejections are counted and reported, never silent.

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_run_core_execute.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_run_core_execute.py`:

```python
def test_offtopic_titles_are_never_stored(tmp_store, fake_scrapers):
    """A nurse posting must not reach the map, whatever it scores."""
    fake_scrapers.queue([
        {"cat": "Data Analyst", "title": "Data Analyst", "company": "Acme",
         "location": "Remote", "platform": "Indeed", "date": "2026-08-27",
         "url": "https://example.com/1", "salary": "", "description": "SQL"},
        {"cat": "Data Analyst", "title": "Nurse Practitioner", "company": "Med",
         "location": "Remote", "platform": "Indeed", "date": "2026-08-27",
         "url": "https://example.com/2", "salary": "", "description": "data"},
    ])
    result = run_execute(tmp_store, fake_scrapers)
    titles = [job["title"] for job in result.scored_jobs]
    assert titles == ["Data Analyst"]
    assert result.offtopic == 1


def test_offtopic_count_reaches_the_progress_payload(tmp_store, fake_scrapers):
    fake_scrapers.queue([
        {"cat": "Data Analyst", "title": "Travel Advisor", "company": "T",
         "location": "Remote", "platform": "Indeed", "date": "2026-08-27",
         "url": "https://example.com/3", "salary": "", "description": ""},
    ])
    seen = []
    run_execute(tmp_store, fake_scrapers, on_progress=seen.append)
    assert seen[-1]["offtopic"] == 1
```

If `tmp_store`, `fake_scrapers` and `run_execute` do not already exist as
fixtures in this file, reuse whatever the existing tests in
`test_run_core_execute.py` use to drive `execute` — do not invent a new
harness.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd job_hunt && python -m pytest tests/test_run_core_execute.py -k offtopic -v`
Expected: FAIL — `RunResult` has no attribute `offtopic`.

- [ ] **Step 3: Add the counter to `RunResult`**

In `job_hunt/src/run_core.py`, add to the `RunResult` dataclass, after `dropped`:

```python
    offtopic: int = 0
```

- [ ] **Step 4: Add the counter and report it**

In `job_hunt/src/run_core.py`, next to `dropped_total = 0`, add:

```python
    offtopic_total = 0
```

Replace the `report` function with:

```python
    def report(stage: str) -> None:
        emit({"stage": stage, "steps": [dict(s) for s in steps],
             "scraped": scraped_total, "dropped": dropped_total,
             "offtopic": offtopic_total})
```

- [ ] **Step 5: Apply the gate**

In `job_hunt/src/run_core.py`, add `relevance` to the local imports near
the top of `execute`:

```python
    from .scoring.relevance import is_target_role
```

Immediately after the `new_jobs = dedupe(...)` line and before the
work-mode policy comment block, insert:

```python
    # Relevance gate. 41% of what these actors return is not a data role
    # at all — Nurse Practitioner, Travel Advisor, Fleet Parking
    # Specialist. The scorer rates them 1-4 and they were stored anyway.
    # Rejecting here means an off-target role costs no enrichment lookup
    # and no scoring pass. Counted, never silent.
    role_cfg = vocab.get("roles") or {}
    on_topic = [job for job in new_jobs if is_target_role(job.get("title"), role_cfg)]
    offtopic_total = len(new_jobs) - len(on_topic)
    new_jobs = on_topic
```

Note: `vocab` is loaded a few lines below this point today. Move the
three lines that load it (`with open(VOCABULARY_PATH...)` through
`loc_cfg = ...`) to just above this block so `vocab` is defined here.

- [ ] **Step 6: Return the count**

In `job_hunt/src/run_core.py`, change the return to:

```python
    return RunResult(scraped=scraped_total, kept=len(scored_jobs),
                     dropped=dropped_total, offtopic=offtopic_total,
                     scored_jobs=scored_jobs, steps=steps, titles=titles)
```

- [ ] **Step 7: Run tests**

Run: `cd job_hunt && python -m pytest tests/test_run_core_execute.py -v`
Expected: PASS.

- [ ] **Step 8: Run the whole suite**

Run: `cd job_hunt && python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add job_hunt/src/run_core.py job_hunt/tests/test_run_core_execute.py
git commit -m "feat: reject off-target titles before scoring, count them on the run"
```

---

### Task 4: LinkedIn keyword lanes

`f_WT` and `remote` are both ignored. Putting the mode in the search words is the only mechanism that partitions results: measured 0 shared job IDs between the remote and hybrid lanes, against 9–25 for the parameter routes.

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_run_core_steps.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_run_core_steps.py`:

```python
def test_mode_lanes_follow_the_users_selection():
    steps = plan_steps(["Data Analyst"], mode_lanes=("remote", "hybrid"))
    lanes = [s["lane"] for s in steps if s["lane"].startswith("mode")]
    assert lanes == ["mode remote", "mode hybrid"]
    assert all(s["source"] == "LinkedIn"
               for s in steps if s["lane"].startswith("mode"))


def test_onsite_never_gets_a_lane():
    """Measured 1/3 precision - postings rarely say "this is on-site"."""
    steps = plan_steps(["Data Analyst"], mode_lanes=("onsite",))
    assert not any(s["lane"].startswith("mode") for s in steps)


def test_no_mode_lanes_when_none_selected():
    steps = plan_steps(["Data Analyst"], mode_lanes=())
    assert not any(s["lane"].startswith("mode") for s in steps)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd job_hunt && python -m pytest tests/test_run_core_steps.py -k mode_lane -v`
Expected: FAIL — `plan_steps` got an unexpected keyword argument `mode_lanes`.

- [ ] **Step 3: Add mode lanes to `plan_steps`**

In `job_hunt/src/run_core.py`, replace `plan_steps` with:

```python
# The only modes a keyword lane can express. On-site has no lane:
# measured 1/3 precision, because postings advertise "remote" and
# "hybrid" as selling points but rarely state on-site at all. It is
# inferred by elimination and served by the local lane.
LANE_MODES = ("remote", "hybrid")


def plan_steps(titles: list[str], sources=SOURCES,
               local: bool = False, mode_lanes=()) -> list[dict]:
    """The whole scrape, listed before any of it runs.

    Grouped by role, worldwide lane before local, which is the order they
    actually run in. The local lane searches the profile's actual place
    with every work mode — it exists so target-country on-site/hybrid
    jobs arrive at all instead of by accident.

    Mode lanes put the work mode in LinkedIn's search words. LinkedIn
    ignores both the `remote` parameter and `f_WT`, but its relevance
    matcher does respond to the words themselves: measured, the remote
    and hybrid lanes share zero job IDs, where the parameter routes
    shared 9 to 25.
    """
    lanes = ("worldwide",) + (("local",) if local else ())
    steps = [{"source": name, "role": title, "lane": lane,
              "state": "pending", "found": 0}
             for title in titles
             for lane in lanes
             for name, _, _ in sources]

    if any(name == "LinkedIn" for name, _, _ in sources):
        for title in titles:
            for mode in mode_lanes:
                if mode not in LANE_MODES:
                    continue
                steps.append({"source": "LinkedIn", "role": title,
                              "lane": f"mode {mode}",
                              "state": "pending", "found": 0})
    return steps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd job_hunt && python -m pytest tests/test_run_core_steps.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing test for lane execution**

Add to `job_hunt/tests/test_run_core_execute.py`:

```python
def test_mode_lane_puts_the_mode_in_the_search_words(tmp_store, recording_scraper):
    """The words are the only thing LinkedIn actually honours."""
    run_execute(tmp_store, {"LinkedIn": recording_scraper},
                work_modes=["remote"])
    mode_calls = [c for c in recording_scraper.calls
                  if c["title"].startswith("remote ")]
    assert mode_calls, "no mode lane ran"
    assert mode_calls[0]["title"] == "remote Data Analyst"


def test_mode_lane_membership_fills_silence_only(tmp_store, fake_scrapers):
    """Lane membership is evidence, not proof - stated text still wins."""
    fake_scrapers.queue_for_lane("mode remote", [
        {"cat": "Data Analyst", "title": "Data Analyst", "company": "A",
         "location": "Berlin, Germany", "platform": "LinkedIn",
         "date": "2026-08-27", "url": "https://example.com/a",
         "salary": "", "description": "This is a hybrid role."},
    ])
    result = run_execute(tmp_store, fake_scrapers, work_modes=["remote"])
    job = result.scored_jobs[0]
    assert job.get("work_mode") == "hybrid"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd job_hunt && python -m pytest tests/test_run_core_execute.py -k mode_lane -v`
Expected: FAIL — no mode lane runs.

- [ ] **Step 7: Execute the mode lanes**

In `job_hunt/src/run_core.py`, compute the lanes before `plan_steps`:

```python
    mode_lanes = tuple(m for m in
                       (str(x).strip().lower() for x in work_modes)
                       if m in LANE_MODES)
    steps = plan_steps(titles, sources=sources,
                      local=bool((profile.get("location") or "").strip()),
                      mode_lanes=mode_lanes)
```

In the scrape loop, add a branch before the `if step["lane"] == "local":` branch:

```python
        if step["lane"].startswith("mode "):
            lane_mode = step["lane"].split(" ", 1)[1]
            lane_location = _LANE_WORLDWIDE
            lane_modes = (lane_mode,)
            lane_kwargs = {"allow_fallback": False,
                           "title_override": f"{lane_mode} {step['role']}"}
        elif step["lane"] == "local":
```

Change the scrape call so a lane can override the search words:

```python
        try:
            jobs = scrapers[name](
                step["role"], lane_kwargs.pop("title_override", step["role"]),
                apify_cfg.get(actor_key, actor_default),
                days_posted, jobs_per_cat, run_timeout,
                location=lane_location, country=country,
                work_modes=lane_modes, **lane_kwargs)
```

Add the constant near `SOURCES`:

```python
# A mode lane asks a worldwide question - "remote data analyst", not
# "remote data analyst in Yerevan".
_LANE_WORLDWIDE = "Worldwide"
```

- [ ] **Step 8: Tag jobs with their lane**

In `job_hunt/src/run_core.py`, in the `else:` branch that appends scraped jobs, replace `all_scraped.extend(jobs)` with:

```python
            if step["lane"].startswith("mode "):
                for job in jobs:
                    # Transient. Popped before scoring, never stored.
                    job["_lane_mode"] = step["lane"].split(" ", 1)[1]
            all_scraped.extend(jobs)
```

- [ ] **Step 9: Use lane membership only to fill silence**

In `job_hunt/src/run_core.py`, replace the mode block inside `for job in new_jobs:` with:

```python
        text_mode = work_mode(f"{job.get('title') or ''}\n"
                              f"{job.get('description') or ''}", mode_cfg)
        lane_mode = job.pop("_lane_mode", None)
        if text_mode and lane_mode and text_mode != lane_mode:
            # A lane is LinkedIn matching words, not a filter - a posting
            # that merely mentions "remote" lands in the remote lane.
            # Disagreement claims nothing, as every other conflict does.
            mode = None
        elif lane_mode and not text_mode:
            mode = lane_mode
        else:
            mode = text_mode
        if mode:
            job["work_mode"] = mode
```

- [ ] **Step 10: Run tests**

Run: `cd job_hunt && python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add job_hunt/src/run_core.py job_hunt/tests/
git commit -m "feat: LinkedIn mode lanes - the search words are the only filter that works"
```

---

### Task 5: Swap the Indeed actor to kaix

Today's payload puts the mode in the location box, and Indeed returns the string "Remote" — our own query reflected back. Four of eleven hand-reviewed roles were admitted on that basis alone, one of which actually reads "Remote (United States)". `kaix` has a real attribute filter and returns `workArrangement.locationType` as a publisher-stated field.

**Files:**
- Modify: `job_hunt/src/scrapers/indeed.py`
- Modify: `job_hunt/config.yaml`
- Test: `job_hunt/tests/test_scrapers.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_scrapers.py`:

```python
from src.scrapers import indeed


def test_indeed_never_puts_remote_in_the_location_box(monkeypatch):
    """Indeed echoes the location box back as the job's location."""
    sent = {}

    def fake_call(actor_id, payload, label, timeout):
        sent.update(payload)
        return []

    monkeypatch.setattr(indeed, "call_actor", fake_call)
    indeed.scrape("Data Analyst", "Data Analyst", "kaix~indeed-scraper",
                  location="Yerevan, Armenia", country="am",
                  work_modes=("remote",))
    assert sent["location"].lower() != "remote"
    assert sent["remote"] == "remote"
    assert sent["keyword"] == 'title:"Data Analyst"'


def test_indeed_uses_one_title_per_search():
    """Combining titles with `or` collapses precision from 15/15 to 11/20."""
    assert indeed._keyword("Data Analyst") == 'title:"Data Analyst"'


def test_indeed_maps_the_kaix_field_shape(monkeypatch):
    item = {
        "title": {"text": "Data Analyst"},
        "company": {"name": "Acme"},
        "location": {"formatted": "Nashville, TN", "country": "US"},
        "workArrangement": {"locationType": "Remote"},
        "salary": {"text": "$65 - $75 an hour"},
        "dates": {"posted": "2026-08-25"},
        "urls": {"indeed": "https://indeed.com/viewjob?jk=abc"},
        "description": {"html": "<p>SQL and Python</p>"},
        "signals": {"isExpired": False},
    }
    monkeypatch.setattr(indeed, "call_actor",
                        lambda *a, **k: [item])
    jobs = indeed.scrape("Data Analyst", "Data Analyst", "kaix~indeed-scraper")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Data Analyst"
    assert job["company"] == "Acme"
    assert job["location"] == "Nashville, TN"
    assert job["work_mode"] == "remote"
    assert job["salary"] == "$65 - $75 an hour"
    assert "SQL and Python" in job["description"]


def test_indeed_drops_expired_postings(monkeypatch):
    item = {
        "title": {"text": "Data Analyst"},
        "company": {"name": "Acme"},
        "location": {"formatted": "Nashville, TN"},
        "urls": {"indeed": "https://indeed.com/viewjob?jk=abc"},
        "description": {"text": "SQL"},
        "signals": {"isExpired": True},
    }
    monkeypatch.setattr(indeed, "call_actor", lambda *a, **k: [item])
    assert indeed.scrape("Data Analyst", "Data Analyst", "x") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd job_hunt && python -m pytest tests/test_scrapers.py -k indeed -v`
Expected: FAIL — `indeed` has no attribute `_keyword`; payload uses `query`/`location`.

- [ ] **Step 3: Rewrite the Indeed scraper**

Replace the whole body of `job_hunt/src/scrapers/indeed.py` below the imports with:

```python
"""Indeed scraper — wraps Apify kaix~indeed-scraper.

Swapped from valig because valig has no work-mode filter, so the old
payload put "remote" in the LOCATION box. Indeed then returned the
string "Remote" as each job's location — our own query reflected back,
which four of eleven hand-reviewed roles were wrongly admitted on.

kaix has Indeed's real attribute filter (`remote`) and returns
`workArrangement.locationType` as a publisher-stated field, plus
`signals.isExpired`, structured `location.country` and parsed salary.
"""
from datetime import date
import logging

from .base import call_actor, extract_description
from ..utils._dates import normalize_date, parse_salary

logger = logging.getLogger(__name__)

_DATE_MAP = {1: "1", 3: "3", 7: "7", 14: "14"}

# kaix speaks Indeed's own remote filter. It has no "onsite" value —
# absence of the filter is how you ask for everything.
_REMOTE_FILTER = {"remote": "remote", "hybrid": "hybrid"}

_LEGACY_LOCATION = "United States"
_LEGACY_COUNTRY = "us"


def _get(item: dict, path: str, default=None):
    """Read a dotted path out of kaix's nested item shape."""
    node = item
    for part in path.split("."):
        if not isinstance(node, dict):
            return default
        node = node.get(part)
    return node if node is not None else default


def _keyword(title: str) -> str:
    """Indeed's title operator, ONE title per search.

    Measured: `title:"Data Analyst"` returns 15/15 on-target, while
    `title:("A" or "B" or "C")` collapses to 11/20 and silently ignores
    `-intern`. So the caller runs one search per role title rather than
    combining them.
    """
    return f'title:"{(title or "").strip()}"'


def _remote_filter(work_modes) -> str:
    """Indeed's filter value, or "" meaning no filter.

    Only set it when the user wants exactly one filterable mode. Asking
    for remote when they also accept hybrid would hide the hybrid work.
    """
    modes = {str(m).strip().lower() for m in work_modes or ()}
    filterable = modes & set(_REMOTE_FILTER)
    if len(filterable) == 1 and modes == filterable:
        return _REMOTE_FILTER[filterable.pop()]
    return ""


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120,
           location: str = _LEGACY_LOCATION,
           country: str = _LEGACY_COUNTRY,
           work_modes=("remote",),
           allow_fallback: bool = True) -> list[dict]:
    payload = {
        "keyword":  _keyword(title),
        "location": (location or "").strip() or _LEGACY_LOCATION,
        "country":  ((country or _LEGACY_COUNTRY).strip().upper()),
        "maxItems": jobs_per_category,
        "sort":     "date",
    }
    remote = _remote_filter(work_modes)
    if remote:
        # kaix documents that fromDays cannot combine with the remote
        # filter, so recency is traded for a real work-mode answer.
        payload["remote"] = remote
    else:
        payload["fromDays"] = _DATE_MAP.get(days_posted, "7")

    raw = call_actor(actor_id, payload, f"Indeed/{category}", run_timeout)

    if allow_fallback and not raw:
        legacy = {**payload, "location": _LEGACY_LOCATION,
                  "country": _LEGACY_COUNTRY.upper()}
        if legacy != payload:
            logger.warning(
                "Indeed returned nothing for %s with location=%r country=%r"
                " — retrying with %s", category, payload["location"],
                payload["country"], _LEGACY_LOCATION)
            raw = call_actor(actor_id, legacy, f"Indeed/{category} (legacy)",
                             run_timeout)

    today = date.today().isoformat()
    jobs: list[dict] = []
    for item in raw:
        if _get(item, "signals.isExpired") is True:
            # A closed posting wastes the user's time. kaix is the only
            # source that tells us; LinkedIn does not.
            continue
        url = (_get(item, "urls.indeed") or _get(item, "urls.apply")
               or _get(item, "urls.external") or "")
        if not url:
            continue

        job = {
            "cat":      category,
            "title":    _get(item, "title.text", ""),
            "company":  _get(item, "company.name", ""),
            "location": _get(item, "location.formatted", ""),
            "platform": "Indeed",
            "date":     normalize_date(_get(item, "dates.posted") or today),
            "url":      url,
            "salary":   parse_salary(_get(item, "salary.text") or ""),
            "description": extract_description(
                {"descriptionHtml": _get(item, "description.html"),
                 "description":     _get(item, "description.text")}),
        }
        # Publisher-stated, unlike the old location-box echo. "In-person"
        # is kaix's wording for on-site.
        stated = (_get(item, "workArrangement.locationType") or "").lower()
        mode = {"remote": "remote", "hybrid": "hybrid",
                "in-person": "onsite"}.get(stated)
        if mode:
            job["work_mode"] = mode
        country_code = (_get(item, "location.country") or "").strip().lower()
        if country_code:
            # Structured, so `location_country`'s ambiguity cases
            # ("Chennai, IN" vs "Gary, IN") never arise for Indeed rows.
            job["country"] = country_code
        jobs.append(job)

    return jobs[:jobs_per_category]
```

- [ ] **Step 4: Point config at the new actor**

In `job_hunt/config.yaml`, change:

```yaml
  indeed_actor:   "kaix~indeed-scraper"
```

- [ ] **Step 5: Run tests**

Run: `cd job_hunt && python -m pytest tests/test_scrapers.py -v`
Expected: PASS.

- [ ] **Step 6: Honour a scraper-supplied work mode**

The Indeed scraper now sets `work_mode` itself. In
`job_hunt/src/run_core.py`, change the mode block so a publisher-stated
value is not overwritten by text inference. Replace the first line of
that block with:

```python
        stated_mode = job.get("work_mode")
        text_mode = stated_mode or work_mode(
            f"{job.get('title') or ''}\n{job.get('description') or ''}",
            mode_cfg)
```

- [ ] **Step 7: Run the whole suite**

Run: `cd job_hunt && python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add job_hunt/src/scrapers/indeed.py job_hunt/config.yaml job_hunt/tests/test_scrapers.py job_hunt/src/run_core.py
git commit -m "feat: swap Indeed to kaix - real remote filter, stated work mode, expiry"
```

---

### Task 6: `location_scope` parser

Remote boards publish reach as a field rather than burying it in prose. Four shapes were measured. The timezone band must be computed, not skipped: Yerevan is UTC+4 and `CET (+/- 3 hours)` reaches UTC+4, so a parser that treats it as unknown discards a real match.

**Files:**
- Create: `job_hunt/src/scoring/location_scope.py`
- Modify: `job_hunt/vocabulary.yaml`
- Test: `job_hunt/tests/test_location_scope.py`

- [ ] **Step 1: Write the failing test**

Create `job_hunt/tests/test_location_scope.py`:

```python
"""Every string here was returned by a live remote-board run."""
import pytest
import yaml

from src.scoring.location_scope import scope_verdict

VOCAB = yaml.safe_load(open("vocabulary.yaml", encoding="utf-8"))
CFG = VOCAB["location_scope"]
# `location_country` needs the eligibility country tables, not this
# section's, so the parser takes both.
GEO = VOCAB["eligibility"]


@pytest.mark.parametrize("text", [
    "Anywhere in the World",
    "anywhere in the world",
    "Worldwide",
])
def test_worldwide_is_open_to_everyone(text):
    assert scope_verdict(text, "am", CFG, GEO) == "open"


def test_a_foreign_country_is_closed():
    assert scope_verdict("United States", "am", CFG, GEO) == "closed"


def test_your_own_country_is_open():
    assert scope_verdict("Armenia", "am", CFG, GEO) == "open"


def test_a_region_list_is_checked_for_membership():
    text = "Europe, North America, Latin America, APAC"
    assert scope_verdict(text, "am", CFG, GEO) == "open"    # Armenia is in APAC
    assert scope_verdict(text, "za", CFG, GEO) == "closed"  # South Africa is not


def test_timezone_band_is_computed_not_skipped():
    """Yerevan is UTC+4; CET+3 reaches UTC+4. This is a real match."""
    assert scope_verdict("Time zone: CET (+/- 3 hours)", "am", CFG, GEO) == "open"
    assert scope_verdict("Time zone: CET (+/- 3 hours)", "us", CFG, GEO) == "closed"


def test_silence_claims_nothing():
    assert scope_verdict("", "am", CFG, GEO) == "unknown"
    assert scope_verdict("Flexible / Remote", "am", CFG, GEO) == "unknown"


def test_unset_user_country_claims_nothing():
    """Same discipline as geo_verdict - the check cannot run."""
    assert scope_verdict("United States", "", CFG, GEO) == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd job_hunt && python -m pytest tests/test_location_scope.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Add the vocabulary section**

Append to `job_hunt/vocabulary.yaml`:

```yaml
# Remote boards publish reach as a FIELD rather than burying it in
# prose. These are the shapes measured on a live run.
location_scope:
  worldwide:
    - "anywhere in the world"
    - "worldwide"
    - "work from anywhere"
    - "anywhere"
  # Region name -> ISO-2 country codes that belong to it. Only the
  # regions the boards actually emit. Partial by design: a region we do
  # not list claims nothing rather than guessing.
  regions:
    apac: [am, au, nz, jp, kr, cn, in, sg, my, th, vn, ph, id, ge, az]
    emea: [gb, ie, de, fr, es, it, nl, be, pl, pt, se, no, dk, fi, am, ge, tr, ae, za]
    europe: [gb, ie, de, fr, es, it, nl, be, pl, pt, se, no, dk, fi, am, ge, tr]
    "north america": [us, ca, mx]
    "latin america": [br, ar, cl, co, pe, mx, uy]
    latam: [br, ar, cl, co, pe, mx, uy]
    americas: [us, ca, mx, br, ar, cl, co, pe, uy]
  # Anchor zone -> UTC offset, for "CET (+/- 3 hours)" style bands.
  timezone_anchors:
    cet: 1
    cest: 2
    utc: 0
    gmt: 0
    est: -5
    pst: -8
  # UTC offset per country, for the timezone-band test. Only countries
  # a user can select today plus the common remote markets.
  country_utc_offset:
    am: 4
    ge: 4
    us: -5
    ca: -5
    gb: 0
    de: 1
    fr: 1
    es: 1
    pl: 1
    ua: 2
    tr: 3
    ae: 4
    in: 5
    sg: 8
    au: 10
    br: -3
    mx: -6
    za: 2
```

- [ ] **Step 4: Write the parser**

Create `job_hunt/src/scoring/location_scope.py`:

```python
"""What a remote board's reach field says, judged for one user.

Indeed and LinkedIn make you mine 8KB of prose for this. Remote boards
publish it as a field, because being borderless is their product:

    "Anywhere in the World"
    "Europe, North America, Latin America, APAC"
    "Time zone: CET (+/- 3 hours)"
    "United States"

Returns "open", "closed" or "unknown". Silence is the default and an
unset user country claims nothing, the same discipline `geo_verdict`
follows — this parser is allowed to be certain only when the field
actually says something.
"""
import re

_BAND_RE = re.compile(
    r"\b([a-z]{2,4})\s*\(\s*\+/-\s*(\d+)\s*(?:hours?|hrs?)?\s*\)", re.I)


def _bounded(phrase: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)")


def scope_verdict(text: str, user_country: str,
                  cfg: dict, geo_cfg: dict) -> str:
    """Read a board's location field for one user.

    `cfg` is vocabulary.yaml's `location_scope`; `geo_cfg` is its
    `eligibility` section, which owns the country name and code tables.
    Both are needed: there must be one spelling of every country in the
    product, and it lives under `eligibility`.

    Checked in order: worldwide wins outright; then a timezone band,
    because "CET (+/- 3 hours)" also contains no country name and would
    otherwise fall through to unknown; then named regions; then country
    names and codes. Anything unrecognised claims nothing.
    """
    text = (text or "").strip().lower()
    user = (user_country or "").strip().lower()
    if not text or not user:
        return "unknown"
    cfg = cfg or {}

    for phrase in cfg.get("worldwide") or []:
        if _bounded(str(phrase).strip().lower()).search(text):
            return "open"

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
        return "unknown"

    regions = {str(k).lower(): [str(c).lower() for c in (v or [])]
               for k, v in (cfg.get("regions") or {}).items()}
    named = [name for name in regions if _bounded(name).search(text)]
    if named:
        return ("open" if any(user in regions[name] for name in named)
                else "closed")

    # A bare country name or code. Reuse the eligibility country tables
    # so there is one spelling of every country in the product.
    from .matching import location_country
    place = location_country(text, geo_cfg or {})
    if place:
        return "open" if place == user else "closed"
    return "unknown"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd job_hunt && python -m pytest tests/test_location_scope.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 6: Commit**

```bash
git add job_hunt/src/scoring/location_scope.py job_hunt/tests/test_location_scope.py job_hunt/vocabulary.yaml
git commit -m "feat: parse the reach field remote boards publish"
```

---

### Task 7: The remote-boards scraper

Measured: LinkedIn and Indeed returned 0 roles open to Armenia across 800 jobs; one 50-row remote-board run returned 11.

**Files:**
- Create: `job_hunt/src/scrapers/remote_boards.py`
- Test: `job_hunt/tests/test_remote_boards.py`

- [ ] **Step 1: Write the failing test**

Create `job_hunt/tests/test_remote_boards.py`:

```python
"""Fixtures are rows from a live flash_scraper~remote-job-aggregator run."""
from src.scrapers import remote_boards


def test_search_terms_are_the_role_titles(monkeypatch):
    sent = {}
    monkeypatch.setattr(remote_boards, "call_actor",
                        lambda a, p, l, t: sent.update(p) or [])
    remote_boards.scrape("Data Analyst", "Data Analyst", "actor")
    assert sent["searchTerms"] == ["Data Analyst"]
    assert sent["maxItems"] > 0


def test_maps_a_worldwide_row(monkeypatch):
    row = {
        "title": "Senior Staff Data Engineer",
        "company": "Faire",
        "location": "Anywhere in the World",
        "url": "https://weworkremotely.com/jobs/1",
        "source_board": "weworkremotely",
        "posted_at": "2026-08-25",
        "salary_min": 276000, "salary_max": 379500,
        "salary_currency": "USD",
        "description": "Build the data platform.",
    }
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: [row])
    jobs = remote_boards.scrape("Data Engineer", "Data Engineer", "actor")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Senior Staff Data Engineer"
    assert job["company"] == "Faire"
    assert job["platform"] == "We Work Remotely"
    assert job["work_mode"] == "remote"
    assert job["location"] == "Anywhere in the World"
    assert "276,000" in job["salary"] or "276000" in job["salary"]


def test_every_row_is_remote(monkeypatch):
    """These boards carry nothing else - that is what they are for."""
    row = {"title": "Data Analyst", "company": "X", "location": "United States",
           "url": "https://remoteok.com/1", "source_board": "remoteok",
           "posted_at": "2026-08-25", "description": ""}
    monkeypatch.setattr(remote_boards, "call_actor", lambda *a, **k: [row])
    assert remote_boards.scrape("Data Analyst", "Data Analyst", "a")[0]["work_mode"] == "remote"


def test_rows_without_a_url_are_skipped(monkeypatch):
    monkeypatch.setattr(remote_boards, "call_actor",
                        lambda *a, **k: [{"title": "X", "company": "Y"}])
    assert remote_boards.scrape("Data Analyst", "Data Analyst", "a") == []


def test_a_failing_actor_returns_nothing_rather_than_raising(monkeypatch):
    """This source is allowed to fail without taking the run down."""
    def boom(*a, **k):
        raise RuntimeError("board down")
    monkeypatch.setattr(remote_boards, "call_actor", boom)
    assert remote_boards.scrape("Data Analyst", "Data Analyst", "a") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd job_hunt && python -m pytest tests/test_remote_boards.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the scraper**

Create `job_hunt/src/scrapers/remote_boards.py`:

```python
"""Remote job boards — wraps Apify flash_scraper~remote-job-aggregator.

The fourth source, and for a user outside the US and EU the only one
that carries anything. Measured on one profile: Indeed and LinkedIn
returned 0 roles open to Armenia across 800 jobs; a single 50-row run
here returned 11.

It sweeps ten public boards (RemoteOK, We Work Remotely, Working
Nomads, Remotive, Jobicy, Himalayas, The Muse, DevITjobs US/UK, HN
"Who is hiring?") into one deduplicated feed. Two things make it a
better fit than either incumbent: `searchTerms` matches job TITLES, so
the relevance gate is enforced before we pay per row; and the location
field states reach outright rather than burying it in prose.

This source is allowed to fail. It is young, one of its boards failed
mid-run during testing, and a run takes minutes rather than seconds —
so every error is swallowed and the run continues on the others.
"""
import logging

from .base import call_actor

logger = logging.getLogger(__name__)

# The aggregator's board slug -> the name we show the user.
_BOARDS = {
    "remoteok": "RemoteOK",
    "weworkremotely": "We Work Remotely",
    "working_nomads": "Working Nomads",
    "remotive": "Remotive",
    "jobicy": "Jobicy",
    "himalayas": "Himalayas",
    "muse": "The Muse",
    "devitjobs_us": "DevITjobs",
    "devitjobs_uk": "DevITjobs",
    "hn_hiring": "Hacker News",
}


def _salary(row: dict) -> str:
    """The aggregator publishes salary already annualised."""
    low, high = row.get("salary_min"), row.get("salary_max")
    currency = (row.get("salary_currency") or "").strip()
    symbol = "$" if currency in ("", "USD") else f"{currency} "
    if low and high:
        return f"{symbol}{int(low):,} – {symbol}{int(high):,}"
    if low:
        return f"{symbol}{int(low):,}"
    return ""


def scrape(category: str, title: str,
           actor_id: str, days_posted: int = 7,
           jobs_per_category: int = 50,
           run_timeout: int = 120,
           location: str = "",
           country: str = "",
           work_modes=("remote",),
           allow_fallback: bool = True) -> list[dict]:
    """One search per role title, same signature as the other scrapers.

    `location`, `country` and `work_modes` are accepted and ignored:
    every row on these boards is remote by definition, and reach is
    judged later from the location field by `location_scope`.
    """
    payload = {
        "searchTerms":      [title],
        "maxItems":         jobs_per_category,
        "postedWithinDays": days_posted,
        "includeDescription": True,
    }
    try:
        raw = call_actor(actor_id, payload, f"RemoteBoards/{category}",
                         run_timeout)
    except Exception as exc:
        # Allowed to fail. The other sources carry the run.
        logger.warning("Remote boards failed for %s: %s", category, exc)
        return []

    jobs: list[dict] = []
    for row in raw or []:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        board = (row.get("source_board") or "").strip().lower()
        jobs.append({
            "cat":      category,
            "title":    row.get("title") or "",
            "company":  row.get("company") or "",
            "location": row.get("location") or "",
            "platform": _BOARDS.get(board, board or "Remote board"),
            "date":     (row.get("posted_at") or "")[:10],
            "url":      url,
            "salary":   _salary(row),
            "description": row.get("description")
                           or row.get("description_snippet") or "",
            # Not inference. These boards carry nothing else.
            "work_mode": "remote",
        })
    return jobs[:jobs_per_category]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd job_hunt && python -m pytest tests/test_remote_boards.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add job_hunt/src/scrapers/remote_boards.py job_hunt/tests/test_remote_boards.py
git commit -m "feat: remote job boards scraper, allowed to fail"
```

---

### Task 8: Register the fourth source

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Modify: `job_hunt/config.yaml`
- Test: `job_hunt/tests/test_run_core_steps.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_run_core_steps.py`:

```python
def test_remote_boards_is_a_source():
    steps = plan_steps(["Data Analyst"])
    assert "Remote boards" in {s["source"] for s in steps}


def test_remote_boards_gets_no_local_lane():
    """A borderless board has no local; asking it for Yerevan is noise."""
    steps = plan_steps(["Data Analyst"], local=True)
    local = {s["source"] for s in steps if s["lane"] == "local"}
    assert "Remote boards" not in local


def test_a_source_can_be_switched_off_in_config():
    from src.run_core import SOURCES
    only_indeed = tuple(s for s in SOURCES if s[0] == "Indeed")
    steps = plan_steps(["Data Analyst"], sources=only_indeed)
    assert {s["source"] for s in steps} == {"Indeed"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd job_hunt && python -m pytest tests/test_run_core_steps.py -k remote_boards -v`
Expected: FAIL — "Remote boards" not in sources.

- [ ] **Step 3: Add the source**

In `job_hunt/src/run_core.py`, extend `SOURCES` and the scraper map:

```python
SOURCES = (
    ("Indeed",        "indeed_actor",        "kaix~indeed-scraper"),
    ("LinkedIn",      "linkedin_actor",      "valig~linkedin-jobs-scraper"),
    ("Remote boards", "remote_boards_actor",
     "flash_scraper~remote-job-aggregator"),
)

# Sources with no meaningful local lane. A borderless board has no
# "near Yerevan" to search — asking costs money and returns noise.
_WORLDWIDE_ONLY = ("Remote boards",)


def _default_scrapers() -> dict:
    from .scrapers import indeed, linkedin, remote_boards
    return {"Indeed": indeed.scrape,
            "LinkedIn": linkedin.scrape,
            "Remote boards": remote_boards.scrape}
```

- [ ] **Step 4: Skip the local lane for worldwide-only sources**

In `job_hunt/src/run_core.py`, replace the list comprehension in `plan_steps` with:

```python
    steps = [{"source": name, "role": title, "lane": lane,
              "state": "pending", "found": 0}
             for title in titles
             for lane in lanes
             for name, _, _ in sources
             if not (lane == "local" and name in _WORLDWIDE_ONLY)]
```

- [ ] **Step 5: Add the actor id to config**

In `job_hunt/config.yaml`, under `apify:`, add:

```yaml
  remote_boards_actor: "flash_scraper~remote-job-aggregator"
```

- [ ] **Step 6: Run tests**

Run: `cd job_hunt && python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add job_hunt/src/run_core.py job_hunt/config.yaml job_hunt/tests/test_run_core_steps.py
git commit -m "feat: register remote boards as the fourth source"
```

---

### Task 9: Schema migration v6

The new sources supply a country code and a reach field that today have nowhere to live.

**Files:**
- Modify: `job_hunt/src/store/schema.py`
- Modify: `job_hunt/src/store/ingest.py`
- Test: `job_hunt/tests/test_store_migration.py`

- [ ] **Step 1: Write the failing test**

Add to `job_hunt/tests/test_store_migration.py`:

```python
def test_v6_adds_country_and_scope(v5_database):
    from src.store.schema import ensure_schema
    ensure_schema(v5_database)
    cols = {row[1] for row in v5_database.execute("PRAGMA table_info(role)")}
    assert {"country", "location_scope", "source_board"} <= cols


def test_v6_defaults_are_null_on_existing_rows(v5_database):
    from src.store.schema import ensure_schema
    ensure_schema(v5_database)
    row = v5_database.execute(
        "SELECT country, location_scope FROM role LIMIT 1").fetchone()
    assert row is None or (row[0] is None and row[1] is None)
```

If no `v5_database` fixture exists, build it the way the existing tests
in `test_store_migration.py` build their older-version fixtures — do not
invent a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd job_hunt && python -m pytest tests/test_store_migration.py -k v6 -v`
Expected: FAIL — column `country` does not exist.

- [ ] **Step 3: Add the migration**

In `job_hunt/src/store/schema.py`, add to `_MIGRATIONS`:

```python
    6: (
        # kaix supplies a structured country code, so Indeed rows never
        # need `location_country`'s ambiguity cases ("Chennai, IN" vs
        # "Gary, IN", which both stay silent).
        ("role", "country", "ALTER TABLE role ADD COLUMN country TEXT"),
        # What the remote boards publish about reach: open / closed /
        # unknown for this user. Null on every pre-existing row.
        ("role", "location_scope",
         "ALTER TABLE role ADD COLUMN location_scope TEXT"),
        # Which board a remote-board row came from, so the card can say.
        ("role", "source_board",
         "ALTER TABLE role ADD COLUMN source_board TEXT"),
    ),
```

- [ ] **Step 4: Add the columns to the CREATE TABLE**

In `job_hunt/src/store/schema.py`, inside `CREATE TABLE IF NOT EXISTS role`, add after the `work_mode TEXT` line:

```sql
    country              TEXT,
    location_scope       TEXT,
    source_board         TEXT,
```

- [ ] **Step 5: Persist the new fields**

In `job_hunt/src/store/ingest.py`, find the INSERT that writes a role and add the three columns to both the column list and the values, reading `job.get("country")`, `job.get("location_scope")` and `job.get("source_board")`. Follow the existing style in that function exactly — if it builds a dict of columns, add three keys; if it lists columns and `?` placeholders, add three of each.

- [ ] **Step 6: Run tests**

Run: `cd job_hunt && python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add job_hunt/src/store/schema.py job_hunt/src/store/ingest.py job_hunt/tests/test_store_migration.py
git commit -m "feat: schema v6 - country, location_scope, source_board"
```

---

### Task 10: Live smoke run

Every earlier task is unit-tested against fixtures. This is the first time the real actors run end to end.

**Files:** none — this is a verification task.

- [ ] **Step 1: Run a real scrape**

```bash
python main.py --serve
```

Open `http://localhost:5000`, start a run, and watch `/searching/<id>`.

- [ ] **Step 2: Check the step list**

Expected in the progress panel:
- No lane beginning `probe`.
- One `mode remote` lane per role (and `mode hybrid` if the profile ticks hybrid).
- `Remote boards` appears with a `worldwide` lane and **no** `local` lane.

- [ ] **Step 3: Check the numbers**

```bash
python - <<'PY'
import sqlite3
c = sqlite3.connect('job_hunt/job_hunt.db')
run = c.execute("SELECT id FROM run ORDER BY id DESC LIMIT 1").fetchone()[0]
print("platform / count / has work_mode:")
for row in c.execute("""SELECT platform, COUNT(*),
                          SUM(CASE WHEN work_mode IS NULL THEN 0 ELSE 1 END)
                        FROM role WHERE last_seen_run_id = ?
                        GROUP BY platform""", (run,)):
    print("  ", row)
print("\nany off-target titles still stored?")
for row in c.execute("""SELECT title FROM role WHERE last_seen_run_id = ?
                        LIMIT 40""", (run,)):
    print("  ", row[0])
PY
```

Expected: every title is a data role. Indeed rows carry a `work_mode`
from `workArrangement.locationType` rather than all reading "remote".
Remote-board rows are present.

- [ ] **Step 4: Record the real numbers**

Append a short "Live results" section to
`docs/superpowers/specs/2026-08-27-search-lanes-and-store-cleanup-design.md`
with the actual counts: rows per source, off-target rejected, and how
many remote-board rows scored `location_scope == "open"`. The spec's
residuals name the 22% figure as measured on one 50-row run — this is
where it gets replaced with a real number, and where Ship 8's scope gets
decided.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-27-search-lanes-and-store-cleanup-design.md
git commit -m "docs: live results from the first Ship 7 run"
```

---

## What this plan does not cover

Ship 8, from the same spec:

- Part 6 — the five eligibility rules from the hand-reviewed postings
  (drop `"work from home"`, add `"(from anywhere)"`, the US-only closed
  list, never trusting a location field of "Remote").
- Part 7 — reading valig's `contractType`, `experienceLevel`,
  `applicationsCount` and `id`, which are already paid for and discarded.
- Part 8 — widening the work-mode phrase list (66 recoverable misses).
- Part 9 — the one-off store cleanup, which re-runs every improved rule
  over the existing 800 rows and soft-drops what cannot apply.

Part 9 in particular must not start before parts 6–8 land: it decides
what to delete using exactly those rules, and running it early would drop
roles the widened rules would have rescued.
