"""Is a stored posting still open? Asked of the posting's own page.

Evidence only, the same rule as everywhere else in this product. A posting
is CLOSED when its source says so; it is OPEN when the source shows it with
nothing saying otherwise; anything else is UNKNOWN, and unknown changes
nothing. A rate limit, a bot wall, a timeout or a page we cannot read is not
proof a job closed - it is a check that did not happen.

What each board says when a job is gone, measured against the live store on
2026-10-14 (closed and open samples both fetched, so every marker below was
seen absent from an open page too):

    LinkedIn        301 to a search page with trk=expired_jd_redirect, or the
                    "No longer accepting applications" banner, or HTTP 404.
                    Open pages carry the public apply link.
    Jobicy          HTTP 404/410, or the "Applications closed" section.
    The Muse        "This job is no longer available." in the job header.
    RemoteOK        the posting's own row carries the `closed` class ("This
                    job post is closed and the position is probably filled").
                    Other rows on the page are related jobs - only the row
                    whose id matches the URL counts.
    We Work Remotely  301 to the board's home page.
    Working Nomads  /job/go/<id>/ forwards an open job to the employer's
                    application, and an expired one back to its own listings.
    Hacker News     the comment is deleted or dead (read from HN's API). A
                    live comment says nothing either way: HN has no "closed".

No checker, and no request made, for: Himalayas (a Cloudflare challenge,
HTTP 403, on every page), devitjobs (every job URL redirects to a jobcopilot
sign-up page), and DataArt (a JS shell, byte-identical for every vacancy).
"""
import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

OPEN, CLOSED, UNKNOWN = "open", "closed", "unknown"

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
_MAX_HOPS = 5
# Statuses that mean "slow down", not "gone". LinkedIn's guest pages
# throttle in bursts - on 2026-10-14 a 429 came back between two 200s a
# second apart - so one refusal doubles that board's spacing, and only a
# run of them benches the board for the rest of the pass. Hammering a
# rate limit only extends it.
_THROTTLED = (429, 999)
_STRIKES = 4
_MAX_DELAY = 60.0


@dataclass(frozen=True)
class Verdict:
    state: str                   # OPEN / CLOSED / UNKNOWN
    evidence: str                # what was seen, in words a person can check
    http_status: int | None = None
    final_url: str | None = None


@dataclass
class Page:
    status: int
    url: str                     # where the last request went
    text: str = ""
    redirects: list[str] = field(default_factory=list)
    offsite: bool = False        # stopped at a redirect leaving the board


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _on(url: str, domain: str) -> bool:
    host = _host(url)
    return host == domain or host.endswith("." + domain)


def _quote(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class Checker:
    """One board. `judge` reads a fetched page; `closed_redirect` may end
    the fetch early when a redirect alone is the evidence."""
    name = ""
    domain = ""
    delay = 1.0                  # seconds between requests to this board

    def request_url(self, url: str) -> str:
        return url

    def closed_redirect(self, location: str) -> str | None:
        return None

    def judge(self, page: Page) -> Verdict:
        raise NotImplementedError

    def gone_status(self, page: Page) -> Verdict | None:
        if page.status in (404, 410):
            return Verdict(CLOSED, f"{self.name} returned HTTP {page.status} "
                                   "for the posting", page.status, page.url)
        return None


class LinkedIn(Checker):
    name, domain, delay = "LinkedIn", "linkedin.com", 3.0
    _BANNER = re.compile(
        r'class="closed-job__flavor--closed"[^>]*>\s*([^<]+?)\s*<', re.I)
    _APPLY = re.compile(r"public_jobs_apply-link|apply-button", re.I)

    def closed_redirect(self, location):
        if "expired_jd_redirect" in location:
            return ("LinkedIn redirected the posting to a job search "
                    "(trk=expired_jd_redirect)")
        return None

    def judge(self, page):
        gone = self.gone_status(page)
        if gone:
            return gone
        if page.status == 200 and not page.offsite:
            banner = self._BANNER.search(page.text)
            if banner:
                return Verdict(CLOSED, f'LinkedIn shows "{_quote(banner.group(1))}"',
                               200, page.url)
            if self._APPLY.search(page.text):
                return Verdict(OPEN, "LinkedIn shows the apply button",
                               200, page.url)
        return None


class Jobicy(Checker):
    name, domain = "Jobicy", "jobicy.com"

    def judge(self, page):
        gone = self.gone_status(page)
        if gone:
            return gone
        if page.status == 200 and not page.offsite:
            if 'class="jv-closed"' in page.text:
                return Verdict(CLOSED, 'Jobicy shows "Applications closed"',
                               200, page.url)
            return Verdict(OPEN, "Jobicy shows the posting with no closed "
                                 "notice", 200, page.url)
        return None


class Muse(Checker):
    name, domain = "The Muse", "themuse.com"
    _ARCHIVED = re.compile(r'archivedJobMessage[^"]*"[^>]*>\s*([^<]+?)\s*<')

    def judge(self, page):
        gone = self.gone_status(page)
        if gone:
            return gone
        if page.status == 200 and not page.offsite:
            archived = self._ARCHIVED.search(page.text)
            if archived:
                return Verdict(CLOSED, f'The Muse shows "{_quote(archived.group(1))}"',
                               200, page.url)
            return Verdict(OPEN, "The Muse shows the posting with no archived "
                                 "notice", 200, page.url)
        return None


class RemoteOK(Checker):
    name, domain = "RemoteOK", "remoteok.com"

    def judge(self, page):
        gone = self.gone_status(page)
        if gone:
            return gone
        job_id = re.search(r"-(\d+)/?$", urlparse(page.url).path)
        if page.status != 200 or page.offsite or not job_id:
            return None
        row = re.search(rf'id="job-{job_id.group(1)}"[^>]*?class="([^"]*)"',
                        page.text)
        if not row:
            return None
        if "closed" in row.group(1).split():
            return Verdict(CLOSED, 'RemoteOK marks the posting "closed" (the '
                                   'position is probably filled)', 200, page.url)
        return Verdict(OPEN, "RemoteOK shows the posting without the closed "
                             "flag", 200, page.url)


class WeWorkRemotely(Checker):
    name, domain = "We Work Remotely", "weworkremotely.com"

    def closed_redirect(self, location):
        if urlparse(location).path in ("", "/"):
            return "We Work Remotely redirected the posting to its home page"
        return None

    def judge(self, page):
        gone = self.gone_status(page)
        if gone:
            return gone
        if page.status == 200 and not page.offsite:
            return Verdict(OPEN, "We Work Remotely shows the posting",
                           200, page.url)
        return None


class WorkingNomads(Checker):
    name, domain = "Working Nomads", "workingnomads.com"

    def closed_redirect(self, location):
        # Only reached for on-board redirects: an expired job is sent back
        # to a listing page rather than on to the employer.
        if not urlparse(location).path.startswith("/job/"):
            return ("Working Nomads sent the job link back to its own "
                    "listings instead of the employer's application")
        return None

    def judge(self, page):
        gone = self.gone_status(page)
        if gone:
            return gone
        if page.offsite and page.redirects:
            return Verdict(OPEN, "Working Nomads still forwards to the "
                                 "employer's application", page.status,
                           page.redirects[-1])
        return None


class HackerNews(Checker):
    name, domain = "Hacker News", "news.ycombinator.com"

    def request_url(self, url):
        item = parse_qs(urlparse(url).query).get("id", [""])[0]
        return f"https://hacker-news.firebaseio.com/v0/item/{item}.json"

    def judge(self, page):
        if page.status != 200:
            return None
        if '"deleted":true' in page.text.replace(" ", ""):
            return Verdict(CLOSED, "the Hacker News comment was deleted",
                           200, page.url)
        if '"dead":true' in page.text.replace(" ", ""):
            return Verdict(CLOSED, "the Hacker News comment is dead "
                                   "(flagged or removed)", 200, page.url)
        return Verdict(UNKNOWN, "the Hacker News comment is still up, and "
                                "HN has no closed state", 200, page.url)


CHECKERS = (LinkedIn(), Jobicy(), Muse(), RemoteOK(), WeWorkRemotely(),
            WorkingNomads(), HackerNews())


def checker_for(url: str) -> Checker | None:
    for checker in CHECKERS:
        if _on(url, checker.domain):
            return checker
    return None


def fetch(checker: Checker, url: str, get=None) -> Page | Verdict:
    """Fetch `url`, following redirects by hand so each one can be read.

    Returns a CLOSED Verdict directly when a redirect alone is the evidence,
    and stops (offsite=True) at a redirect leaving the board, because where
    the employer's own form lives is not this check's business.
    `get(url) -> requests.Response` is injectable for tests.
    """
    get = get or (lambda u: requests.get(u, headers=_HEADERS, timeout=20,
                                         allow_redirects=False))
    page = Page(status=0, url=checker.request_url(url))
    for _ in range(_MAX_HOPS + 1):
        resp = get(page.url)
        location = resp.headers.get("location") if resp.is_redirect else None
        if not location:
            page.status, page.text = resp.status_code, resp.text
            return page
        target = urljoin(page.url, location)
        page.redirects.append(target)
        page.status = resp.status_code
        if not _on(target, checker.domain):
            page.offsite = True
            return page
        evidence = checker.closed_redirect(target)
        if evidence:
            return Verdict(CLOSED, evidence, resp.status_code, target)
        page.url = target
    return page


def check(url: str, get=None) -> Verdict:
    """One posting's verdict. Never raises for a network problem."""
    checker = checker_for(url)
    if checker is None:
        return Verdict(UNKNOWN, "no checker for this board")
    try:
        result = fetch(checker, url, get)
    except requests.RequestException as exc:
        return Verdict(UNKNOWN, f"could not reach {checker.name} "
                                f"({type(exc).__name__})")
    if isinstance(result, Verdict):
        return result
    verdict = checker.judge(result)
    if verdict:
        return verdict
    if result.status in _THROTTLED:
        why = "rate limited"
    elif result.offsite:
        why = "redirected off the board"
    elif result.status == 200:
        why = "page loaded but showed neither a closed notice nor the posting"
    else:
        why = "unexpected response"
    return Verdict(UNKNOWN, f"{checker.name}: {why} (HTTP {result.status})",
                   result.status, result.url)


def check_postings(conn, user_id: int, limit: int | None = None,
                   get=None, sleep=time.sleep, on_verdict=None) -> dict:
    """One pass over the stored postings that are still believed open.

    Least-recently-checked first, so repeated capped passes cover the whole
    store. Each verdict is written as it arrives, so a pass cut short (the
    app closed, the laptop slept) keeps everything it learned. A board that
    rate-limits us is left alone for the rest of the pass.
    """
    from .store.liveness import candidates, record_check

    summary = {"checked": 0, OPEN: 0, CLOSED: 0, UNKNOWN: 0,
               "throttled": [], "closed_roles": []}
    last_hit: dict[str, float] = {}
    delay: dict[str, float] = {}
    strikes: dict[str, int] = {}
    for row in candidates(conn, user_id):
        if limit is not None and summary["checked"] >= limit:
            break
        checker = checker_for(row["url"])
        if checker is None or checker.name in summary["throttled"]:
            continue
        name = checker.name
        spacing = delay.get(name, checker.delay)
        wait = spacing - (time.monotonic() - last_hit.get(name, -1e9))
        if wait > 0:
            sleep(wait)
        verdict = check(row["url"], get)
        last_hit[name] = time.monotonic()
        if verdict.http_status in _THROTTLED:
            strikes[name] = strikes.get(name, 0) + 1
            delay[name] = min(spacing * 2, _MAX_DELAY)
            if strikes[name] >= _STRIKES:
                summary["throttled"].append(name)
                logger.warning("%s kept rate-limiting the check; leaving it "
                               "for the next pass", name)
        else:
            strikes[name] = 0

        record_check(conn, user_id, row["id"], verdict)
        summary["checked"] += 1
        summary[verdict.state] += 1
        if verdict.state == CLOSED:
            summary["closed_roles"].append(
                {"role_id": row["id"], "title": row["title"],
                 "company": row["company"], "evidence": verdict.evidence})
        if on_verdict:
            on_verdict(row, verdict)
    return summary
