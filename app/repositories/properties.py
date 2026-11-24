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


def search(
    conn: sqlite3.Connection,
    *,
    property_type: Optional[str] = None,
    location: Optional[str] = None,
    keyword: Optional[str] = None,
    min_area: Optional[int] = None,
    max_price: Optional[int] = None,
    available_only: bool = True,
    limit: int = 5,
    offset: int = 0,
):
    """Return (total_count, page_rows); all dynamic values are SQL parameters."""
    where = []
    params = []
    if available_only:
        where.append("status = 'available'")
    if property_type:
        where.append("property_type = ?")
        params.append(property_type)
    if location:
        where.append("location LIKE ?")
        params.append(f"%{location}%")
    if keyword:
        where.append("(title LIKE ? OR location LIKE ?)")
        params.extend((f"%{keyword}%", f"%{keyword}%"))
    if min_area is not None:
        where.append("area_m2 >= ?")
        params.append(min_area)
    if max_price is not None:
        where.append("price <= ?")
        params.append(max_price)
    clause = " WHERE " + " AND ".join(where) if where else ""
    count_row = conn.execute("SELECT COUNT(*) AS c FROM properties" + clause, params).fetchone()
    rows = conn.execute(
        "SELECT id, title, property_type, area_m2, location, price, status, created_at "
        "FROM properties" + clause +
        " ORDER BY CASE status WHEN 'available' THEN 0 WHEN 'reserved' THEN 1 ELSE 2 END, id DESC "
        "LIMIT ? OFFSET ?",
        [*params, max(1, min(int(limit), 20)), max(0, int(offset))],
    ).fetchall()
    return int(count_row["c"]), rows


def list_media(conn: sqlite3.Connection, property_id: int):
    return conn.execute(
        "SELECT kind, file_id, caption FROM property_media WHERE property_id = ? ORDER BY id",
        (property_id,),
    ).fetchall()


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
