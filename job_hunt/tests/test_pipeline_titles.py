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
