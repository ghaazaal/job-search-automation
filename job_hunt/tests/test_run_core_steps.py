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
    # Both lanes, because no single lane reaches every source any more:
    # Remote boards is worldwide-only and Indeed is local-only.
    steps = plan_steps(["BI Developer", "Data Analyst"], local=True)

    assert {s["source"] for s in steps} == {name for name, _, _ in SOURCES}
    for title in ("BI Developer", "Data Analyst"):
        planned = {s["source"] for s in steps if s["role"] == title}
        assert planned == {name for name, _, _ in SOURCES}


def test_steps_start_pending_with_nothing_found():
    steps = plan_steps(["BI Developer"])
    assert all(s["state"] == "pending" and s["found"] == 0 for s in steps)


def test_steps_are_grouped_by_role_so_the_screen_reads_in_order():
    """A reader follows one role across every source, then the next role."""
    steps = plan_steps(["BI Developer", "Data Analyst"])
    # Only Remote boards has a worldwide lane, and no local lane was
    # requested: one step per role.
    assert [s["role"] for s in steps] == ["BI Developer", "Data Analyst"]


def test_a_location_adds_a_local_lane():
    # Neither lane carries every source: Remote boards is worldwide-only,
    # LinkedIn local-only. 1 worldwide + 1 local = 2.
    steps = plan_steps(["BI Developer"], local=True)
    assert len(steps) == 2
    assert [s["lane"] for s in steps] == ["worldwide", "local"]


def test_without_a_location_the_plan_is_worldwide_only():
    # Remote boards is the only source with a worldwide lane; LinkedIn is
    # local-only, so with no location it drops out entirely.
    steps = plan_steps(["BI Developer"])
    assert len(steps) == 1
    assert all(s["lane"] == "worldwide" for s in steps)
    assert "LinkedIn" not in {s["source"] for s in steps}


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
    indeed_only = (("Indeed", "indeed_actor", "kaix~indeed-scraper"),)
    steps = plan_steps(["Data Analyst"], sources=indeed_only,
                       mode_lanes=("remote", "hybrid"))
    assert not any(s["lane"].startswith("mode") for s in steps)


def test_remote_boards_is_a_source():
    steps = plan_steps(["Data Analyst"])
    assert "Remote boards" in {s["source"] for s in steps}


def test_remote_boards_gets_no_local_lane():
    """A borderless board has no local; asking it for Yerevan is noise."""
    steps = plan_steps(["Data Analyst"], local=True)
    local = {s["source"] for s in steps if s["lane"] == "local"}
    assert "Remote boards" not in local


def test_plan_steps_only_plans_the_given_sources():
    """plan_steps' own `sources` filter — not the config.yaml gate, which
    execute() applies before calling plan_steps (see
    test_a_disabled_source_is_never_planned_or_called and
    test_a_multi_word_source_can_be_switched_off_in_config in
    test_run_core_execute.py for that path)."""
    only_linkedin = tuple(s for s in SOURCES if s[0] == "LinkedIn")
    # local=True because LinkedIn is local-only — see
    # test_linkedin_gets_no_plain_worldwide_lane.
    steps = plan_steps(["Data Analyst"], sources=only_linkedin, local=True)
    assert {s["source"] for s in steps} == {"LinkedIn"}


def test_default_scrapers_cover_every_source():
    """SOURCES and _default_scrapers are two hand-maintained lists of the
    same names; a drift is a runtime KeyError the suite would stay green
    through if nothing checked they agree."""
    from src.run_core import _default_scrapers
    assert set(_default_scrapers()) == {name for name, _, _ in SOURCES}


def test_indeed_is_not_a_source():
    """Indeed is organised one site per country: 22 of the 66 countries
    this product supports have no Indeed at all, and for the rest it
    answers the local question the LinkedIn local lane already covers."""
    assert "Indeed" not in {name for name, _, _ in SOURCES}


def test_linkedin_gets_no_plain_worldwide_lane():
    """The mode lanes ask the same worldwide question with better
    precision. The local lane stays: a hybrid role in the user's own city
    is a role they can work."""
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
