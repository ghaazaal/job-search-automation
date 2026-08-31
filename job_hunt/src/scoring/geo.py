"""Is this place the user's? Dataset-backed, membership-only.

The question this module answers is deliberately smaller than "which
country is this location in". Eligibility never needs to know WHICH
Dublin a posting means: every Dublin on earth is not Armenia, so for an
Armenian user the answer is "foreign" without disambiguating. Ambiguity
only matters when one candidate IS the user's own country — and then the
honest answer is silence, the same rule the phrase matchers follow.

That reframing (the user's, 2026-08-28) is what makes a 34,000-city
dataset safe to use. A resolver forced to pick one country would call
"Dublin, CA" Ireland, because Dublin, Ireland is the biggest Dublin; a
membership test never has to pick.

Data comes from two offline packages, not an API: `pycountry` (ISO 3166,
249 countries) and `geonamescache` (cities over 15k population). No
network at scoring time, no key, no rate limit, reproducible runs. The
hand-kept `eligibility.countries` aliases still participate — they carry
spellings postings actually use ("UK", "USA") that ISO names lack.

`location_relation` returns:
    "local"   — every place the string names is in the user's country
    "foreign" — the string names places, and none can be the user's
    None      — no recognisable place, or ambiguity touching the user
"""
import re
import unicodedata
from functools import lru_cache

# Compiled once; a location is short but this runs per stored row.
_SPLIT_RE = re.compile(r"[,;/|]")
_WORD_RE = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.U)

# Noise that wraps a city name in LinkedIn's metro phrasings:
# "Greater Hyderabad Area", "New York City Metropolitan Area",
# "Warsaw Metropolitan Area", "Hanoi Capital Region".
_STRIP_PREFIXES = ("greater ",)
_STRIP_SUFFIXES = (
    " metropolitan area", " metropolitan region", " statistical region",
    " capital region", " metro area", " bay area", " area", " region",
    " sar",
)

_MAX_NGRAM = 4


def _fold(text: str) -> str:
    """Lowercase and strip accents, so "Cañon" matches "Canon" and
    "Türkiye" matches however the dataset spells it."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # Hyphens split places ("Pueblo-Cañon City Area" is Pueblo and Cañon
    # City), and treating them as word glue hid the second name entirely.
    return text.replace("-", " ").lower()


@lru_cache(maxsize=1)
def _country_names() -> dict[str, set[str]]:
    """Folded country name -> {iso2}. ISO names plus common variants."""
    import pycountry

    names: dict[str, set[str]] = {}

    def add(name, code):
        name = _fold(str(name).strip())
        if name:
            names.setdefault(name, set()).add(code.lower())

    for c in pycountry.countries:
        add(c.name, c.alpha_2)
        for attr in ("common_name", "official_name"):
            if hasattr(c, attr):
                add(getattr(c, attr), c.alpha_2)
        # "Iran, Islamic Republic of" is also just "Iran".
        if "," in c.name:
            add(c.name.split(",")[0], c.alpha_2)
    return names


@lru_cache(maxsize=1)
def _city_names() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(single-word cities, multi-word cities), folded name -> {iso2}.

    Split because they carry different risk. A multi-word name ("san
    francisco", "buenos aires") is safe to find anywhere in the string —
    prose does not produce it by accident. A single-word name collides
    with ordinary words ("Nice", "Mobile", "Best" and "Split" are all
    real cities over 15k people), so it may only match a whole segment.
    """
    import geonamescache

    single: dict[str, set[str]] = {}
    multi: dict[str, set[str]] = {}
    for city in geonamescache.GeonamesCache().get_cities().values():
        name = _fold(city["name"].strip())
        if not name:
            continue
        code = city["countrycode"].lower()
        target = multi if " " in name else single
        target.setdefault(name, set()).add(code)
    return single, multi


def _segments(location: str) -> list[str]:
    """Comma-ish segments, metro noise stripped, folded."""
    out = []
    for seg in _SPLIT_RE.split(location):
        seg = _fold(seg).strip()
        for prefix in _STRIP_PREFIXES:
            if seg.startswith(prefix):
                seg = seg[len(prefix):]
        for suffix in _STRIP_SUFFIXES:
            if seg.endswith(suffix):
                seg = seg[: -len(suffix)]
        seg = seg.strip()
        if seg:
            out.append(seg)
    return out


def location_candidates(location: str, cfg: dict) -> set[str]:
    """Every country the location could plausibly be in, as iso2 codes.

    Sources, all additive:
    - the hand-kept `eligibility.countries` aliases, word-bounded per
      segment (they carry "uk", "usa", "u.s." — spellings ISO lacks);
    - ISO country names, whole-segment;
    - US state names and tail codes, resolving to "us" (the existing
      tail discipline: "Dublin, CA" ends in a state code);
    - city names: whole-segment for single words, anywhere in the
      string for multi-word names.

    Two tiers, not one pool. An explicit COUNTRY or US-state name is a
    stronger claim than a city that happens to share a name: "Armenia" is
    also a city of 300,000 in Colombia, and pooling it with the country
    made the parser go silent on an Armenian user's own country. So city
    names only speak when no country or state was named at all — the tier
    where "Springfield" and "Greater Hyderabad Area" live.

    A US state name that is also a country ("georgia") contributes BOTH
    tier-one candidates — the membership test is what keeps that honest,
    and "Atlanta, Georgia" stays silent for a Georgian user exactly as
    the hand parser always did.
    """
    if not location or not str(location).strip():
        return set()
    cfg = cfg or {}
    raw = str(location)
    folded = _fold(raw)
    segments = _segments(raw)
    found: set[str] = set()

    countries = _country_names()
    single_cities, multi_cities = _city_names()

    # Hand-kept aliases, word-bounded — a segment like "remote - usa"
    # still names the US even though the segment is not exactly "usa".
    for code, aliases in (cfg.get("countries") or {}).items():
        for alias in aliases or ():
            alias = _fold(str(alias).strip())
            if alias and re.search(
                    r"(?<!\w)" + re.escape(alias) + r"(?!\w)", folded):
                found.add(str(code).strip().lower())
                break

    state_names = {_fold(str(s)) for s in cfg.get("us_state_names") or []}
    state_codes = {str(s).strip().lower() for s in cfg.get("us_states") or []}

    for seg in segments:
        if seg in countries:
            found |= countries[seg]
        if seg in state_names:
            found.add("us")

    # Tail state code: "Dublin, CA", "Bolingbrook, IL 60440".
    tail = segments[-1] if segments else ""
    code_match = re.fullmatch(r"([a-z]{2})(?:\s+\d{5})?", tail)
    if code_match and code_match.group(1) in state_codes:
        found.add("us")

    if found:
        return found

    # Tier two: city names, only when nothing named a country. Whole
    # segments for single-word names, n-grams anywhere for multi-word.
    for seg in segments:
        if seg in single_cities:
            found |= single_cities[seg]
    words = _WORD_RE.findall(folded)
    for n in range(2, _MAX_NGRAM + 1):
        for i in range(len(words) - n + 1):
            gram = " ".join(words[i:i + n])
            if gram in multi_cities:
                found |= multi_cities[gram]

    return found


def location_relation(location: str | None, user_country: str,
                      cfg: dict) -> str | None:
    """"local", "foreign", or None — see the module docstring."""
    user = (user_country or "").strip().lower()
    if not user or not location:
        return None
    candidates = location_candidates(str(location), cfg)
    if not candidates:
        return None
    if user not in candidates:
        return "foreign"
    if candidates == {user}:
        return "local"
    # The user's country is one reading among several. Might be theirs,
    # might not: silence, never a guess.
    return None
