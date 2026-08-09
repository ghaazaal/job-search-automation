"""Weighted job scorer — reads keyword lists and weights from config."""
import re
from pathlib import Path
from typing import Any

import yaml


def _load_keywords(keywords_path: Path) -> dict:
    with open(keywords_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _has(term: str, haystack: str) -> bool:
    """Word-boundary keyword match.

    Descriptions are long enough that substring matching produces false
    positives on short tokens — 'opt' inside 'optimize', 'bi' inside
    'ambitious'. Boundaries keep multi-word terms ('power bi') working.
    """
    return bool(re.search(r"\b" + re.escape(term.strip()) + r"\b", haystack))


class Scorer:
    def __init__(self, config: dict, keywords_path: Path):
        self._cfg = config.get("scoring", {}).get("weights", {})
        self._kw = _load_keywords(keywords_path)

    def score_job(self, title: str, category: str,
                  salary_str: str, url: str,
                  description: str = "") -> dict:
        t = title.lower()
        # Skills and penalties are stated in the JD body, not the title.
        # Falls back to the title alone when no description was captured.
        body = f"{t}\n{(description or '').lower()}"

        groups = self._kw["title_groups"]
        scores_map = self._kw["title_scores"]

        def _hit(group_name: str) -> bool:
            return any(k in t for k in groups.get(group_name, []))

        for name in ("core_ae", "core_de", "core_da", "core_pa", "adjacent", "weak"):
            if _hit(name):
                title_score = scores_map.get(name, scores_map["default"])
                break
        else:
            title_score = scores_map["default"]

        cat_bonus = {"Analytics Engineer": 10, "Data Engineer": 8,
                     "Data Analyst": 7, "Product Analyst": 5}.get(category, 5)

        seniority = self._kw["seniority"]
        is_senior = any(k in t for k in seniority["senior_keywords"])
        is_junior = any(k in t for k in seniority["junior_keywords"])
        is_exec   = any(k in t for k in seniority["exec_keywords"])
        if   is_exec:   seniority_score = seniority["scores"]["exec"]
        elif is_junior: seniority_score = seniority["scores"]["junior"]
        elif is_senior: seniority_score = seniority["scores"]["senior"]
        else:           seniority_score = seniority["scores"]["mid"]

        skill_kws = {k: v for k, v in self._kw["skills"].items()
                     if k != "skill_max"}
        skill_max = self._kw["skills"].get("skill_max", 20)
        skill_score = 0
        for kw, pts in skill_kws.items():
            if _has(kw, body):
                skill_score = min(skill_score + pts, skill_max)

        penalties_cfg = self._kw["penalties"]
        penalty = 0
        if _has("w2 only", body):
            penalty += penalties_cfg.get("w2 only", 15)
        if _has("clearance", body) or _has("secret", body):
            penalty += penalties_cfg.get("clearance", 30)
        if _has("cpt", body) or _has("opt", body):
            penalty += penalties_cfg.get("cpt", 20)
        if is_exec:
            penalty += penalties_cfg.get("exec_penalty", 10)
        if any(_has(k, body) for k in penalties_cfg.get("legacy_tech", {}).get("keywords", [])):
            penalty += penalties_cfg["legacy_tech"].get("value", 25)
        if any(_has(k, body) for k in penalties_cfg.get("frontend_tech", {}).get("keywords", [])):
            penalty += penalties_cfg["frontend_tech"].get("value", 30)

        raw = max(0, min(title_score + cat_bonus + seniority_score
                         + skill_score - penalty, 90))
        match_score = max(1, round(raw / 9))

        base = {10: 45, 9: 45, 8: 45, 7: 30, 6: 30,
                5: 15, 4: 15}.get(match_score, 5)
        sal_nums = re.findall(r'\d+', (salary_str or "").replace(',', ''))
        if sal_nums:
            top_sal = int(sal_nums[-1])
            if   top_sal >= 400_000: base -= 15
            elif top_sal >= 200_000: base -= 5
        interview_chance = f"{max(5, min(base, 60))}%"

        groups_for_cat = {
            "Analytics Engineer": groups.get("core_ae", []),
            "Data Engineer":      groups.get("core_de", []),
            "Data Analyst":       groups.get("core_da", []),
            "Product Analyst":    groups.get("core_pa", []),
        }
        if any(k in t for k in groups_for_cat.get(category, [])):
            tailoring = "Minor" if category != "Product Analyst" else "Moderate"
        elif match_score >= 6: tailoring = "Moderate"
        elif match_score >= 4: tailoring = "Significant"
        else:                  tailoring = "N/A"

        return {
            "match_score":      match_score,
            "interview_chance": interview_chance,
            "tailoring":        tailoring,
        }
