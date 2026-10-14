"""The market view: what the stored postings ask for, counted.

No model decides a number here. Claude's one job in this module is to say
which differently-spelled names are the same skill ("AWS" / "Amazon Web
Services"), and it may only choose among names the postings produced.
Every figure the page shows is a count of postings, with the postings
behind it one click away.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta

from ..scoring.matching import has_term
from .extract import squash

OTHER_FAMILY = "Other data roles"

# Trends need two windows big enough that a share is not noise.
TREND_WINDOW_DAYS = 28
TREND_MIN_POSTINGS = 60
TREND_MIN_MENTIONS = 8
TREND_MIN_SHIFT = 0.03          # three percentage points
TREND_MIN_RATIO = 1.5

_SAMPLES = 3

MERGE_SYSTEM = """You tidy a list of skill names taken from job postings.

Some names are the same skill written differently: abbreviations, vendor prefixes, version numbers or plurals ("AWS" and "Amazon Web Services"; "Spark" and "Apache Spark"; "Data model" and "Data modeling"). Group those.

Rules:
- Only group names that mean the same skill. Related but different skills stay apart: "PySpark" is not "Apache Spark", "Azure Data Factory" is not "Azure", "Power BI" is not "Tableau", "Statistics" is not "Machine learning".
- The canonical name must be one of the names in the group, copied exactly.
- Only use names from the list. Names that need no grouping can be left out."""

MERGE_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "canonical": {"type": "string"},
                    "names": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["canonical", "names"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["groups"],
    "additionalProperties": False,
}

# Names that appear in fewer postings than this are not sent for merging;
# they cannot move a ranking and they would make the request large.
_MERGE_MIN_COUNT = 2
_MERGE_MAX_NAMES = 600


def spelling_groups(rows: list[dict]) -> dict[str, str]:
    """name -> display name, merging spellings that differ only in case,
    spacing or punctuation ("Power BI" / "PowerBI" / "power-bi").

    The display name is the most common spelling, ties to the first seen.
    """
    by_key: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        by_key[squash(row["name"])][row["name"]] += 1
    mapping = {}
    for spellings in by_key.values():
        display = spellings.most_common(1)[0][0]
        for spelling in spellings:
            mapping[spelling] = display
    return mapping


def merge_synonyms(model, counts: Counter) -> dict[str, str]:
    """Ask Claude which names are the same skill. name -> canonical.

    The answer is checked, not trusted: a group naming anything outside the
    list, or a canonical outside its own group, is ignored whole.
    """
    names = [n for n, c in counts.most_common(_MERGE_MAX_NAMES)
             if c >= _MERGE_MIN_COUNT]
    if len(names) < 2 or model is None:
        return {}
    listing = "\n".join(f"{n} ({counts[n]} postings)" for n in names)
    answer = model(system=MERGE_SYSTEM,
                   prompt="Skill names, with how many postings use each:\n"
                          + listing,
                   schema=MERGE_SCHEMA, effort="low")
    allowed = set(names)
    mapping: dict[str, str] = {}
    for group in (answer or {}).get("groups") or []:
        members = [n for n in group.get("names") or []]
        canonical = group.get("canonical")
        if (canonical not in members or not set(members) <= allowed
                or len(members) < 2):
            continue
        # A name already placed in another group keeps its first home.
        if any(m in mapping for m in members):
            continue
        for member in members:
            mapping[member] = canonical
    # The canonical is the group's most-used spelling, whatever Claude
    # picked — the page should say what most postings say.
    by_canonical = defaultdict(list)
    for member, canonical in mapping.items():
        by_canonical[canonical].append(member)
    final = {}
    for members in by_canonical.values():
        best = max(members, key=lambda m: (counts[m], -members.index(m)))
        for member in members:
            final[member] = best
    return final


def posting_date(posting: dict) -> date | None:
    for value in (posting.get("posted_date"), posting.get("first_seen")):
        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            continue
    return None


def family_of(title: str, families: list[dict]) -> str:
    lowered = (title or "").lower()
    for family in families or []:
        if any(has_term(p, lowered) for p in family.get("phrases") or []):
            return family["name"]
    return OTHER_FAMILY


def build(rows: list[dict], postings: list[dict], families: list[dict],
          names: dict[str, str]) -> dict:
    """The market snapshot.

    `rows` are skill mentions (one per posting per skill), `postings` every
    read posting (some name no skill at all, and still count in the
    denominator), `names` maps each raw name to its canonical name.
    """
    total = len(postings)
    family_by_role = {p["id"]: family_of(p["title"], families)
                      for p in postings}
    date_by_role = {p["id"]: posting_date(p) for p in postings}

    skills: dict[str, dict] = {}
    for row in rows:
        canonical = names.get(row["name"], row["name"])
        skill = skills.setdefault(canonical, {
            "name": canonical, "roles": set(), "required": set(),
            "categories": Counter(), "samples": [], "variants": set()})
        role_id = row["role_id"]
        if role_id not in family_by_role:
            continue
        skill["variants"].add(row["name"])
        skill["categories"][row["category"]] += 1
        if role_id in skill["roles"]:
            # Two spellings merged in one posting: count the posting once,
            # and keep the stronger requirement.
            if row["requirement"] == "required":
                skill["required"].add(role_id)
            continue
        skill["roles"].add(role_id)
        if row["requirement"] == "required":
            skill["required"].add(role_id)
        if len(skill["samples"]) < _SAMPLES:
            skill["samples"].append({
                "role_id": role_id, "quote": row["evidence"],
                "title": row["title"], "company": row["company"],
                "url": row["url"]})

    demand = []
    for skill in skills.values():
        if not skill["roles"]:
            continue
        demand.append({
            "name": skill["name"],
            "category": skill["categories"].most_common(1)[0][0],
            "postings": len(skill["roles"]),
            "required": len(skill["required"]),
            "share": round(len(skill["roles"]) / total, 4) if total else 0,
            "variants": sorted(skill["variants"]),
            "samples": skill["samples"],
            "role_ids": sorted(skill["roles"]),
            "required_ids": sorted(skill["required"]),
        })
    demand.sort(key=lambda s: (-s["postings"], -s["required"], s["name"]))

    dates = [d for d in date_by_role.values() if d]
    return {
        "postings": total,
        "date_from": min(dates).isoformat() if dates else None,
        "date_to": max(dates).isoformat() if dates else None,
        "skills": demand,
        "families": _families(demand, family_by_role),
        "trends": _trends(demand, date_by_role),
    }


def _families(demand: list[dict], family_by_role: dict) -> list[dict]:
    sizes = Counter(family_by_role.values())
    out = []
    for family, size in sizes.most_common():
        top = []
        for skill in demand:
            n = sum(1 for r in skill["role_ids"]
                    if family_by_role.get(r) == family)
            if n:
                top.append({"name": skill["name"], "postings": n,
                            "share": round(n / size, 4)})
        top.sort(key=lambda s: (-s["postings"], s["name"]))
        out.append({"name": family, "postings": size, "top": top[:8]})
    return out


def _trends(demand: list[dict], date_by_role: dict) -> dict:
    dated = {r: d for r, d in date_by_role.items() if d}
    if not dated:
        return {"available": False,
                "reason": "No posting carries a date, so nothing can be "
                          "compared over time."}
    newest = max(dated.values())
    cutoff = newest - timedelta(days=TREND_WINDOW_DAYS)
    recent = {r for r, d in dated.items() if d > cutoff}
    earlier = {r for r, d in dated.items() if d <= cutoff}
    if len(recent) < TREND_MIN_POSTINGS or len(earlier) < TREND_MIN_POSTINGS:
        return {"available": False,
                "reason": f"Trends need at least {TREND_MIN_POSTINGS} "
                          f"postings on each side of {cutoff.isoformat()}; "
                          f"there are {len(recent)} newer and "
                          f"{len(earlier)} older."}
    rising, falling = [], []
    for skill in demand:
        if skill["postings"] < TREND_MIN_MENTIONS:
            continue
        ids = set(skill["role_ids"])
        new_share = len(ids & recent) / len(recent)
        old_share = len(ids & earlier) / len(earlier)
        shift = new_share - old_share
        entry = {"name": skill["name"], "recent": round(new_share, 4),
                 "earlier": round(old_share, 4)}
        if shift >= TREND_MIN_SHIFT and new_share >= TREND_MIN_RATIO * old_share:
            rising.append((shift, entry))
        elif -shift >= TREND_MIN_SHIFT and old_share >= TREND_MIN_RATIO * new_share:
            falling.append((-shift, entry))
    rising.sort(key=lambda t: -t[0])
    falling.sort(key=lambda t: -t[0])
    return {"available": True, "cutoff": cutoff.isoformat(),
            "recent_postings": len(recent), "earlier_postings": len(earlier),
            "rising": [e for _, e in rising[:8]],
            "falling": [e for _, e in falling[:8]]}
