"""Flask routes.

No SQL lives here. Routes call the store and hand read models to renderers.
Binds to localhost only — this is a local application, not a service.
"""
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request

from .activity_page import render as render_activity
from .map_page import render as render_map
from .store.db import DEFAULT_PATH, connect
from .store.ingest import ensure_user
from .store.queries import activity_board, map_sections, mark_seen
from .store.schema import init_db
from .store.tracking import COMPANY_STATES, STATUSES, set_company_state, set_role_status


def create_app(db_path: Path | str = DEFAULT_PATH,
               user_name: str = "default",
               shortlist_min: int = 7) -> Flask:
    app = Flask(__name__)

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
            return jsonify({"error": "not found"}), 404
        finally:
            conn.close()

    return app
