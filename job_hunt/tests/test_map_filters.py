"""Tests for src/map_filters.py and the sort/filter bar on the map page."""
import re
from datetime import date

from src import map_filters
from src.map_filters import apply, is_active, options, parse
from src.map_page import render

TODAY = date(2026, 10, 14)

VOCAB = {
    "role_families": [
        {"name": "Analytics Engineer", "phrases": ["analytics engineer"]},
        {"name": "Data Engineer", "phrases": ["data engineer"]},
    ],
    "seniority": {"senior_keywords": ["senior"], "junior_keywords": ["junior"],
                  "exec_keywords": ["director"]},
}


def _role(title="Analytics Engineer", band="STRONG FIT", captured=True,
          posted="2026-10-12", mode="remote", platform="LinkedIn",
          scope=None, rid=1):
    return {"id": rid, "title": title, "band": band if captured else None,
            "reason": "matches dbt" if captured else "no description",
            "description_captured": captured, "date": posted,
            "work_mode": mode, "platform": platform, "location_scope": scope,
            "matched": [], "gaps": [], "url": "https://x/" + str(rid)}


def _co(name, roles, state="ACT_NOW", section="new", cid=None):
    return {"id": cid, "name": name, "state": state, "why": "why",
            "section": section, "roles": roles}


def _names(maps):
    return [m["name"] for m in maps]


def _run(maps, **args):
    return apply(maps, parse(args), today=TODAY, vocab=VOCAB)


# ── parse ────────────────────────────────────────────────────────────────────

def test_plain_map_is_not_a_filtered_view():
    view = parse({})
    assert view["sort"] == "fit"
    assert not is_active(view)


def test_unknown_closed_set_values_fall_back_to_no_filter():
    view = parse({"sort": "salary", "fit": "great", "posted": "999",
                  "since": "abc"})
    assert view["sort"] == "fit" and view["fit"] == "" and view["posted"] == ""
    assert view["since"] is None


def test_since_is_read_as_a_run_id():
    assert parse({"since": "12"})["since"] == 12


def test_the_plain_view_returns_the_maps_untouched():
    maps = [_co("B", [_role()]), _co("A", [_role()])]
    assert apply(maps, parse({}), today=TODAY, vocab=VOCAB) is maps


# ── filters test roles, not companies ───────────────────────────────────────

def test_fit_filter_drops_companies_with_no_passing_role():
    maps = [_co("Strong", [_role()]),
            _co("Partial", [_role(band="PARTIAL FIT")]),
            _co("Unchecked", [_role(captured=False)])]
    assert _names(_run(maps, fit="strong")) == ["Strong"]
    assert _names(_run(maps, fit="partial")) == ["Strong", "Partial"]
    assert _names(_run(maps, fit="unchecked")) == ["Unchecked"]


def test_the_card_role_is_the_best_role_that_passed():
    acme = _co("Acme", [_role(rid=1, mode="remote"),
                        _role(rid=2, mode="hybrid", band="PARTIAL FIT")])
    shown = _run([acme], mode="hybrid")
    assert [r["id"] for r in shown[0]["roles"]] == [2]
    assert shown[0]["roles_total"] == 2
    # The input is not mutated: the unfiltered map still has both.
    assert len(acme["roles"]) == 2


def test_posted_window_counts_days_and_drops_unreadable_dates():
    maps = [_co("Fresh", [_role(posted="2026-10-10")]),
            _co("Old", [_role(posted="2026-09-01")]),
            _co("Undated", [_role(posted="")])]
    assert _names(_run(maps, posted="7")) == ["Fresh"]
    assert _names(_run(maps, posted="30")) == ["Fresh"]


def test_work_mode_filter_including_not_stated():
    maps = [_co("R", [_role(mode="remote")]), _co("H", [_role(mode="hybrid")]),
            _co("N", [_role(mode=None)])]
    assert _names(_run(maps, mode="hybrid")) == ["H"]
    assert _names(_run(maps, mode=map_filters.NO_MODE)) == ["N"]


def test_location_reach_matches_the_header_split():
    maps = [_co("Open", [_role(scope="open")]),
            _co("Unknown", [_role(scope="unknown")]),
            _co("Null", [_role(scope=None)])]
    assert _names(_run(maps, reach="open")) == ["Open"]
    assert _names(_run(maps, reach="unverified")) == ["Unknown", "Null"]


def test_board_kind_and_level_filters():
    maps = [_co("A", [_role(title="Senior Analytics Engineer",
                            platform="Himalayas")]),
            _co("B", [_role(title="Junior Data Engineer")]),
            _co("C", [_role(title="Marketing Lead")])]
    assert _names(_run(maps, board="Himalayas")) == ["A"]
    assert _names(_run(maps, kind="Data Engineer")) == ["B"]
    assert _names(_run(maps, kind="Other data roles")) == ["C"]
    assert _names(_run(maps, level="senior")) == ["A"]
    # No level word in the title reads as mid, the way the scorer reads it.
    assert _names(_run(maps, level="mid")) == ["C"]


def test_company_search_is_case_insensitive():
    maps = [_co("DataArt", [_role()]), _co("Acme", [_role()])]
    assert _names(_run(maps, q="data")) == ["DataArt"]


def test_an_unknown_open_set_value_matches_nothing():
    assert _run([_co("A", [_role()])], board="Nowhere") == []


def test_watched_companies_with_nothing_open_pass_through():
    shelf = _co("Watched", [], state="WATCH")
    assert _names(_run([shelf, _co("A", [_role(band="STRETCH")])],
                       fit="strong")) == ["Watched"]


# ── sorts ────────────────────────────────────────────────────────────────────

def test_newest_sorts_companies_by_their_newest_role_and_leads_with_it():
    maps = [_co("Older", [_role(posted="2026-10-01")]),
            _co("Newer", [_role(rid=1, posted="2026-10-02"),
                          _role(rid=2, posted="2026-10-13")])]
    shown = _run(maps, sort="newest")
    assert _names(shown) == ["Newer", "Older"]
    assert shown[0]["roles"][0]["id"] == 2


def test_company_and_role_count_sorts_keep_fit_order_on_ties():
    maps = [_co("b", [_role()]), _co("C", [_role(), _role(rid=2)]),
            _co("a", [_role()])]
    assert _names(_run(maps, sort="company")) == ["a", "b", "C"]
    assert _names(_run(maps, sort="roles")) == ["C", "b", "a"]


# ── options ──────────────────────────────────────────────────────────────────

def test_options_list_only_values_present():
    maps = [_co("A", [_role(title="Senior Analytics Engineer", mode=None,
                            platform="Himalayas")]),
            _co("B", [_role(platform="jobicy")])]
    got = options(maps, vocab=VOCAB)
    assert got["mode"] == ["remote", map_filters.NO_MODE]
    assert got["kind"] == ["Analytics Engineer"]
    assert got["level"] == ["mid", "senior"]
    assert got["board"] == ["Himalayas", "jobicy"]


# ── the page ─────────────────────────────────────────────────────────────────

def _page_maps():
    return [_co("Acme", [_role(rid=1)], cid=1),
            _co("Globex", [_role(rid=2, band="STRETCH")], state="DISCOVER",
                cid=2)]


def _visible(html):
    return re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.DOTALL)


def test_the_bar_renders_on_the_plain_map_without_a_state_line():
    html = render(_page_maps())
    assert '<form class="filters"' in html
    assert "SHOWING" not in html


def test_a_filter_says_how_many_companies_it_set_aside():
    html = render(_page_maps(), view=parse({"fit": "strong", "since": "3"}))
    body = _visible(html)
    assert "SHOWING 1 OF 2 COMPANIES" in body
    assert 'href="/?since=3"' in body
    assert "Globex" not in body
    assert '<option value="strong" selected>' in body


def test_a_filter_that_matches_nothing_says_so():
    html = _visible(render(_page_maps(), view=parse({"q": "zzz"})))
    assert "SHOWING 0 OF 2 COMPANIES" in html
    assert "nothing matches these filters" in html


def test_the_since_baseline_rides_along_in_the_form():
    html = render(_page_maps(), view={**parse({}), "since": 7})
    assert '<input type="hidden" name="since" value="7">' in html


def test_the_lead_card_is_only_for_the_stores_own_ranking():
    assert 'class="lead"' in render(_page_maps())
    assert 'class="lead"' not in render(_page_maps(),
                                        view=parse({"sort": "company"}))


def test_search_text_is_escaped():
    html = render(_page_maps(), view=parse({"q": '"><b>x'}))
    assert '"><b>x' not in html


def test_the_bar_adds_no_score_or_percentage():
    html = _visible(render(_page_maps(), view=parse({"sort": "newest"})))
    assert not re.search(r"\d+%", html)
    assert "match_score" not in html


def test_drawer_keys_follow_the_filtered_cards():
    html = render(_page_maps(), view=parse({"fit": "strong"}))
    # Only Acme is shown, so the drawer payload holds one company, c0.
    assert '"c0"' in html and '"c1"' not in html


# ── the route ────────────────────────────────────────────────────────────────

def test_filtering_after_the_first_load_keeps_the_new_section(tmp_path):
    from src.app import create_app
    from src.store.db import connect
    from src.store.ingest import ensure_user, upsert_jobs
    from src.store.runs import finish_run, start_run
    from src.store.schema import init_db
    from tests.test_app import _finish_setup, _job

    db = tmp_path / "test.db"
    conn = connect(db)
    init_db(conn)
    user_id = ensure_user(conn, "G")
    _finish_setup(conn, user_id)
    first = start_run(conn, user_id)
    upsert_jobs(conn, user_id, first, [_job("https://x/1")])
    finish_run(conn, first, scraped=1, kept=1)

    app = create_app(db_path=db, user_name="G")
    app.config.update(TESTING=True)
    client = app.test_client()
    client.get("/")  # first visit: the first run is now seen

    second = start_run(conn, user_id)
    upsert_jobs(conn, user_id, second,
                [_job("https://x/2", title="Data Engineer")])
    finish_run(conn, second, scraped=1, kept=1)
    conn.close()

    plain = client.get("/").data.decode("utf-8")
    since = re.search(r'name="since" value="(\d+)"', plain).group(1)
    assert int(since) == first

    # The plain load just marked the second run seen; a filtered reload
    # carrying `since` still files the second run's role as new.
    body = _visible(client.get(f"/?since={since}&sort=company")
                    .data.decode("utf-8"))
    heading = body.index("still here from earlier")
    # A card sits above the heading: the new section is not empty. The
    # company counts once per section, as the header's count does.
    assert body.index('class="card"') < heading
    assert "SHOWING 2 OF 2 COMPANIES" in body


def test_a_filtered_card_says_how_many_of_its_roles_it_shows():
    maps = [_co("Acme", [_role(rid=1), _role(rid=2, band="STRETCH")], cid=1)]
    assert "1 OF 2 ROLES OPEN" in _visible(
        render(maps, view=parse({"fit": "strong"})))
    assert "2 ROLES OPEN" in _visible(render(maps))
    assert " OF 2 ROLES" not in _visible(render(maps))
