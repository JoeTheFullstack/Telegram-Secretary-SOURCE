"""Conversation state stored in SQLite (survives restarts)."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

SESSION_TTL_MINUTES = 30


@dataclass
class Session:
    flow: str
    awaiting: Optional[str] = None
    data: dict = field(default_factory=dict)


def get(conn: sqlite3.Connection, user_id: int, ttl_minutes: int = SESSION_TTL_MINUTES) -> Optional[Session]:
    row = conn.execute("SELECT * FROM sessions WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    age = datetime.now(timezone.utc) - datetime.fromisoformat(row["updated_at"])
    if age > timedelta(minutes=ttl_minutes):
        clear(conn, user_id)
        return None
    return Session(row["flow"], row["awaiting"], json.loads(row["data"]))


def save(conn: sqlite3.Connection, user_id: int, session: Session) -> None:
    conn.execute(
        "INSERT INTO sessions(user_id, flow, awaiting, data, updated_at) VALUES(?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET flow = excluded.flow, awaiting = excluded.awaiting, "
        "data = excluded.data, updated_at = excluded.updated_at",
        (user_id, session.flow, session.awaiting,
         json.dumps(session.data, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
    )


def clear(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
