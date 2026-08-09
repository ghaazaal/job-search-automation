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

# Actors disagree on the description field name; take the first non-empty one.
_DESCRIPTION_KEYS = ("description", "descriptionText", "jobDescription",
                     "descriptionHtml", "jobDescriptionText", "snippet")

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
        if isinstance(raw, str) and raw.strip():
            text = html.unescape(_TAG_RE.sub(" ", raw))
            return _WS_RE.sub(" ", text).strip()
    return ""


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
    params = {"token": token, "timeout": timeout}
    try:
        resp = requests.post(
            url, json=payload,
            headers={"Content-Type": "application/json"},
            params=params, timeout=timeout + 30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logger.warning("Timeout for %s", label)
    except requests.exceptions.RequestException as e:
        logger.warning("Request error for %s: %s", label, e)
    except json.JSONDecodeError:
        logger.warning("Could not parse response for %s", label)
    return []
