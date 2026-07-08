"""
Week 3: MySQL connection pool for the property-search skill.

Reads connection settings from the project's .env file (falls back to
already-exported environment variables, e.g. when run under OpenClaw).
"""

import os
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
_POOL = None


def _load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _get_pool() -> pooling.MySQLConnectionPool:
    global _POOL
    if _POOL is None:
        _load_dotenv(_ENV_PATH)
        _POOL = pooling.MySQLConnectionPool(
            pool_name="idx_exchange_pool",
            pool_size=5,
            host=os.environ.get("MYSQL_HOST", "localhost"),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DATABASE", "idx_exchange"),
        )
    return _POOL


@contextmanager
def get_connection():
    """Borrow a pooled connection; returns it to the pool on exit."""
    conn = _get_pool().get_connection()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor(dictionary: bool = True):
    """Borrow a pooled connection and yield a cursor, committing on success."""
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=dictionary)
        try:
            yield cursor
            conn.commit()
        finally:
            cursor.close()
