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

# A word that turns the country name after it into a different place.
# "Northern Ireland" is not Ireland. Word-bounded matching stops
# "Irelander"; it does nothing about what comes before.
_ALIAS_PREFIX_TRAPS = ("northern",)


def scope_verdict(text: str, user_country: str,
                  cfg: dict, geo_cfg: dict) -> str:
    """Read a board's location field for one user.

    `cfg` is vocabulary.yaml's `location_scope`; `geo_cfg` is its
    `eligibility` section, which owns the country name and code tables
    AND the region table. Both are needed: there must be one spelling
    of every country and one definition of every region in the
    product, and both live under `eligibility` — `eligibility.regions`
    already encodes a reviewed judgment call (the Caucasus and Turkey
    are deliberately excluded from "Europe" but included in "EMEA");
    this parser must defer to that, not keep a second, conflicting copy.

    Checked in order: an unambiguous worldwide phrase wins outright; then
    a timezone band, because "CET (+/- 3 hours)" also contains no country
    name and would otherwise fall through to unknown; then named regions;
    then country names and codes; and last of all the bare word
    "anywhere", which is worldwide only when nothing above claimed the
    field. Anything unrecognised claims nothing.

    Region membership is eligible-only evidence, same discipline as
    `geo_verdict`: a region the field names but that does not list the
    user's country stays "unknown", not "closed" — `eligibility.regions`
    documents itself as non-exhaustive (a region can genuinely include a
    country it doesn't enumerate), so absence from a partial list is not
    evidence of exclusion. "closed" is reserved for the bare-country-name
    path below, where the field names one specific country and resolving
    it against the user's own is a confident, positive comparison rather
    than an argument from silence.
    """
    text = (text or "").strip().lower()
    user = (user_country or "").strip().lower()
    if not text or not user:
        return "unknown"
    cfg = cfg or {}
    geo_cfg = geo_cfg or {}

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
        # Anchor or user offset unknown: this branch has nothing to say,
        # so it says nothing and lets the region and country checks below
        # try. Returning "unknown" here took the whole field down —
        # `timezone_anchors` lists six zones, so a board writing IST or
        # AEST silenced any country list in the same string.

    region_named = False
    for region in geo_cfg.get("regions") or []:
        names = [str(n).strip().lower() for n in (region.get("names") or [])]
        if not any(re.search(bounded(n), text) for n in names if n):
            continue
        region_named = True
        codes = {str(c).strip().lower() for c in (region.get("codes") or [])}
        if user in codes:
            return "open"
    # A named region matched but did not list the user, or no region
    # matched at all — both fall through to the country-name check
    # rather than returning here, since region absence never claims
    # exclusion on its own (see docstring).

    # Country names. Reuse the eligibility country tables so there is one
    # spelling of every country in the product — but NOT
    # `location_country`, which answers a different question.
    #
    # `location_country` reads a single job's place and takes the
    # RIGHTMOST country, because a location string ends with its country
    # ("Tbilisi, Georgia"). A reach field is an ENUMERATION of the places
    # an employer will hire from, and the rightmost one is meaningless.
    # A live run returned "Armenia, Cyprus, Georgia, Kazakhstan, Poland";
    # rightmost-wins resolved that to Poland and called it closed to an
    # Armenian user whose country is named in the string. The verdict
    # even flipped on word order — "Poland, Armenia" came back open.
    #
    # So scan for every country the text names and test membership, the
    # same way the region branch above does.
    named = _countries_named(text, geo_cfg)
    if user in named:
        return "open"
    if named:
        return "closed"

    # The bare word "anywhere", last of all. It is genuinely worldwide on
    # Remotive and Jobicy, which publish it alone — but it is also the
    # first word of "Anywhere in the United States", a live value and
    # exactly the US-only posting rule 6d exists to exclude. Grouped with
    # the certain phrases above it matched first and returned open to an
    # Armenian user. Here it fires only once no country and no region has
    # claimed the field: a qualified "anywhere" defers to its qualifier,
    # and "Anywhere in Europe" stays unknown rather than open, because
    # `eligibility.regions` deliberately leaves the Caucasus out of
    # "Europe" and region absence never claims exclusion either.
    if not region_named:
        for phrase in cfg.get("worldwide_unqualified") or []:
            if re.search(bounded(str(phrase).strip().lower()), text):
                return "open"
    return "unknown"


def _countries_named(text: str, geo_cfg: dict) -> set[str]:
    """Every country code the text names, word-bounded.

    Two guards the previous docstring claimed and the code did not have.

    `eligibility.ambiguous_names` is honoured, the same way `geo_verdict`
    honours it: a name that collides with an ordinary English word counts
    only when written with its article. "Anywhere in **the US**" names the
    country; "Remote - come join us" does not. Dropping the alias outright
    would have been simpler and wrong — it turned "Anywhere in the US"
    back into an open field for every non-US user, which is the exact
    failure Ship 7's review fixed.

    And word-bounding does not stop a preceding word: `ireland` matches
    inside "Northern Ireland", which is a different place. An alias
    preceded by a trap word does not count.
    """
    ambiguous = {str(n).strip().lower()
                 for n in (geo_cfg.get("ambiguous_names") or [])}
    found: set[str] = set()
    for code, aliases in (geo_cfg.get("countries") or {}).items():
        for alias in aliases or ():
            alias = str(alias).strip().lower()
            if not alias:
                continue
            pattern = (r"(?<!\w)the\s+" + re.escape(alias) + r"(?!\w)"
                       if alias in ambiguous else bounded(alias))
            match = re.search(pattern, text)
            if not match:
                continue
            before = text[:match.start()].rstrip()
            if any(before.endswith(trap) for trap in _ALIAS_PREFIX_TRAPS):
                continue
            found.add(str(code).strip().lower())
            break
    return found
