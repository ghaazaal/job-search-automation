"""Opportunity maps — scored jobs regrouped around the company.

The product's core reframe: the user does not review a list of postings, they
review a short ranked list of companies, each carrying the roles that made it
relevant. Spec rules 4-7 live here.
"""
ACT_NOW = "ACT_NOW"
WATCH = "WATCH"
DISCOVER = "DISCOVER"

# Rule 7 — act now above discover, watch last.
_STATE_RANK = {ACT_NOW: 0, DISCOVER: 1, WATCH: 2}


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def _company_why(roles: list[dict], best: dict) -> str:
    """One line of evidence for why this company is in the list at all."""
    n = len(roles)
    noun, verb = ("role", "matches") if n == 1 else ("roles", "match")
    lead = f"{n} {noun} {verb} your target titles"
    matched = [m for r in roles for m in (r.get("matched") or [])]
    if matched:
        return f"{lead}, naming {matched[0]} among others"
    if not best.get("description_captured"):
        return f"{lead}, descriptions not captured yet"
    return lead


def build_maps(scored_jobs: list[dict],
               shortlist_min: int = 7,
               watched: list[str] | None = None,
               hidden: list[str] | None = None) -> list[dict]:
    """Group scored jobs into ranked, company-centred opportunity maps.

    Args:
        scored_jobs:   job dicts merged with their Scorer evidence.
        shortlist_min: internal score at which a company becomes ACT_NOW.
        watched:       company names the user explicitly watches.
        hidden:        company names the user has hidden.
    """
    watched_set = {_norm(w) for w in (watched or [])}
    hidden_set = {_norm(h) for h in (hidden or [])}

    grouped: dict[str, dict] = {}
    for job in scored_jobs:
        key = _norm(job.get("company"))
        if not key or key in hidden_set:
            continue
        entry = grouped.setdefault(key, {"name": job.get("company"), "roles": []})
        entry["roles"].append(job)

    maps: list[dict] = []
    for key, entry in grouped.items():
        # Strongest role leads the card.
        roles = sorted(entry["roles"],
                       key=lambda r: -(r.get("match_score") or 0))
        best = roles[0]
        state = (ACT_NOW if (best.get("match_score") or 0) >= shortlist_min
                 else DISCOVER)
        maps.append({
            "name":  entry["name"],
            "state": state,
            "why":   _company_why(roles, best),
            "roles": roles,
            "_rank": best.get("match_score") or 0,
        })

    # Rule 5 — a watched company with no current role is a different shape.
    represented = {_norm(m["name"]) for m in maps}
    for name in (watched or []):
        if _norm(name) in represented or _norm(name) in hidden_set:
            continue
        maps.append({
            "name":  name,
            "state": WATCH,
            "why":   "had a matching role previously, none open right now",
            "roles": [],
            "_rank": 0,
        })

    maps.sort(key=lambda m: (_STATE_RANK[m["state"]], -m["_rank"],
                             _norm(m["name"])))
    return maps
