"""SQLite outcome store — records application outcomes for scoring feedback."""
import json
import sqlite3
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = _BASE_DIR / "job_hunt.db"


class JobDB:
    def __init__(self, db_path: Path = DB_PATH):
        self._db = Path(db_path)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS outcomes (
                    url        TEXT PRIMARY KEY,
                    outcome    TEXT NOT NULL,
                    score      INTEGER,
                    recorded_at TEXT NOT NULL
                )
            """)

    def record_outcome(self, url: str, outcome: str, score: int = 0) -> None:
        """outcome: 'applied' | 'interview' | 'rejected' | 'ignored'"""
        from datetime import datetime, timezone
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO outcomes (url, outcome, score, recorded_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                     outcome = excluded.outcome,
                     recorded_at = excluded.recorded_at""",
                (url, outcome, score, datetime.now(timezone.utc).isoformat()),
            )

    def get_score_adjustments(self) -> dict:
        """Return score delta hints based on outcome history.

        Currently returns empty dict — future: tune weights from outcomes.
        """
        return {}
