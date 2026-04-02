"""
Database Module

Provides a PostgreSQL connection using the DATABASE_URL environment variable.
Used for persistent storage on Railway (and other cloud platforms).
Falls back gracefully to file-based persistence when DATABASE_URL is not set.
"""

import os
import logging
import threading

logger = logging.getLogger(__name__)

_local = threading.local()
_initialized = False
_db_available = None  # None = unknown, True/False after first check


def get_connection():
    """Return a thread-local psycopg2 connection, or None if DB is unavailable."""
    global _db_available

    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        if _db_available is not False:
            logger.info("DATABASE_URL not set — using file-based persistence")
            _db_available = False
        return None

    try:
        import psycopg2
    except ImportError:
        if _db_available is not False:
            logger.warning("psycopg2 not installed — using file-based persistence")
            _db_available = False
        return None

    conn = getattr(_local, 'conn', None)

    # Reconnect if connection is closed or broken
    if conn is None or conn.closed:
        conn = None
    else:
        try:
            # Quick liveness check
            conn.isolation_level  # noqa: accessing attribute pings the connection
        except Exception:
            conn = None

    if conn is None:
        try:
            conn = psycopg2.connect(database_url)
            conn.autocommit = True
            _local.conn = conn
            logger.debug("PostgreSQL connection established")
        except Exception as e:
            logger.error("PostgreSQL connection failed: %s", e)
            _db_available = False
            return None

    return conn


def init_db() -> bool:
    """
    Create required tables if they do not exist.
    Returns True if the database is available, False otherwise.
    """
    global _initialized, _db_available

    if _initialized:
        return _db_available is True

    conn = get_connection()
    if conn is None:
        _initialized = True
        return False

    try:
        import psycopg2
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kv_store (
                    key        TEXT        PRIMARY KEY,
                    value      JSONB       NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        _db_available = True
        _initialized = True
        logger.info("PostgreSQL tables ready — using database persistence")
        return True
    except Exception as e:
        logger.error("Database init failed: %s", e)
        _db_available = False
        _initialized = True
        return False


def db_set(key: str, value) -> bool:
    """
    Upsert a JSON value by key.
    Returns True on success, False if DB is unavailable or an error occurs.
    """
    if not init_db():
        return False
    conn = get_connection()
    if conn is None:
        return False
    try:
        import psycopg2.extras
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kv_store (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = NOW()
                """,
                (key, psycopg2.extras.Json(value))
            )
        return True
    except Exception as e:
        logger.error("DB write error [%s]: %s", key, e)
        return False


def db_get(key: str):
    """
    Fetch a JSON value by key.
    Returns the deserialized value, or None if the key does not exist
    or the DB is unavailable.
    """
    if not init_db():
        return None
    conn = get_connection()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM kv_store WHERE key = %s", (key,))
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error("DB read error [%s]: %s", key, e)
        return None
