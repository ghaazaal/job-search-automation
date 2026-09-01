"""ApifyClient wrapper — single point for all actor calls."""
import html
import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

# Actors disagree on the description field name; take the first non-empty
# one. HTML-shaped fields come first: the actors' plain fields arrive
# pre-flattened without separators (e.g. "...RemoteTravel Required..."),
# which defeats word-boundary phrase matching, while tag-flattening below
# inserts a space per tag — so HTML input always yields separated text.
_DESCRIPTION_KEYS = ("descriptionHtml", "description", "descriptionText",
                     "jobDescription", "jobDescriptionText", "snippet")

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE  = re.compile(r"\s+")


def extract_description(item: dict) -> str:
    """Return the job description as plain text, or '' if the actor sent none.

    Bodies arrive as either plain text or HTML depending on the actor and the
    source listing. Scoring matches keywords against this, so markup is
    flattened rather than preserved.
    """
    for key in _DESCRIPTION_KEYS:
        raw = item.get(key)
        if isinstance(raw, dict):
            # Some actors nest the body as description: {"text": ...,
            # "html": ...} instead of putting a string directly on the
            # top-level key (the now-retired valig~indeed-jobs-scraper
            # did this; the current indeed.py pre-flattens before ever
            # reaching here, but the branch stays in case another actor
            # is shaped this way). Prefer html: the text sibling arrives
            # pre-flattened with no separators.
            raw = raw.get("html") or raw.get("text")
        if isinstance(raw, str) and raw.strip():
            text = html.unescape(_TAG_RE.sub(" ", raw))
            return _WS_RE.sub(" ", text).strip()
    return ""


# HTTP statuses that indict the ACCOUNT rather than the request: bad
# token, payment required, credit exhausted, rate limited. Only these
# rotate to the next token - a 500 is the actor's fault, and burning the
# second account's credit on it would be a silent cost.
_ACCOUNT_STATUSES = {401, 402, 403, 429}

# Index of the token that last worked. Sticky, so one dead account costs
# one failed request per process, not one per call.
_preferred = 0


def _reset_token_preference() -> None:
    """Tests only."""
    global _preferred
    _preferred = 0


def _tokens() -> list[str]:
    """Every configured Apify token, in preference order.

    Two accounts, one pipeline: APIFY_TOKEN is the primary and
    APIFY_TOKEN_2 / APIFY_TOKEN_3 are failovers, tried when the current
    account is refused (credit exhausted mid-cycle, as run 10 was).
    """
    ordered = [os.environ.get(k, "").strip()
               for k in ("APIFY_TOKEN", "APIFY_TOKEN_2", "APIFY_TOKEN_3")]
    ordered = [t for t in ordered if t]
    if not ordered:
        return []
    start = _preferred % len(ordered)
    return ordered[start:] + ordered[:start]


def _redact_all(text: str) -> str:
    """Every configured token, wherever it turns up in text about to log.

    Belt and braces. Sending tokens as headers keeps them out of request
    URLs, which is where one leaked from originally (PR #8) — but a token
    can still reach an exception message by other routes: a redirect
    Location, a proxying error, a future caller that builds its own URL.
    Everything logged from this module goes through here, so a new leak
    path has to get past two mistakes rather than one, for every account.
    """
    for tok in _tokens():
        text = text.replace(tok, "***")
    return text


def call_actor(actor_id: str, payload: dict, label: str,
               timeout: int = 120, strict: bool = False) -> list[dict]:
    """POST to Apify run-sync endpoint, return raw items list.

    Returns empty list on any error so callers can always iterate safely.

    `strict=True` raises on transport/HTTP errors instead. Run 10 showed
    why the soft default is not always right: the account's credit ran
    out mid-run, every later call 403'd, and the resolver read those []s
    as "this company is not on LinkedIn" - a transport failure recorded
    as a fact about the world. Callers that turn absence into a stored
    claim must use strict; callers that merely lose a page of results
    may keep the soft default.
    """
    global _preferred
    tokens = _tokens()
    if not tokens:
        logger.warning("APIFY_TOKEN not set — skipping %s", label)
        return []

    url = APIFY_BASE.format(actor=actor_id)
    last_exc: Exception | None = None
    for attempt, token in enumerate(tokens):
        try:
            resp = requests.post(
                url, json=payload,
                # Bearer, not `?token=`. `requests` embeds the full request
                # URL in its exception messages, and those messages were
                # logged verbatim — so a query-string credential was written
                # to every log sink the run had, once per failed actor call.
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {token}"},
                params={"timeout": timeout}, timeout=timeout + 30,
            )
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            last_exc = e
            status = getattr(e.response, "status_code", None)
            if status in _ACCOUNT_STATUSES and attempt < len(tokens) - 1:
                # The ACCOUNT was refused, not the request — the next
                # token gets the identical call. Token values never
                # reach the log, only their position.
                logger.warning("token %d refused for %s (HTTP %s) — "
                               "trying the next account",
                               attempt + 1, label, status)
                continue
            logger.warning("Request error for %s: %s", label,
                           _redact_all(str(e)))
            break
        except requests.exceptions.Timeout as e:
            last_exc = e
            logger.warning("Timeout for %s: %s", label,
                           _redact_all(str(e)))
            break
        except requests.exceptions.RequestException as e:
            last_exc = e
            logger.warning("Request error for %s: %s", label,
                           _redact_all(str(e)))
            break
        try:
            items = resp.json()
        except json.JSONDecodeError:
            logger.warning("Could not parse response for %s", label)
            return []
        if attempt:
            # Remember the account that worked so the next call starts
            # here instead of re-paying a refused request every time.
            _preferred = (_preferred + attempt) % len(tokens)
            logger.warning("%s served by failover token — the primary "
                           "account was refused", label)
        return items
    if strict and last_exc is not None:
        raise last_exc
    return []
