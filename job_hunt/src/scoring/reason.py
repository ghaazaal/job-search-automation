"""Reason sentences composed from scorer evidence.

The user never sees a score, only a band word and this sentence, so the
sentence carries the entire justification. Every clause is built from what the
scorer actually matched. An LLM may rephrase the output but must not be the
source of any fact here.
"""

# Cards stay readable only if the sentence stays short.
_MAX_SKILLS = 4

_SENIORITY_PHRASE = {
    "senior": "senior level",
    "junior": "junior level",
    "exec":   "executive level",
}


def _readable_list(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def compose_reason(evidence: dict) -> str:
    """Build the one-sentence explanation shown beneath a fit band.

    `evidence` is the dict returned by Scorer.score_job.
    """
    if not evidence.get("description_captured"):
        # Rule 3: nothing was compared, so claim nothing about skills.
        return ("this listing arrived without a description, so no skills "
                "have been compared against it")

    clauses: list[str] = []

    matched = list(evidence.get("matched") or [])[:_MAX_SKILLS]
    if matched:
        clauses.append(f"matches {_readable_list(matched)} from your resume")

    phrase = _SENIORITY_PHRASE.get(evidence.get("seniority", "mid"))
    if phrase:
        clauses.append(phrase)

    penalties = list(evidence.get("penalties") or [])
    if penalties:
        clauses.append(_readable_list(penalties))
    elif matched:
        # Only worth stating the absence when something else was found.
        clauses.append("no visa or clearance limits found")

    if not clauses:
        clauses.append("none of your tools were named in this posting")

    return " · ".join(clauses)
