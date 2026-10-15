"""Job deduplication — URL normalization plus a company/title fingerprint.

Matching on raw URLs alone let ~13% of the tracker fill with duplicates: the
same posting arrives from Indeed and LinkedIn under different URLs, LinkedIn
mirrors each job across country subdomains, and boards append per-scrape
tracking parameters.
"""
import re
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Params that identify the *referrer*, not the posting. Everything else is
# preserved — gh_jid, id, req and friends are the posting's identity, and
# dropping them would collapse every job on a board into one entry.
_TRACKING_PARAMS = {
    "source", "src", "lever-source", "jobsite", "jbsrc", "gclid", "trk",
    "refid", "trackingid", "position", "pagenum", "ebp", "savedsearchid",
    "originalsubdomain", "recommendedflavor", "eid", "applyurl",
}

_LINKEDIN_HOST = re.compile(r"^([a-z]{2}\.|www\.)?linkedin\.com$")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
# Legal suffixes vary between boards for the same employer.
_COMPANY_SUFFIXES = re.compile(
    r"\b(inc|llc|ltd|limited|corp|corporation|co|gmbh|bv|plc|sa|ag|pty|group)\b")


def normalize_url(url: str) -> str:
    """Collapse cosmetic URL differences so the same posting compares equal."""
    if not url or not url.strip():
        return ""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if ":" in host:                       # drop default ports
        host = host.split(":", 1)[0]

    # LinkedIn mirrors each posting on every country subdomain.
    if _LINKEDIN_HOST.match(host):
        host = "linkedin.com"
    elif host.startswith("www."):
        host = host[4:]

    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS
            and not k.lower().startswith("utm_")]
    query = urlencode(sorted(kept))

    path = parts.path.rstrip("/") or "/"
    # Scheme and fragment carry no identity.
    return urlunsplit(("https", host, path, query, ""))


def _norm_text(value: str) -> str:
    text = _PUNCT_RE.sub(" ", str(value or "").lower())
    return _WS_RE.sub(" ", text).strip()


# Title segments are split on a spaced dash or a pipe; "Data-Engineer" and
# "BI/Data Engineer" stay whole.
_TITLE_SEGMENTS = re.compile(r"\s+[-–—]\s+|\s*\|\s*")
_PARENS = re.compile(r"\(([^()]*)\)")
# A posting's own reference number: BairesDev lists one job per country,
# each under its own "REF#302087", which made every copy look new.
_REF_CODE = re.compile(r"\b(?:ref|req|job\s*id)\s*[#:]?\s*\w*\d\w*", re.I)
# Words that say where or how the job is worked, never which job it is.
# "Contract" and "freelance" are left out on purpose: they change the job.
_MODE_WORDS = {"remote", "work", "fully", "100", "hybrid", "onsite", "on",
               "site", "flexible", "worldwide", "anywhere", "wfh", "from",
               "home", "global", "language", "speaker", "speaking", "native"}
_TITLE_WORDS = {"sr": "senior", "jr": "junior"}


@lru_cache(maxsize=1)
def _language_names() -> frozenset[str]:
    """Folded names of the ~180 languages with a two-letter ISO code."""
    import pycountry
    names = {"odia", "punjabi", "greek", "farsi", "bangla", "mandarin",
             "cantonese", "filipino", "tagalog"}
    for lang in pycountry.languages:
        if not hasattr(lang, "alpha_2"):
            continue
        for name in (lang.name, getattr(lang, "common_name", "")):
            name = re.sub(r"\(.*?\)", "", name or "").split(";")[0]
            name = _norm_text(name)
            if name:
                names.add(name)
    return frozenset(names)


def _is_variant(segment: str, raw: str = "") -> bool:
    """True when a title segment names only a place, a language, a work
    mode or a reference code - what one copy of a job differs from the
    next copy by, not what the job is.

    TELUS Digital posted "Online Data Analyst - Bengali (IN)", "- English
    (AU)", "- Czech (CZ)" and four more; each read as its own role.
    """
    from ..scoring.geo import _country_names
    text = _norm_text(_REF_CODE.sub(" ", segment))
    if not text or text.isdigit():
        return True
    # A bare two-letter code is a country only when the posting wrote it
    # in capitals - "(IN)" is India, "in" is a word.
    if re.fullmatch(r"[A-Z]{2}", raw.strip()):
        return True
    words = [w for w in text.split() if w not in _MODE_WORDS]
    if not words:
        return True
    rest = " ".join(words)
    return rest in _language_names() or rest in _country_names()


def title_key(title: str) -> str:
    """A title with its per-copy noise removed, for duplicate checks only.

    Distinctions that change the job survive: "(Azure)" vs "(Python)",
    "Engineer III - Platform Data Engineer" vs "- FinOps Data Analytics".
    """
    title = str(title or "")
    title = _PARENS.sub(
        lambda m: " " if _is_variant(m.group(1), m.group(1)) else m.group(0),
        title)
    kept = [seg for seg in _TITLE_SEGMENTS.split(title)
            if not _is_variant(_PARENS.sub(" ", seg), seg)]
    text = _norm_text(" ".join(kept) if kept else title)
    return " ".join(_TITLE_WORDS.get(w, w) for w in text.split())


def fingerprint(job: dict) -> str:
    """Identity of a posting independent of which board it came from.

    Location is deliberately excluded: remote roles are mirrored per-country
    with differing location strings, and including it would defeat the point.
    """
    company = _norm_text(job.get("company") or job.get("Company") or "")
    company = _WS_RE.sub(" ", _COMPANY_SUFFIXES.sub("", company)).strip()
    title = title_key(job.get("title") or job.get("Job Title") or "")
    return f"{company}|{title}"


def dedupe(jobs: list[dict],
           existing_urls: list[str] | None = None,
           existing_rows: list[dict] | None = None) -> list[dict]:
    """Return the unseen jobs from `jobs`, collapsing duplicates.

    Args:
        jobs:           Freshly scraped job dicts.
        existing_urls:  Apply links already in the tracker.
        existing_rows:  Tracker rows, used to fingerprint prior jobs whose URL
                        has since changed (reposts).

    When two candidates collide, the one carrying a description wins — scoring
    now depends on that text.
    """
    seen_urls = {normalize_url(u) for u in (existing_urls or [])}
    seen_urls.discard("")
    seen_fps = {fingerprint(r) for r in (existing_rows or [])}
    seen_fps.discard("|")

    kept: dict[str, dict] = {}          # fingerprint -> winning job
    order: list[str] = []
    url_owner: dict[str, str] = {}      # normalised url -> that fingerprint

    for job in jobs:
        url = normalize_url(job.get("url", ""))
        if not url:
            continue
        if url in seen_urls:
            # Already claimed — by a job kept above, or by a row already in
            # the store. Only the first case has somewhere to put lane
            # evidence; the second is not ours to annotate.
            owner = url_owner.get(url)
            if owner is not None:
                _carry_lane(kept[owner], job)
            continue
        fp = fingerprint(job)
        if fp in seen_fps:
            continue

        if fp in kept:
            # Same posting, second source: upgrade only if it adds a body.
            incumbent = kept[fp]
            if not incumbent.get("description") and job.get("description"):
                kept[fp] = job
                # The incumbent's url still resolves to this fingerprint.
                url_owner[normalize_url(incumbent.get("url", ""))] = fp
            winner = kept[fp]
            _carry_lane(winner, incumbent if winner is job else job)
            continue

        seen_urls.add(url)
        url_owner[url] = fp
        kept[fp] = job
        order.append(fp)

    return [kept[fp] for fp in order]


def _carry_lane(winner: dict, loser: dict) -> None:
    """Move lane membership onto the copy that survives a collapse.

    A mode lane runs after the plain lanes, so its copy is always the
    challenger — and for a posting whose own text says nothing about work
    mode, lane membership is the only evidence there is. Discarding the
    loser wholesale threw it away for exactly the postings the lane exists
    to serve.

    Never overwritten: if both copies carry a lane, the one already on the
    winner stands. Two lanes disagreeing is a conflict, and a conflict
    claims nothing — `_apply_gates` decides that, not this function, and it
    can only decide it if the first-recorded value is stable.
    """
    lane = winner.get("_lane_mode") or loser.get("_lane_mode")
    if lane:
        winner.setdefault("_lane_mode", lane)
