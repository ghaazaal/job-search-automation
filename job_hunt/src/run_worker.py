"""Running a scrape off the request thread.

The whole of threading in this feature is here, and it is deliberately thin:
open a connection, call the runner, make sure the run row ends in a terminal
state whatever happens.
"""
import logging
import threading
from pathlib import Path

from .store.db import connect
from .store.runs import fail_run, get_run, set_progress

logger = logging.getLogger(__name__)


def default_runner(conn, user_id: int, run_id: int, on_progress):
    """Load config and hand off to run_core. Replaced wholesale in tests."""
    import yaml

    from .run_core import execute
    from .store.profile import get_profile, list_resumes

    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    resumes = list_resumes(conn, user_id, active_only=True)
    profile = get_profile(conn, user_id)
    execute(conn, user_id, run_id, config, resumes, profile,
            on_progress=on_progress)


def work(db_path: Path | str, user_id: int, run_id: int, runner=None) -> None:
    """Run one scrape to completion on the calling thread.

    Opens its own connection: SQLite connections cannot be shared across
    threads, and this is the single most likely place in the feature to
    introduce a defect. WAL and busy_timeout, already set in db.py, cover this
    writer against the poll endpoint's reads.
    """
    runner = runner or default_runner
    conn = connect(db_path)
    try:
        def on_progress(event: dict) -> None:
            set_progress(conn, run_id, event.get("stage", ""), event)

        runner(conn, user_id, run_id, on_progress)
    except Exception as exc:
        # A crashed worker must never leave the run RUNNING — that row blocks
        # every future run until the app restarts. But if the runner already
        # finished the run before raising (e.g. cleanup code that runs after
        # persist_run and throws), don't overwrite whatever terminal status
        # it already recorded.
        logger.exception("Run %s failed", run_id)
        try:
            stored = get_run(conn, run_id)
            if stored and stored["status"] == "RUNNING":
                fail_run(conn, run_id, str(exc))
        except Exception:
            logger.exception("Could not even record the failure of run %s",
                             run_id)
    else:
        # The runner is expected to finish the run. If it returned without
        # doing so, fail it rather than leave it hanging.
        stored = get_run(conn, run_id)
        if stored and stored["status"] == "RUNNING":
            logger.warning("Run %s ended without reporting a result", run_id)
            fail_run(conn, run_id, "the run ended without reporting a result")
    finally:
        conn.close()


def run_in_background(db_path: Path | str, user_id: int, run_id: int,
                      runner=None) -> threading.Thread:
    """Start `work` on a daemon thread and return immediately."""
    thread = threading.Thread(
        target=work, args=(db_path, user_id, run_id, runner),
        name=f"run-{run_id}", daemon=True)
    thread.start()
    return thread
