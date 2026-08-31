"""A dead-simple SQLite response cache.

Overpass rate-limits aggressively and Open-Meteo is slow for 34 years of daily
data. Everything fetched is stored here, and the demo cache is committed to the
repo so the app works with no network at all.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from .config import CACHE_DB

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(CACHE_DB, check_same_thread=False)
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            "  key TEXT PRIMARY KEY,"
            "  value TEXT NOT NULL,"
            "  fetched_at REAL NOT NULL)"
        )
        _conn.commit()
    return _conn


def get(key: str) -> Any | None:
    with _lock:
        row = _connect().execute(
            "SELECT value FROM cache WHERE key = ?", (key,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def put(key: str, value: Any) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, fetched_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, separators=(",", ":")), time.time()),
        )
        conn.commit()


def keys() -> list[str]:
    with _lock:
        rows = _connect().execute("SELECT key FROM cache ORDER BY key").fetchall()
    return [r[0] for r in rows]
