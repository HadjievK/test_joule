"""Unit tests for hana_cache.py.

All HANA connectivity is mocked via unittest.mock so tests run without a
live database. The tests verify the cache-key logic, TTL selection,
write-query detection, and cache-through behaviour.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure app/ is on sys.path so hana_cache can be imported
_APP_DIR = str(Path(__file__).parent.parent / "app")
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)


# ---------------------------------------------------------------------------
# Helpers to stub out hdbcli before importing hana_cache
# ---------------------------------------------------------------------------

def _make_hdbcli_stub():
    """Return a fake hdbcli.dbapi module with a connect() stub."""
    hdbcli_mod = types.ModuleType("hdbcli")
    dbapi_mod = types.ModuleType("hdbcli.dbapi")

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.rowcount = 0

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    dbapi_mod.connect = MagicMock(return_value=mock_conn)
    hdbcli_mod.dbapi = dbapi_mod

    return hdbcli_mod, dbapi_mod, mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_pool():
    """Reset the connection pool singleton between tests."""
    # Reload hana_cache with a fresh singleton state
    if "hana_cache" in sys.modules:
        del sys.modules["hana_cache"]
    yield
    if "hana_cache" in sys.modules:
        del sys.modules["hana_cache"]


@pytest.fixture()
def hana_env(monkeypatch):
    monkeypatch.setenv("HANA_USER", "TEST_USER")
    monkeypatch.setenv("HANA_PASSWORD", "TEST_PASS")
    monkeypatch.setenv("HANA_HOST", "test.hana.cloud:443")


# ---------------------------------------------------------------------------
# Tests: _is_write_query
# ---------------------------------------------------------------------------

class TestIsWriteQuery:
    def _load(self):
        hdbcli_mod, dbapi_mod, _, _ = _make_hdbcli_stub()
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            return hana_cache

    def test_read_query_not_write(self):
        mod = self._load()
        assert mod._is_write_query("show me the payroll run status") is False

    def test_trigger_is_write(self):
        mod = self._load()
        assert mod._is_write_query("trigger a new payroll run") is True

    def test_cancel_is_write(self):
        mod = self._load()
        assert mod._is_write_query("cancel the S4 payroll run") is True

    def test_create_is_write(self):
        mod = self._load()
        assert mod._is_write_query("create a time sheet entry for employee 1001") is True

    def test_update_is_write(self):
        mod = self._load()
        assert mod._is_write_query("update cost assignment for EMP-001") is True

    def test_upsert_is_write(self):
        mod = self._load()
        assert mod._is_write_query("upsert employee compensation record") is True


# ---------------------------------------------------------------------------
# Tests: _resolve_ttl
# ---------------------------------------------------------------------------

class TestResolveTtl:
    def _load(self):
        hdbcli_mod, dbapi_mod, _, _ = _make_hdbcli_stub()
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            return hana_cache

    def test_report_ttl(self):
        mod = self._load()
        assert mod._resolve_ttl("generate payroll report for Q1") == mod.REPORT_TTL

    def test_compliance_ttl(self):
        mod = self._load()
        assert mod._resolve_ttl("run compliance check for statutory deductions") == mod.COMPLIANCE_TTL

    def test_default_ttl(self):
        mod = self._load()
        assert mod._resolve_ttl("get time sheets for employee 1001") == mod.DEFAULT_TTL


# ---------------------------------------------------------------------------
# Tests: cache_get
# ---------------------------------------------------------------------------

class TestCacheGet:
    def _setup(self, row_value=None):
        hdbcli_mod, dbapi_mod, mock_conn, mock_cursor = _make_hdbcli_stub()
        mock_cursor.fetchone.return_value = (row_value,) if row_value else None
        mock_conn.cursor.return_value = mock_cursor
        return hdbcli_mod, dbapi_mod, mock_conn, mock_cursor

    def test_cache_miss_returns_none(self, hana_env):
        hdbcli_mod, dbapi_mod, _, _ = self._setup(None)
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            result = hana_cache.cache_get("get payroll run status", "ctx-001")
        assert result is None

    def test_cache_hit_returns_value(self, hana_env):
        cached_response = '{"status": "completed", "records": 42}'
        hdbcli_mod, dbapi_mod, _, _ = self._setup(cached_response)
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            result = hana_cache.cache_get("get payroll run status", "ctx-001")
        assert result == cached_response

    def test_write_query_skips_cache(self, hana_env):
        hdbcli_mod, dbapi_mod, mock_conn, _ = self._setup(None)
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            result = hana_cache.cache_get("trigger payroll run", "ctx-001")
        assert result is None
        # No DB call should have been made
        mock_conn.cursor.assert_not_called()

    def test_db_error_returns_none(self, hana_env):
        hdbcli_mod, dbapi_mod, mock_conn, _ = self._setup(None)
        mock_conn.cursor.side_effect = RuntimeError("DB connection lost")
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            # Should not raise
            result = hana_cache.cache_get("get payroll run status", "ctx-001")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: cache_set
# ---------------------------------------------------------------------------

class TestCacheSet:
    def test_stores_read_query(self, hana_env):
        hdbcli_mod, dbapi_mod, mock_conn, mock_cursor = _make_hdbcli_stub()
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            hana_cache.cache_set("get time sheets", "ctx-002", "time sheet data here")
        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()

    def test_skips_write_query(self, hana_env):
        hdbcli_mod, dbapi_mod, mock_conn, mock_cursor = _make_hdbcli_stub()
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            hana_cache.cache_set("trigger payroll run", "ctx-002", "run result")
        # No DB interaction expected
        mock_conn.cursor.assert_not_called()

    def test_db_error_is_non_fatal(self, hana_env):
        hdbcli_mod, dbapi_mod, mock_conn, mock_cursor = _make_hdbcli_stub()
        mock_cursor.execute.side_effect = RuntimeError("insert failed")
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            # Must not raise
            hana_cache.cache_set("get time sheets", "ctx-002", "data")


# ---------------------------------------------------------------------------
# Tests: cache_invalidate
# ---------------------------------------------------------------------------

class TestCacheInvalidate:
    def test_deletes_entries_for_context(self, hana_env):
        hdbcli_mod, dbapi_mod, mock_conn, mock_cursor = _make_hdbcli_stub()
        mock_cursor.rowcount = 3
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            hana_cache.cache_invalidate("ctx-003")
        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()

    def test_db_error_is_non_fatal(self, hana_env):
        hdbcli_mod, dbapi_mod, mock_conn, mock_cursor = _make_hdbcli_stub()
        mock_cursor.execute.side_effect = RuntimeError("delete failed")
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            hana_cache.cache_invalidate("ctx-003")  # must not raise


# ---------------------------------------------------------------------------
# Tests: cache_stats
# ---------------------------------------------------------------------------

class TestCacheStats:
    def test_returns_stats_dict(self, hana_env):
        hdbcli_mod, dbapi_mod, mock_conn, mock_cursor = _make_hdbcli_stub()
        mock_cursor.fetchone.return_value = (10, 7)
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            stats = hana_cache.cache_stats()
        assert stats["total_entries"] == 10
        assert stats["active_entries"] == 7
        assert "hana_host" in stats

    def test_db_error_returns_error_dict(self, hana_env):
        hdbcli_mod, dbapi_mod, mock_conn, mock_cursor = _make_hdbcli_stub()
        mock_cursor.execute.side_effect = RuntimeError("query failed")
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            stats = hana_cache.cache_stats()
        assert "error" in stats


# ---------------------------------------------------------------------------
# Tests: make_key determinism
# ---------------------------------------------------------------------------

class TestMakeKey:
    def test_same_inputs_same_key(self):
        hdbcli_mod, dbapi_mod, _, _ = _make_hdbcli_stub()
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            k1, h1 = hana_cache._make_key("payroll query", "ctx-1")
            k2, h2 = hana_cache._make_key("payroll query", "ctx-1")
        assert k1 == k2
        assert h1 == h2

    def test_different_context_different_key(self):
        hdbcli_mod, dbapi_mod, _, _ = _make_hdbcli_stub()
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            k1, _ = hana_cache._make_key("payroll query", "ctx-A")
            k2, _ = hana_cache._make_key("payroll query", "ctx-B")
        assert k1 != k2

    def test_key_length_within_bounds(self):
        hdbcli_mod, dbapi_mod, _, _ = _make_hdbcli_stub()
        with patch.dict(sys.modules, {"hdbcli": hdbcli_mod, "hdbcli.dbapi": dbapi_mod}):
            import hana_cache
            cache_key, query_hash = hana_cache._make_key("x" * 500, "long-context-id")
        assert len(cache_key) <= 128
        assert len(query_hash) <= 64
