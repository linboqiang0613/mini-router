# tests/unit/test_database_connection.py
"""Tests for DatabaseConnection."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mini_router.database.config import DatabaseConfig
from mini_router.database.connection import DatabaseConnection
import mini_router.database.connection as connection_module


class TestDatabaseConnection:
    """Test DatabaseConnection class."""

    @pytest.fixture(autouse=True)
    def mock_aiomysql(self, monkeypatch):
        """Provide a fake aiomysql module for connection tests."""
        fake_aiomysql = MagicMock()
        fake_aiomysql.create_pool = AsyncMock()
        fake_aiomysql.DictCursor = object()
        monkeypatch.setattr(connection_module, "aiomysql", fake_aiomysql, raising=False)
        monkeypatch.setattr(connection_module, "AIOMYSQL_AVAILABLE", True)
        return fake_aiomysql

    def test_init(self):
        """Test initialization."""
        config = DatabaseConfig(host="testhost", port=3307)
        conn = DatabaseConnection(config)
        assert conn.config.host == "testhost"
        assert conn.config.port == 3307
        assert conn._pool is None
        assert conn._connected == False

    def test_is_connected_false_by_default(self):
        """Test is_connected property default."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)
        assert conn.is_connected == False

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self, mock_aiomysql):
        """Test connect creates connection pool."""
        config = DatabaseConfig(host="localhost")
        conn = DatabaseConnection(config)

        # Mock aiomysql.create_pool
        mock_pool = MagicMock()
        mock_pool.close = MagicMock()
        mock_pool.wait_closed = AsyncMock()

        mock_aiomysql.create_pool.return_value = mock_pool
        await conn.connect()

        mock_aiomysql.create_pool.assert_called_once_with(
            host="localhost",
            port=3306,
            user="root",
            password="",
            db="mini_router",
            charset="utf8mb4",
            minsize=2,
            maxsize=10,
            autocommit=True,
        )
        assert conn.is_connected == True

    @pytest.mark.asyncio
    async def test_close_closes_pool(self):
        """Test close closes connection pool."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)

        mock_pool = MagicMock()
        mock_pool.close = MagicMock()
        mock_pool.wait_closed = AsyncMock()
        conn._pool = mock_pool
        conn._connected = True

        await conn.close()

        mock_pool.close.assert_called_once()
        mock_pool.wait_closed.assert_called_once()
        assert conn._pool is None
        assert conn.is_connected == False

    @pytest.mark.asyncio
    async def test_close_without_pool_does_nothing(self):
        """Test close when pool is None."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)
        conn._pool = None
        conn._connected = False

        await conn.close()

        assert conn._pool is None
        assert conn.is_connected == False

    @pytest.mark.asyncio
    async def test_execute_returns_rowcount(self):
        """Test execute returns affected rows."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)

        # Create proper async context manager mocks
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 5
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

        conn._pool = mock_pool
        conn._connected = True

        result = await conn.execute("UPDATE test SET x = ?", ("value",))
        assert result == 5

    @pytest.mark.asyncio
    async def test_execute_many_returns_rowcount(self):
        """Test execute_many returns affected rows."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)

        # Create proper async context manager mocks
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 3
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

        conn._pool = mock_pool
        conn._connected = True

        result = await conn.execute_many(
            "INSERT INTO test (x) VALUES (?)",
            [("value1",), ("value2",), ("value3",)]
        )
        assert result == 3

    @pytest.mark.asyncio
    async def test_execute_many_empty_params_returns_zero(self):
        """Test execute_many returns 0 for empty params list."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)

        result = await conn.execute_many("INSERT INTO test (x) VALUES (?)", [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_fetch_one_returns_dict(self):
        """Test fetch_one returns dict when row found."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)

        # Create proper async context manager mocks
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"id": 1, "name": "test"})
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

        conn._pool = mock_pool
        conn._connected = True

        result = await conn.fetch_one("SELECT * FROM test WHERE id = ?", (1,))
        assert result == {"id": 1, "name": "test"}

    @pytest.mark.asyncio
    async def test_fetch_one_returns_none_when_no_row(self):
        """Test fetch_one returns None when no row found."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)

        # Create proper async context manager mocks
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

        conn._pool = mock_pool
        conn._connected = True

        result = await conn.fetch_one("SELECT * FROM test WHERE id = ?", (999,))
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_all_returns_list_of_dicts(self):
        """Test fetch_all returns list of dicts."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)

        # Create proper async context manager mocks
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[
            {"id": 1, "name": "test1"},
            {"id": 2, "name": "test2"},
        ])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

        conn._pool = mock_pool
        conn._connected = True

        result = await conn.fetch_all("SELECT * FROM test")
        assert result == [
            {"id": 1, "name": "test1"},
            {"id": 2, "name": "test2"},
        ]

    @pytest.mark.asyncio
    async def test_fetch_all_returns_empty_list_when_no_rows(self):
        """Test fetch_all returns empty list when no rows found."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)

        # Create proper async context manager mocks
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

        conn._pool = mock_pool
        conn._connected = True

        result = await conn.fetch_all("SELECT * FROM test WHERE id = ?", (999,))
        assert result == []

    @pytest.mark.asyncio
    async def test_acquire_raises_runtime_error_when_not_connected(self):
        """Test acquire raises RuntimeError when pool is not connected."""
        config = DatabaseConfig()
        conn = DatabaseConnection(config)
        # conn._pool is None by default, so not connected

        with pytest.raises(RuntimeError, match="Database not connected"):
            async with conn.acquire():
                pass
