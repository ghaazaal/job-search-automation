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


def _redact(text: str, token: str) -> str:
    """The token, wherever it turns up in text we are about to log.

    Belt and braces. Sending it as a header (below) keeps it out of the
    request URL, which is where it used to leak from — but a token can
    still reach an exception message by other routes: a redirect Location,
    a proxying error, a future caller that builds its own URL. Everything
    logged from here goes through this, so a new leak path has to get past
    two mistakes rather than one.
    """
    return text.replace(token, "***") if token else text


def call_actor(actor_id: str, payload: dict, label: str,
               timeout: int = 120) -> list[dict]:
    """POST to Apify run-sync endpoint, return raw items list.

    Returns empty list on any error so callers can always iterate safely.
    """
    token = os.environ.get("APIFY_TOKEN", "")
    if not token:
        logger.warning("APIFY_TOKEN not set — skipping %s", label)
        return []

    url = APIFY_BASE.format(actor=actor_id)
    try:
        resp = requests.post(
            url, json=payload,
            # Bearer, not `?token=`. `requests` embeds the full request URL
            # in its exception messages, and those messages were logged
            # verbatim — so a query-string credential was written to every
            # log sink the run had, once per failed actor call.
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"},
            params={"timeout": timeout}, timeout=timeout + 30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout as e:
        logger.warning("Timeout for %s: %s", label, _redact(str(e), token))
    except requests.exceptions.RequestException as e:
        logger.warning("Request error for %s: %s", label,
                       _redact(str(e), token))
    except json.JSONDecodeError:
        logger.warning("Could not parse response for %s", label)
    return []
