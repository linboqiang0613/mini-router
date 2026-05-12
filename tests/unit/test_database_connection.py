# tests/unit/test_database_connection.py
"""Tests for DatabaseConnection."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mini_router.database.config import DatabaseConfig
from mini_router.database.connection import DatabaseConnection


class TestDatabaseConnection:
    """Test DatabaseConnection class."""

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
    async def test_connect_creates_pool(self):
        """Test connect creates connection pool."""
        config = DatabaseConfig(enabled=True, host="localhost")
        conn = DatabaseConnection(config)

        # Mock aiomysql.create_pool
        mock_pool = MagicMock()
        mock_pool.close = MagicMock()
        mock_pool.wait_closed = AsyncMock()

        with patch("aiomysql.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool
            await conn.connect()

            mock_create.assert_called_once_with(
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