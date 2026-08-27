"""Tests for run_core's search titles and step planning — both pure."""
from src.run_core import SOURCES, plan_steps, search_titles


def _resume(label, roles):
    return {"id": 1, "label": label,
            "target_roles": [{"title": t} for t in roles]}


def test_titles_come_from_the_resumes_target_roles():
    assert search_titles([_resume("bi", ["BI Developer"])]) == ["BI Developer"]


def test_titles_from_several_resumes_are_combined_in_order():
    resumes = [_resume("bi", ["BI Developer"]), _resume("de", ["Data Engineer"])]
    assert search_titles(resumes) == ["BI Developer", "Data Engineer"]


def test_the_same_title_twice_is_searched_once():
    resumes = [_resume("bi", ["BI Developer"]),
               _resume("other", ["bi developer", "Data Analyst"])]
    assert search_titles(resumes) == ["BI Developer", "Data Analyst"]


def test_a_resume_with_no_target_roles_contributes_nothing():
    assert search_titles([_resume("empty", [])]) == []


def test_every_title_is_planned_against_every_source():
    steps = plan_steps(["BI Developer", "Data Analyst"])

    assert len(steps) == len(SOURCES) * 2
    assert {s["source"] for s in steps} == {name for name, _, _ in SOURCES}


def test_steps_start_pending_with_nothing_found():
    steps = plan_steps(["BI Developer"])
    assert all(s["state"] == "pending" and s["found"] == 0 for s in steps)


def test_steps_are_grouped_by_role_so_the_screen_reads_in_order():
    """A reader follows one role across both sources, then the next role."""
    steps = plan_steps(["BI Developer", "Data Analyst"])
    assert [s["role"] for s in steps] == [
        "BI Developer", "BI Developer", "Data Analyst", "Data Analyst"]


def test_a_location_doubles_the_plan_with_a_local_lane():
    steps = plan_steps(["BI Developer"], local=True)
    assert len(steps) == 4
    assert [s["lane"] for s in steps] == ["worldwide", "worldwide",
                                          "local", "local"]


def test_without_a_location_the_plan_is_worldwide_only():
    steps = plan_steps(["BI Developer"])
    assert len(steps) == 2
    assert all(s["lane"] == "worldwide" for s in steps)


def test_plan_steps_emits_no_probe_lanes():
    """Probes never filtered anything - valig has no `remote` parameter."""
    steps = plan_steps(["Data Analyst"], local=True)
    lanes = {step["lane"] for step in steps}
    assert lanes == {"worldwide", "local"}
    assert not any(step["lane"].startswith("probe") for step in steps)


def test_plan_steps_takes_no_probes_argument():
    import inspect
    assert "probes" not in inspect.signature(plan_steps).parameters


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


def test_no_mode_lanes_when_linkedin_is_not_a_source():
    indeed_only = (("Indeed", "indeed_actor", "valig~indeed-jobs-scraper"),)
    steps = plan_steps(["Data Analyst"], sources=indeed_only,
                       mode_lanes=("remote", "hybrid"))
    assert not any(s["lane"].startswith("mode") for s in steps)
