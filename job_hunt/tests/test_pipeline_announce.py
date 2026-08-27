"""main._announce_step: each completed scrape step prints exactly once.

run_core.execute's report() hands `on_progress` a *fresh dict copy* of every
step on every single progress event (specifically so a retained event can't
be corrupted by a later mutation) — a completed step keeps reappearing as
"done" in every subsequent event (e.g. once per remaining scraping-loop
step, then again at the "scoring" and "storing" stages), each time as a
different dict object. A de-dup flag mutated onto the step dict itself is
therefore discarded the instant it's handed back, and never survives to the
next event — this test is the regression coverage for that exact bug.
"""
import main


def test_announce_step_prints_each_completed_step_exactly_once(capsys):
    printed_steps: set[tuple[str, str]] = set()
    step = {"source": "Indeed", "role": "BI Developer", "state": "done",
           "found": 5}

    # Simulate the same completed step arriving as a fresh dict copy in two
    # separate progress events, exactly as run_core.execute's report() does
    # once later stages (scoring, storing) also fire.
    main._announce_step(dict(step), printed_steps)
    main._announce_step(dict(step), printed_steps)

    output = capsys.readouterr().out
    assert output.count("fetched") == 1


def test_announce_step_prints_a_failed_step_exactly_once(capsys):
    printed_steps: set[tuple[str, str]] = set()
    step = {"source": "LinkedIn", "role": "Data Engineer", "state": "failed",
           "found": 0}

    main._announce_step(dict(step), printed_steps)
    main._announce_step(dict(step), printed_steps)

    output = capsys.readouterr().out
    assert output.count("FAILED") == 1


def test_announce_step_distinguishes_different_steps():
    printed_steps: set[tuple[str, str]] = set()
    indeed_step = {"source": "Indeed", "role": "BI Developer",
                   "state": "done", "found": 3}
    linkedin_step = {"source": "LinkedIn", "role": "BI Developer",
                     "state": "done", "found": 2}

    main._announce_step(dict(indeed_step), printed_steps)
    main._announce_step(dict(linkedin_step), printed_steps)

    assert printed_steps == {("Indeed", "BI Developer", "worldwide"),
                             ("LinkedIn", "BI Developer", "worldwide")}


def test_announce_step_prints_both_lanes_of_the_same_source_and_role(capsys):
    """The dedup key must include the lane, or the local step is silently
    swallowed as a duplicate of the worldwide one."""
    printed_steps: set = set()
    worldwide_step = {"source": "Indeed", "role": "BI Developer",
                      "lane": "worldwide", "state": "done", "found": 3}
    local_step = {"source": "Indeed", "role": "BI Developer",
                  "lane": "local", "state": "done", "found": 2}

    main._announce_step(dict(worldwide_step), printed_steps)
    main._announce_step(dict(local_step), printed_steps)

    output = capsys.readouterr().out
    lines = [line for line in output.splitlines()
             if "BI Developer" in line]
    assert len(lines) == 2
    assert any("local" in line for line in lines)


def test_announce_step_labels_a_non_worldwide_lane(capsys):
    """Any lane other than 'worldwide' gets a '· <lane>' suffix — the
    labeling logic is generic, not a special case for one lane name. A
    worldwide step stays unsuffixed."""
    printed_steps: set = set()
    local_step = {"source": "LinkedIn", "role": "BI Developer",
                  "lane": "local", "state": "done", "found": 3}
    worldwide_step = {"source": "LinkedIn", "role": "BI Developer",
                      "lane": "worldwide", "state": "done", "found": 5}

    main._announce_step(dict(local_step), printed_steps)
    main._announce_step(dict(worldwide_step), printed_steps)

    output = capsys.readouterr().out
    lines = [line for line in output.splitlines()
             if "BI Developer" in line]
    assert len(lines) == 2
    assert any("· local" in line for line in lines)
    assert not any("worldwide" in line for line in lines)
