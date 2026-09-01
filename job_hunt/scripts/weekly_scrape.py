"""One scheduled scrape: fetch, score, store, exit.

Run by Windows Task Scheduler weekly. Does exactly what a browser-started
run does (`run_core.execute`) and nothing the terminal path adds — no LLM
shortlist, no Excel. The user reviews results on the map, where a
finished run shows up like any other.

Safe to fire blind:
- If a run is already RUNNING and not stale, this exits without starting
  a second one — two workers writing at once is the failure
  STALE_AFTER_MINUTES exists to prevent.
- Needs APIFY_TOKEN, which is a per-user Windows env var; the scheduled
  task runs as the user, so it is visible.
- Appends a line-per-run log to output/weekly_scrape.log so a silent
  Monday can be diagnosed months later.
"""
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

LOG_PATH = REPO / "output" / "weekly_scrape.log"
LOG_PATH.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("weekly_scrape")

USER_ID = 1

# Leave this much headroom: a run that starts with less will die mid-way
# and its tail of 403s would read as an empty market.
_MIN_CREDIT_USD = 0.50


def apify_credit_remaining() -> float | None:
    """The BEST remaining monthly credit across all accounts, or None.

    call_actor fails over between tokens, so the run can proceed as long
    as ANY configured account still has credit.

    Run 10 ran out of credit mid-run: the main lanes finished, then every
    later call 403'd, and the zeros looked like results. Refusing to
    start is the honest failure; an unreachable limits endpoint returns
    None and the run proceeds - this guard must never be the thing that
    blocks scraping.
    """
    import os

    import requests
    tokens = [os.environ.get(k, "").strip()
              for k in ("APIFY_TOKEN", "APIFY_TOKEN_2", "APIFY_TOKEN_3")]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    best = None
    for i, token in enumerate(tokens, 1):
        try:
            resp = requests.get(
                "https://api.apify.com/v2/users/me/limits",
                headers={"Authorization": f"Bearer {token}"}, timeout=20)
            resp.raise_for_status()
            data = resp.json()["data"]
            left = (float(data["limits"]["maxMonthlyUsageUsd"])
                    - float(data["current"]["monthlyUsageUsd"]))
            log.info("account %d: $%.2f credit remaining", i, left)
            best = left if best is None else max(best, left)
        except Exception:
            log.warning("could not read Apify limits for account %d - "
                        "ignoring it", i, exc_info=True)
    return best


def main() -> int:
    import yaml

    from src.run_core import execute
    from src.store.db import connect
    from src.store.profile import get_profile, list_resumes
    from src.store.runs import active_run, is_stale, start_run
    from src.store.schema import init_db

    remaining = apify_credit_remaining()
    if remaining is not None and remaining < _MIN_CREDIT_USD:
        log.error(
            "Apify monthly credit exhausted ($%.2f remaining) - refusing "
            "to start a run that would half-die into silent zeros. Wait "
            "for the cycle reset or raise the plan limit.", remaining)
        return 1

    conn = connect()
    init_db(conn)

    in_flight = active_run(conn, USER_ID)
    if in_flight and not is_stale(in_flight["started_at"]):
        log.info("run %s is already RUNNING and not stale - exiting "
                 "rather than starting a second scrape over the same "
                 "titles", in_flight["id"])
        return 0

    with open(REPO / "config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    resumes = list_resumes(conn, USER_ID, active_only=True)
    profile = get_profile(conn, USER_ID)
    if not resumes or not profile.get("setup_complete"):
        log.error("setup incomplete (resumes=%d) - nothing to search for",
                  len(resumes))
        return 1

    run_id = start_run(conn, USER_ID)
    log.info("run %s open (weekly scheduled scrape)", run_id)
    try:
        result = execute(conn, USER_ID, run_id, config, resumes, profile)
    except Exception:
        # execute's caller owns terminal state on a crash; run_worker does
        # this for browser runs and the same duty falls to us here.
        from src.store.runs import fail_run, get_run
        log.exception("run %s failed", run_id)
        stored = get_run(conn, run_id)
        if stored and stored["status"] == "RUNNING":
            fail_run(conn, run_id, "weekly scheduled scrape crashed")
        return 1

    log.info("run %s done: scraped=%d kept=%d offtopic=%d dropped=%d",
             run_id, result.scraped, result.kept, result.offtopic,
             result.dropped)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
