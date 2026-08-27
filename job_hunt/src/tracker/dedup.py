"""Job deduplication — URL normalization plus a company/title fingerprint.

Matching on raw URLs alone let ~13% of the tracker fill with duplicates: the
same posting arrives from Indeed and LinkedIn under different URLs, LinkedIn
mirrors each job across country subdomains, and boards append per-scrape
tracking parameters.
"""
import re
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


def fingerprint(job: dict) -> str:
    """Identity of a posting independent of which board it came from.

    Location is deliberately excluded: remote roles are mirrored per-country
    with differing location strings, and including it would defeat the point.
    """
    company = _norm_text(job.get("company") or job.get("Company") or "")
    company = _WS_RE.sub(" ", _COMPANY_SUFFIXES.sub("", company)).strip()
    title = _norm_text(job.get("title") or job.get("Job Title") or "")
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
