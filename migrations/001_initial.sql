-- Initial schema. Never edit an applied migration; add 002_... instead.

CREATE TABLE kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE users (
    id           INTEGER PRIMARY KEY,
    telegram_id  INTEGER NOT NULL UNIQUE,
    display_name TEXT,
    role         TEXT NOT NULL CHECK (role IN ('owner', 'manager', 'staff', 'customer')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE customers (
    id                 INTEGER PRIMARY KEY,
    full_name          TEXT NOT NULL,
    phone              TEXT NOT NULL,
    budget_min         INTEGER,
    budget_max         INTEGER,
    preferred_location TEXT,
    property_type      TEXT,
    created_by         INTEGER NOT NULL REFERENCES users(id),
    assigned_to        INTEGER REFERENCES users(id),
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX idx_customers_phone ON customers(phone);

-- One active conversation flow per user; survives restarts.
CREATE TABLE sessions (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id),
    flow       TEXT NOT NULL,
    awaiting   TEXT,
    data       TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE audit_logs (
    id         INTEGER PRIMARY KEY,
    actor_id   INTEGER,
    action     TEXT NOT NULL,
    entity     TEXT,
    entity_id  INTEGER,
    details    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
