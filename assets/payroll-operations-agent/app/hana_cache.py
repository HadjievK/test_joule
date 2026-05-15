"""
SAP HANA Cloud caching layer for the Payroll Operations Agent.

Connection details are resolved from environment variables:

  HANA_HOST     — SQL Endpoint host
                  Default: a3dacfda-9c88-4a95-9466-a995043a281d.hana.prod-eu12.hanacloud.ondemand.com
  HANA_PORT     — SQL Endpoint port (default: 443)
  HANA_USER     — Database user (required)
  HANA_PASSWORD — Database password (required)

The module creates a single PAYROLL_CACHE table on first connection and exposes
a simple async-compatible interface for get / set / invalidate operations.
Cache entries are keyed by (query_hash, context_id) and carry a TTL.
Write-type queries (trigger, cancel, create, update, upsert) are never cached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection configuration
# ---------------------------------------------------------------------------

HANA_HOST = os.environ.get(
    "HANA_HOST",
    "a3dacfda-9c88-4a95-9466-a995043a281d.hana.prod-eu12.hanacloud.ondemand.com",
)
HANA_PORT = int(os.environ.get("HANA_PORT", "443"))
HANA_USER = os.environ.get("HANA_USER", "")
HANA_PASSWORD = os.environ.get("HANA_PASSWORD", "")

# Default TTLs (seconds) per query category
DEFAULT_TTL = int(os.environ.get("HANA_CACHE_TTL_DEFAULT", "300"))   # 5 min
REPORT_TTL = int(os.environ.get("HANA_CACHE_TTL_REPORT", "1800"))    # 30 min
COMPLIANCE_TTL = int(os.environ.get("HANA_CACHE_TTL_COMPLIANCE", "600"))  # 10 min

# Keywords that indicate a write / mutating operation — never cache these
_WRITE_KEYWORDS = frozenset(
    [
        "trigger",
        "cancel",
        "create",
        "update",
        "upsert",
        "delete",
        "patch",
        "post",
        "initiate",
        "correct",
    ]
)

# DDL for the cache table
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS PAYROLL_CACHE (
    CACHE_KEY     NVARCHAR(128)  NOT NULL,
    CONTEXT_ID    NVARCHAR(256)  NOT NULL DEFAULT '',
    CACHE_DATA    NCLOB          NOT NULL,
    CREATED_AT    TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    EXPIRES_AT    TIMESTAMP      NOT NULL,
    QUERY_HASH    NVARCHAR(64)   NOT NULL,
    PRIMARY KEY (CACHE_KEY, CONTEXT_ID)
)
"""


# ---------------------------------------------------------------------------
# Connection pool (thread-local singleton)
# ---------------------------------------------------------------------------

class _HanaConnectionPool:
    """Lazy-initialised, thread-safe HANA connection wrapper."""

    _instance: Optional["_HanaConnectionPool"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._conn = None
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "_HanaConnectionPool":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _connect(self):
        """Create a new HANA connection. Raises if credentials are missing."""
        try:
            from hdbcli import dbapi  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "hdbcli is not installed. Add 'hdbcli' to requirements.txt."
            ) from exc

        if not HANA_USER or not HANA_PASSWORD:
            raise RuntimeError(
                "HANA_USER and HANA_PASSWORD environment variables must be set."
            )

        logger.info(
            "Connecting to SAP HANA Cloud at %s:%s as %s", HANA_HOST, HANA_PORT, HANA_USER
        )
        conn = dbapi.connect(
            address=HANA_HOST,
            port=HANA_PORT,
            user=HANA_USER,
            password=HANA_PASSWORD,
            encrypt=True,
            sslValidateCertificate=True,
        )
        return conn

    def get_connection(self):
        """Return a live connection, reconnecting if necessary."""
        if self._conn is None or not self._is_alive():
            self._conn = self._connect()
            if not self._initialized:
                self._ensure_table()
                self._initialized = True
        return self._conn

    def _is_alive(self) -> bool:
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT 1 FROM DUMMY")
            cur.close()
            return True
        except Exception:
            return False

    def _ensure_table(self) -> None:
        """Create PAYROLL_CACHE table if it does not exist."""
        try:
            cur = self._conn.cursor()
            cur.execute(_CREATE_TABLE_SQL)
            self._conn.commit()
            cur.close()
            logger.info("PAYROLL_CACHE table verified / created.")
        except Exception as exc:
            logger.warning("Could not create PAYROLL_CACHE table: %s", exc)


# ---------------------------------------------------------------------------
# Public cache API
# ---------------------------------------------------------------------------

def _make_key(query: str, context_id: str) -> tuple[str, str]:
    """Return (cache_key, query_hash) for the given inputs."""
    query_hash = hashlib.sha256(query.encode()).hexdigest()[:64]
    cache_key = hashlib.sha256(f"{context_id}:{query}".encode()).hexdigest()[:128]
    return cache_key, query_hash


def _is_write_query(query: str) -> bool:
    """Return True if the query describes a mutating / write operation."""
    lower = query.lower()
    return any(kw in lower for kw in _WRITE_KEYWORDS)


def _resolve_ttl(query: str) -> int:
    """Pick an appropriate TTL based on query content."""
    lower = query.lower()
    if any(kw in lower for kw in ("report", "summary", "generate")):
        return REPORT_TTL
    if any(kw in lower for kw in ("compliance", "statutory", "tax")):
        return COMPLIANCE_TTL
    return DEFAULT_TTL


def cache_get(query: str, context_id: str) -> Optional[str]:
    """
    Retrieve a cached response for the given query and context.

    Returns the cached response string, or None if not found / expired.
    Never raises — cache misses are always safe to ignore.
    """
    if _is_write_query(query):
        return None

    try:
        pool = _HanaConnectionPool.get_instance()
        conn = pool.get_connection()
        cache_key, _ = _make_key(query, context_id)

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.cursor()
        cur.execute(
            "SELECT CACHE_DATA FROM PAYROLL_CACHE "
            "WHERE CACHE_KEY = ? AND CONTEXT_ID = ? AND EXPIRES_AT > ?",
            (cache_key, context_id, now_str),
        )
        row = cur.fetchone()
        cur.close()

        if row:
            logger.debug("HANA cache HIT for key %s", cache_key[:16])
            return row[0]

        logger.debug("HANA cache MISS for key %s", cache_key[:16])
        return None

    except Exception as exc:
        logger.warning("HANA cache_get failed (non-fatal): %s", exc)
        return None


def cache_set(query: str, context_id: str, response: str) -> None:
    """
    Store a response in the HANA cache.

    Never raises — cache write failures are always non-fatal.
    """
    if _is_write_query(query):
        return

    try:
        pool = _HanaConnectionPool.get_instance()
        conn = pool.get_connection()
        cache_key, query_hash = _make_key(query, context_id)
        ttl = _resolve_ttl(query)

        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        expires_str = expires.strftime("%Y-%m-%d %H:%M:%S")

        cur = conn.cursor()
        # UPSERT semantics via DELETE + INSERT
        cur.execute(
            "DELETE FROM PAYROLL_CACHE WHERE CACHE_KEY = ? AND CONTEXT_ID = ?",
            (cache_key, context_id),
        )
        cur.execute(
            "INSERT INTO PAYROLL_CACHE "
            "(CACHE_KEY, CONTEXT_ID, CACHE_DATA, CREATED_AT, EXPIRES_AT, QUERY_HASH) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cache_key, context_id, response, now_str, expires_str, query_hash),
        )
        conn.commit()
        cur.close()
        logger.debug("HANA cache SET key %s (TTL %ds)", cache_key[:16], ttl)

    except Exception as exc:
        logger.warning("HANA cache_set failed (non-fatal): %s", exc)


def cache_invalidate(context_id: str) -> None:
    """
    Remove all cached entries for a given context.

    Call after any write operation that may affect subsequent read results.
    Never raises.
    """
    try:
        pool = _HanaConnectionPool.get_instance()
        conn = pool.get_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM PAYROLL_CACHE WHERE CONTEXT_ID = ?", (context_id,)
        )
        conn.commit()
        deleted = cur.rowcount
        cur.close()
        logger.info("HANA cache invalidated %d entr(ies) for context %s", deleted, context_id)

    except Exception as exc:
        logger.warning("HANA cache_invalidate failed (non-fatal): %s", exc)


def cache_stats() -> dict[str, Any]:
    """Return basic cache statistics. Never raises."""
    try:
        pool = _HanaConnectionPool.get_instance()
        conn = pool.get_connection()
        cur = conn.cursor()

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN EXPIRES_AT > ? THEN 1 ELSE 0 END) "
            "FROM PAYROLL_CACHE",
            (now_str,),
        )
        row = cur.fetchone()
        cur.close()

        return {
            "total_entries": row[0] if row else 0,
            "active_entries": row[1] if row else 0,
            "hana_host": HANA_HOST,
            "hana_port": HANA_PORT,
        }

    except Exception as exc:
        logger.warning("HANA cache_stats failed (non-fatal): %s", exc)
        return {"error": str(exc)}
