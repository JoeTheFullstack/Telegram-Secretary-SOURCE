"""audit_logs table: who did what. Append-only."""
from __future__ import annotations

import json
import sqlite3
from typing import Optional


def log(conn: sqlite3.Connection, actor_id: Optional[int], action: str,
        entity: Optional[str] = None, entity_id: Optional[int] = None,
        details: Optional[dict] = None) -> None:
    conn.execute(
        "INSERT INTO audit_logs(actor_id, action, entity, entity_id, details) VALUES(?, ?, ?, ?, ?)",
        (actor_id, action, entity, entity_id,
         json.dumps(details, ensure_ascii=False) if details else None),
    )
