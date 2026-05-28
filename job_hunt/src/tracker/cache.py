"""SQLite company cache — prevents re-hitting the API for known companies."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = _BASE_DIR / "job_hunt.db"


class CompanyCache:
    def __init__(self, db_path: Path = DB_PATH, ttl_days: int = 7):
        self._db = Path(db_path)
        self._ttl = ttl_days
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS company_cache (
                    name       TEXT PRIMARY KEY,
                    data       TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def get(self, company_name: str) -> dict | None:
        """Return cached data or None if expired / missing."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._ttl)).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data, updated_at FROM company_cache WHERE name = ?",
                (company_name.lower(),),
            ).fetchone()
        if row and row["updated_at"] >= cutoff:
            return json.loads(row["data"])
        return None

    def set(self, company_name: str, data: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO company_cache (name, data, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     data = excluded.data,
                     updated_at = excluded.updated_at""",
                (company_name.lower(), json.dumps(data),
                 datetime.now(timezone.utc).isoformat()),
            )
