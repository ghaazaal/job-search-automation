"""Which gaps matter most, and why, in countable terms.

The ask was to rank by market demand, relevance to the user's background
and the potential to improve employability. Each becomes one measured
signal:

    demand        postings that name the skill; a requirement counts 1,
                  a nice-to-have 0.5.
    near misses   postings where the skill is one of AT MOST TWO named
                  requirements the user lacks — the roles it would bring
                  within reach.
    background    1 when the resume shows a related skill ("builds on"),
                  because that gap closes faster.

The weighted score is internal and only orders the list (CLAUDE.md: never a
bare number). What the page says is the reason, built from the counts.
"""
from .compare import ADJACENT, HAVE

WEIGHTS = {"demand": 0.5, "near_miss": 0.3, "background": 0.2}
NEAR_MISS_MAX_MISSING = 2
TOP_GAPS = 12


def _postings(n: int) -> str:
    return f"{n} posting" if n == 1 else f"{n} postings"


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def requirement_sets(demand: list[dict]) -> dict[int, set[str]]:
    """posting -> the non-soft skills it names as requirements."""
    sets: dict[int, set[str]] = {}
    for skill in demand:
        if skill["category"] == "soft":
            continue
        for role_id in skill["required_ids"]:
            sets.setdefault(role_id, set()).add(skill["name"])
    return sets


def coverage(req_sets: dict[int, set[str]], have: set[str]) -> dict:
    """How many postings the user meets every named requirement of, and how
    many they are within one or two skills of."""
    full = within_two = 0
    for required in req_sets.values():
        missing = len(required - have)
        if missing == 0:
            full += 1
        elif missing <= NEAR_MISS_MAX_MISSING:
            within_two += 1
    return {"with_requirements": len(req_sets), "meets_all": full,
            "within_two": within_two}


def rank(market: dict, statuses: dict[str, dict], top: int = TOP_GAPS) -> dict:
    demand = market["skills"]
    total = market["postings"]
    req_sets = requirement_sets(demand)
    have = {name for name, s in statuses.items() if s["status"] == HAVE}

    near_miss: dict[str, int] = {}
    for required in req_sets.values():
        missing = required - have
        if 0 < len(missing) <= NEAR_MISS_MAX_MISSING:
            for name in missing:
                near_miss[name] = near_miss.get(name, 0) + 1

    rising = {t["name"]: t for t in
              (market.get("trends") or {}).get("rising") or []}

    candidates = []
    for skill in demand:
        status = statuses.get(skill["name"], {})
        if skill["category"] == "soft" or status.get("status") == HAVE:
            continue
        weight = skill["required"] + 0.5 * (skill["postings"] - skill["required"])
        candidates.append((skill, status, weight,
                           near_miss.get(skill["name"], 0)))
    if not candidates:
        return {"gaps": [], "coverage": coverage(req_sets, have),
                "after": None}

    max_weight = max(c[2] for c in candidates) or 1
    max_near = max(c[3] for c in candidates) or 1
    scored = []
    for skill, status, weight, near in candidates:
        adjacent = status.get("status") == ADJACENT
        score = (WEIGHTS["demand"] * weight / max_weight
                 + WEIGHTS["near_miss"] * near / max_near
                 + WEIGHTS["background"] * (1 if adjacent else 0))
        scored.append((score, skill, status, near))
    scored.sort(key=lambda t: (-t[0], -t[1]["postings"], t[1]["name"]))

    gaps = []
    for score, skill, status, near in scored[:top]:
        reasons = [f"Named in {skill['postings']} of {total} postings"
                   f" ({skill['required']} as a requirement)."]
        if near:
            reasons.append(f"One of your last {NEAR_MISS_MAX_MISSING} missing"
                           f" requirements in {_postings(near)}.")
        if status.get("status") == ADJACENT:
            related = status.get("related_to") or "a related skill"
            reasons.append(f"Builds on {related} from your resume.")
        if skill["name"] in rising:
            t = rising[skill["name"]]
            reasons.append(f"Rising: named in {_pct(t['recent'])} of recent"
                           f" postings, {_pct(t['earlier'])} before.")
        gaps.append({
            "name": skill["name"],
            "category": skill["category"],
            "status": status.get("status"),
            "how": status.get("how", ""),
            "related_to": status.get("related_to", ""),
            "resume_evidence": status.get("evidence", ""),
            "postings": skill["postings"],
            "required": skill["required"],
            "near_miss": near,
            "reasons": reasons,
            "samples": skill["samples"],
            "_score": round(score, 4),
        })

    before = coverage(req_sets, have)
    after = coverage(req_sets, have | {g["name"] for g in gaps})
    return {"gaps": gaps, "coverage": before, "after": after}
