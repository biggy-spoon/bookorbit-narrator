import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


class StateStore:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS book_states (
                    book_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL,
                    last_attempt_at TEXT NOT NULL,
                    error TEXT
                )
                """
            )

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_status(self, book_id: int) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM book_states WHERE book_id = ?", (book_id,)
            ).fetchone()
        return row[0] if row else None

    def set_status(self, book_id: int, status: str, error: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO book_states (book_id, status, last_attempt_at, error)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    status = excluded.status,
                    last_attempt_at = excluded.last_attempt_at,
                    error = excluded.error
                """,
                (book_id, status, datetime.now(timezone.utc).isoformat(), error),
            )
