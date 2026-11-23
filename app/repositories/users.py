"""users table access. SQL only."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class User:
    id: int
    telegram_id: int
    display_name: Optional[str]
    role: str


def _row(r) -> Optional[User]:
    return User(r["id"], r["telegram_id"], r["display_name"], r["role"]) if r else None


def get_by_telegram_id(conn: sqlite3.Connection, telegram_id: int) -> Optional[User]:
    return _row(conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone())


def create(conn: sqlite3.Connection, telegram_id: int, display_name: Optional[str], role: str) -> User:
    cur = conn.execute(
        "INSERT INTO users(telegram_id, display_name, role) VALUES(?, ?, ?)",
        (telegram_id, display_name, role),
    )
    return User(cur.lastrowid, telegram_id, display_name, role)


def set_role(conn: sqlite3.Connection, user_id: int, role: str) -> None:
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
