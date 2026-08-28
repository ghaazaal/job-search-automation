"""Scores one posting against one resume.

Every rule lives in `matching`, every number in `vocabulary.yaml`. This
module's job is to compose them, hand back the evidence, and never let the
total reach a caller that renders — the band word and the reason sentence are
the only fit signals the UI may show.
"""
from pathlib import Path

import yaml

from . import matching
from .reason import compose_reason

# The most a posting can earn: 40 title + 20 seniority + 20 skills.
_MAX_RAW = 80


def _load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _tailoring(match_score: int) -> str:
    """How much rewriting a posting is likely to need.

    Used only by the Excel tracker. It used to be derived from membership in
    the four hardcoded search categories; with those gone it reads off the
    score, which is what the category was standing in for anyway.
    """
    if match_score >= 8:
        return "Minor"
    if match_score >= 6:
        return "Moderate"
    if match_score >= 4:
        return "Significant"
    return "N/A"


class Scorer:
    """Scores postings against resumes. One instance per run."""

    def __init__(self, config: dict, vocabulary_path: Path,
                 user_country: str = "", user_modes: tuple = ()):
        self._vocab = _load(vocabulary_path)
        # Band cut-offs on the internal 1-10 score.
        self._bands = config.get("scoring", {}).get("bands",
                                                    {"strong": 8, "partial": 5})
        # Where the user can be hired. Empty means unknown, and unknown
        # means the geography checks stay silent rather than guess.
        self._user_country = (user_country or "").strip().lower()
        # What the user searched for. Only used to word the mode-mismatch
        # clause — the policy decision lives in run_core.
        self._user_modes = tuple(str(m).strip().lower()
                                 for m in user_modes if str(m).strip())

    def score_job(self, title: str, description: str, resume: dict,
                  mode_mismatch: str | None = None,
                  local_evidence: bool = False) -> dict:
        """Evidence for one posting judged against one resume."""
        vocab = self._vocab
        lowered = (title or "").lower()
        # Skills and constraints are stated in the body, not the title. The
        # title is folded in so a posting that arrived without a description
        # can still match something.
        body = f"{lowered}\n{(description or '').lower()}"

        tier = matching.title_tier(title, resume.get("target_roles") or [],
                                   vocab.get("stopwords") or [])
        title_score = vocab["title_scores"][tier]

        jd_band = matching.seniority_band(title, vocab.get("seniority") or {})
        my_band = resume.get("seniority") or "mid"
        distance = matching.band_distance(jd_band, my_band)
        seniority_cfg = vocab["seniority_scores"]
        seniority_score = (seniority_cfg["same"] if distance == 0
                           else seniority_cfg["one_apart"] if distance == 1
                           else seniority_cfg["far"])

        skills = resume.get("skills") or []
        matched, skill_score = matching.skill_hits(body, skills,
                                                   vocab["skill_scores"])

        mine = matching.resume_terms(skills)
        tools = vocab.get("market_tools") or []
        found_gaps = matching.gaps(description, tools, mine)
        mismatch = matching.mismatch_penalty(description, tools, mine,
                                             vocab.get("mismatch") or {})

        penalty, fired, geo_verdict = self._constraints(
            body, jd_band, my_band, mode_mismatch,
            local_evidence)
        if mismatch:
            fired.append("little overlap with the tools this post names")

        raw = max(0, min(title_score + seniority_score + skill_score
                         - penalty - mismatch, _MAX_RAW))
        match_score = max(1, round(raw / (_MAX_RAW / 10)))

        # Without a description nothing was compared, so no band is claimed.
        described = bool((description or "").strip())
        if not described:
            band = None
        elif match_score >= self._bands.get("strong", 8):
            band = "STRONG FIT"
        elif match_score >= self._bands.get("partial", 5):
            band = "PARTIAL FIT"
        else:
            band = "STRETCH"

        evidence = {
            # Internal only — never rendered. Used for ranking.
            "match_score":          match_score,
            "band":                 band,
            "matched":              matched,
            "gaps":                 found_gaps,
            "penalties":            fired,
            "seniority":            jd_band,
            "description_captured": described,
            "tailoring":            _tailoring(match_score),
            "resume_id":            resume.get("id"),
            "resume_label":         resume.get("label") or "",
            # Internal + stored: positive evidence the user can take the
            # job. Never rendered as a number — reason.py words it. Local
            # evidence (the job is in the user's own place) cannot verify
            # past a stated restriction: a Yerevan-tagged posting that
            # says "must be based in the UK" is not a verified sure
            # thing, whatever its location field says — the tier and the
            # sentence must agree.
            "eligibility_verified": bool(
                (local_evidence and geo_verdict not in ("restricted",
                                                        "excluded"))
                or geo_verdict == "eligible"),
        }
        # A band is never handed out without its sentence.
        evidence["reason"] = compose_reason(evidence)
        return evidence

    def best_match(self, title: str, description: str,
                   resumes: list[dict],
                   mode_mismatch: str | None = None,
                   local_evidence: bool = False) -> dict:
        """Score against every active resume and keep the strongest.

        Someone with a Data Engineer resume and a BI Developer resume should
        see each posting judged by whichever of the two actually fits it, and
        be told which one that was.

        Ties go to the earliest resume — `list_resumes` orders by creation, and
        `max` keeps the first of equals — so re-running a scrape cannot
        reshuffle the map for no reason.
        """
        if not resumes:
            raise ValueError("cannot score without at least one active resume")
        scored = [self.score_job(title, description, resume,
                                 mode_mismatch=mode_mismatch,
                                 local_evidence=local_evidence)
                  for resume in resumes]
        return max(scored, key=lambda evidence: evidence["match_score"])

    def _constraints(
        self, body: str, jd_band: str, my_band: str,
        mode_mismatch: str | None = None,
        local_evidence: bool = False,
    ) -> tuple[int, list[str], str]:
        """Employment constraints that rule a posting out whatever your stack.

        Returns `(penalty, fired, verdict)` — `verdict` is the geo-verdict
        string (`eligible` / `restricted` / `excluded` / `unknown`) so
        `score_job` can use it as positive eligibility evidence.
        """
        cfg = self._vocab["penalties"]
        penalty = 0
        fired: list[str] = []

        if matching.has_term("w2 only", body):
            penalty += cfg.get("w2 only", 15)
            fired.append("w2 only")
        if matching.has_term("clearance", body) or matching.has_term("secret", body):
            penalty += cfg.get("clearance", 30)
            fired.append("clearance")
        if matching.has_term("cpt", body) or matching.has_term("opt", body):
            penalty += cfg.get("cpt", 20)
            fired.append("visa restriction")

        verdict, detail = matching.geo_verdict(
            body, self._user_country, self._vocab.get("eligibility") or {})
        if verdict == "restricted":
            penalty += cfg.get("geo_restricted", 30)
            fired.append(f"remote, but restricted to {detail}")
        elif verdict == "excluded":
            penalty += cfg.get("geo_restricted", 30)
            fired.append(f"remote, but open only to {detail}")

        if mode_mismatch:
            # run_core sends this only for the keep-and-flag rung of the
            # policy ladder: the posting states a mode the user did not
            # search for and its location could not be placed. Confirmed
            # foreign ones were dropped before scoring; local ones were
            # kept clean.
            searched = "/".join(self._user_modes) or "remote"
            penalty += cfg.get("mode_mismatch", 15)
            fired.append(f"says {mode_mismatch}, "
                         f"you searched {searched}-only")

        # An executive posting only counts against you if you are not one.
        if jd_band == "exec" and my_band != "exec":
            penalty += cfg.get("exec_penalty", 10)
            fired.append("executive role")

        return penalty, fired, verdict
