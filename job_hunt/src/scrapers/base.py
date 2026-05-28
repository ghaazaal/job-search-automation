"""ApifyClient wrapper — single point for all actor calls."""
import json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


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
