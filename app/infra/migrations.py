"""Versioned SQL migrations: apply migrations/*.sql in order, once each."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_NAME_RE = re.compile(r"^[0-9A-Za-z_.\-]+$")


def run_migrations(conn: sqlite3.Connection, directory: Path) -> list:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in sorted(Path(directory).glob("*.sql")):
        version = path.stem
        if version in done:
            continue
        if not _NAME_RE.match(version):
            raise ValueError(f"bad migration file name: {path.name}")
        sql = path.read_text(encoding="utf-8")
        # Script + bookkeeping row in one transaction: all or nothing.
        conn.executescript(
            f"BEGIN;\n{sql}\n"
            f"INSERT INTO schema_migrations(version) VALUES ('{version}');\nCOMMIT;"
        )
        applied.append(version)
    return applied
