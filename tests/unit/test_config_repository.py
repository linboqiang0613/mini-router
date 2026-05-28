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

        # delete_tenant calls execute twice: tenant and apikey_pool cleanup
        assert mock_db.execute.call_count == 2
        # First call deletes the tenant
        first_call = mock_db.execute.call_args_list[0][0]
        assert "DELETE" in first_call[0]
        assert "mini_router_tenant" in first_call[0]
        # Second call deletes apikey_pool entries
        second_call = mock_db.execute.call_args_list[1][0]
        assert "DELETE" in second_call[0]
        assert "mini_router_apikey_pool" in second_call[0]

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

    @pytest.mark.asyncio
    async def test_get_tenant_versions(self, mock_db):
        """Test getting all tenant_id → version mappings."""
        mock_db.fetch_all.return_value = [
            {"tenant_id": "t1", "version": 5},
            {"tenant_id": "t2", "version": 12},
        ]

        repo = ConfigRepository(mock_db)
        result = await repo.get_tenant_versions()

        assert result == {"t1": 5, "t2": 12}
        mock_db.fetch_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_tenant_versions_empty(self, mock_db):
        """Test getting version mappings when no tenants exist."""
        mock_db.fetch_all.return_value = []

        repo = ConfigRepository(mock_db)
        result = await repo.get_tenant_versions()

        assert result == {}


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