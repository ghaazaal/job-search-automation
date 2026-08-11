"""Flask routes.

No SQL lives here. Routes call the store and hand read models to renderers.
Binds to localhost only — this is a local application, not a service.
"""
import logging
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request

from . import resume_intake as intake
from .activity_page import render as render_activity
from .agents.profile_parser import parse_profile
from .llm.base import LLMClient
from .map_page import render as render_map
from .setup_page import render_confirm, render_profile, render_upload
from .store.db import DEFAULT_PATH, connect
from .store.ingest import ensure_user
from .store.profile import (create_resume, delete_resume, get_profile,
                            get_resume, list_resumes, resume_by_sha,
                            set_profile, unique_label, update_resume)
from .store.queries import activity_board, map_sections, mark_seen
from .store.schema import init_db
from .store.tracking import COMPANY_STATES, STATUSES, set_company_state, set_role_status
from .utils.pdf import extract_text

logger = logging.getLogger(__name__)

# Uploaded resumes live next to the database, not in the source tree.
DEFAULT_DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


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
               llm_factory=None) -> Flask:
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
            sections = map_sections(conn, user_id, shortlist_min)
            latest = conn.execute(
                "SELECT MAX(id) AS i FROM run WHERE user_id = ?",
                (user_id,)).fetchone()["i"]
            tagged = (
                [{**m, "section": "new"} for m in sections["new"]]
                + [{**m, "section": "earlier"} for m in sections["earlier"]]
                + [{**m, "section": "watching"} for m in sections["watching"]]
            )
            html = render_map(
                tagged,
                meta={"companies": len(sections["new"]) + len(sections["earlier"]),
                      "roles": sum(len(m["roles"]) for m in
                                   sections["new"] + sections["earlier"])})
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

    @app.get("/profile")
    def profile_screen():
        conn = _conn()
        try:
            user_id = _user(conn)
            return render_profile(list_resumes(conn, user_id),
                                  get_profile(conn, user_id))
        finally:
            conn.close()

    return app
