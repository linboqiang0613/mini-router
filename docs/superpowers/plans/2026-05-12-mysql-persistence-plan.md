# MySQL Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 mini-router 的配置存储从 YAML 文件迁移到 MySQL 数据库，支持生产环境多实例部署时的配置同步。

**Architecture:** 新增 database 基础设施层（连接池、配置类、Repository、同步服务），改造 TenantManager 和 Router 支持数据库存储，改造 server.py 启动逻辑支持环境变量选择配置文件和数据库初始化。

**Tech Stack:** aiomysql（异步连接池）、structlog（日志）、Pydantic（配置验证）、MySQL 5.7+（JSON 类型支持）

---

## File Structure

### 新增文件

| 文件 | 职责 |
|-----|-----|
| `mini_router/database/__init__.py` | 导出 DatabaseConfig, DatabaseConnection, ConfigRepository |
| `mini_router/database/config.py` | DatabaseConfig 配置类，环境变量加载逻辑 |
| `mini_router/database/connection.py` | DatabaseConnection 异步连接池管理 |
| `mini_router/database/repository.py` | ConfigRepository 数据表 CRUD 操作 |
| `mini_router/database/sync.py` | ConfigSyncService 配置同步轮询服务 |
| `mini_router/config/loader.py` | 配置加载器，支持环境变量选择 config_dev.yaml / config_prd.yaml |
| `config/config_dev.yaml` | 开发环境配置文件（数据库可选） |
| `config/config_prd.yaml` | 生产环境配置文件（数据库启用） |
| `scripts/init_db.sql` | 数据库表初始化 SQL |
| `scripts/yaml_to_mysql.py` | YAML 配置迁移脚本 |
| `tests/unit/test_database_config.py` | DatabaseConfig 测试 |
| `tests/unit/test_database_connection.py` | DatabaseConnection 测试 |
| `tests/unit/test_config_repository.py` | ConfigRepository 测试 |
| `tests/unit/test_config_sync.py` | ConfigSyncService 测试 |

### 改造文件

| 文件 | 改造内容 |
|-----|---------|
| `mini_router/config/config.py` | 新增 DatabaseConfig 字段到 RouterConfig |
| `mini_router/tenant/manager.py` | 支持 repository 加载，增加 reload() 方法 |
| `mini_router/router/router.py` | 增加 reload_config() 方法 |
| `mini_router/server.py` | 环境变量选择配置文件、数据库初始化、轮询任务启动 |
| `pyproject.toml` | 新增 aiomysql 依赖 |

---

## Task 1: 添加 aiomysql 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 编辑 pyproject.toml 添加 aiomysql**

```toml
# 在 dependencies 数组中添加
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "structlog>=23.0",
    "httpx>=0.25",
    "numpy>=1.24",
    "pyyaml>=6.0",
    "fastapi>=0.109",
    "uvicorn>=0.27",
    "transformers>=5.0",
    "aiomysql>=0.2.0",  # 新增
]
```

- [ ] **Step 2: 提交**

```bash
git add pyproject.toml
git commit -m "chore: add aiomysql dependency for MySQL persistence"
```

---

## Task 2: 创建 database/config.py

**Files:**
- Create: `mini_router/database/config.py`
- Test: `tests/unit/test_database_config.py`

- [ ] **Step 1: 编写失败的测试**

```python
# tests/unit/test_database_config.py
"""Tests for DatabaseConfig."""

import os
import pytest

from mini_router.database.config import DatabaseConfig, get_database_config


class TestDatabaseConfig:
    """Test DatabaseConfig class."""

    def test_default_values(self):
        """Test default configuration values."""
        config = DatabaseConfig()
        assert config.enabled == False
        assert config.host == "localhost"
        assert config.port == 3306
        assert config.user == "root"
        assert config.password == ""
        assert config.database == "mini_router"
        assert config.min_connections == 2
        assert config.max_connections == 10
        assert config.charset == "utf8mb4"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = DatabaseConfig(
            enabled=True,
            host="mysql.prod.internal",
            port=3307,
            user="app_user",
            password="secret",
            database="router_db",
            min_connections=5,
            max_connections=20,
        )
        assert config.enabled == True
        assert config.host == "mysql.prod.internal"
        assert config.port == 3307
        assert config.user == "app_user"
        assert config.password == "secret"
        assert config.database == "router_db"
        assert config.min_connections == 5
        assert config.max_connections == 20


class TestGetDatabaseConfig:
    """Test get_database_config function."""

    def test_with_config_object(self):
        """Test loading from config object."""
        config = DatabaseConfig(
            enabled=True,
            host="custom.host",
            database="custom_db",
        )
        result = get_database_config(config)
        assert result.enabled == True
        assert result.host == "custom.host"
        assert result.database == "custom_db"

    def test_without_config_uses_defaults(self):
        """Test default values when no config provided."""
        result = get_database_config()
        assert result.enabled == False
        assert result.host == "localhost"
        assert result.database == "mini_router"

    def test_password_from_env_strip_bee_prefix(self):
        """Test password extraction with BEE_ prefix."""
        os.environ["MINI_ROUTER_DB_ACCESS"] = "BEE_secret_password"
        result = get_database_config()
        assert result.password == "secret_password"
        del os.environ["MINI_ROUTER_DB_ACCESS"]

    def test_password_from_env_without_prefix(self):
        """Test password without BEE_ prefix."""
        os.environ["MINI_ROUTER_DB_ACCESS"] = "plain_password"
        result = get_database_config()
        assert result.password == "plain_password"
        del os.environ["MINI_ROUTER_DB_ACCESS"]

    def test_password_from_env_empty(self):
        """Test empty password."""
        os.environ["MINI_ROUTER_DB_ACCESS"] = ""
        result = get_database_config()
        assert result.password == ""
        del os.environ["MINI_ROUTER_DB_ACCESS"]

    def test_password_from_env_short_prefix(self):
        """Test password shorter than 4 chars."""
        os.environ["MINI_ROUTER_DB_ACCESS"] = "BEE"
        result = get_database_config()
        assert result.password == "BEE"
        del os.environ["MINI_ROUTER_DB_ACCESS"]
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/unit/test_database_config.py -v
```
Expected: FAIL - ModuleNotFoundError: No module named 'mini_router.database'

- [ ] **Step 3: 创建 mini_router/database/__init__.py**

```python
# mini_router/database/__init__.py
"""Database module for mini-router."""

from mini_router.database.config import DatabaseConfig, get_database_config
from mini_router.database.connection import DatabaseConnection
from mini_router.database.repository import ConfigRepository

__all__ = [
    "DatabaseConfig",
    "get_database_config",
    "DatabaseConnection",
    "ConfigRepository",
]
```

- [ ] **Step 4: 创建 mini_router/database/config.py**

```python
# mini_router/database/config.py
"""Database configuration module."""

import os
from typing import Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class DatabaseConfig(BaseModel):
    """Database connection configuration.

    Supports MySQL-compatible databases.
    """

    enabled: bool = Field(default=False, description="Whether database storage is enabled")
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=3306, description="Database port")
    user: str = Field(default="root", description="Database user")
    password: str = Field(default="", description="Database password (from env)")
    database: str = Field(default="mini_router", description="Database name")
    min_connections: int = Field(default=2, description="Minimum connection pool size")
    max_connections: int = Field(default=10, description="Maximum connection pool size")
    charset: str = Field(default="utf8mb4", description="Character set")


def get_database_config(
    config: Optional[DatabaseConfig] = None,
) -> DatabaseConfig:
    """Get database configuration with unified loading logic.

    Configuration priority (highest to lowest):
    1. Provided config object
    2. Environment variable MINI_ROUTER_DB_ACCESS (password, strip "BEE_" prefix)
    3. DatabaseConfig model defaults

    Args:
        config: Optional DatabaseConfig from YAML file

    Returns:
        DatabaseConfig instance
    """
    # Extract password from environment variable
    db_access = os.environ.get("MINI_ROUTER_DB_ACCESS", "")

    # Strip "BEE_" prefix (first 4 characters) - matches CoPaw convention
    if len(db_access) > 4:
        password = db_access[4:]
        logger.info("database_password_loaded", prefix_removed=True)
    else:
        password = db_access

    return DatabaseConfig(
        enabled=config.enabled if config else False,
        host=config.host if config else "localhost",
        port=config.port if config else 3306,
        user=config.user if config else "root",
        password=password,
        database=config.database if config else "mini_router",
        min_connections=config.min_connections if config else 2,
        max_connections=config.max_connections if config else 10,
        charset=config.charset if config else "utf8mb4",
    )
```

- [ ] **Step 5: 运行测试验证通过**

```bash
pytest tests/unit/test_database_config.py -v
```
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add mini_router/database/__init__.py mini_router/database/config.py tests/unit/test_database_config.py
git commit -m "feat: add DatabaseConfig for MySQL connection configuration"
```

---

## Task 3: 创建 database/connection.py

**Files:**
- Create: `mini_router/database/connection.py`
- Test: `tests/unit/test_database_connection.py`

- [ ] **Step 1: 编写失败的测试**

```python
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
    async def close_without_pool_does_nothing(self):
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

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 5

        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=MagicMock(return_value=mock_conn)))
        mock_conn.cursor = MagicMock(return_value=AsyncMock(__aenter__=MagicMock(return_value=mock_cursor), __aexit__=AsyncMock()))

        conn._pool = mock_pool
        conn._connected = True

        result = await conn.execute("UPDATE test SET x = ?", ("value",))
        assert result == 5
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/unit/test_database_connection.py -v
```
Expected: FAIL - ModuleNotFoundError: No module named 'mini_router.database.connection'

- [ ] **Step 3: 创建 mini_router/database/connection.py**

```python
# mini_router/database/connection.py
"""Database connection module.

Provides async connection pool management for MySQL-compatible databases.
Reference: CoPaw database/connection.py (with TDSQL aliases removed, structlog used).
"""

from contextlib import asynccontextmanager
from typing import Any, Optional

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
    async def acquire(self):
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
        params: Optional[tuple] = None,
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
                return cur.rowcount

    async def execute_many(
        self,
        query: str,
        params_list: list[tuple],
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
                return cur.rowcount

    async def fetch_one(
        self,
        query: str,
        params: Optional[tuple] = None,
    ) -> Optional[dict]:
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
        params: Optional[tuple] = None,
    ) -> list[dict]:
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
```

- [ ] **Step 4: 更新 __init__.py 导出 DatabaseConnection**

```python
# mini_router/database/__init__.py
"""Database module for mini-router."""

from mini_router.database.config import DatabaseConfig, get_database_config
from mini_router.database.connection import DatabaseConnection

__all__ = [
    "DatabaseConfig",
    "get_database_config",
    "DatabaseConnection",
]
```

- [ ] **Step 5: 运行测试验证通过**

```bash
pytest tests/unit/test_database_connection.py -v
```
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add mini_router/database/connection.py mini_router/database/__init__.py tests/unit/test_database_connection.py
git commit -m "feat: add DatabaseConnection with async pool management"
```

---

## Task 4: 创建 database/repository.py

**Files:**
- Create: `mini_router/database/repository.py`
- Test: `tests/unit/test_config_repository.py`

- [ ] **Step 1: 编写失败的测试**

```python
# tests/unit/test_config_repository.py
"""Tests for ConfigRepository."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from mini_router.database.config import DatabaseConfig
from mini_router.database.connection import DatabaseConnection
from mini_router.database.repository import ConfigRepository


class TestConfigRepositoryGlobalConfig:
    """Test global config operations."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database connection."""
        mock = MagicMock(spec=DatabaseConnection)
        mock.fetch_one = AsyncMock()
        mock.fetch_all = AsyncMock()
        mock.execute = AsyncMock(return_value=1)
        return mock

    @pytest.mark.asyncio
    async def test_get_global_config(self, mock_db):
        """Test fetching global config."""
        mock_db.fetch_one.return_value = {
            "config_data": {"server": {"host": "0.0.0.0"}},
            "version": 5,
        }

        repo = ConfigRepository(mock_db)
        result = await repo.get_global_config()

        assert result["config_data"]["server"]["host"] == "0.0.0.0"
        assert result["version"] == 5
        mock_db.fetch_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_global_config_not_found(self, mock_db):
        """Test fetching global config when not found."""
        mock_db.fetch_one.return_value = None

        repo = ConfigRepository(mock_db)
        result = await repo.get_global_config()

        assert result is None

    @pytest.mark.asyncio
    async def test_get_global_version(self, mock_db):
        """Test getting global config version."""
        mock_db.fetch_one.return_value = {"version": 10}

        repo = ConfigRepository(mock_db)
        result = await repo.get_global_version()

        assert result == 10

    @pytest.mark.asyncio
    async def test_get_global_version_empty_table(self, mock_db):
        """Test getting version when table is empty."""
        mock_db.fetch_one.return_value = None

        repo = ConfigRepository(mock_db)
        result = await repo.get_global_version()

        assert result == 0


class TestConfigRepositoryTenant:
    """Test tenant operations."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database connection."""
        mock = MagicMock(spec=DatabaseConnection)
        mock.fetch_one = AsyncMock()
        mock.fetch_all = AsyncMock()
        mock.execute = AsyncMock(return_value=1)
        return mock

    @pytest.mark.asyncio
    async def test_get_all_tenants(self, mock_db):
        """Test fetching all tenants."""
        mock_db.fetch_all.return_value = [
            {"tenant_id": "tenant-1", "apikey": "key-1", "enabled": True},
            {"tenant_id": "tenant-2", "apikey": "key-2", "enabled": True},
        ]

        repo = ConfigRepository(mock_db)
        result = await repo.get_all_tenants()

        assert len(result) == 2
        assert result[0]["tenant_id"] == "tenant-1"

    @pytest.mark.asyncio
    async def test_get_tenant_by_id(self, mock_db):
        """Test fetching tenant by ID."""
        mock_db.fetch_one.return_value = {
            "tenant_id": "test-tenant",
            "apikey": "test-key",
            "name": "Test Tenant",
        }

        repo = ConfigRepository(mock_db)
        result = await repo.get_tenant_by_id("test-tenant")

        assert result["tenant_id"] == "test-tenant"

    @pytest.mark.asyncio
    async def test_get_tenant_by_apikey(self, mock_db):
        """Test fetching tenant by apikey."""
        mock_db.fetch_one.return_value = {
            "tenant_id": "test-tenant",
            "apikey": "secret-key",
        }

        repo = ConfigRepository(mock_db)
        result = await repo.get_tenant_by_apikey("secret-key")

        assert result["apikey"] == "secret-key"

    @pytest.mark.asyncio
    async def test_create_tenant(self, mock_db):
        """Test creating tenant."""
        repo = ConfigRepository(mock_db)
        tenant_data = {
            "tenant_id": "new-tenant",
            "apikey": "new-key",
            "name": "New Tenant",
            "base_url_template": "https://api.example.com/v1",
            "timeout": 120.0,
        }

        await repo.create_tenant(tenant_data)

        mock_db.execute.assert_called_once()
        # Check that SQL contains INSERT
        call_args = mock_db.execute.call_args[0]
        assert "INSERT" in call_args[0]

    @pytest.mark.asyncio
    async def test_update_tenant(self, mock_db):
        """Test updating tenant."""
        repo = ConfigRepository(mock_db)
        updates = {"name": "Updated Name", "timeout": 180.0}

        await repo.update_tenant("test-tenant", updates)

        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        assert "UPDATE" in call_args[0]
        assert "version = version + 1" in call_args[0]

    @pytest.mark.asyncio
    async def test_delete_tenant(self, mock_db):
        """Test deleting tenant."""
        repo = ConfigRepository(mock_db)

        await repo.delete_tenant("test-tenant")

        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        assert "DELETE" in call_args[0]

    @pytest.mark.asyncio
    async def test_get_tenant_max_version(self, mock_db):
        """Test getting max tenant version."""
        mock_db.fetch_one.return_value = {"max_version": 15}

        repo = ConfigRepository(mock_db)
        result = await repo.get_tenant_max_version()

        assert result == 15

    @pytest.mark.asyncio
    async def test_get_tenant_max_version_empty(self, mock_db):
        """Test getting max version when empty."""
        mock_db.fetch_one.return_value = {"max_version": None}

        repo = ConfigRepository(mock_db)
        result = await repo.get_tenant_max_version()

        assert result == 0


class TestConfigRepositoryApiKeyPool:
    """Test API key pool operations."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database connection."""
        mock = MagicMock(spec=DatabaseConnection)
        mock.fetch_all = AsyncMock()
        mock.execute = AsyncMock(return_value=1)
        return mock

    @pytest.mark.asyncio
    async def test_get_apikey_pool(self, mock_db):
        """Test fetching API key pool."""
        mock_db.fetch_all.return_value = [
            {"tenant_id": "tenant-1", "apikey": "llm-key-1", "apikey_order": 0, "is_active": True},
            {"tenant_id": "tenant-1", "apikey": "llm-key-2", "apikey_order": 1, "is_active": True},
        ]

        repo = ConfigRepository(mock_db)
        result = await repo.get_apikey_pool("tenant-1")

        assert len(result) == 2
        assert result[0]["apikey"] == "llm-key-1"

    @pytest.mark.asyncio
    async def test_add_apikey_to_pool(self, mock_db):
        """Test adding API key to pool."""
        repo = ConfigRepository(mock_db)

        await repo.add_apikey_to_pool("tenant-1", "new-llm-key", 2)

        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        assert "INSERT" in call_args[0]
        assert "mini_router_apikey_pool" in call_args[0]

    @pytest.mark.asyncio
    async def test_update_apikey_status(self, mock_db):
        """Test updating API key status."""
        repo = ConfigRepository(mock_db)

        await repo.update_apikey_status("tenant-1", 0, False)

        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        assert "UPDATE" in call_args[0]
        assert "is_active" in call_args[0]
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/unit/test_config_repository.py -v
```
Expected: FAIL - ModuleNotFoundError: No module named 'mini_router.database.repository'

- [ ] **Step 3: 创建 mini_router/database/repository.py**

```python
# mini_router/database/repository.py
"""Config repository for database CRUD operations."""

import json
import structlog

from mini_router.database.connection import DatabaseConnection

logger = structlog.get_logger()


class ConfigRepository:
    """Repository for configuration tables CRUD operations."""

    def __init__(self, db: DatabaseConnection) -> None:
        """Initialize repository.

        Args:
            db: Database connection instance
        """
        self.db = db

    # === Global Config Operations ===

    async def get_global_config(self) -> dict | None:
        """Get global router configuration.

        Returns:
            Dict with config_data and version, or None if not found
        """
        row = await self.db.fetch_one(
            "SELECT config_data, version FROM mini_router_config LIMIT 1"
        )
        return row

    async def save_global_config(self, config_data: dict) -> None:
        """Save global router configuration.

        Args:
            config_data: Full router config as dict
        """
        await self.db.execute(
            "UPDATE mini_router_config SET config_data = ?, version = version + 1",
            (json.dumps(config_data),)
        )
        logger.info("global_config_saved")

    async def get_global_version(self) -> int:
        """Get global config version number.

        Returns:
            Version number, 0 if no config exists
        """
        row = await self.db.fetch_one(
            "SELECT version FROM mini_router_config LIMIT 1"
        )
        return row["version"] if row else 0

    # === Tenant Operations ===

    async def get_all_tenants(self) -> list[dict]:
        """Get all enabled tenants.

        Returns:
            List of tenant dicts
        """
        rows = await self.db.fetch_all(
            "SELECT * FROM mini_router_tenant WHERE enabled = TRUE"
        )
        return rows

    async def get_tenant_by_id(self, tenant_id: str) -> dict | None:
        """Get tenant by tenant_id.

        Args:
            tenant_id: Tenant identifier

        Returns:
            Tenant dict or None
        """
        row = await self.db.fetch_one(
            "SELECT * FROM mini_router_tenant WHERE tenant_id = ?",
            (tenant_id,)
        )
        return row

    async def get_tenant_by_apikey(self, apikey: str) -> dict | None:
        """Get tenant by authentication API key.

        Args:
            apikey: Authentication API key

        Returns:
            Tenant dict or None
        """
        row = await self.db.fetch_one(
            "SELECT * FROM mini_router_tenant WHERE apikey = ?",
            (apikey,)
        )
        return row

    async def create_tenant(self, tenant_data: dict) -> None:
        """Create a new tenant.

        Args:
            tenant_data: Tenant configuration dict
        """
        # Insert tenant (version starts at 1)
        await self.db.execute(
            """
            INSERT INTO mini_router_tenant
            (tenant_id, apikey, name, enabled, base_url_template, timeout,
             apikey_pool_mode, decisions, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                tenant_data["tenant_id"],
                tenant_data["apikey"],
                tenant_data.get("name"),
                tenant_data.get("enabled", True),
                tenant_data["base_url_template"],
                tenant_data.get("timeout", 120.0),
                tenant_data.get("apikey_pool_mode", "round_robin"),
                json.dumps(tenant_data.get("decisions")) if tenant_data.get("decisions") else None,
            )
        )
        logger.info("tenant_created", tenant_id=tenant_data["tenant_id"])

    async def update_tenant(self, tenant_id: str, updates: dict) -> None:
        """Update tenant configuration.

        Args:
            tenant_id: Tenant identifier
            updates: Dict of fields to update
        """
        # Build dynamic UPDATE query
        update_fields = []
        params = []
        for key, value in updates.items():
            if key in ("tenant_id", "id", "created_at"):
                continue  # Skip immutable fields
            if key == "decisions":
                update_fields.append("decisions = ?")
                params.append(json.dumps(value) if value else None)
            else:
                update_fields.append(f"{key} = ?")
                params.append(value)

        if not update_fields:
            return

        # Add version increment
        update_fields.append("version = version + 1")
        params.append(tenant_id)

        sql = f"UPDATE mini_router_tenant SET {', '.join(update_fields)} WHERE tenant_id = ?"
        await self.db.execute(sql, tuple(params))
        logger.info("tenant_updated", tenant_id=tenant_id)

    async def delete_tenant(self, tenant_id: str) -> None:
        """Delete tenant.

        Args:
            tenant_id: Tenant identifier
        """
        await self.db.execute(
            "DELETE FROM mini_router_tenant WHERE tenant_id = ?",
            (tenant_id,)
        )
        # Also delete API key pool entries
        await self.db.execute(
            "DELETE FROM mini_router_apikey_pool WHERE tenant_id = ?",
            (tenant_id,)
        )
        logger.info("tenant_deleted", tenant_id=tenant_id)

    async def get_tenant_max_version(self) -> int:
        """Get maximum version number across all tenants.

        Returns:
            Max version, 0 if no tenants
        """
        row = await self.db.fetch_one(
            "SELECT MAX(version) as max_version FROM mini_router_tenant"
        )
        return row["max_version"] if row and row["max_version"] else 0

    # === API Key Pool Operations ===

    async def get_apikey_pool(self, tenant_id: str) -> list[dict]:
        """Get API key pool for tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            List of API key pool entries
        """
        rows = await self.db.fetch_all(
            """
            SELECT * FROM mini_router_apikey_pool
            WHERE tenant_id = ?
            ORDER BY apikey_order
            """,
            (tenant_id,)
        )
        return rows

    async def add_apikey_to_pool(
        self,
        tenant_id: str,
        apikey: str,
        order: int,
    ) -> None:
        """Add API key to tenant's pool.

        Args:
            tenant_id: Tenant identifier
            apikey: LLM API key
            order: Order index
        """
        await self.db.execute(
            """
            INSERT INTO mini_router_apikey_pool
            (tenant_id, apikey, apikey_order, is_active)
            VALUES (?, ?, ?, TRUE)
            """,
            (tenant_id, apikey, order)
        )
        logger.info("apikey_added_to_pool", tenant_id=tenant_id, order=order)

    async def update_apikey_status(
        self,
        tenant_id: str,
        order: int,
        is_active: bool,
    ) -> None:
        """Update API key active status (for fallback mode).

        Args:
            tenant_id: Tenant identifier
            order: Order index
            is_active: Whether key is usable
        """
        await self.db.execute(
            """
            UPDATE mini_router_apikey_pool
            SET is_active = ?
            WHERE tenant_id = ? AND apikey_order = ?
            """,
            (is_active, tenant_id, order)
        )
        logger.info(
            "apikey_status_updated",
            tenant_id=tenant_id,
            order=order,
            is_active=is_active,
        )
```

- [ ] **Step 4: 更新 __init__.py 导出 ConfigRepository**

```python
# mini_router/database/__init__.py
"""Database module for mini-router."""

from mini_router.database.config import DatabaseConfig, get_database_config
from mini_router.database.connection import DatabaseConnection
from mini_router.database.repository import ConfigRepository

__all__ = [
    "DatabaseConfig",
    "get_database_config",
    "DatabaseConnection",
    "ConfigRepository",
]
```

- [ ] **Step 5: 运行测试验证通过**

```bash
pytest tests/unit/test_config_repository.py -v
```
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add mini_router/database/repository.py mini_router/database/__init__.py tests/unit/test_config_repository.py
git commit -m "feat: add ConfigRepository for database CRUD operations"
```

---

## Task 5: 创建 database/sync.py

**Files:**
- Create: `mini_router/database/sync.py`
- Test: `tests/unit/test_config_sync.py`

- [ ] **Step 1: 编写失败的测试**

```python
# tests/unit/test_config_sync.py
"""Tests for ConfigSyncService."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mini_router.database.sync import ConfigSyncService


class TestConfigSyncService:
    """Test ConfigSyncService."""

    @pytest.fixture
    def mock_components(self):
        """Create mock components."""
        repo = MagicMock()
        repo.get_global_version = AsyncMock(return_value=1)
        repo.get_tenant_max_version = AsyncMock(return_value=5)

        tenant_manager = MagicMock()
        tenant_manager.reload = AsyncMock()

        router = MagicMock()
        router.reload_config = AsyncMock()

        return repo, tenant_manager, router

    def test_init(self, mock_components):
        """Test initialization."""
        repo, tm, router = mock_components
        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
            global_poll_interval=120,
            tenant_poll_interval=10,
        )

        assert sync.global_poll_interval == 120
        assert sync.tenant_poll_interval == 10
        assert sync._running == False
        assert sync._global_version == 0
        assert sync._tenant_version == 0

    def test_init_with_env_vars(self, mock_components):
        """Test initialization with environment variables."""
        repo, tm, router = mock_components

        with patch.dict("os.environ", {
            "MINI_ROUTER_GLOBAL_POLL_INTERVAL": "60",
            "MINI_ROUTER_TENANT_POLL_INTERVAL": "5",
        }):
            sync = ConfigSyncService(
                repository=repo,
                tenant_manager=tm,
                router=router,
            )
            # Should use default values (env vars handled in server.py)
            assert sync.global_poll_interval == 120
            assert sync.tenant_poll_interval == 10

    @pytest.mark.asyncio
    async def test_poll_global_version_change(self, mock_components):
        """Test global config poll detects version change."""
        repo, tm, router = mock_components
        repo.get_global_version = AsyncMock(side_effect=[1, 2, 2])

        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
            global_poll_interval=0.1,  # Fast for testing
        )

        # Set initial version
        sync._global_version = 1

        # Run one poll iteration
        sync._running = True
        await sync._poll_global_once()
        sync._running = False

        # Should have called reload_config
        router.reload_config.assert_called_once()
        assert sync._global_version == 2

    @pytest.mark.asyncio
    async def test_poll_global_no_change(self, mock_components):
        """Test global config poll with no version change."""
        repo, tm, router = mock_components
        repo.get_global_version = AsyncMock(return_value=1)

        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
        )
        sync._global_version = 1
        sync._running = True

        await sync._poll_global_once()
        sync._running = False

        # Should NOT have called reload_config
        router.reload_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_tenant_version_change(self, mock_components):
        """Test tenant config poll detects version change."""
        repo, tm, router = mock_components
        repo.get_tenant_max_version = AsyncMock(side_effect=[10, 15, 15])

        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
            tenant_poll_interval=0.1,
        )

        sync._tenant_version = 10
        sync._running = True

        await sync._poll_tenant_once()
        sync._running = False

        tm.reload.assert_called_once()
        assert sync._tenant_version == 15

    @pytest.mark.asyncio
    async def test_poll_tenant_no_change(self, mock_components):
        """Test tenant config poll with no version change."""
        repo, tm, router = mock_components
        repo.get_tenant_max_version = AsyncMock(return_value=10)

        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
        )
        sync._tenant_version = 10
        sync._running = True

        await sync._poll_tenant_once()
        sync._running = False

        tm.reload.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_creates_tasks(self, mock_components):
        """Test start creates polling tasks."""
        repo, tm, router = mock_components
        sync = ConfigSyncService(repo, tm, router)

        await sync.start()

        assert sync._running == True
        assert sync._global_task is not None
        assert sync._tenant_task is not None

        await sync.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, mock_components):
        """Test stop cancels polling tasks."""
        repo, tm, router = mock_components
        sync = ConfigSyncService(repo, tm, router)

        await sync.start()
        await sync.stop()

        assert sync._running == False
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/unit/test_config_sync.py -v
```
Expected: FAIL - ModuleNotFoundError

- [ ] **Step 3: 创建 mini_router/database/sync.py**

```python
# mini_router/database/sync.py
"""Config sync service for polling database changes."""

import asyncio
import os
import structlog

from mini_router.database.repository import ConfigRepository
from mini_router.tenant.manager import TenantManager
from mini_router.router.router import Router

logger = structlog.get_logger()


class ConfigSyncService:
    """Configuration sync service.

    Polls database for version changes and triggers reloads.
    """

    def __init__(
        self,
        repository: ConfigRepository,
        tenant_manager: TenantManager,
        router: Router,
        global_poll_interval: int = 120,
        tenant_poll_interval: int = 10,
    ) -> None:
        """Initialize sync service.

        Args:
            repository: Config repository
            tenant_manager: Tenant manager instance
            router: Router instance
            global_poll_interval: Global config poll interval (seconds), default 120
            tenant_poll_interval: Tenant config poll interval (seconds), default 10
        """
        self.repository = repository
        self.tenant_manager = tenant_manager
        self.router = router

        # Use environment variables if set
        env_global = os.environ.get("MINI_ROUTER_GLOBAL_POLL_INTERVAL")
        env_tenant = os.environ.get("MINI_ROUTER_TENANT_POLL_INTERVAL")

        self.global_poll_interval = int(env_global) if env_global else global_poll_interval
        self.tenant_poll_interval = int(env_tenant) if env_tenant else tenant_poll_interval

        self._running = False
        self._global_version = 0
        self._tenant_version = 0
        self._global_task: asyncio.Task | None = None
        self._tenant_task: asyncio.Task | None = None

        logger.info(
            "sync_service_initialized",
            global_interval=self.global_poll_interval,
            tenant_interval=self.tenant_poll_interval,
        )

    async def start(self) -> None:
        """Start polling tasks."""
        if self._running:
            return

        self._running = True

        # Initialize version tracking
        self._global_version = await self.repository.get_global_version()
        self._tenant_version = await self.repository.get_tenant_max_version()

        logger.info(
            "sync_service_started",
            initial_global_version=self._global_version,
            initial_tenant_version=self._tenant_version,
        )

        # Create polling tasks
        self._global_task = asyncio.create_task(self._poll_global_loop())
        self._tenant_task = asyncio.create_task(self._poll_tenant_loop())

    async def stop(self) -> None:
        """Stop polling tasks."""
        self._running = False

        if self._global_task:
            self._global_task.cancel()
            try:
                await self._global_task
            except asyncio.CancelledError:
                pass
            self._global_task = None

        if self._tenant_task:
            self._tenant_task.cancel()
            try:
                await self._tenant_task
            except asyncio.CancelledError:
                pass
            self._tenant_task = None

        logger.info("sync_service_stopped")

    async def _poll_global_loop(self) -> None:
        """Global config polling loop."""
        while self._running:
            await asyncio.sleep(self.global_poll_interval)
            if not self._running:
                break
            await self._poll_global_once()

    async def _poll_global_once(self) -> None:
        """Single global config poll."""
        try:
            version = await self.repository.get_global_version()
            if version > self._global_version:
                logger.info(
                    "global_config_changed",
                    old_version=self._global_version,
                    new_version=version,
                )
                self._global_version = version
                await self.router.reload_config()
        except Exception as e:
            logger.error(
                "global_poll_error",
                error=str(e),
                error_type=type(e).__name__,
            )

    async def _poll_tenant_loop(self) -> None:
        """Tenant config polling loop."""
        while self._running:
            await asyncio.sleep(self.tenant_poll_interval)
            if not self._running:
                break
            await self._poll_tenant_once()

    async def _poll_tenant_once(self) -> None:
        """Single tenant config poll."""
        try:
            version = await self.repository.get_tenant_max_version()
            if version > self._tenant_version:
                logger.info(
                    "tenant_config_changed",
                    old_version=self._tenant_version,
                    new_version=version,
                )
                self._tenant_version = version
                await self.tenant_manager.reload()
        except Exception as e:
            logger.error(
                "tenant_poll_error",
                error=str(e),
                error_type=type(e).__name__,
            )
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/unit/test_config_sync.py -v
```
Expected: PASS (可能需要调整测试方法名，添加 `_poll_global_once` 和 `_poll_tenant_once` 方法)

- [ ] **Step 5: 提交**

```bash
git add mini_router/database/sync.py tests/unit/test_config_sync.py
git commit -m "feat: add ConfigSyncService for polling database changes"
```

---

## Task 6: 创建 config/loader.py

**Files:**
- Create: `mini_router/config/loader.py`

- [ ] **Step 1: 创建配置加载器**

```python
# mini_router/config/loader.py
"""Configuration loader with environment-based file selection."""

import os
from pathlib import Path

import structlog
import yaml

from mini_router.config.config import RouterConfig
from mini_router.database.config import DatabaseConfig, get_database_config

logger = structlog.get_logger()


def get_config_path() -> Path:
    """Get config file path based on environment.

    Environment variable MINI_ROUTER_ENV controls which config file to load:
    - dev: config/config_dev.yaml
    - prd: config/config_prd.yaml
    - default: config/config_dev.yaml

    Returns:
        Path to config file
    """
    env = os.environ.get("MINI_ROUTER_ENV", "dev")
    config_file = f"config/config_{env}.yaml"
    path = Path(config_file)

    if not path.exists():
        # Fallback to default config.yaml if env-specific file not found
        fallback = Path("config.yaml")
        if fallback.exists():
            logger.warning(
                "config_file_not_found",
                path=str(path),
                fallback=str(fallback),
            )
            return fallback
        else:
            logger.error(
                "no_config_file_found",
                attempted=str(path),
                fallback=str(fallback),
            )
            raise FileNotFoundError(f"No config file found: {path} or {fallback}")

    return path


def load_config() -> RouterConfig:
    """Load router configuration from file.

    Loads config from environment-specific file and merges with
    database configuration from environment variables.

    Returns:
        RouterConfig instance
    """
    config_path = get_config_path()
    logger.info("loading_config", path=str(config_path))

    # Load YAML config
    router_config = RouterConfig.from_yaml(config_path)

    # Extract database config if present
    raw_data = yaml.safe_load(config_path.open())
    db_config_raw = raw_data.get("database", {})
    if db_config_raw:
        db_config = DatabaseConfig(**db_config_raw)
        db_config = get_database_config(db_config)
        router_config.database = db_config
        logger.info(
            "database_config_loaded",
            enabled=db_config.enabled,
            host=db_config.host,
            database=db_config.database,
        )
    else:
        router_config.database = get_database_config()
        logger.info("database_config_default")

    return router_config
```

- [ ] **Step 2: 提交**

```bash
git add mini_router/config/loader.py
git commit -m "feat: add config loader with environment-based file selection"
```

---

## Task 7: 改造 mini_router/config/config.py

**Files:**
- Modify: `mini_router/config/config.py`

- [ ] **Step 1: 新增 DatabaseConfig 字段到 RouterConfig**

在 `mini_router/config/config.py` 文件末尾，修改 `RouterConfig` 类：

```python
# 在 RouterConfig 类中新增 database 字段

class RouterConfig(BaseModel):
    """Root configuration for the router."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    decisions: list[Decision] = Field(default_factory=list)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    database: DatabaseConfig | None = None  # 新增

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RouterConfig":
        """Load configuration from YAML file."""
        path = Path(path)
        with path.open() as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RouterConfig":
        """Create configuration from dictionary."""
        return cls.model_validate(data)
```

同时在文件顶部添加导入：

```python
# 在文件顶部导入区域添加
from mini_router.database.config import DatabaseConfig
```

- [ ] **Step 2: 提交**

```bash
git add mini_router/config/config.py
git commit -m "feat: add database field to RouterConfig"
```

---

## Task 8: 改造 mini_router/tenant/manager.py

**Files:**
- Modify: `mini_router/tenant/manager.py`
- Test: `tests/unit/test_tenant_manager.py`（改造现有测试）

- [ ] **Step 1: 改造 TenantManager 支持数据库**

```python
# mini_router/tenant/manager.py 改造后的完整代码

"""Tenant manager for CRUD operations and persistence."""

from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
import yaml

from mini_router.tenant.types import TenantConfig

logger = structlog.get_logger()


class TenantManager:
    """Manages tenant configurations with CRUD operations.

    Supports both YAML file and database persistence.
    """

    def __init__(
        self,
        repository: Any = None,  # ConfigRepository (avoid circular import)
        yaml_path: str = "config/tenants.yaml",
    ) -> None:
        """Initialize TenantManager.

        Args:
            repository: ConfigRepository instance for database operations
            yaml_path: Path to YAML file for file-based persistence
        """
        self.repository = repository
        self.yaml_path = yaml_path
        self._tenants: dict[str, TenantConfig] = {}
        self._apikey_index: dict[str, str] = {}
        self._apikey_pool: dict[str, list[str]] = {}  # LLM API keys

    def load(self) -> None:
        """Load tenants from storage.

        Delegates to _load_from_db() or _load_from_yaml() based on repository.
        """
        if self.repository:
            self._load_from_db()
        else:
            self._load_from_yaml()

    def _load_from_yaml(self) -> None:
        """Load tenants from YAML file."""
        path = Path(self.yaml_path)

        if not path.exists():
            self._tenants = {}
            self._apikey_index = {}
            self._apikey_pool = {}
            return

        with path.open() as f:
            data = yaml.safe_load(f)

        if data is None or "tenants" not in data:
            self._tenants = {}
            self._apikey_index = {}
            self._apikey_pool = {}
            return

        self._tenants = {}
        self._apikey_index = {}
        self._apikey_pool = {}

        for tenant_data in data.get("tenants", []):
            tenant = TenantConfig(**tenant_data)
            self._tenants[tenant.tenant_id] = tenant
            self._apikey_index[tenant.apikey] = tenant.tenant_id
            # Load API key pool from tenant data
            if tenant.apikey_pool:
                self._apikey_pool[tenant.tenant_id] = tenant.apikey_pool

        logger.info("tenants_loaded_from_yaml", count=len(self._tenants))

    async def _load_from_db(self) -> None:
        """Load tenants from database."""
        self._tenants = {}
        self._apikey_index = {}
        self._apikey_pool = {}

        tenants_data = await self.repository.get_all_tenants()
        for t in tenants_data:
            tenant = TenantConfig(
                tenant_id=t["tenant_id"],
                apikey=t["apikey"],
                name=t.get("name"),
                enabled=t["enabled"],
                base_url_template=t["base_url_template"],
                timeout=t.get("timeout", 120.0),
                apikey_pool_mode=t.get("apikey_pool_mode", "round_robin"),
                decisions=t.get("decisions") or [],
                created_at=t.get("created_at"),
                updated_at=t.get("updated_at"),
            )
            self._tenants[tenant.tenant_id] = tenant
            self._apikey_index[tenant.apikey] = tenant.tenant_id

            # Load API key pool from database
            pool_data = await self.repository.get_apikey_pool(tenant.tenant_id)
            self._apikey_pool[tenant.tenant_id] = [
                k["apikey"] for k in pool_data if k["is_active"]
            ]

        logger.info("tenants_loaded_from_db", count=len(self._tenants))

    async def reload(self) -> None:
        """Reload all tenants from storage.

        Called by ConfigSyncService when version changes detected.
        """
        self._tenants.clear()
        self._apikey_index.clear()
        self._apikey_pool.clear()

        if self.repository:
            await self._load_from_db()
        else:
            self._load_from_yaml()

        logger.info("tenants_reloaded", count=len(self._tenants))

    def _save_to_yaml(self) -> None:
        """Save tenants to YAML file."""
        path = Path(self.yaml_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        tenants_data = [tenant.model_dump(mode="json") for tenant in self._tenants.values()]
        data = {"tenants": tenants_data}

        with path.open("w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    async def _save_to_db(self, tenant: TenantConfig) -> None:
        """Save tenant to database."""
        tenant_dict = tenant.model_dump(mode="json")
        await self.repository.create_tenant(tenant_dict)

        # Save API key pool
        if tenant.apikey_pool:
            for i, key in enumerate(tenant.apikey_pool):
                await self.repository.add_apikey_to_pool(tenant.tenant_id, key, i)

    # === CRUD Operations ===

    def get_by_apikey(self, apikey: str) -> TenantConfig | None:
        """Get tenant by authentication API key."""
        tenant_id = self._apikey_index.get(apikey)
        if tenant_id is None:
            return None
        return self._tenants.get(tenant_id)

    def get_by_id(self, tenant_id: str) -> TenantConfig | None:
        """Get tenant by ID."""
        return self._tenants.get(tenant_id)

    def list_all(self) -> list[TenantConfig]:
        """List all tenants."""
        return list(self._tenants.values())

    def create(self, tenant: TenantConfig) -> TenantConfig:
        """Create a new tenant.

        For database mode, this should be async. We keep sync for YAML compatibility.
        """
        if tenant.tenant_id in self._tenants:
            raise ValueError(f"Tenant '{tenant.tenant_id}' already exists")

        if tenant.apikey in self._apikey_index:
            raise ValueError(f"Apikey '{tenant.apikey}' already exists")

        now = datetime.now()
        tenant.created_at = now
        tenant.updated_at = now

        self._tenants[tenant.tenant_id] = tenant
        self._apikey_index[tenant.apikey] = tenant.tenant_id

        if tenant.apikey_pool:
            self._apikey_pool[tenant.tenant_id] = tenant.apikey_pool

        # Persist
        if self.repository:
            # Note: sync wrapper for async operation - caller should use async_create
            import asyncio
            asyncio.get_event_loop().run_until_complete(self._save_to_db(tenant))
        else:
            self._save_to_yaml()

        logger.info("tenant_created", tenant_id=tenant.tenant_id)
        return tenant

    async def async_create(self, tenant: TenantConfig) -> TenantConfig:
        """Async create for database mode."""
        if tenant.tenant_id in self._tenants:
            raise ValueError(f"Tenant '{tenant.tenant_id}' already exists")

        if tenant.apikey in self._apikey_index:
            raise ValueError(f"Apikey '{tenant.apikey}' already exists")

        now = datetime.now()
        tenant.created_at = now
        tenant.updated_at = now

        self._tenants[tenant.tenant_id] = tenant
        self._apikey_index[tenant.apikey] = tenant.tenant_id

        if tenant.apikey_pool:
            self._apikey_pool[tenant.tenant_id] = tenant.apikey_pool

        if self.repository:
            await self._save_to_db(tenant)
        else:
            self._save_to_yaml()

        logger.info("tenant_created", tenant_id=tenant.tenant_id)
        return tenant

    def update(self, tenant_id: str, updates: dict[str, Any]) -> TenantConfig | None:
        """Update tenant with partial updates."""
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return None

        valid_fields = set(TenantConfig.model_fields.keys())
        unknown_fields = set(updates.keys()) - valid_fields
        if unknown_fields:
            raise ValueError(f"Unknown fields: {unknown_fields}")

        # Handle apikey change
        if "apikey" in updates and updates["apikey"] != tenant.apikey:
            new_apikey = updates["apikey"]
            if new_apikey in self._apikey_index and self._apikey_index[new_apikey] != tenant_id:
                raise ValueError(f"Apikey '{new_apikey}' already exists")
            del self._apikey_index[tenant.apikey]
            self._apikey_index[new_apikey] = tenant_id

        # Merge updates
        update_data = tenant.model_dump()
        update_data.update(updates)

        updated_tenant = TenantConfig(**update_data)
        updated_tenant.updated_at = datetime.now()

        self._tenants[tenant_id] = updated_tenant

        if self.repository:
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                self.repository.update_tenant(tenant_id, updates)
            )
        else:
            self._save_to_yaml()

        logger.info("tenant_updated", tenant_id=tenant_id)
        return updated_tenant

    async def async_update(self, tenant_id: str, updates: dict[str, Any]) -> TenantConfig | None:
        """Async update for database mode."""
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return None

        valid_fields = set(TenantConfig.model_fields.keys())
        unknown_fields = set(updates.keys()) - valid_fields
        if unknown_fields:
            raise ValueError(f"Unknown fields: {unknown_fields}")

        if "apikey" in updates and updates["apikey"] != tenant.apikey:
            new_apikey = updates["apikey"]
            if new_apikey in self._apikey_index and self._apikey_index[new_apikey] != tenant_id:
                raise ValueError(f"Apikey '{new_apikey}' already exists")
            del self._apikey_index[tenant.apikey]
            self._apikey_index[new_apikey] = tenant_id

        update_data = tenant.model_dump()
        update_data.update(updates)

        updated_tenant = TenantConfig(**update_data)
        updated_tenant.updated_at = datetime.now()

        self._tenants[tenant_id] = updated_tenant

        if self.repository:
            await self.repository.update_tenant(tenant_id, updates)
        else:
            self._save_to_yaml()

        logger.info("tenant_updated", tenant_id=tenant_id)
        return updated_tenant

    def delete(self, tenant_id: str) -> bool:
        """Delete tenant."""
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return False

        del self._apikey_index[tenant.apikey]
        del self._tenants[tenant_id]
        if tenant_id in self._apikey_pool:
            del self._apikey_pool[tenant_id]

        if self.repository:
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                self.repository.delete_tenant(tenant_id)
            )
        else:
            self._save_to_yaml()

        logger.info("tenant_deleted", tenant_id=tenant_id)
        return True

    async def async_delete(self, tenant_id: str) -> bool:
        """Async delete for database mode."""
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return False

        del self._apikey_index[tenant.apikey]
        del self._tenants[tenant_id]
        if tenant_id in self._apikey_pool:
            del self._apikey_pool[tenant_id]

        if self.repository:
            await self.repository.delete_tenant(tenant_id)
        else:
            self._save_to_yaml()

        logger.info("tenant_deleted", tenant_id=tenant_id)
        return True
```

- [ ] **Step 2: 提交**

```bash
git add mini_router/tenant/manager.py
git commit -m "feat: add database persistence support to TenantManager"
```

---

## Task 9: 改造 mini_router/router/router.py

**Files:**
- Modify: `mini_router/router/router.py`

- [ ] **Step 1: 添加 reload_config 方法**

在 `Router` 类中添加方法：

```python
# 在 Router 类末尾添加

async def reload_config(self) -> None:
    """Reload configuration from database.

    Called by ConfigSyncService when global config version changes.
    """
    if not self._repository:
        logger.warning("reload_config_no_repository")
        return

    config_data = await self._repository.get_global_config()
    if config_data:
        new_config = RouterConfig.from_dict(config_data["config_data"])
        self.config = new_config
        self._initialize_components()
        logger.info("router_config_reloaded", version=config_data["version"])
```

同时在 `__init__` 中添加 repository 参数：

```python
def __init__(
    self,
    config: RouterConfig,
    repository: Any = None,  # ConfigRepository
) -> None:
    self.config = config
    self._repository = repository
    self._latency_tracker = LatencyTracker()
    self._initialize_components()
```

- [ ] **Step 2: 提交**

```bash
git add mini_router/router/router.py
git commit -m "feat: add reload_config method to Router"
```

---

## Task 10: 改造 mini_router/server.py

**Files:**
- Modify: `mini_router/server.py`

- [ ] **Step 1: 改造启动逻辑**

修改 `server.py` 的全局状态和初始化逻辑：

```python
# 在全局状态区域添加
_database_connection: DatabaseConnection | None = None
_repository: ConfigRepository | None = None
_sync_service: ConfigSyncService | None = None

# 修改 lifespan 函数
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    global _config, _database_connection, _repository, _tenant_manager, _router, _sync_service

    # Load config from environment-specific file
    from mini_router.config.loader import load_config
    _config = load_config()

    # Initialize database if enabled
    if _config.database and _config.database.enabled:
        from mini_router.database import DatabaseConnection, ConfigRepository
        from mini_router.database.sync import ConfigSyncService

        _database_connection = DatabaseConnection(_config.database)
        await _database_connection.connect()

        _repository = ConfigRepository(_database_connection)

        # Initialize TenantManager with repository
        _tenant_manager = TenantManager(repository=_repository)
        await _tenant_manager._load_from_db()

        # Initialize Router with repository
        _router = Router(_config, repository=_repository)

        # Initialize sync service
        _sync_service = ConfigSyncService(
            repository=_repository,
            tenant_manager=_tenant_manager,
            router=_router,
        )
        await _sync_service.start()

        logger.info(
            "database_initialized",
            host=_config.database.host,
            database=_config.database.database,
        )
    else:
        # YAML mode
        _tenant_manager = TenantManager()
        _tenant_manager.load()

        _router = Router(_config)

        logger.info("yaml_mode_initialized")

    logger.info("router_initialized", decisions=len(_router.config.decisions))

    yield

    # Shutdown
    if _sync_service:
        await _sync_service.stop()

    if _database_connection:
        await _database_connection.close()

    logger.info("router_shutdown")

# 修改 tenant API handlers 使用 async 方法
@app.post("/v1/tenants", response_model=TenantResponse, status_code=201)
async def create_tenant(request: TenantCreateRequest) -> TenantResponse:
    """Create a new tenant."""
    manager = get_tenant_manager()
    try:
        tenant = TenantConfig(**request.model_dump())
        if manager.repository:
            created = await manager.async_create(tenant)
        else:
            created = manager.create(tenant)
        return TenantResponse.from_config(created)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/v1/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(tenant_id: str, request: TenantUpdateRequest) -> TenantResponse:
    """Update a tenant."""
    manager = get_tenant_manager()
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        tenant = manager.get_by_id(tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
        return TenantResponse.from_config(tenant)

    try:
        if manager.repository:
            updated = await manager.async_update(tenant_id, updates)
        else:
            updated = manager.update(tenant_id, updates)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
        return TenantResponse.from_config(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/v1/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str) -> dict[str, str]:
    """Delete a tenant."""
    manager = get_tenant_manager()
    if manager.repository:
        deleted = await manager.async_delete(tenant_id)
    else:
        deleted = manager.delete(tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return {"status": "deleted"}

# 修改 main 函数
def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Mini-Router HTTP Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    logger.info("starting_server", host=args.host, port=args.port)

    uvicorn.run(app, host=args.host, port=args.port)
```

- [ ] **Step 2: 提交**

```bash
git add mini_router/server.py
git commit -m "feat: integrate database initialization and config sync in server startup"
```

---

## Task 11: 创建配置文件

**Files:**
- Create: `config/config_dev.yaml`
- Create: `config/config_prd.yaml`

- [ ] **Step 1: 创建 config/config_dev.yaml**

```yaml
# Mini-Router 开发环境配置

server:
  host: "0.0.0.0"
  port: 8080

# 数据库配置（开发环境可禁用）
database:
  enabled: false
  host: "localhost"
  port: 3306
  user: "root"
  database: "mini_router_dev"
  min_connections: 2
  max_connections: 5

models:
  base_url: "https://coding.dashscope.aliyuncs.com/v1"
  api_key: ""  # 通过环境变量传入
  tokenizer_path: "~/models/Qwen3-tokenizer"
  timeout: 120.0

  classifier:
    intent:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 50.0
      fallback_label: null
    pii:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 50.0
      fallback_label: "detected"
    security:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 50.0
      fallback_label: "detected"
    complexity:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 50.0
      fallback_label: "complex"
    context_length:
      enabled: true
      timeout: 5.0
      fallback_label: "short"
      threshold: 10000

signals:
  keyword_rules:
    - name: "code_related"
      keywords: ["code", "programming", "function", "debug", "error"]
      operator: "any"
      case_sensitive: false

decisions:
  - name: "default_route"
    priority: 0
    rules:
      type: "or"
      children:
        - type: "signal"
          signal: "complexity"
          condition: "simple"
        - type: "signal"
          signal: "complexity"
          condition: "complex"
    model_refs:
      - model: "qwen3.5-plus"
        weight: 1.0

selection:
  strategy: "latency_aware"

cache:
  enabled: true
  similarity_threshold: 0.95
  max_entries: 10000
```

- [ ] **Step 2: 创建 config/config_prd.yaml**

```yaml
# Mini-Router 生产环境配置

server:
  host: "0.0.0.0"
  port: 8080

# 数据库配置（生产环境启用）
database:
  enabled: true
  host: "mysql.prod.internal"  # 替换为实际生产数据库地址
  port: 3306
  user: "mini_router"
  database: "mini_router"
  min_connections: 5
  max_connections: 20

models:
  base_url: "https://coding.dashscope.aliyuncs.com/v1"
  api_key: ""  # 通过环境变量传入
  tokenizer_path: "/app/models/Qwen3-tokenizer"
  timeout: 120.0

  classifier:
    intent:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 50.0
      fallback_label: null
    pii:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 50.0
      fallback_label: "detected"
    security:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 50.0
      fallback_label: "detected"
    complexity:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 50.0
      fallback_label: "complex"
    context_length:
      enabled: true
      timeout: 5.0
      fallback_label: "short"
      threshold: 10000

signals:
  keyword_rules: []

decisions: []

selection:
  strategy: "latency_aware"

cache:
  enabled: true
  similarity_threshold: 0.95
  max_entries: 10000
```

- [ ] **Step 3: 提交**

```bash
git add config/config_dev.yaml config/config_prd.yaml
git commit -m "feat: add environment-specific config files"
```

---

## Task 12: 创建数据库初始化 SQL

**Files:**
- Create: `scripts/init_db.sql`

- [ ] **Step 1: 创建 scripts/init_db.sql**

```sql
-- Mini-Router MySQL Database Initialization Script
-- Execute this script before starting the service in production mode

-- 1. 全局配置表
CREATE TABLE IF NOT EXISTS `mini_router_config` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `config_data` JSON NOT NULL COMMENT '完整路由配置',
    `version` INT NOT NULL DEFAULT 1 COMMENT '配置版本号',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Mini-Router 全局配置表';

-- 2. 租户配置表
CREATE TABLE IF NOT EXISTS `mini_router_tenant` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `tenant_id` VARCHAR(64) NOT NULL COMMENT '租户唯一标识',
    `apikey` VARCHAR(128) NOT NULL COMMENT '认证 API Key',
    `name` VARCHAR(128) DEFAULT NULL COMMENT '租户名称',
    `enabled` BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否启用',
    `base_url_template` VARCHAR(256) NOT NULL COMMENT 'LLM API URL模板',
    `timeout` FLOAT NOT NULL DEFAULT 120.0 COMMENT '请求超时时间',
    `apikey_pool_mode` VARCHAR(20) DEFAULT 'round_robin' COMMENT 'Key池模式',
    `decisions` JSON DEFAULT NULL COMMENT '租户路由规则',
    `version` INT NOT NULL DEFAULT 1 COMMENT '版本号',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY `uk_tenant_id` (`tenant_id`),
    INDEX `idx_apikey` (`apikey`),
    INDEX `idx_version` (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Mini-Router 租户配置表';

-- 3. API Key 池表
CREATE TABLE IF NOT EXISTS `mini_router_apikey_pool` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `tenant_id` VARCHAR(64) NOT NULL COMMENT '关联租户ID',
    `apikey` VARCHAR(128) NOT NULL COMMENT 'LLM调用 API Key',
    `apikey_order` INT NOT NULL DEFAULT 0 COMMENT 'Key顺序',
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否可用',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX `idx_tenant` (`tenant_id`),
    UNIQUE KEY `uk_tenant_order` (`tenant_id`, `apikey_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Mini-Router API Key池';

-- 4. 插入默认全局配置（需要根据实际配置修改）
-- INSERT INTO `mini_router_config` (`config_data`, `version`)
-- VALUES ('{"server":{"host":"0.0.0.0","port":8080},"models":{...}}', 1);
```

- [ ] **Step 2: 提交**

```bash
git add scripts/init_db.sql
git commit -m "feat: add database initialization SQL script"
```

---

## Task 13: 创建配置迁移脚本

**Files:**
- Create: `scripts/yaml_to_mysql.py`

- [ ] **Step 1: 创建 scripts/yaml_to_mysql.py**

```python
#!/usr/bin/env python3
"""YAML to MySQL configuration migration script.

Usage:
    python scripts/yaml_to_mysql.py --config config.yaml --tenants config/tenants.yaml
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml


async def migrate_config(config_path: str, db_config: dict) -> None:
    """Migrate global config to database."""
    from mini_router.database import DatabaseConnection, ConfigRepository

    # Read YAML
    with open(config_path) as f:
        data = yaml.safe_load(f)

    # Initialize database
    db = DatabaseConnection(db_config)
    await db.connect()
    repo = ConfigRepository(db)

    # Insert global config
    config_json = json.dumps(data)
    await db.execute(
        "INSERT INTO mini_router_config (config_data, version) VALUES (?, 1) "
        "ON DUPLICATE KEY UPDATE config_data = ?, version = version + 1",
        (config_json, config_json)
    )

    print(f"Migrated global config from {config_path}")
    await db.close()


async def migrate_tenants(tenants_path: str, db_config: dict) -> None:
    """Migrate tenant configs to database."""
    from mini_router.database import DatabaseConnection, ConfigRepository

    # Read YAML
    with open(tenants_path) as f:
        data = yaml.safe_load(f)

    if not data or "tenants" not in data:
        print(f"No tenants found in {tenants_path}")
        return

    # Initialize database
    db = DatabaseConnection(db_config)
    await db.connect()
    repo = ConfigRepository(db)

    tenants = data.get("tenants", [])
    for tenant_data in tenants:
        tenant_id = tenant_data["tenant_id"]

        # Insert tenant
        await repo.create_tenant(tenant_data)

        # Insert API key pool
        apikey_pool = tenant_data.get("apikey_pool", [])
        for i, key in enumerate(apikey_pool):
            await repo.add_apikey_to_pool(tenant_id, key, i)

        print(f"Migrated tenant: {tenant_id}")

    print(f"Migrated {len(tenants)} tenants from {tenants_path}")
    await db.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate YAML configs to MySQL")
    parser.add_argument("--config", default="config.yaml", help="Global config YAML path")
    parser.add_argument("--tenants", default="config/tenants.yaml", help="Tenants YAML path")
    parser.add_argument("--host", default="localhost", help="Database host")
    parser.add_argument("--port", type=int, default=3306, help="Database port")
    parser.add_argument("--user", default="root", help="Database user")
    parser.add_argument("--password", default="", help="Database password")
    parser.add_argument("--database", default="mini_router", help="Database name")

    args = parser.parse_args()

    db_config = {
        "host": args.host,
        "port": args.port,
        "user": args.user,
        "password": args.password,
        "database": args.database,
    }

    async def run():
        if Path(args.config).exists():
            await migrate_config(args.config, db_config)
        else:
            print(f"Config file not found: {args.config}")

        if Path(args.tenants).exists():
            await migrate_tenants(args.tenants, db_config)
        else:
            print(f"Tenants file not found: {args.tenants}")

    asyncio.run(run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 提交**

```bash
git add scripts/yaml_to_mysql.py
git commit -m "feat: add YAML to MySQL migration script"
```

---

## Plan Complete

实现计划完成。按照 TDD 原则，每个任务包含：
1. 失败测试编写
2. 实现代码
3. 测试验证通过
4. 提交

执行顺序：Task 1 → Task 13，建议每完成一个任务后提交，便于回滚和追踪。