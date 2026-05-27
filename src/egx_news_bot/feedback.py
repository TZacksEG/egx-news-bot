from __future__ import annotations

from dataclasses import dataclass
from os import environ
from pathlib import Path
import sqlite3
from time import time
from typing import Any


VALID_FEEDBACK_ACTIONS = frozenset({"good", "wrong", "too_strong", "too_weak", "not_relevant"})
TELEGRAM_UPDATE_OFFSET_KEY = "telegram_update_offset"


@dataclass(frozen=True)
class FeedbackRecord:
    alert_id: int
    action: str
    user_id: int
    username: str | None = None
    message_id: int | None = None
    created_at: float | None = None


class FeedbackStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def record_alert(
        self,
        *,
        external_id: str | None,
        source_name: str,
        source_url: str,
        title: str,
        event_type: str,
        analysis_method: str,
        max_strength: int,
    ) -> int:
        now = time()
        key = external_id or source_url or title
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alerts (
                  dedupe_key, external_id, source_name, source_url, title,
                  event_type, analysis_method, max_strength, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO UPDATE SET
                  external_id=excluded.external_id,
                  source_name=excluded.source_name,
                  source_url=excluded.source_url,
                  title=excluded.title,
                  event_type=excluded.event_type,
                  analysis_method=excluded.analysis_method,
                  max_strength=excluded.max_strength,
                  updated_at=excluded.updated_at
                """,
                (
                    key,
                    external_id,
                    source_name,
                    source_url,
                    title,
                    event_type,
                    analysis_method,
                    max_strength,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT alert_id FROM alerts WHERE dedupe_key = ?", (key,)).fetchone()
            return int(row["alert_id"])

    def has_sent_alert(self, *, external_id: str | None, source_url: str, title: str) -> bool:
        key = _alert_dedupe_key(external_id=external_id, source_url=source_url, title=title)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT telegram_message_id
                FROM alerts
                WHERE dedupe_key = ?
                """,
                (key,),
            ).fetchone()
        return row is not None and row["telegram_message_id"] is not None

    def mark_alert_sent(self, alert_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE alerts
                SET telegram_message_id = ?, sent_at = ?
                WHERE alert_id = ?
                """,
                (message_id, time(), alert_id),
            )

    def record_feedback(self, record: FeedbackRecord) -> None:
        if record.action not in VALID_FEEDBACK_ACTIONS:
            raise ValueError(f"Unsupported feedback action: {record.action}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback (alert_id, action, user_id, username, message_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.alert_id,
                    record.action,
                    record.user_id,
                    record.username,
                    record.message_id,
                    record.created_at or time(),
                ),
            )

    def get_alert(self, alert_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
            return dict(row) if row is not None else None

    def feedback_counts(self, alert_id: int, *, actions: tuple[str, ...] | None = None) -> dict[str, int]:
        selected_actions = actions or tuple(sorted(VALID_FEEDBACK_ACTIONS))
        if not selected_actions:
            return {}
        placeholders = ", ".join("?" for _ in selected_actions)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT latest.action, COUNT(*) AS count
                FROM feedback AS latest
                JOIN (
                  SELECT user_id, MAX(feedback_id) AS feedback_id
                  FROM feedback
                  WHERE alert_id = ?
                  GROUP BY user_id
                ) AS per_user
                  ON per_user.feedback_id = latest.feedback_id
                WHERE latest.action IN ({placeholders})
                GROUP BY latest.action
                """,
                (alert_id, *selected_actions),
            )
            counts = {action: 0 for action in selected_actions}
            counts.update({str(row["action"]): int(row["count"]) for row in rows})
            return counts

    def list_alerts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM alerts ORDER BY alert_id")]

    def list_feedback(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT feedback.*, alerts.title, alerts.source_name, alerts.max_strength
                FROM feedback
                JOIN alerts ON alerts.alert_id = feedback.alert_id
                ORDER BY feedback.feedback_id
                """
            )
            return [dict(row) for row in rows]

    def get_telegram_update_offset(self) -> int | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM state WHERE key = ?", (TELEGRAM_UPDATE_OFFSET_KEY,)).fetchone()
            return int(row["value"]) if row is not None else None

    def set_telegram_update_offset(self, offset: int) -> None:
        if offset < 0:
            raise ValueError("Telegram update offset must be non-negative")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (TELEGRAM_UPDATE_OFFSET_KEY, str(offset)),
            )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                  alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  dedupe_key TEXT NOT NULL UNIQUE,
                  external_id TEXT,
                  source_name TEXT NOT NULL,
                  source_url TEXT NOT NULL,
                  title TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  analysis_method TEXT NOT NULL,
                  max_strength INTEGER NOT NULL,
                  telegram_message_id INTEGER,
                  sent_at REAL,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL
                )
                """
            )
            _ensure_column(conn, "alerts", "telegram_message_id", "INTEGER")
            _ensure_column(conn, "alerts", "sent_at", "REAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                  feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  alert_id INTEGER NOT NULL,
                  action TEXT NOT NULL,
                  user_id INTEGER NOT NULL,
                  username TEXT,
                  message_id INTEGER,
                  created_at REAL NOT NULL,
                  FOREIGN KEY(alert_id) REFERENCES alerts(alert_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn


def default_feedback_db_path(env: dict[str, str] | None = None) -> Path:
    values = env or environ
    configured = values.get("EGX_NEWS_BOT_FEEDBACK_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "feedback.sqlite3"


def _alert_dedupe_key(*, external_id: str | None, source_url: str, title: str) -> str:
    return external_id or source_url or title


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
