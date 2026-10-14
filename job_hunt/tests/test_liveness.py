"""Tests for posting liveness: src/liveness.py and src/store/liveness.py.

Every board marker here is the shape measured on the live boards on
2026-10-14 (see the module docstring), cut down to the part that matters.
"""
import pytest
import requests

from src import liveness
from src.activity_page import render as render_board
from src.liveness import CLOSED, OPEN, UNKNOWN, check, check_postings
from src.map_page import render as render_map
from src.store.db import connect
from src.store.ingest import ensure_user, upsert_jobs
from src.store.liveness import closed_posting_count, record_check
from src.store.queries import (activity_board, eligibility_counts,
                               map_sections, open_company_count)
from src.store.runs import finish_run, start_run
from src.store.schema import init_db
from src.store.tracking import role_events, role_status, set_role_status


class Resp:
    def __init__(self, status=200, text="", location=None):
        self.status_code = status
        self.text = text
        self.headers = {"location": location} if location else {}
        self.is_redirect = bool(location) and 300 <= status < 400


def server(pages: dict):
    """A `get` that answers from `pages` and records every URL asked."""
    asked = []

    def get(url):
        asked.append(url)
        answer = pages[url]
        if isinstance(answer, Exception):
            raise answer
        return answer
    get.asked = asked
    return get


LI = "https://www.linkedin.com/jobs/view/data-analyst-at-acme-4459890873"

# ── LinkedIn ───────────────────────────────────────────────────────────────
def test_linkedin_expired_redirect_closes_without_following_it():
    get = server({LI: Resp(301, location=(
        "https://www.linkedin.com/jobs/analyst-jobs?trk=expired_jd_redirect"))})
    v = check(LI, get)
    assert v.state == CLOSED
    assert "expired_jd_redirect" in v.evidence
    assert get.asked == [LI]        # the search page is never fetched


def test_linkedin_banner_is_quoted_word_for_word():
    page = ('<figure class="closed-job"><figcaption class="closed-job__flavor'
            '--closed">No longer accepting applications</figcaption>'
            '<a data-tracking-control-name="public_jobs_apply-link">')
    v = check(LI, server({LI: Resp(200, page)}))
    assert v.state == CLOSED
    assert v.evidence == 'LinkedIn shows "No longer accepting applications"'


def test_linkedin_apply_button_is_open():
    page = '<a data-tracking-control-name="public_jobs_apply-link-offsite">'
    assert check(LI, server({LI: Resp(200, page)})).state == OPEN


def test_linkedin_404_is_closed():
    v = check(LI, server({LI: Resp(404, "<title>LinkedIn</title>")}))
    assert (v.state, v.http_status) == (CLOSED, 404)


@pytest.mark.parametrize("status", [429, 999, 403, 500])
def test_a_refusal_is_not_a_closure(status):
    v = check(LI, server({LI: Resp(status, "slow down")}))
    assert v.state == UNKNOWN
    assert v.http_status == status


def test_a_page_with_no_marker_is_unknown():
    wall = "https://www.linkedin.com/authwall?trk=x"
    get = server({LI: Resp(302, location=wall), wall: Resp(200, "sign in")})
    assert check(LI, get).state == UNKNOWN


def test_a_network_error_is_not_a_closure():
    v = check(LI, server({LI: requests.ConnectionError("down")}))
    assert v.state == UNKNOWN
    assert "ConnectionError" in v.evidence


# ── the other boards ───────────────────────────────────────────────────────
JOBICY = "https://jobicy.com/jobs/151769-sr-hr-systems-data-analyst-ii"


@pytest.mark.parametrize("resp,state", [
    (Resp(410, "gone"), CLOSED),
    (Resp(200, '<section class="jv-closed"><span>Applications closed'), CLOSED),
    (Resp(200, "<h1>Sr HR Systems Data Analyst</h1>"), OPEN),
])
def test_jobicy(resp, state):
    assert check(JOBICY, server({JOBICY: resp})).state == state


MUSE = "https://www.themuse.com/jobs/allstate/senior-business-data-analyst"


def test_muse_archived_message():
    page = ('<p class="job-header_archivedJobMessage__YtlXk">This job is no '
            'longer available.</p>')
    v = check(MUSE, server({MUSE: Resp(200, page)}))
    assert v.state == CLOSED
    assert "This job is no longer available." in v.evidence
    assert check(MUSE, server({MUSE: Resp(200, "<h1>Analyst</h1>")})).state == OPEN


ROK = "https://remoteok.com/remote-jobs/remote-data-analyst-sparksoft-1135698"


def test_remoteok_reads_only_the_postings_own_row():
    own_closed = ('<tr id="job-1135698" data-id="1135698" class="job '
                  'job-1135698 verified active active == closed tooltip">')
    assert check(ROK, server({ROK: Resp(200, own_closed)})).state == CLOSED

    # A related job further down the page is closed; ours is not.
    other_closed = ('<tr id="job-1135698" data-id="1135698" class="job '
                    'job-1135698 verified active active == ">'
                    '<tr id="job-77" data-id="77" class="job closed">')
    assert check(ROK, server({ROK: Resp(200, other_closed)})).state == OPEN


WWR = "https://weworkremotely.com/remote-jobs/doximity-data-analyst"


def test_weworkremotely_home_redirect_is_closed():
    v = check(WWR, server({WWR: Resp(301, location="https://weworkremotely.com/")}))
    assert v.state == CLOSED
    assert check(WWR, server({WWR: Resp(200, "<h1>Data Analyst</h1>")})).state == OPEN


WN = "https://www.workingnomads.com/job/go/1775628/"


def test_working_nomads_forward_target_decides():
    expired = server({WN: Resp(302, location="/remote-development-jobs")})
    assert check(WN, expired).state == CLOSED
    assert expired.asked == [WN]

    live = server({WN: Resp(302, location="https://boards.greenhouse.io/x/1")})
    v = check(WN, live)
    assert v.state == OPEN
    assert live.asked == [WN]       # the employer's site is never fetched


HN = "https://news.ycombinator.com/item?id=49185103"
HN_API = "https://hacker-news.firebaseio.com/v0/item/49185103.json"


def test_hacker_news_reads_the_api_and_only_deletion_closes():
    assert check(HN, server({HN_API: Resp(200, '{"deleted": true}')})).state == CLOSED
    assert check(HN, server({HN_API: Resp(200, '{"dead":true}')})).state == CLOSED
    assert check(HN, server({HN_API: Resp(200, '{"text": "hiring"}')})).state == UNKNOWN


def test_a_board_without_a_checker_is_never_asked():
    get = server({})
    url = "https://himalayas.app/companies/acme/jobs/data-analyst"
    assert check(url, get).state == UNKNOWN
    assert get.asked == []


# ── the store ──────────────────────────────────────────────────────────────
def _job(url, company="Acme", title="Data Analyst", **kw):
    return {"company": company, "title": title, "url": url,
            "location": "Remote", "platform": "LinkedIn", "date": "2026-10-01",
            "description": "sql", "description_captured": True,
            "match_score": 9, "band": "STRONG FIT", "reason": "names sql",
            "matched": ["sql"], "gaps": [], "location_scope": "open", **kw}


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "t.db")
    init_db(conn)
    user = ensure_user(conn, "G")
    run = start_run(conn, user)
    upsert_jobs(conn, user, run, [
        _job(LI), _job(JOBICY, company="Globex"), _job(WWR, company="Initech")])
    finish_run(conn, run, scraped=3, kept=3)
    ids = {r["url"]: r["id"] for r in conn.execute("SELECT id, url FROM role")}
    return conn, user, ids


def _map_titles(conn, user):
    s = map_sections(conn, user)
    return {m["name"] for m in s["new"] + s["earlier"]}


def test_a_closed_posting_leaves_the_map_and_is_counted(store):
    conn, user, ids = store
    record_check(conn, user, ids[LI],
                 liveness.Verdict(CLOSED, 'LinkedIn shows "No longer accepting'
                                          ' applications"', 200, LI))
    assert _map_titles(conn, user) == {"Globex", "Initech"}
    assert closed_posting_count(conn, user) == 1
    assert eligibility_counts(conn, user)["open"] == 2
    assert open_company_count(conn, user) == 2

    row = conn.execute("SELECT * FROM posting_check").fetchone()
    assert (row["role_id"], row["verdict"], row["http_status"]) == (ids[LI], CLOSED, 200)
    assert "No longer accepting" in row["evidence"]
    kinds = [(e["kind"], e["to_status"]) for e in role_events(conn, ids[LI])]
    assert kinds == [("POSTING", "CLOSED")]


def test_unknown_and_open_change_nothing_but_are_kept(store):
    conn, user, ids = store
    record_check(conn, user, ids[LI], liveness.Verdict(UNKNOWN, "rate limited", 429))
    record_check(conn, user, ids[WWR], liveness.Verdict(OPEN, "shows it", 200))
    assert _map_titles(conn, user) == {"Acme", "Globex", "Initech"}
    assert closed_posting_count(conn, user) == 0
    assert [r["verdict"] for r in conn.execute(
        "SELECT verdict FROM posting_check ORDER BY id")] == [UNKNOWN, OPEN]


def test_saved_follows_the_posting_to_closed_but_applied_stays(store):
    conn, user, ids = store
    set_role_status(conn, user, ids[LI], "SAVED")
    set_role_status(conn, user, ids[JOBICY], "APPLIED")
    for url in (LI, JOBICY):
        record_check(conn, user, ids[url], liveness.Verdict(CLOSED, "gone", 404))

    assert role_status(conn, ids[LI]) == "CLOSED"
    assert role_status(conn, ids[JOBICY]) == "APPLIED"
    moves = [(e["from_status"], e["to_status"]) for e in role_events(conn, ids[LI])
             if e["kind"] == "STATUS"]
    assert moves[-1] == ("SAVED", "CLOSED")

    board = activity_board(conn, user)
    applied = board["APPLIED"][0]
    assert applied["closed_at"] and applied["closed_evidence"] == "gone"
    html = render_board(board)
    assert "POSTING CLOSED" in html and 'title="gone"' in html


def test_closing_twice_stamps_once(store):
    conn, user, ids = store
    for _ in range(2):
        record_check(conn, user, ids[LI], liveness.Verdict(CLOSED, "gone", 404))
    assert len([e for e in role_events(conn, ids[LI]) if e["kind"] == "POSTING"]) == 1


def test_map_header_states_the_count():
    html = render_map([], meta={"gone": 4})
    assert "4 HIDDEN (POSTING CLOSED)" in html
    assert "POSTING CLOSED" not in render_map([], meta={"gone": 0})


# ── a pass ─────────────────────────────────────────────────────────────────
def _many_linkedin(tmp_path, n):
    conn = connect(tmp_path / "p.db")
    init_db(conn)
    user = ensure_user(conn, "G")
    run = start_run(conn, user)
    urls = [f"https://www.linkedin.com/jobs/view/analyst-at-co{i}-44000000{i:02d}"
            for i in range(n)]
    upsert_jobs(conn, user, run,
                [_job(u, company=f"Co{i}") for i, u in enumerate(urls)]
                + [_job(WWR, company="Initech")])
    finish_run(conn, run, scraped=n + 1, kept=n + 1)
    return conn, user, urls


def test_one_rate_limit_slows_the_board_down_and_the_pass_goes_on(tmp_path):
    conn, user, urls = _many_linkedin(tmp_path, 3)
    waits = []
    page = '<a data-tracking-control-name="public_jobs_apply-link">'
    get = server({urls[0]: Resp(429, "slow"), urls[1]: Resp(200, page),
                  urls[2]: Resp(200, page),
                  WWR: Resp(301, location="https://weworkremotely.com/")})
    summary = check_postings(conn, user, get=get, sleep=waits.append)

    assert get.asked[:3] == urls          # not benched by a single 429
    assert summary["throttled"] == []
    assert (summary[OPEN], summary[UNKNOWN], summary[CLOSED]) == (2, 1, 1)
    assert max(waits) > 3.0               # the spacing doubled after the 429
    assert summary["closed_roles"][0]["company"] == "Initech"


def test_a_run_of_rate_limits_benches_that_board_for_the_pass(tmp_path):
    conn, user, urls = _many_linkedin(tmp_path, 6)
    get = server({**{u: Resp(429, "slow") for u in urls},
                  WWR: Resp(200, "ok")})
    summary = check_postings(conn, user, get=get, sleep=lambda s: None)

    assert [u for u in get.asked if "linkedin" in u] == urls[:4]
    assert summary["throttled"] == ["LinkedIn"]
    assert WWR in get.asked                # other boards carry on


def test_tracked_roles_are_checked_first_and_the_limit_holds(store):
    conn, user, ids = store
    set_role_status(conn, user, ids[WWR], "APPLIED")
    get = server({WWR: Resp(200, "ok"), LI: Resp(200, "x"), JOBICY: Resp(200, "x")})
    summary = check_postings(conn, user, limit=1, get=get, sleep=lambda s: None)
    assert get.asked == [WWR]
    assert summary["checked"] == 1


def test_closed_roles_are_not_checked_again(store):
    conn, user, ids = store
    record_check(conn, user, ids[LI], liveness.Verdict(CLOSED, "gone", 404))
    get = server({JOBICY: Resp(200, "x"), WWR: Resp(200, "x")})
    check_postings(conn, user, get=get, sleep=lambda s: None)
    assert LI not in get.asked
