"""properties table access. SQL only."""
from __future__ import annotations

import sqlite3
from typing import Optional


def insert(conn: sqlite3.Connection, data: dict, title: str, created_by: int) -> int:
    cur = conn.execute(
        "INSERT INTO properties(title, property_type, area_m2, location, price, created_by) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        (title, data["property_type"], data["area_m2"], data["location"], data["price"], created_by),
    )
    return cur.lastrowid


def get(conn: sqlite3.Connection, property_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM properties WHERE id = ?", (property_id,)).fetchone()



def media_exists(conn: sqlite3.Connection, property_id: int, file_unique_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM property_media WHERE property_id = ? AND file_unique_id = ? LIMIT 1",
        (property_id, file_unique_id),
    ).fetchone() is not None


def insert_media(conn: sqlite3.Connection, property_id: int, media: dict, added_by: int) -> int:
    cur = conn.execute(
        "INSERT INTO property_media(property_id, kind, file_id, file_unique_id, media_group_id, caption, added_by) "
        "VALUES(?, ?, ?, ?, ?, ?, ?)",
        (property_id, media["kind"], media["file_id"], media.get("file_unique_id"),
         media.get("media_group_id"), media.get("caption") or None, added_by),
    )
    return cur.lastrowid


def count_media(conn: sqlite3.Connection, property_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM property_media WHERE property_id = ?", (property_id,)
    ).fetchone()
    return int(row["c"])
