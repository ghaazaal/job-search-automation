# Badge Probes + Eligibility Tiers (Ship 6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unmangle descriptions at the source, recover LinkedIn's workplace badge via filtered-search set membership, and make every card honest about whether eligibility was verified — verified outranks unverified.

**Architecture:** `extract_description` prefers HTML-shaped fields (tag-flattening inserts separators; the actor's plain field is pre-fused). Two probe steps per role (LinkedIn hybrid- and onsite-filtered searches) contribute a `url → badge` map; the Ship 5 ladder consumes the badge as the mode when text says nothing, and badge-vs-text conflicts claim nothing. A per-job `eligibility_verified` flag (geo verdict `eligible`, or the job's parsed country / profile city matching the user) flows scorer → reason sentence → schema v5 column → company ranking.

**Tech Stack:** Python 3, pytest, PyYAML, sqlite forward-only migrations. No new dependencies, no actor switch.

**Spec:** `docs/superpowers/specs/2026-08-26-badge-probe-eligibility-tiers-design.md`

---

## Read this before Task 1

- Working directory: `job_hunt/`; pytest as `python -m pytest`. Baseline at branch start: **632 passed**.
- Full suite green after every task; signature changes are keyword-with-default.
- House style: fail-first TDD, docstrings state the defended rule, mutation-check fixes.
- **Never render a score; never fabricate.** The verified tier is worded, never numbered. Badge evidence is set-membership fact; a probe miss is silence.
- The current `run_core.execute` ladder (read it first — lines ~180–231) runs: text `work_mode` → stamp → mismatch branch (remote-token veto → profile-city rung → `location_country` → drop/flag). Task 6 restructures the mode SOURCE and adds per-job local evidence; the rung ORDER and drop boundary must not change.
- `compose_reason`'s absence clause ("no visa or clearance limits found", `src/scoring/reason.py:57`) is asserted by NO test (verified by grep at planning time) — but re-grep before Task 4 and update any assertion that appeared since.

### File map

| File | Action |
|---|---|
| `job_hunt/src/scrapers/base.py` | Modify — HTML-first key order + dict unwrap |
| `job_hunt/tests/test_scrapers.py` | Modify — unmangling tests |
| `job_hunt/vocabulary.yaml` | Modify — JD-header idiom phrases |
| `job_hunt/tests/test_vocabulary.py` | No change expected (guards hold) |
| `job_hunt/src/store/schema.py` | Modify — v5: `role.eligibility_verified` |
| `job_hunt/src/store/ingest.py` | Modify — write the flag |
| `job_hunt/src/store/queries.py` | Modify — expose flag; verified-first company sort |
| `job_hunt/tests/test_store_migration.py`, `test_store_ingest.py`, `test_store_queries.py` | Modify — v5 + ranking tests |
| `job_hunt/src/scoring/scorer.py` | Modify — `_constraints` returns the geo verdict; `local_evidence` param; `eligibility_verified` in evidence |
| `job_hunt/src/scoring/reason.py` | Modify — tier-aware absence clause (deliberate, spec-approved) |
| `job_hunt/tests/test_eligibility_tier.py` | Create |
| `job_hunt/tests/test_reason.py` | Modify — clause expectations |
| `job_hunt/src/run_core.py` | Modify — probe steps, badge map, local evidence, `RunResult.badge_hits` |
| `job_hunt/tests/test_run_core_steps.py`, `test_run_core_execute.py` | Modify — probe + badge + verified tests |
| `job_hunt/src/searching_page.py` | Modify — generalize lane label |
| `job_hunt/src/main.py` → `job_hunt/main.py` | Modify — generalize lane suffix in `_announce` |
| `job_hunt/tests/test_searching_page.py`, `test_pipeline_announce.py` | Modify — label tests |
| `job_hunt/tests/test_map_page.py` | No change expected |

---

### Task 1: HTML-first descriptions

**Files:**
- Modify: `job_hunt/src/scrapers/base.py`
- Test: `job_hunt/tests/test_scrapers.py`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_scrapers.py`:

```python
@pytest.mark.parametrize("module", [indeed, linkedin])
def test_html_is_preferred_over_a_prefused_plain_field(module, monkeypatch):
    """valig's plain `description` arrives pre-flattened with NO
    separators ("…RemoteTravel Required…"), defeating word-boundary
    matching. The html sibling has real structure, and tag-flattening
    inserts a space per tag — so html wins whenever both exist."""
    item = {**_MINIMAL,
            "description": "Location: RemoteTravel Required: 2-5 Weeks",
            "descriptionHtml": "<p>Location: Remote</p>"
                               "<p>Travel Required: 2-5 Weeks</p>"}
    job = _scrape(module, monkeypatch, item)
    assert "RemoteTravel" not in job["description"]
    assert "Location: Remote" in job["description"]


def test_indeed_nested_dict_prefers_html_over_text(monkeypatch):
    item = {**_MINIMAL,
            "description": {"text": "runtogetherText here",
                            "html": "<p>run</p><p>together</p><p>Text here</p>"}}
    job = _scrape(indeed, monkeypatch, item)
    assert "runtogetherText" not in job["description"]
    assert "run together Text here" == job["description"]
```

- [ ] **Step 2: Run to verify they fail.** `python -m pytest tests/test_scrapers.py -v -k "prefused or nested_dict_prefers"` — both FAIL (plain field currently wins).

- [ ] **Step 3: Implement.** In `src/scrapers/base.py`:
1. Reorder: `_DESCRIPTION_KEYS = ("descriptionHtml", "description", "descriptionText", "jobDescription", "jobDescriptionText", "snippet")` — update the comment above it: html-shaped fields first, because the actors' plain fields arrive pre-flattened without separators while tag-flattening inserts a space per tag.
2. In the dict-unwrap, swap the preference: `raw = raw.get("html") or raw.get("text")` (adjust its comment likewise).

- [ ] **Step 4: Verify.** `python -m pytest tests/test_scrapers.py -v` — ALL pass. Watch `test_indeed_description_under_the_real_nested_shape`: its fixture carries both `text` and `html`; with html now preferred, its content assertion must still hold — if the trimmed html in that fixture lacks the asserted phrase, extend the FIXTURE's html to carry it (flag this in your report; do not weaken the assertion).

- [ ] **Step 5: Full suite + commit.** `python -m pytest -q` (expect 634).

```bash
git add src/scrapers/base.py tests/test_scrapers.py
git commit -m "fix: html-shaped descriptions win — the plain field arrives pre-fused"
```

---

### Task 2: JD-header idiom phrases

**Files:**
- Modify: `job_hunt/vocabulary.yaml`
- Test: `job_hunt/tests/test_work_mode.py`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_work_mode.py`:

```python
def test_jd_header_idioms_are_detected():
    """'Work setup & shift: Onsite' is how BPO postings state the mode —
    only matchable now that descriptions arrive unmangled."""
    import yaml
    cfg = yaml.safe_load(open("vocabulary.yaml", encoding="utf-8"))["work_mode"]
    assert work_mode("work setup & shift: onsite. why join us?", cfg) == "onsite"
    assert work_mode("work setup: hybrid, 3 days on site.", cfg) == "hybrid"
    assert work_mode("work setup & shift: remote, night shift.", cfg) == "remote"
```

- [ ] **Step 2: Run to verify it fails.** All three assertions fail (phrases unknown).

- [ ] **Step 3: Implement.** In `vocabulary.yaml`'s `work_mode` section add, each with the entry style already in the file:
- to `remote_phrases`: `"work setup & shift: remote"`, `"work setup: remote"`
- to `hybrid_phrases`: `"work setup & shift: hybrid"`, `"work setup: hybrid"`
- to `onsite_phrases`: `"work setup & shift: onsite"`, `"work setup: onsite"`

(Note: `work_mode("work setup: hybrid, 3 days on site.")` must yield "hybrid", not a conflict — "on site" with a space is not an onsite phrase; verify, and if any new phrase creates a cross-category conflict in these test bodies, report rather than tweak silently.)

- [ ] **Step 4: Verify + commit.** `python -m pytest tests/test_work_mode.py tests/test_vocabulary.py -q` then full suite (expect 635).

```bash
git add vocabulary.yaml tests/test_work_mode.py
git commit -m "feat: the mode vocabulary learns the JD-header idiom"
```

---

### Task 3: schema v5 — `role.eligibility_verified`

**Files:**
- Modify: `job_hunt/src/store/schema.py`, `job_hunt/src/store/ingest.py`, `job_hunt/src/store/queries.py`
- Test: `job_hunt/tests/test_store_migration.py`, `job_hunt/tests/test_store_ingest.py`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_store_migration.py`:

```python
def test_version_five_adds_eligibility_verified_defaulting_honest(tmp_path):
    """Old rows were scored before verification existed — 0, never a
    guessed backfill."""
    conn = _v1_database(tmp_path / "v1.db")
    init_db(conn)
    assert "eligibility_verified" in _columns(conn, "role")
    assert conn.execute("SELECT eligibility_verified FROM role"
                        ).fetchone()["eligibility_verified"] == 0
```

Append to `tests/test_store_ingest.py` (follow its fixture style, as the Ship 5 v4 tests did): a round-trip test writing a job dict with `"eligibility_verified": True` and reading back 1, and one with the key absent reading back 0.

- [ ] **Step 2: Run to verify they fail** (`no such column`).

- [ ] **Step 3: Implement.**
1. `schema.py`: `SCHEMA_VERSION = 5`; `_DDL` role table gains `    eligibility_verified INTEGER NOT NULL DEFAULT 0,` after `work_mode`; `_MIGRATIONS[5] = (("role", "eligibility_verified", "ALTER TABLE role ADD COLUMN eligibility_verified INTEGER NOT NULL DEFAULT 0"),)`.
2. `ingest.py` `_upsert_role`: `1 if job.get("eligibility_verified") else 0` added to the `values` tuple right after the `work_mode` element, with the matching column in BOTH UPDATE and INSERT and one more placeholder each (count them; verify with a distinct-values read-back as Ship 5 did).
3. `queries.py` `_role_view`: add `"eligibility_verified": bool(row["eligibility_verified"]),` after `"work_mode"`.

- [ ] **Step 4: Verify + commit.** Store/migration/queries/map-routing suites, then full (expect ~638).

```bash
git add src/store/schema.py src/store/ingest.py src/store/queries.py tests/test_store_migration.py tests/test_store_ingest.py
git commit -m "feat: roles remember whether eligibility was verified"
```

---

### Task 4: scorer + reason — the tier is computed and worded

**Files:**
- Modify: `job_hunt/src/scoring/scorer.py`, `job_hunt/src/scoring/reason.py`
- Create: `job_hunt/tests/test_eligibility_tier.py`
- Possibly modify: `job_hunt/tests/test_reason.py` (re-grep for the old literal first)

- [ ] **Step 1: Write the failing tests.** Create `tests/test_eligibility_tier.py`:

```python
"""The verified tier: positive evidence the user can take the job.

Verified = geo verdict `eligible` OR run_core-supplied local evidence
(job's parsed country / profile city == the user's). Everything else is
unverified and says so — unchecked must not masquerade as fine.
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
    return Scorer(_CONFIG, _VOCAB, user_country="am", user_modes=("remote",))


def test_an_eligible_geo_verdict_verifies():
    e = _scorer().score_job(
        "BI Developer", _JD + " Open to candidates in EMEA.", _RESUME)
    assert e["eligibility_verified"] is True
    assert "open to your location" in e["reason"]
    assert "not verified" not in e["reason"]


def test_local_evidence_verifies():
    e = _scorer().score_job("BI Developer", _JD, _RESUME,
                            local_evidence=True)
    assert e["eligibility_verified"] is True
    assert "open to your location" in e["reason"]


def test_no_evidence_says_so():
    e = _scorer().score_job("BI Developer", _JD, _RESUME)
    assert e["eligibility_verified"] is False
    assert "location eligibility not verified" in e["reason"]
    assert "no visa or clearance limits found" not in e["reason"]


def test_a_restriction_is_not_reworded():
    """A fired penalty already carries the story — the absence clause
    never appears alongside it."""
    e = _scorer().score_job(
        "BI Developer", _JD + " Must be based in the UK.", _RESUME)
    assert e["eligibility_verified"] is False
    assert "restricted to UK" in e["reason"]
    assert "not verified" not in e["reason"]


def test_no_description_claims_no_tier():
    """Rule 3 territory: nothing was compared, so the reduced-confidence
    sentence stands alone."""
    e = _scorer().score_job("BI Developer", "", _RESUME)
    assert "not verified" not in e["reason"]


def test_best_match_passes_local_evidence_through():
    e = _scorer().best_match("BI Developer", _JD, [_RESUME],
                             local_evidence=True)
    assert e["eligibility_verified"] is True
```

- [ ] **Step 2: Run to verify they fail** (`unexpected keyword argument 'local_evidence'`). Also `grep -rn "no visa or clearance limits found" tests/` — update any assertion found to the new wording (none existed at planning time).

- [ ] **Step 3: Implement.**

`scorer.py`:
1. `_constraints` returns a triple — change its return to `(penalty, fired, verdict)` where `verdict` is the geo_verdict string already computed there ("eligible"/"restricted"/"excluded"/"unknown"); update its docstring/signature annotation.
2. `score_job` gains `local_evidence: bool = False` (after `mode_mismatch`); unpacks the triple; evidence gains, next to the other internal fields:

```python
            # Internal + stored: positive evidence the user can take the
            # job. Never rendered as a number — reason.py words it.
            "eligibility_verified": bool(local_evidence
                                         or geo_verdict == "eligible"),
```

3. `best_match` gains and forwards `local_evidence: bool = False`.

`reason.py` — replace the absence branch (currently `elif matched: clauses.append("no visa or clearance limits found")`) with:

```python
    elif matched and evidence.get("eligibility_verified"):
        clauses.append("open to your location")
    elif matched:
        # Nothing was verifiable either way — unchecked must not
        # masquerade as fine ("no limits found" used to imply exactly
        # that).
        clauses.append("location eligibility not verified")
```

- [ ] **Step 4: Verify.** `python -m pytest tests/test_eligibility_tier.py tests/test_reason.py tests/test_scorer.py tests/test_scorer_evidence.py tests/test_scorer_geo.py tests/test_scorer_mode.py -v` — all pass (fix any old-wording assertions per the grep, flagging each).

- [ ] **Step 5: Full suite + commit** (expect ~644 — plus any test_reason updates).

```bash
git add src/scoring/scorer.py src/scoring/reason.py tests/test_eligibility_tier.py tests/test_reason.py
git commit -m "feat: cards say whether eligibility was verified, never imply it"
```

---

### Task 5: probe steps — planned, scraped, labeled

**Files:**
- Modify: `job_hunt/src/run_core.py`, `job_hunt/src/searching_page.py`, `job_hunt/main.py`
- Test: `job_hunt/tests/test_run_core_steps.py`, `job_hunt/tests/test_run_core_execute.py`, `job_hunt/tests/test_searching_page.py`, `job_hunt/tests/test_pipeline_announce.py`

- [ ] **Step 1: Write the failing tests.**

`tests/test_run_core_steps.py`:

```python
def test_probes_append_two_linkedin_steps_per_role():
    steps = plan_steps(["BI Developer"], probes=True)
    lanes = [(s["source"], s["lane"]) for s in steps]
    assert lanes == [("Indeed", "worldwide"), ("LinkedIn", "worldwide"),
                     ("LinkedIn", "probe hybrid"),
                     ("LinkedIn", "probe onsite")]


def test_probes_require_linkedin_to_be_enabled():
    indeed_only = tuple(s for s in SOURCES if s[0] == "Indeed")
    steps = plan_steps(["BI Developer"], sources=indeed_only, probes=True)
    assert all(not s["lane"].startswith("probe") for s in steps)
```

(Import `SOURCES` alongside `plan_steps` per the file's import style.)

`tests/test_run_core_execute.py`:

```python
def test_probe_results_are_evidence_not_candidates(conn, user, resume):
    """Probe jobs are never scored or stored; their step still reports
    a found count."""
    probe_job = _job("https://x/probe1")

    def spy(category, title, actor_id, *args, **kwargs):
        modes = tuple(kwargs.get("work_modes") or ())
        if modes in (("hybrid",), ("onsite",)):
            return [probe_job]
        return []

    seen = []
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     on_progress=seen.append,
                     scrapers={"Indeed": spy, "LinkedIn": spy})
    assert result.kept == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM role").fetchone()["n"] == 0
    probe_steps = [s for s in seen[-1]["steps"]
                   if s["lane"].startswith("probe")]
    assert [s["found"] for s in probe_steps] == [1, 1]
    assert result.scraped == 0      # probes don't inflate the count


def test_probe_calls_are_worldwide_and_single_mode(conn, user, resume):
    calls = []

    def spy(category, title, actor_id, *args, **kwargs):
        calls.append((kwargs.get("location"),
                      tuple(kwargs.get("work_modes") or ())))
        return []

    run_id = start_run(conn, user)
    execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
            scrapers={"Indeed": spy, "LinkedIn": spy})
    probe_calls = [c for c in calls if c[1] in (("hybrid",), ("onsite",))]
    assert len(probe_calls) == 2
    assert all(loc == "" for loc, _ in probe_calls)
```

`tests/test_searching_page.py`:

```python
def test_any_non_worldwide_lane_is_labeled():
    html = render(9)
    assert "s.lane !== 'worldwide'" in html
```

`tests/test_pipeline_announce.py`: a test that a step with `lane: "probe hybrid"` prints with `· probe hybrid` in its line (follow the file's `_announce_step` conventions; the worldwide line stays unsuffixed).

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.**

`run_core.py` `plan_steps` — new keyword `probes: bool = False`; after the existing comprehension's steps are built, append per title (only when `probes` and a source named "LinkedIn" survives `sources`):

```python
    if probes and any(name == "LinkedIn" for name, _, _ in sources):
        for title in titles:
            for lane in ("probe hybrid", "probe onsite"):
                steps.append({"source": "LinkedIn", "role": title,
                              "lane": lane, "state": "pending", "found": 0})
```

(Restructure the function body from a single return-comprehension into build-then-return; keep the docstring, extend it: probes are evidence-gathering searches, LinkedIn-only, appended after the real lanes.)

`execute`: `steps = plan_steps(titles, sources=sources, local=..., probes=True)`. In the scrape loop, before the existing lane-args block:

```python
        if step["lane"].startswith("probe"):
            probe_mode = step["lane"].split(" ", 1)[1]      # hybrid|onsite
            try:
                found = scrapers[name](
                    step["role"], step["role"],
                    apify_cfg.get(actor_key, actor_default),
                    days_posted, jobs_per_cat, run_timeout,
                    location="", country=country,
                    work_modes=(probe_mode,))
            except Exception as exc:
                logger.warning("%s/%s failed: %s", name, step["role"], exc)
                step["state"] = "failed"
                step["found"] = 0
            else:
                step["state"] = "done"
                step["found"] = len(found)
                for job in found:
                    probe_badges.setdefault(
                        normalize_url(job.get("url") or ""), probe_mode)
            report("scraping")
            continue
```

with `probe_badges: dict[str, str] = {}` initialized next to `all_scraped`, and `normalize_url` added to the lazy `from .tracker.dedup import dedupe` import. Probe finds do NOT touch `all_scraped`/`scraped_total`.

`searching_page.py`: the name-span ternary becomes `${{s.lane && s.lane !== 'worldwide' ? ' · ' + esc(s.lane) : ''}}`.

`main.py` `_announce_step` (or equivalent): the printed suffix generalizes — any lane other than `"worldwide"` prints `· {lane}` (the dedup key already includes the lane from Ship 5).

- [ ] **Step 4: Verify.** The four named files, then full suite. NOTE: `test_the_first_event_already_lists_every_step` counts steps — with probes it becomes 6 for one role (2 worldwide + 2 local + 2 probes); update it with the comment `# two lanes + two probes`. Likewise `test_no_location_means_no_local_lane` becomes 4. `test_the_local_lane_searches_the_actual_place_with_all_modes`'s spy sees probe calls too — its filter on `("remote","hybrid","onsite")` still isolates the local calls; verify unchanged. Flag every existing assertion you had to update.

- [ ] **Step 5: Commit.**

```bash
git add src/run_core.py src/searching_page.py main.py tests/test_run_core_steps.py tests/test_run_core_execute.py tests/test_searching_page.py tests/test_pipeline_announce.py
git commit -m "feat: probe searches recover the badge as set membership"
```

---

### Task 6: badge into the ladder; verified evidence to the scorer

**Files:**
- Modify: `job_hunt/src/run_core.py`
- Test: `job_hunt/tests/test_run_core_execute.py`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_run_core_execute.py`:

```python
def _with_probe(probe_url, probe_mode, jobs):
    """Scrapers where the probe lane returns a job at probe_url."""
    def spy(category, title, actor_id, *args, **kwargs):
        modes = tuple(kwargs.get("work_modes") or ())
        if modes == (probe_mode,):
            return [_job(probe_url)]
        if modes in (("hybrid",), ("onsite",)):
            return []
        return list(jobs)
    return {"Indeed": spy, "LinkedIn": spy}


def test_the_salford_case_a_badge_hybrid_foreign_job_is_dropped(conn, user, resume):
    """The ship's reason to exist: badge-only hybrid in another country.
    Text says nothing; probe membership says hybrid; UK != ca -> drop."""
    job = _job("https://x/salford")
    job["location"] = "Salford, England, United Kingdom"
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_with_probe("https://x/salford", "hybrid",
                                          [job]))
    assert result.dropped == 1
    assert result.kept == 0
    assert result.badge_hits == 1


def test_a_badge_conflicting_with_text_claims_nothing(conn, user, resume):
    """LinkedIn badges mislabel ~19% of the time (our own measurement) —
    badge says hybrid, text says fully remote: no claim, job kept."""
    job = _job("https://x/conflict")
    job["location"] = "Salford, England, United Kingdom"
    job["description"] += " This is a fully remote role."
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_with_probe("https://x/conflict", "hybrid",
                                          [job]))
    assert result.dropped == 0
    assert result.kept == 1
    assert result.scored_jobs[0].get("work_mode") is None


def test_a_badge_hybrid_local_job_is_kept_clean(conn, user, resume):
    job = _job("https://x/localbadge")
    job["location"] = "Toronto, Ontario, Canada"
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_with_probe("https://x/localbadge", "hybrid",
                                          [job]))
    assert result.kept == 1
    evidence = result.scored_jobs[0]
    assert evidence["work_mode"] == "hybrid"
    assert "says hybrid" not in evidence["reason"]


def test_local_country_verifies_eligibility(conn, user, resume):
    job = _job("https://x/verified")           # Toronto, ON default? use full form
    job["location"] = "Toronto, Ontario, Canada"
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[job]))
    evidence = result.scored_jobs[0]
    assert evidence["eligibility_verified"] is True
    assert "open to your location" in evidence["reason"]
    assert conn.execute(
        "SELECT eligibility_verified FROM role WHERE url = ?",
        ("https://x/verified",)).fetchone()["eligibility_verified"] == 1


def test_an_unplaceable_job_is_stored_unverified(conn, user, resume):
    run_id = start_run(conn, user)
    result = execute(conn, user, run_id, _CONFIG, [resume], _PROFILE,
                     scrapers=_scrapers(indeed_jobs=[_job("https://x/unv")]))
    evidence = result.scored_jobs[0]
    assert evidence["eligibility_verified"] is False
    assert "location eligibility not verified" in evidence["reason"]
    assert "_local_ok" not in evidence
```

(`_job`'s default location is "Toronto, ON" — the profile-CITY rung: decide the expectation for the unverified test consciously: "Toronto, ON" MATCHES the profile city, so use `_job` as-is only if you change its location; the test above must use a location with NO local/country/city match — `_job`'s default WILL match the city rung and verify. Set `job["location"] = "Remote"` explicitly in the unverified test. Re-derive before running; fix the test body, not the rules.)

- [ ] **Step 2: Run to verify they fail** (no `badge_hits`, wrong verdicts).

- [ ] **Step 3: Implement.** In `run_core.py`:

1. `RunResult` gains `badge_hits: int = 0`.
2. In the ladder loop, replace the mode computation and add local evidence (rung order unchanged):

```python
    badge_hits = 0
    kept_jobs = []
    for job in new_jobs:
        text_mode = work_mode(f"{job.get('title') or ''}\n"
                              f"{job.get('description') or ''}", mode_cfg)
        badge = probe_badges.get(normalize_url(job.get("url") or ""))
        if text_mode and badge and text_mode != badge:
            # LinkedIn badges mislabel ~19% of the time (our own
            # measurement) and text can lie too — disagreement claims
            # nothing, the same rule every other conflict follows.
            mode = None
        elif badge and not text_mode:
            mode = badge
            badge_hits += 1
        else:
            if badge and text_mode == badge:
                badge_hits += 1
            mode = text_mode
        if mode:
            job["work_mode"] = mode

        raw_location = (job.get("location") or "").strip().lower()
        place = location_country(job.get("location") or "", loc_cfg)
        local_ok = bool(
            (profile_city and has_term(profile_city, raw_location))
            or (place and user_country and place == user_country))
        if local_ok:
            job["_local_ok"] = True

        if mode and user_modes and mode not in user_modes:
            ...  # the existing rungs, unchanged in order:
                 # remote-token veto -> profile-city/local keep (now via
                 # local_ok) -> drop on foreign place -> flag on
                 # unplaceable
```

Concretely: the veto rung keeps its `has_term("remote", raw_location)` check (a vetoed job keeps `_local_ok` if set); the city rung becomes `if local_ok: kept_jobs.append(job); continue` (it now also covers place == user_country, which previously fell through to the bottom — same outcome, one rung); the drop and flag rungs are unchanged (`place` is already computed above — do not compute it twice).
3. Scoring loop pops the new transient and forwards it:

```python
        local_ok = job.pop("_local_ok", False)
        ...
        scorer.best_match(..., mode_mismatch=mode_mismatch,
                          local_evidence=local_ok)
```

4. `RunResult(...)` gains `badge_hits=badge_hits`.

- [ ] **Step 4: Verify.** `python -m pytest tests/test_run_core_execute.py -v` — every pre-existing ladder test must still pass; the Ship 5 rung tests (foreign drop, local hybrid, veto, Cincinnati rescue) are the regression net for the restructure. Then full suite.

- [ ] **Step 5: Mutation-check.** (1) Remove the conflict rule (badge wins over text) → the conflict test fails; restore. (2) Make `local_ok` ignore `place == user_country` → `test_local_country_verifies_eligibility` fails (city rung doesn't match "Toronto, Ontario, Canada"? it DOES — profile city "toronto" appears; so mutate BOTH city and country checks to False → the verified test fails); restore; report exactly what you mutated.

- [ ] **Step 6: Commit.**

```bash
git add src/run_core.py tests/test_run_core_execute.py
git commit -m "feat: the badge and local evidence reach the ladder and the scorer"
```

---

### Task 7: verified-first company ranking

**Files:**
- Modify: `job_hunt/src/store/queries.py`
- Test: `job_hunt/tests/test_store_queries.py`

- [ ] **Step 1: Write the failing test.** Append to `tests/test_store_queries.py` (follow its fixture style for inserting roles — read it first; it has helpers to insert companies/roles with scores):

```python
def test_verified_companies_outrank_unverified_within_a_section(conn):
    """A verified-eligible PARTIAL FIT beats an unverified STRONG FIT:
    a sure thing you can take outranks a maybe you might not."""
    # insert two companies in the same section:
    #   "Unverified Corp": one role, match_score 9, eligibility_verified 0
    #   "Verified Ltd":    one role, match_score 6, eligibility_verified 1
    # (use the file's existing insert helpers; both ACT_NOW is fine if
    #  shortlist_min <= 6, or both DISCOVER with shortlist_min high —
    #  same-state is the point)
    sections = map_sections(conn, 1, shortlist_min=5)
    names = [m["name"] for m in sections["new"]]
    assert names.index("Verified Ltd") < names.index("Unverified Corp")
```

Adapt the plumbing to the file's helpers; the contract is the ordering assertion with both companies in the SAME state.

- [ ] **Step 2: Run to verify it fails** (score orders them today).

- [ ] **Step 3: Implement.** In `queries.py` `_group`:

```python
        verified = max((1 if r["eligibility_verified"] else 0)
                       for r in group)
```

added next to `best`, kept on the map dict as `"_tier": verified`, and the sort key becomes:

```python
    maps.sort(key=lambda m: (0 if m["state"] == "ACT_NOW" else 1,
                             -m["_tier"], -m["_rank"], m["name"].lower()))
    for m in maps:
        del m["_rank"], m["_tier"]
```

(Company-level tier = best role's tier; the internal score still never leaves this module.)

- [ ] **Step 4: Verify + commit.** Queries/map suites then full.

```bash
git add src/store/queries.py tests/test_store_queries.py
git commit -m "feat: a verified sure thing outranks an unverified maybe"
```

---

### Task 8: full suite, live smoke

**Files:** none — verification only.

- [ ] **Step 1:** `python -m pytest -q` — everything passes; report the count.
- [ ] **Step 2:** Smoke the whole composition with injected scrapers (no Apify): run the Salford shape end-to-end via a small scratch script or the existing tests, then print one verified and one unverified stored reason from a scratch DB — confirm the sentences read exactly per spec.
- [ ] **Step 3:** `git status --short` clean.

---

## Self-review notes (done at planning time)

- **Spec coverage:** A → Tasks 1–2; B (probes as evidence, badge into ladder, conflicts claim nothing, counts, labels) → Tasks 5–6; C (column, sentence, ranking, migration) → Tasks 3, 4, 7; smoke → Task 8.
- **Placeholder scan:** Task 6 Step 3 point 2 shows the restructured head plus named unchanged rungs — the rung bodies exist verbatim in the current file the implementer must read first; the `...` marks preserved code, not TBD work, and the concrete rung-by-rung instruction follows it.
- **Type consistency:** `probe_badges: dict[str, str]` keyed by `normalize_url` (Tasks 5, 6); lane strings `"probe hybrid"`/`"probe onsite"` identical in Tasks 5 (plan/labels) and 6 (split on space); `local_evidence: bool = False` threaded `best_match → score_job` (Task 4) and supplied from `_local_ok` (Task 6); `eligibility_verified` key identical in scorer evidence (4), ingest (3), `_role_view` (3), ranking (7); `badge_hits` on `RunResult` (6).
- **Known assertion updates:** step-count tests in Task 5 Step 4 (6 and 4), the unverified-test location trap flagged inline in Task 6 Step 1.
