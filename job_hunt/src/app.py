"""Flask routes.

No SQL lives here. Routes call the store and hand read models to renderers.
Binds to localhost only — this is a local application, not a service.
"""
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, redirect, request

from . import resume_intake as intake
from .activity_page import render as render_activity
from .agents.profile_parser import parse_profile
from .llm.base import LLMClient
from .map_page import render as render_map
from .run_core import search_titles
from .run_worker import run_in_background, work
from .searching_page import render as render_searching
from .setup_page import render_confirm, render_profile, render_upload
from .store.db import DEFAULT_PATH, connect, transaction
from .store.ingest import ensure_user
from .store.profile import (create_resume, delete_resume, get_profile,
                            get_resume, list_resumes, resume_by_sha,
                            set_profile, unique_label, update_resume)
from .store.queries import activity_board, map_sections, mark_seen
from .store.runs import (active_run, clear_running, fail_run, get_run,
                         is_stale, latest_ok_run)
from .store.schema import init_db
from .store.tracking import COMPANY_STATES, STATUSES, set_company_state, set_role_status
from .utils.pdf import extract_text

logger = logging.getLogger(__name__)

# Uploaded resumes live next to the database, not in the source tree.
DEFAULT_DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_llm() -> LLMClient:
    """Build the configured client. Only called when a resume is uploaded."""
    import yaml

    from .llm.factory import get_client

    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as handle:
        return get_client(yaml.safe_load(handle))


def create_app(db_path: Path | str = DEFAULT_PATH,
               user_name: str = "default",
               shortlist_min: int = 7,
               data_root: Path | str = DEFAULT_DATA_ROOT,
               llm_factory=None,
               runner=None,
               run_in_thread: bool = True) -> Flask:
    app = Flask(__name__)

    # Defense in depth: reject a request body far larger than any legitimate
    # upload before it is buffered into memory. resume_intake.MAX_BYTES (5 MB)
    # is the real, user-facing limit — this is a coarser ceiling that only
    # ever fires for requests that check would also reject.
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

    @app.errorhandler(413)
    def _too_large(_error):
        return jsonify({"error": "That file is too large."}), 413

    data_root = Path(data_root)
    build_llm = llm_factory or _default_llm

    # Injected so tests drive a run synchronously instead of chasing a thread.
    run_runner = runner

    def _conn():
        conn = connect(db_path)
        init_db(conn)
        return conn

    def _user(conn) -> int:
        return ensure_user(conn, user_name)

    @app.get("/")
    def map_screen():
        conn = _conn()
        try:
            user_id = _user(conn)

            # Nothing to show and nothing to search for — send them to setup
            # rather than to an empty map they cannot act on.
            profile = get_profile(conn, user_id)
            resumes = list_resumes(conn, user_id, active_only=True)
            if not resumes or not profile.get("setup_complete"):
                return redirect("/setup")

            sections = map_sections(conn, user_id, shortlist_min)
            tagged = (
                [{**m, "section": "new"} for m in sections["new"]]
                + [{**m, "section": "earlier"} for m in sections["earlier"]]
                + [{**m, "section": "watching"} for m in sections["watching"]]
            )
            in_flight = active_run(conn, user_id)

            # Only a finished run may be marked seen. Marking the in-flight
            # run would file every role it is about to store as already seen.
            # Fetched here (not after rendering) so the same lookup can also
            # supply the last run's drop count to the banner.
            latest = latest_ok_run(conn, user_id)
            hidden = 0
            offtopic = 0
            if latest:
                latest_run = get_run(conn, latest)
                if latest_run:
                    hidden = latest_run.get("dropped") or 0
                    offtopic = latest_run.get("offtopic") or 0

            html = render_map(
                tagged,
                meta={"companies": len(sections["new"]) + len(sections["earlier"]),
                      "roles": sum(len(m["roles"]) for m in
                                   sections["new"] + sections["earlier"]),
                      "hidden": hidden, "offtopic": offtopic},
                running_run_id=in_flight["id"] if in_flight else None)

            if latest:
                mark_seen(conn, user_id, latest)
            return html
        finally:
            conn.close()

    @app.get("/activity")
    def activity_screen():
        conn = _conn()
        try:
            return render_activity(activity_board(conn, _user(conn)))
        finally:
            conn.close()

    @app.post("/api/roles/<int:role_id>/status")
    def set_status(role_id: int):
        status = (request.get_json(silent=True) or {}).get("status", "")
        if status not in STATUSES:
            return jsonify({"error": "unknown status"}), 400
        conn = _conn()
        try:
            set_role_status(conn, _user(conn), role_id, status)
            return jsonify({"role_id": role_id, "status": status})
        except sqlite3.IntegrityError:
            # status is already validated above, so the only FK this can trip
            # is role_id referencing a role that doesn't exist.
            return jsonify({"error": "not found"}), 404
        finally:
            conn.close()

    @app.post("/api/companies/<int:company_id>/state")
    def set_state(company_id: int):
        state = (request.get_json(silent=True) or {}).get("state", "")
        if state not in COMPANY_STATES:
            return jsonify({"error": "unknown state"}), 400
        conn = _conn()
        try:
            set_company_state(conn, _user(conn), company_id, state)
            return jsonify({"company_id": company_id, "state": state})
        except sqlite3.IntegrityError:
            # state is already validated above, so the only FK this can trip
            # is company_id referencing a company that doesn't exist.
            return jsonify({"error": "not found"}), 404
        finally:
            conn.close()

    @app.get("/setup")
    def setup_screen():
        return render_upload()

    @app.post("/api/resumes")
    def add_resume():
        upload = request.files.get("resume")
        if upload is None:
            return jsonify({"error": "No file was sent."}), 400
        data = upload.read()
        filename = upload.filename or ""
        try:
            intake.validate(filename, data)
        except intake.UploadRejected as rejected:
            return jsonify({"error": str(rejected)}), 400

        conn = _conn()
        try:
            user_id = _user(conn)
            sha256 = intake.digest(data)
            if resume_by_sha(conn, user_id, sha256):
                return jsonify(
                    {"error": "You have already uploaded this resume."}), 409

            stored_path = intake.store(data_root, user_id, sha256, data)
            try:
                text = extract_text(data_root / stored_path)
            except Exception:
                logger.exception("PDF text extraction failed")
                return jsonify({"error": "That PDF could not be read. Try "
                                         "exporting it again."}), 400

            label = unique_label(conn, user_id, Path(filename).stem)
            resume_id = create_resume(
                conn, user_id, label=label, orig_filename=filename,
                sha256=sha256, stored_path=stored_path, extracted_text=text)

            # A parse failure must not lose the upload — the confirm screen
            # asks for the roles and skills by hand instead.
            try:
                parsed = parse_profile(text, build_llm())
            except Exception:
                logger.exception("Resume parse failed for resume %s", resume_id)
            else:
                update_resume(conn, user_id, resume_id, label=label,
                              target_roles=parsed["target_roles"],
                              skills=parsed["skills"],
                              seniority=parsed["seniority"])
            return jsonify({"resume_id": resume_id}), 201
        finally:
            conn.close()

    @app.get("/setup/confirm/<int:resume_id>")
    def confirm_screen(resume_id: int):
        conn = _conn()
        try:
            user_id = _user(conn)
            resume = get_resume(conn, user_id, resume_id)
            if resume is None:
                return jsonify({"error": "not found"}), 404
            profile = get_profile(conn, user_id)
            # Where you live is asked once, on the first resume.
            return render_confirm(resume, profile,
                                  ask_location=not profile["setup_complete"])
        finally:
            conn.close()

    @app.post("/api/resumes/<int:resume_id>")
    def save_resume(resume_id: int):
        payload = request.get_json(silent=True) or {}
        label = str(payload.get("label") or "").strip().lower()[:40]
        if not label:
            return jsonify({"error": "A label is required."}), 400
        roles_raw = payload.get("target_roles")
        skills_raw = payload.get("skills")
        target_roles = roles_raw if isinstance(roles_raw, list) else []
        skills = skills_raw if isinstance(skills_raw, list) else []
        conn = _conn()
        try:
            update_resume(
                conn, _user(conn), resume_id, label=label,
                target_roles=target_roles,
                skills=skills,
                seniority=str(payload.get("seniority") or "mid"),
                is_active=bool(payload.get("is_active", True)))
            return jsonify({"resume_id": resume_id})
        except ValueError as bad:
            return jsonify({"error": str(bad)}), 400
        except LookupError:
            return jsonify({"error": "not found"}), 404
        except sqlite3.IntegrityError:
            return jsonify(
                {"error": "You already have a resume with that label."}), 409
        finally:
            conn.close()

    @app.delete("/api/resumes/<int:resume_id>")
    def remove_resume(resume_id: int):
        conn = _conn()
        try:
            stored_path = delete_resume(conn, _user(conn), resume_id)
            if stored_path is None:
                return jsonify({"error": "not found"}), 404
            (data_root / stored_path).unlink(missing_ok=True)
            return jsonify({"resume_id": resume_id, "deleted": True})
        finally:
            conn.close()

    @app.post("/api/profile")
    def save_profile():
        payload = request.get_json(silent=True) or {}
        modes_raw = payload.get("work_modes")
        work_modes = modes_raw if isinstance(modes_raw, list) else []
        conn = _conn()
        try:
            set_profile(conn, _user(conn),
                        location=str(payload.get("location") or ""),
                        country=str(payload.get("country") or ""),
                        work_modes=work_modes)
            return jsonify({"saved": True})
        except ValueError as bad:
            return jsonify({"error": str(bad)}), 400
        finally:
            conn.close()

    @app.post("/api/runs")
    def start_scrape():
        conn = _conn()
        try:
            user_id = _user(conn)

            # Refuse before creating a row. A run that exists only to fail two
            # seconds later is worse than a clear message now.
            resumes = list_resumes(conn, user_id, active_only=True)
            if not resumes:
                return jsonify({"error": "Upload a resume before searching."}), 400
            if not search_titles(resumes):
                return jsonify({"error": "Your resumes name no target roles. "
                                         "Add one on the profile screen."}), 400
            if not os.environ.get("APIFY_TOKEN"):
                return jsonify({"error": "APIFY_TOKEN is not set, so no "
                                         "search can run."}), 400
            if not get_profile(conn, user_id).get("setup_complete"):
                return jsonify({"error": "Finish setup — add your location "
                                         "and work mode — before searching."}), 400

            # Check and insert together: transaction() uses BEGIN IMMEDIATE,
            # so two rapid posts cannot both find no RUNNING run.
            with transaction(conn):
                existing = active_run(conn, user_id)
                if existing and not is_stale(existing["started_at"]):
                    return jsonify(
                        {"error": "A search is already running.",
                         "run_id": existing["id"]}), 409
                if existing:
                    conn.execute(
                        "UPDATE run SET status = 'FAILED', error = ?"
                        " WHERE id = ?",
                        ("abandoned — superseded by a new search",
                         existing["id"]))
                conn.execute(
                    "INSERT INTO run (user_id, started_at, status)"
                    " VALUES (?, ?, 'RUNNING')", (user_id, _utc_now()))
            run_id = conn.execute(
                "SELECT last_insert_rowid() AS i").fetchone()["i"]
        finally:
            conn.close()

        try:
            if run_in_thread:
                run_in_background(db_path, user_id, run_id, run_runner)
            else:
                work(db_path, user_id, run_id, run_runner)
        except Exception as exc:
            fail_conn = connect(db_path)
            try:
                fail_run(fail_conn, run_id, str(exc))
            finally:
                fail_conn.close()
            return jsonify({"error": "Could not start the search."}), 500
        return jsonify({"run_id": run_id}), 201

    @app.get("/api/runs/<int:run_id>")
    def poll_scrape(run_id: int):
        conn = _conn()
        try:
            stored = get_run(conn, run_id)
            if stored is None:
                return jsonify({"error": "not found"}), 404
            return jsonify({"status": stored["status"],
                            "stage": stored["stage"],
                            "progress": stored["progress"],
                            "error": stored["error"]})
        finally:
            conn.close()

    @app.get("/searching/<int:run_id>")
    def searching_screen(run_id: int):
        conn = _conn()
        try:
            if get_run(conn, run_id) is None:
                return jsonify({"error": "not found"}), 404
            return render_searching(run_id)
        finally:
            conn.close()

    @app.get("/profile")
    def profile_screen():
        conn = _conn()
        try:
            user_id = _user(conn)
            return render_profile(list_resumes(conn, user_id),
                                  get_profile(conn, user_id))
        finally:
            conn.close()

    # Any RUNNING run belongs to a process that is no longer here — at boot
    # none of ours are alive yet. Without this one hard kill locks the user
    # out of ever starting another run, because POST /api/runs sees a RUNNING
    # row and refuses.
    #
    # This must stay in create_app, which runs once. init_db() is called by
    # _conn() on every single request; recovering there would mark the run
    # currently in flight as failed.
    _boot_conn = connect(db_path)
    try:
        init_db(_boot_conn)
        cleared = clear_running(_boot_conn,
                                "interrupted — the app restarted mid-run")
        if cleared:
            logger.info("Cleared %s run(s) left running by a previous process",
                        cleared)
    finally:
        _boot_conn.close()

    return app
