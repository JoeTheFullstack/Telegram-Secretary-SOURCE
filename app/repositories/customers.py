"""customers table access. SQL only."""
from __future__ import annotations

import sqlite3
from typing import Optional


def find_by_phone(conn: sqlite3.Connection, phone: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT id, full_name FROM customers WHERE phone = ?", (phone,)).fetchone()


def insert(conn: sqlite3.Connection, data: dict, created_by: int) -> int:
    cur = conn.execute(
        "INSERT INTO customers(full_name, phone, budget_min, budget_max, "
        "preferred_location, property_type, created_by, assigned_to) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data["full_name"], data["phone"], data.get("budget_min"), data.get("budget_max"),
            data.get("preferred_location"), data.get("property_type"), created_by, created_by,
        ),
    )
    return cur.lastrowid
