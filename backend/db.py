"""
Database Module

Priority order:
  1. Supabase (SUPABASE_URL + SUPABASE_KEY) — preferred
  2. PostgreSQL via psycopg2 (DATABASE_URL) — fallback
  3. File-based persistence — local dev fallback
"""

import os
import logging
import threading

logger = logging.getLogger(__name__)

_local = threading.local()
_initialized = False
_db_available = None  # None = unknown, True/False after first check
_supabase_client = None


# ──────────────────────────────────────────────
# Supabase client
# ──────────────────────────────────────────────

def _get_supabase():
    """Return a cached Supabase client, or None if not configured."""
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    url = os.environ.get('SUPABASE_URL')
    key = os.environ.get('SUPABASE_KEY')
    if not url or not key:
        return None

    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
        logger.info("Supabase client initialised")
        return _supabase_client
    except ImportError:
        logger.warning("supabase package not installed — pip install supabase")
        return None
    except Exception as e:
        logger.error("Supabase init failed: %s", e)
        return None


def _supabase_ensure_table():
    """
    Supabase tables must be created via the dashboard or migrations.
    This logs a warning if the kv_store table doesn't exist yet.
    """
    client = _get_supabase()
    if client is None:
        return False
    try:
        client.table('kv_store').select('key').limit(1).execute()
        return True
    except Exception as e:
        logger.error(
            "kv_store table not found in Supabase. "
            "Create it with:\n"
            "  CREATE TABLE kv_store (\n"
            "    key TEXT PRIMARY KEY,\n"
            "    value JSONB NOT NULL,\n"
            "    updated_at TIMESTAMPTZ DEFAULT NOW()\n"
            "  );\n"
            "Error: %s", e
        )
        return False


# ──────────────────────────────────────────────
# psycopg2 / PostgreSQL fallback
# ──────────────────────────────────────────────

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

    if conn is None or conn.closed:
        conn = None
    else:
        try:
            conn.isolation_level  # liveness ping
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
    Create required tables if they do not exist (psycopg2 path only).
    Returns True if the database is available, False otherwise.
    """
    global _initialized, _db_available

    # Supabase path — table must exist already
    if _get_supabase() is not None:
        if not _initialized:
            _db_available = _supabase_ensure_table()
            _initialized = True
        return _db_available is True

    if _initialized:
        return _db_available is True

    conn = get_connection()
    if conn is None:
        _initialized = True
        return False

    try:
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


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def db_set(key: str, value) -> bool:
    """
    Upsert a JSON value by key.
    Returns True on success, False if DB is unavailable or an error occurs.
    """
    # Try Supabase first
    client = _get_supabase()
    if client is not None:
        if not init_db():
            return False
        try:
            client.table('kv_store').upsert(
                {'key': key, 'value': value, 'updated_at': 'now()'}
            ).execute()
            return True
        except Exception as e:
            logger.error("Supabase write error [%s]: %s", key, e)
            return False

    # psycopg2 fallback
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
    Returns the deserialized value, or None if not found / DB unavailable.
    """
    # Try Supabase first
    client = _get_supabase()
    if client is not None:
        if not init_db():
            return None
        try:
            res = client.table('kv_store').select('value').eq('key', key).execute()
            if res.data:
                return res.data[0]['value']
            return None
        except Exception as e:
            logger.error("Supabase read error [%s]: %s", key, e)
            return None

    # psycopg2 fallback
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
