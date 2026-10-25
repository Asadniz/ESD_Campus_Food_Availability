"""SQLite access. One short-lived connection per operation keeps the code simple."""
import contextlib
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS eateries (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    location TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS menu_items (
    id INTEGER PRIMARY KEY,
    eatery_id INTEGER NOT NULL REFERENCES eateries(id),
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price_pkr INTEGER NOT NULL,
    default_portions INTEGER NOT NULL,
    portions_left INTEGER NOT NULL,
    available INTEGER NOT NULL DEFAULT 1   -- staff switch; effective availability also needs portions_left > 0
);
CREATE TABLE IF NOT EXISTS holds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES menu_items(id),
    eatery_id INTEGER NOT NULL REFERENCES eateries(id),
    pickup_code TEXT NOT NULL,
    created_at REAL NOT NULL,
    planned_pickup_minutes INTEGER NOT NULL,
    status TEXT NOT NULL,                  -- active | picked_up | cancelled | expired
    closed_at REAL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,            -- fingerprint of the request body
    status_code INTEGER NOT NULL,
    response_body TEXT NOT NULL,           -- JSON of the original response
    created_at REAL NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextlib.contextmanager
def session():
    """Commit on success, roll back on any exception."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
