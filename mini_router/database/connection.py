# mini_router/database/connection.py
"""Database connection module.

Provides async connection pool management for MySQL-compatible databases.
Reference: CoPaw database/connection.py (with TDSQL aliases removed, structlog used).
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

import structlog

from mini_router.database.config import DatabaseConfig

logger = structlog.get_logger()

# Try to import aiomysql, fall back to None if not available
try:
    import aiomysql
    AIOMYSQL_AVAILABLE = True
except ImportError:
    AIOMYSQL_AVAILABLE = False
    logger.warning("aiomysql_not_installed", message="Database features will be unavailable")


class DatabaseConnection:
    """Database connection with async connection pool.

    Uses aiomysql for async MySQL operations.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        """Initialize database connection.

        Args:
            config: Database configuration
        """
        self.config = config
        self._pool: Optional[Any] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._connected and self._pool is not None

    async def connect(self) -> None:
        """Create connection pool."""
        if not AIOMYSQL_AVAILABLE:
            raise RuntimeError(
                "aiomysql is not installed. Please install it with: pip install aiomysql"
            )

        if self._pool is not None:
            return

        try:
            self._pool = await aiomysql.create_pool(
                host=self.config.host,
                port=self.config.port,
                user=self.config.user,
                password=self.config.password,
                db=self.config.database,
                charset=self.config.charset,
                minsize=self.config.min_connections,
                maxsize=self.config.max_connections,
                autocommit=True,
            )
            self._connected = True
            logger.info(
                "database_pool_created",
                host=self.config.host,
                port=self.config.port,
                database=self.config.database,
                minsize=self.config.min_connections,
                maxsize=self.config.max_connections,
            )
        except Exception as e:
            logger.error("database_pool_failed", error=str(e), error_type=type(e).__name__)
            self._connected = False
            raise

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            self._connected = False
            logger.info("database_pool_closed")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        """Acquire a connection from the pool.

        Yields:
            aiomysql.Connection: Database connection
        """
        if self._pool is None:
            raise RuntimeError("Database not connected")
        async with self._pool.acquire() as conn:
            yield conn

    async def execute(
        self,
        query: str,
        params: Optional[tuple[Any, ...]] = None,
    ) -> int:
        """Execute a query and return affected rows.

        Args:
            query: SQL query
            params: Query parameters

        Returns:
            Number of affected rows
        """
        async with self.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return int(cur.rowcount)

    async def execute_many(
        self,
        query: str,
        params_list: list[tuple[Any, ...]],
    ) -> int:
        """Execute a query multiple times with different parameters.

        Args:
            query: SQL query
            params_list: List of parameter tuples

        Returns:
            Number of affected rows
        """
        if not params_list:
            return 0
        async with self.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(query, params_list)
                return int(cur.rowcount)

    async def fetch_one(
        self,
        query: str,
        params: Optional[tuple[Any, ...]] = None,
    ) -> Optional[dict[str, Any]]:
        """Fetch a single row.

        Args:
            query: SQL query
            params: Query parameters

        Returns:
            Row as dict or None
        """
        async with self.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
                return dict(row) if row else None

    async def fetch_all(
        self,
        query: str,
        params: Optional[tuple[Any, ...]] = None,
    ) -> list[dict[str, Any]]:
        """Fetch all rows.

        Args:
            query: SQL query
            params: Query parameters

        Returns:
            List of rows as dicts
        """
        async with self.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
                return [dict(row) for row in rows] if rows else []
