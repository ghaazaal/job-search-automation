"""Sorting and filtering the opportunity map.

The user's own choice of what to look at, applied after the store has
ranked and grouped. Nothing here is a policy rule: the three hiding
exceptions in CLAUDE.md live in the store and are counted in the header.
A filter only narrows what the user asked to narrow, and the page says
how many companies it set aside.

Filters test ROLES, not companies. A company stays if any of its roles
passes, its card shows its best remaining role, and its role count is
the roles that passed. Testing the company instead would show a card
whose role is the one the filter asked to leave out.

Every value is read from fields the store already holds — band, posted
date, work mode, platform, location scope — or derived the same way the
scorer and the learning path derive it (`seniority_band`, `family_of`),
so a filter can never disagree with the reason sentence on the card.
"""
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import yaml

from .scoring.matching import seniority_band
from .skills.market import OTHER_FAMILY, family_of

VOCABULARY_PATH = Path(__file__).resolve().parent.parent / "vocabulary.yaml"

# Option tables: value in the URL -> label on the page. The first entry
# of SORTS is the store's own ranking and the default.
SORTS = {"fit": "BEST FIT", "newest": "NEWEST POSTED",
         "company": "COMPANY A-Z", "roles": "MOST OPEN ROLES"}
FITS = {"strong": "STRONG FIT", "partial": "STRONG OR PARTIAL",
        "unchecked": "NOT CHECKED YET"}
POSTED = {"7": "PAST 7 DAYS", "30": "PAST 30 DAYS"}
REACH = {"open": "PROVEN OPEN TO YOU", "unverified": "NOT VERIFIED"}
# The scorer reads a title with no level word as mid, so the filter
# does too — but says so, rather than claiming the posting said "mid".
LEVELS = {"junior": "JUNIOR", "mid": "MID OR UNSTATED",
          "senior": "SENIOR", "exec": "EXEC"}
NO_MODE = "unstated"

FILTER_KEYS = ("fit", "posted", "mode", "kind", "level", "reach", "board",
               "q")


@lru_cache(maxsize=1)
def _vocabulary() -> dict:
    with open(VOCABULARY_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def parse(args) -> dict:
    """Read the view from query parameters. Unknown sorts and closed-set
    values fall back to "no filter" rather than to an empty map."""
    def pick(key, allowed):
        value = (args.get(key) or "").strip()
        return value if value in allowed else ""

    since = (args.get("since") or "").strip()
    return {
        "sort": pick("sort", SORTS) or "fit",
        "fit": pick("fit", FITS),
        "posted": pick("posted", POSTED),
        "level": pick("level", LEVELS),
        "reach": pick("reach", REACH),
        # Open sets: whatever the data holds. An unknown value matches
        # nothing, and the header says 0 of N with a way back.
        "mode": (args.get("mode") or "").strip(),
        "kind": (args.get("kind") or "").strip(),
        "board": (args.get("board") or "").strip(),
        "q": (args.get("q") or "").strip()[:80],
        "since": int(since) if since.isdigit() else None,
    }


def is_active(view: dict | None) -> bool:
    """Whether the view differs from the plain map."""
    if not view:
        return False
    return view.get("sort", "fit") != "fit" or any(view.get(k)
                                                   for k in FILTER_KEYS)


def _posted(role: dict) -> date | None:
    try:
        return datetime.strptime(str(role.get("date"))[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _day(role: dict) -> int:
    """Posting day as a number for sorting; undated sorts last."""
    return (_posted(role) or date.min).toordinal()


def kind_of(role: dict, vocab: dict | None = None) -> str:
    vocab = _vocabulary() if vocab is None else vocab
    return family_of(role.get("title") or "", vocab.get("role_families") or [])


def level_of(role: dict, vocab: dict | None = None) -> str:
    vocab = _vocabulary() if vocab is None else vocab
    return seniority_band(role.get("title") or "", vocab.get("seniority") or {})


def _mode_of(role: dict) -> str:
    return (role.get("work_mode") or "").strip().lower() or NO_MODE


def _keeps(role: dict, view: dict, today: date, vocab: dict) -> bool:
    fit = view.get("fit")
    captured = bool(role.get("description_captured"))
    if fit == "strong" and not (captured and role.get("band") == "STRONG FIT"):
        return False
    if fit == "partial" and not (captured and role.get("band")
                                 in ("STRONG FIT", "PARTIAL FIT")):
        return False
    if fit == "unchecked" and captured:
        return False

    if view.get("posted"):
        # An unreadable date cannot be claimed as recent.
        posted = _posted(role)
        if posted is None or (today - posted).days > int(view["posted"]):
            return False

    if view.get("mode") and _mode_of(role) != view["mode"].lower():
        return False

    reach = view.get("reach")
    scope = role.get("location_scope")
    if reach == "open" and scope != "open":
        return False
    if reach == "unverified" and scope not in (None, "unknown"):
        return False

    if view.get("board") and (role.get("platform") or "") != view["board"]:
        return False
    if view.get("kind") and kind_of(role, vocab) != view["kind"]:
        return False
    if view.get("level") and level_of(role, vocab) != view["level"]:
        return False
    return True


def apply(maps: list[dict], view: dict | None, today: date | None = None,
          vocab: dict | None = None) -> list[dict]:
    """The maps the view asks for, in the order it asks for.

    Watched companies with nothing open carry no roles to test and are
    passed through untouched — they are a shelf, not a result."""
    if not is_active(view):
        return maps
    today = today or date.today()
    vocab = _vocabulary() if vocab is None else vocab
    needle = (view.get("q") or "").casefold()

    out = []
    for m in maps:
        if not m.get("roles"):
            out.append(m)
            continue
        if needle and needle not in (m.get("name") or "").casefold():
            continue
        roles = [r for r in m["roles"] if _keeps(r, view, today, vocab)]
        if not roles:
            continue
        if view.get("sort") == "newest":
            # Stable: equally new roles keep their fit order.
            roles = sorted(roles, key=lambda r: -_day(r))
        out.append({**m, "roles": roles, "roles_total": len(m["roles"])})

    # Python's sort is stable, so every tie keeps the store's ranking.
    sort = view.get("sort")
    if sort == "newest":
        out.sort(key=lambda m: -max((_day(r) for r in m.get("roles") or []),
                                    default=0))
    elif sort == "company":
        out.sort(key=lambda m: (m.get("name") or "").casefold())
    elif sort == "roles":
        out.sort(key=lambda m: -len(m.get("roles") or []))
    return out


def options(maps: list[dict], vocab: dict | None = None) -> dict:
    """The open-set choices present in the unfiltered map, so a menu never
    offers a value that would match nothing."""
    vocab = _vocabulary() if vocab is None else vocab
    roles = [r for m in maps for r in m.get("roles") or []]

    modes = sorted({_mode_of(r) for r in roles} - {NO_MODE})
    if any(_mode_of(r) == NO_MODE for r in roles):
        modes.append(NO_MODE)

    present = {kind_of(r, vocab) for r in roles}
    kinds = [f["name"] for f in vocab.get("role_families") or []
             if f["name"] in present]
    if OTHER_FAMILY in present:
        kinds.append(OTHER_FAMILY)

    levels_present = {level_of(r, vocab) for r in roles}
    return {
        "mode": modes,
        "kind": kinds,
        "level": [k for k in LEVELS if k in levels_present],
        "board": sorted({r.get("platform") for r in roles
                         if r.get("platform")}, key=str.casefold),
    }
