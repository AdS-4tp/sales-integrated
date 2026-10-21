"""SQLite storage. One connection per request/operation; WAL for concurrent reads."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY,
  name TEXT, org TEXT, role TEXT,
  email TEXT NOT NULL UNIQUE,
  country TEXT, recipient_type TEXT, description TEXT,
  source_name TEXT, source_url TEXT, found_at TEXT,
  fit_score INTEGER, fit_reason TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  hold_reason TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS decisions(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                  -- email | reply | post
  lead_id INTEGER REFERENCES leads(id),
  subject TEXT, body TEXT, footer TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  guard TEXT, adjusted TEXT, model TEXT,
  edited INTEGER NOT NULL DEFAULT 0,
  decided_by TEXT,
  created_at TEXT, decided_at TEXT
);

-- Audit trail: every outbound, inbound and system event on a lead.
CREATE TABLE IF NOT EXISTS touches(
  id INTEGER PRIMARY KEY,
  lead_id INTEGER REFERENCES leads(id),
  direction TEXT NOT NULL,             -- out | in | sys
  kind TEXT NOT NULL,                  -- intro | response | reply | booked | won
  body TEXT, at TEXT,
  rules_version TEXT, guard TEXT,
  simulated INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS suppression(email TEXT PRIMARY KEY, reason TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY, decision_id INTEGER, to_email TEXT,
  subject TEXT, body TEXT, at TEXT
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def get_json(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_json(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )
    conn.commit()
