"""Tests for src/opportunity.py — jobs become company-centred maps.

Spec rules 4-7: state assignment, the company-level why line, and ranking.
"""
from src.opportunity import build_maps

_STRONG = {"band": "STRONG FIT", "match_score": 9, "reason": "matches dbt",
           "matched": ["dbt"], "gaps": [], "description_captured": True}
_WEAK = {"band": "STRETCH", "match_score": 3, "reason": "little overlap",
         "matched": [], "gaps": [], "description_captured": True}


def _job(company="Acme", title="Analytics Engineer", **kw):
    base = {"company": company, "title": title, "location": "Remote, US",
            "url": "https://x/1", "date": "2026-08-08", "salary": "",
            "description": "jd text", "platform": "LinkedIn"}
    return {**base, **{k: v for k, v in kw.items()}}


def _scored(job, evidence):
    return {**job, **evidence}


# ── State assignment ──────────────────────────────────────────────────────────

def test_company_with_a_shortlist_role_is_act_now():
    maps = build_maps([_scored(_job(), _STRONG)], shortlist_min=7)
    assert maps[0]["state"] == "ACT_NOW"


def test_company_below_threshold_is_discover():
    maps = build_maps([_scored(_job(), _WEAK)], shortlist_min=7)
    assert maps[0]["state"] == "DISCOVER"


def test_watched_company_with_no_role_is_watch():
    maps = build_maps([], shortlist_min=7, watched=["Initech"])
    assert [m["name"] for m in maps if m["state"] == "WATCH"] == ["Initech"]


def test_watch_companies_carry_no_roles():
    """Rule 5 — a watch entry is a different shape, not an empty act-now."""
    maps = build_maps([], shortlist_min=7, watched=["Initech"])
    assert maps[0]["roles"] == []


def test_watched_company_that_has_a_role_again_becomes_act_now():
    maps = build_maps([_scored(_job(company="Initech"), _STRONG)],
                      shortlist_min=7, watched=["Initech"])
    assert maps[0]["state"] == "ACT_NOW"


# ── Grouping ──────────────────────────────────────────────────────────────────

def test_roles_group_under_one_company():
    jobs = [_scored(_job(title="Analytics Engineer", url="https://x/1"), _STRONG),
            _scored(_job(title="Data Engineer", url="https://x/2"), _STRONG)]
    maps = build_maps(jobs, shortlist_min=7)
    assert len(maps) == 1
    assert len(maps[0]["roles"]) == 2


def test_best_role_leads_the_company():
    jobs = [_scored(_job(title="Weak Role", url="https://x/1"), _WEAK),
            _scored(_job(title="Strong Role", url="https://x/2"), _STRONG)]
    maps = build_maps(jobs, shortlist_min=7)
    assert maps[0]["roles"][0]["title"] == "Strong Role"


# ── The why line (rule 6) ─────────────────────────────────────────────────────

def test_company_why_is_present_and_counts_roles():
    jobs = [_scored(_job(url="https://x/1"), _STRONG),
            _scored(_job(url="https://x/2"), _STRONG)]
    why = build_maps(jobs, shortlist_min=7)[0]["why"]
    assert "2 roles" in why


def test_single_role_why_is_not_pluralised():
    why = build_maps([_scored(_job(), _STRONG)], shortlist_min=7)[0]["why"]
    assert "1 role" in why and "1 roles" not in why


def test_single_role_why_uses_singular_verb():
    why = build_maps([_scored(_job(), _STRONG)], shortlist_min=7)[0]["why"]
    assert "1 role matches" in why


def test_plural_why_uses_plural_verb():
    jobs = [_scored(_job(url="https://x/1"), _STRONG),
            _scored(_job(url="https://x/2"), _STRONG)]
    assert "2 roles match your" in build_maps(jobs, shortlist_min=7)[0]["why"]


def test_watch_company_has_its_own_why():
    why = build_maps([], shortlist_min=7, watched=["Initech"])[0]["why"]
    assert why.strip()


# ── Ranking (rule 7) ──────────────────────────────────────────────────────────

def test_act_now_ranks_above_discover():
    jobs = [_scored(_job(company="Weak Co"), _WEAK),
            _scored(_job(company="Strong Co"), _STRONG)]
    states = [m["state"] for m in build_maps(jobs, shortlist_min=7)]
    assert states == ["ACT_NOW", "DISCOVER"]


def test_watch_ranks_last():
    jobs = [_scored(_job(company="Weak Co"), _WEAK)]
    maps = build_maps(jobs, shortlist_min=7, watched=["Initech"])
    assert maps[-1]["state"] == "WATCH"


def test_stronger_company_ranks_first_within_a_state():
    better = {**_STRONG, "match_score": 10}
    jobs = [_scored(_job(company="Good Co"), _STRONG),
            _scored(_job(company="Best Co"), better)]
    assert build_maps(jobs, shortlist_min=7)[0]["name"] == "Best Co"


def test_hidden_companies_are_dropped():
    maps = build_maps([_scored(_job(company="Acme"), _STRONG)],
                      shortlist_min=7, hidden=["Acme"])
    assert maps == []


def test_empty_input_yields_no_maps():
    assert build_maps([], shortlist_min=7) == []
