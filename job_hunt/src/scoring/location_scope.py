"""What a remote board's reach field says, judged for one user.

Indeed and LinkedIn make you mine 8KB of prose for this. Remote boards
publish it as a field, because being borderless is their product:

    "Anywhere in the World"
    "Europe, North America, Latin America, APAC"
    "Time zone: CET (+/- 3 hours)"
    "United States"

Returns "open", "closed" or "unknown". Silence is the default and an
unset user country claims nothing, the same discipline `geo_verdict`
follows — this parser is allowed to be certain only when the field
actually says something.
"""
import re

from .matching import bounded, location_country

_BAND_RE = re.compile(
    r"\b([a-z]{2,4})\s*\(\s*\+/-\s*(\d+)\s*(?:hours?|hrs?)?\s*\)", re.I)


def scope_verdict(text: str, user_country: str,
                  cfg: dict, geo_cfg: dict) -> str:
    """Read a board's location field for one user.

    `cfg` is vocabulary.yaml's `location_scope`; `geo_cfg` is its
    `eligibility` section, which owns the country name and code tables.
    Both are needed: there must be one spelling of every country in the
    product, and it lives under `eligibility`.

    Checked in order: worldwide wins outright; then a timezone band,
    because "CET (+/- 3 hours)" also contains no country name and would
    otherwise fall through to unknown; then named regions; then country
    names and codes. Anything unrecognised claims nothing.
    """
    text = (text or "").strip().lower()
    user = (user_country or "").strip().lower()
    if not text or not user:
        return "unknown"
    cfg = cfg or {}

    for phrase in cfg.get("worldwide") or []:
        if re.search(bounded(str(phrase).strip().lower()), text):
            return "open"

    band = _BAND_RE.search(text)
    if band:
        anchors = {str(k).lower(): int(v)
                   for k, v in (cfg.get("timezone_anchors") or {}).items()}
        offsets = {str(k).lower(): int(v)
                   for k, v in (cfg.get("country_utc_offset") or {}).items()}
        anchor, span = band.group(1).lower(), int(band.group(2))
        if anchor in anchors and user in offsets:
            centre = anchors[anchor]
            return ("open" if abs(offsets[user] - centre) <= span
                    else "closed")
        return "unknown"

    regions = {str(k).lower(): [str(c).lower() for c in (v or [])]
               for k, v in (cfg.get("regions") or {}).items()}
    named = [name for name in regions if re.search(bounded(name), text)]
    if named:
        return ("open" if any(user in regions[name] for name in named)
                else "closed")

    # A bare country name or code. Reuse the eligibility country tables
    # so there is one spelling of every country in the product.
    place = location_country(text, geo_cfg or {})
    if place:
        return "open" if place == user else "closed"
    return "unknown"
