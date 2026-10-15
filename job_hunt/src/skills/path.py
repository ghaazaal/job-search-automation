"""Claude turns the ranked gaps into one ordered learning path.

The facts are fixed before Claude sees them: which skills, and why each one
(the ranking's counted reasons). Claude decides the ORDER — what has to come
first for the rest to make sense — and writes the advice: what to study, a
project that uses what the user already knows, and how to show it. Advice
is allowed to be Claude's; facts are not. So the answer is checked:

- a stage may only hold skills from the ranked list (anything else is cut),
- every ranked skill ends up placed or explicitly left out with a reason,
- links are stripped — a URL Claude remembers may not exist.
"""
import re

EFFORTS = ("small", "medium", "large")
MAX_STAGES = 6

SYSTEM = """You are a career coach for data professionals. You turn a ranked list of skill gaps into one learning path.

You receive the candidate's current skills and a ranked list of skills to develop, each with the reasons it was ranked (counts from real job postings). Build a path of up to 6 stages; with only a few skills, use only as many stages as they need:
- Order stages so that each one builds on the previous ones and on skills the candidate already has. Foundations first.
- Group skills that are naturally learned together; a stage holds 1 to 3 skills.
- Use only skill names from the ranked list, written exactly as given. You may leave a ranked skill out if it does not fit; say why in left_out.
- goal: what the candidate can do at the end of the stage, in one sentence.
- why_now: one sentence on why this stage comes at this point in the order.
- learn: 3 to 5 concrete topics to study.
- project: one hands-on project that combines the stage's skills with skills the candidate already has.
- show_it: one sentence on how to show it on a resume or portfolio.
- effort: small, medium or large, a rough relative size.

Write plainly, for someone reading quickly. Do not cite numbers other than those you were given. Do not include links or name specific paid courses; you may point to a tool's official documentation by name."""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "stages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "goal": {"type": "string"},
                    "why_now": {"type": "string"},
                    "learn": {"type": "array", "items": {"type": "string"}},
                    "project": {"type": "string"},
                    "show_it": {"type": "string"},
                    "effort": {"type": "string", "enum": list(EFFORTS)},
                },
                "required": ["title", "skills", "goal", "why_now", "learn",
                             "project", "show_it", "effort"],
                "additionalProperties": False,
            },
        },
        "left_out": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"skill": {"type": "string"},
                               "reason": {"type": "string"}},
                "required": ["skill", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "stages", "left_out"],
    "additionalProperties": False,
}

_URL = re.compile(r"\(?\bhttps?://\S+|\bwww\.\S+", re.IGNORECASE)


def _text(value, limit: int = 600) -> str:
    cleaned = _URL.sub("", str(value or ""))
    return " ".join(cleaned.split())[:limit]


def prompt(gaps: list[dict], resume: dict, strengths: list[str],
           focus: str | None = None, intro: str | None = None) -> str:
    lines = []
    if intro:
        lines += [intro, ""]
    elif focus:
        lines += [f"This path is for {focus} roles. The counts below come "
                  f"from {focus} postings only.", ""]
    lines.append("Candidate:")
    lines.append(f"- Seniority: {resume.get('seniority') or 'not stated'}")
    roles = [r.get("title", "") for r in resume.get("target_roles") or []]
    if roles:
        lines.append("- Target roles: " + ", ".join(roles))
    lines.append("- Skills on the resume: " + ", ".join(
        s.get("name", "") for s in resume.get("skills") or []))
    if strengths:
        lines.append("- In-demand skills the candidate already has: "
                     + ", ".join(strengths))
    lines.append("")
    lines.append("Ranked skills to develop (most important first):")
    for i, gap in enumerate(gaps, 1):
        lines.append(f"{i}. {gap['name']} ({gap['category']}) — "
                     + " ".join(gap["reasons"]))
    return "\n".join(lines)


def validate(answer: dict, gaps: list[dict]) -> dict:
    """Keep only what the ranking supports; place every ranked skill."""
    by_key = {g["name"].lower(): g["name"] for g in gaps}
    placed: set[str] = set()
    stages = []
    for raw in (answer or {}).get("stages") or []:
        skills = []
        for name in raw.get("skills") or []:
            canonical = by_key.get(str(name).strip().lower())
            if canonical and canonical not in placed:
                placed.add(canonical)
                skills.append(canonical)
        if not skills:
            continue
        stages.append({
            "title": _text(raw.get("title"), 120),
            "skills": skills,
            "goal": _text(raw.get("goal")),
            "why_now": _text(raw.get("why_now")),
            "learn": [_text(t, 200) for t in raw.get("learn") or [] if _text(t)][:6],
            "project": _text(raw.get("project"), 900),
            "show_it": _text(raw.get("show_it")),
            "effort": raw.get("effort") if raw.get("effort") in EFFORTS
            else "medium",
        })
        if len(stages) == MAX_STAGES:
            break

    left_out = []
    for raw in (answer or {}).get("left_out") or []:
        canonical = by_key.get(str(raw.get("skill", "")).strip().lower())
        if canonical and canonical not in placed:
            placed.add(canonical)
            left_out.append({"skill": canonical,
                             "reason": _text(raw.get("reason"), 300)})
    for gap in gaps:
        if gap["name"] not in placed:
            left_out.append({"skill": gap["name"],
                             "reason": "Not placed in a stage by the planner."})
    return {"summary": _text((answer or {}).get("summary"), 900),
            "stages": stages, "left_out": left_out}


def build_path(model, gaps: list[dict], resume: dict,
               strengths: list[str], focus: str | None = None,
               intro: str | None = None) -> dict:
    if not gaps:
        return {"summary": "", "stages": [], "left_out": []}
    answer = model(system=SYSTEM,
                   prompt=prompt(gaps, resume, strengths, focus, intro),
                   schema=SCHEMA, effort="medium")
    return validate(answer, gaps)
