"""Weighted job scorer — reads keyword lists and weights from config."""
import re
from pathlib import Path
from typing import Any

import yaml

from .reason import compose_reason


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
        # Band cut-offs on the internal 1-10 score.
        self._bands = config.get("scoring", {}).get("bands",
                                                    {"strong": 8, "partial": 5})

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
        matched: list[str] = []
        # Strongest signals first so the reason sentence names them in order.
        for kw, pts in sorted(skill_kws.items(), key=lambda kv: -kv[1]):
            if _has(kw, body):
                matched.append(kw)
                skill_score = min(skill_score + pts, skill_max)

        # Gaps come from the description only — a tool named in the post that
        # the candidate's own skill list did not match.
        desc_l = (description or "").lower()
        gaps = [tool for tool in self._kw.get("market_tools", [])
                if _has(tool, desc_l) and tool not in matched]

        penalties_cfg = self._kw["penalties"]
        penalty = 0
        fired: list[str] = []
        if _has("w2 only", body):
            penalty += penalties_cfg.get("w2 only", 15)
            fired.append("w2 only")
        if _has("clearance", body) or _has("secret", body):
            penalty += penalties_cfg.get("clearance", 30)
            fired.append("clearance")
        if _has("cpt", body) or _has("opt", body):
            penalty += penalties_cfg.get("cpt", 20)
            fired.append("visa restriction")
        if is_exec:
            penalty += penalties_cfg.get("exec_penalty", 10)
            fired.append("executive role")
        if any(_has(k, body) for k in penalties_cfg.get("legacy_tech", {}).get("keywords", [])):
            penalty += penalties_cfg["legacy_tech"].get("value", 25)
            fired.append("legacy tech")
        if any(_has(k, body) for k in penalties_cfg.get("frontend_tech", {}).get("keywords", [])):
            penalty += penalties_cfg["frontend_tech"].get("value", 30)
            fired.append("frontend focus")

        raw = max(0, min(title_score + cat_bonus + seniority_score
                         + skill_score - penalty, 90))
        match_score = max(1, round(raw / 9))

        # The band is the only fit signal the UI may render. Without a
        # description nothing was compared, so no band may be claimed.
        described = bool((description or "").strip())
        if not described:
            band = None
        elif match_score >= self._bands.get("strong", 8):
            band = "STRONG FIT"
        elif match_score >= self._bands.get("partial", 5):
            band = "PARTIAL FIT"
        else:
            band = "STRETCH"

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

        evidence = {
            # Internal only — never rendered. Used for ranking.
            "match_score":          match_score,
            "band":                 band,
            "matched":              matched,
            "gaps":                 gaps,
            "penalties":            fired,
            "seniority":            ("exec" if is_exec else
                                     "junior" if is_junior else
                                     "senior" if is_senior else "mid"),
            "description_captured": described,
            "tailoring":            tailoring,
        }
        # Rule 2: the band is never handed out without its sentence.
        evidence["reason"] = compose_reason(evidence)
        return evidence
