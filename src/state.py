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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS read_aloud_states (
                    book_id INTEGER PRIMARY KEY,
                    stage TEXT NOT NULL,
                    job_id TEXT,
                    started_at TEXT NOT NULL
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

    def track_read_aloud_job(self, book_id: int, job_id: str) -> None:
        """The file was already uploaded directly to this book (no Book Dock wait
        needed) and a read-aloud job was just created for it - track it here so the
        poll loop can check on its progress without blocking."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO read_aloud_states (book_id, stage, job_id, started_at)
                VALUES (?, 'job_created', ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    stage = 'job_created', job_id = excluded.job_id, started_at = excluded.started_at
                """,
                (book_id, job_id, datetime.now(timezone.utc).isoformat()),
            )

    def clear_read_aloud_tracking(self, book_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM read_aloud_states WHERE book_id = ?", (book_id,))

    def pending_read_aloud(self) -> list[tuple[int, str, str]]:
        """Returns (book_id, job_id, started_at) for every read-aloud job still being tracked."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT book_id, job_id, started_at FROM read_aloud_states"
            ).fetchall()
        return rows
