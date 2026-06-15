"""Tests for TenantManager."""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mini_router.config.config import Decision, ModelRef, RuleNode, RuleType
from mini_router.tenant.manager import TenantManager
from mini_router.tenant.types import TenantConfig


class TestTenantManagerLoadSave:
    """Tests for TenantManager load and save operations."""

    def test_load_empty_file(self) -> None:
        """Test loading from an empty YAML file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)
            manager.load()
            assert manager.list_all() == []
        finally:
            Path(temp_path).unlink()

    def test_save_and_load(self) -> None:
        """Test saving and loading tenants."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)

            # Create a tenant
            tenant = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-test-key-123",
                name="Test Tenant",
                enabled=True,
                base_url_template="http://api.example.com/{model}/v1",
                timeout=60.0,
            )
            manager.create(tenant)

            # Create new manager and load
            manager2 = TenantManager(config_path=temp_path)
            manager2.load()

            tenants = manager2.list_all()
            assert len(tenants) == 1
            assert tenants[0].tenant_id == "tenant1"
            assert tenants[0].apikey == "sk-test-key-123"
            assert tenants[0].name == "Test Tenant"
        finally:
            Path(temp_path).unlink()

    def test_load_rejects_yaml_tenant_without_decisions(self) -> None:
        """YAML mode should reject tenants missing decisions."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("tenants:\n")
            f.write("  - tenant_id: broken\n")
            f.write("    apikey: broken-key\n")
            f.write("    base_url_template: https://api.example.com\n")
            f.write("    selection:\n")
            f.write("      strategy: static\n")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)
            with pytest.raises(ValueError, match="missing required 'decisions'"):
                manager.load()
        finally:
            Path(temp_path).unlink()

    def test_load_rejects_yaml_tenant_without_selection(self) -> None:
        """YAML mode should reject tenants missing selection."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("tenants:\n")
            f.write("  - tenant_id: broken\n")
            f.write("    apikey: broken-key\n")
            f.write("    base_url_template: https://api.example.com\n")
            f.write("    decisions: []\n")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)
            with pytest.raises(ValueError, match="missing required 'selection'"):
                manager.load()
        finally:
            Path(temp_path).unlink()


class TestTenantManagerCRUD:
    """Tests for TenantManager CRUD operations."""

    def test_create_tenant(self) -> None:
        """Test creating a tenant."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)

            tenant = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-test-key-123",
                name="Test Tenant",
                enabled=True,
                base_url_template="http://api.example.com/{model}/v1",
                timeout=60.0,
            )

            created = manager.create(tenant)

            assert created.tenant_id == "tenant1"
            assert created.apikey == "sk-test-key-123"
            assert created.created_at is not None
            assert created.updated_at is not None

            # Verify it's in the list
            all_tenants = manager.list_all()
            assert len(all_tenants) == 1
        finally:
            Path(temp_path).unlink()

    def test_get_by_apikey(self) -> None:
        """Test getting tenant by API key."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)

            tenant = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-test-key-123",
                name="Test Tenant",
                base_url_template="http://api.example.com/{model}/v1",
            )
            manager.create(tenant)

            found = manager.get_by_apikey("sk-test-key-123")
            assert found is not None
            assert found.tenant_id == "tenant1"
        finally:
            Path(temp_path).unlink()

    def test_get_by_apikey_not_found(self) -> None:
        """Test getting tenant by non-existent API key."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)
            manager.load()

            found = manager.get_by_apikey("nonexistent-key")
            assert found is None
        finally:
            Path(temp_path).unlink()

    def test_get_by_id(self) -> None:
        """Test getting tenant by ID."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)

            tenant = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-test-key-123",
                name="Test Tenant",
                base_url_template="http://api.example.com/{model}/v1",
            )
            manager.create(tenant)

            found = manager.get_by_id("tenant1")
            assert found is not None
            assert found.apikey == "sk-test-key-123"
        finally:
            Path(temp_path).unlink()

    def test_get_by_id_not_found(self) -> None:
        """Test getting tenant by non-existent ID."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)
            manager.load()

            found = manager.get_by_id("nonexistent")
            assert found is None
        finally:
            Path(temp_path).unlink()

    def test_update_tenant(self) -> None:
        """Test updating a tenant."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)

            tenant = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-test-key-123",
                name="Test Tenant",
                enabled=True,
                base_url_template="http://api.example.com/{model}/v1",
                timeout=60.0,
            )
            manager.create(tenant)

            # Update the tenant
            updated = manager.update("tenant1", {"name": "Updated Tenant", "timeout": 120.0})

            assert updated is not None
            assert updated.name == "Updated Tenant"
            assert updated.timeout == 120.0
            assert updated.enabled is True  # Unchanged
            assert updated.updated_at is not None
        finally:
            Path(temp_path).unlink()

    def test_update_tenant_apikey(self) -> None:
        """Test updating tenant's API key updates the index."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)

            tenant = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-old-key",
                name="Test Tenant",
                base_url_template="http://api.example.com/{model}/v1",
            )
            manager.create(tenant)

            # Update the API key
            updated = manager.update("tenant1", {"apikey": "sk-new-key"})

            assert updated is not None
            assert updated.apikey == "sk-new-key"

            # Old key should not find tenant
            assert manager.get_by_apikey("sk-old-key") is None

            # New key should find tenant
            found = manager.get_by_apikey("sk-new-key")
            assert found is not None
            assert found.tenant_id == "tenant1"
        finally:
            Path(temp_path).unlink()

    def test_update_nonexistent_tenant(self) -> None:
        """Test updating a non-existent tenant."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)
            manager.load()

            updated = manager.update("nonexistent", {"name": "New Name"})
            assert updated is None
        finally:
            Path(temp_path).unlink()

    def test_delete_tenant(self) -> None:
        """Test deleting a tenant."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)

            tenant = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-test-key-123",
                name="Test Tenant",
                base_url_template="http://api.example.com/{model}/v1",
            )
            manager.create(tenant)

            # Delete the tenant
            result = manager.delete("tenant1")
            assert result is True

            # Verify it's gone
            assert manager.get_by_id("tenant1") is None
            assert manager.get_by_apikey("sk-test-key-123") is None
        finally:
            Path(temp_path).unlink()

    def test_delete_nonexistent_tenant(self) -> None:
        """Test deleting a non-existent tenant."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)
            manager.load()

            result = manager.delete("nonexistent")
            assert result is False
        finally:
            Path(temp_path).unlink()


class TestTenantManagerDuplicate:
    """Tests for duplicate handling in TenantManager."""

    def test_create_duplicate_tenant_id(self) -> None:
        """Test that creating a tenant with duplicate tenant_id raises error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)

            tenant1 = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-key-1",
                name="Tenant 1",
                base_url_template="http://api1.example.com/{model}/v1",
            )
            manager.create(tenant1)

            tenant2 = TenantConfig(
                tenant_id="tenant1",  # Same tenant_id
                apikey="sk-key-2",
                name="Tenant 2",
                base_url_template="http://api2.example.com/{model}/v1",
            )

            with pytest.raises(ValueError, match="tenant_id"):
                manager.create(tenant2)
        finally:
            Path(temp_path).unlink()

    def test_create_duplicate_apikey(self) -> None:
        """Test that creating a tenant with duplicate apikey raises error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)

            tenant1 = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-same-key",
                name="Tenant 1",
                base_url_template="http://api1.example.com/{model}/v1",
            )
            manager.create(tenant1)

            tenant2 = TenantConfig(
                tenant_id="tenant2",
                apikey="sk-same-key",  # Same apikey
                name="Tenant 2",
                base_url_template="http://api2.example.com/{model}/v1",
            )

            with pytest.raises(ValueError, match="apikey"):
                manager.create(tenant2)
        finally:
            Path(temp_path).unlink()


class TestTenantManagerWithDecisions:
    """Tests for TenantManager with tenant-specific decisions."""

    def test_create_tenant_with_decisions(self) -> None:
        """Test creating a tenant with tenant-specific decisions."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(config_path=temp_path)

            tenant = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-test-key-123",
                name="Test Tenant",
                base_url_template="http://api.example.com/{model}/v1",
                decisions=[
                    Decision(
                        name="custom_route",
                        priority=100,
                        rules=RuleNode(type=RuleType.KEYWORD, name="custom_keyword"),
                        model_refs=[ModelRef(model="custom-model", weight=1.0)],
                    )
                ],
            )

            created = manager.create(tenant)

            assert len(created.decisions) == 1
            assert created.decisions[0].name == "custom_route"

            # Save and reload
            manager.save()
            manager2 = TenantManager(config_path=temp_path)
            manager2.load()

            found = manager2.get_by_id("tenant1")
            assert found is not None
            assert len(found.decisions) == 1
            assert found.decisions[0].name == "custom_route"
        finally:
            Path(temp_path).unlink()


class TestTenantManagerDatabase:
    """Test TenantManager with database repository."""

    @pytest.fixture
    def mock_repo(self):
        """Create mock repository."""
        repo = MagicMock()
        repo.get_all_tenants = AsyncMock(return_value=[
            {
                "tenant_id": "test-1",
                "apikey": "auth-key-1",
                "name": "Test 1",
                "enabled": True,
                "base_url_template": "https://api.example.com/{model}/v1",
                "timeout": 120.0,
                "apikey_pool_mode": "round_robin",
                "decisions": [],
            },
        ])
        repo.get_apikey_pool = AsyncMock(return_value=[
            {"tenant_id": "test-1", "apikey": "llm-key-1", "apikey_order": 0, "is_active": True},
        ])
        repo.create_tenant = AsyncMock()
        repo.update_tenant = AsyncMock()
        repo.delete_tenant = AsyncMock()
        repo.add_apikey_to_pool = AsyncMock()
        repo.update_apikey_status = AsyncMock()
        repo.delete_apikey_pool = AsyncMock()
        repo.bump_tenant_version = AsyncMock()
        return repo

    def test_init_with_repository(self, mock_repo):
        """Test initialization with repository."""
        manager = TenantManager(repository=mock_repo)

        assert manager.repository == mock_repo
        assert manager._tenants == {}
        assert manager._apikey_index == {}
        assert manager._apikey_pool == {}

    def test_init_with_yaml_path(self):
        """Test initialization with yaml_path."""
        manager = TenantManager(yaml_path="custom/path.yaml")

        assert manager.yaml_path == "custom/path.yaml"
        assert manager.config_path == "custom/path.yaml"  # backward compat

    def test_init_with_deprecated_config_path(self):
        """Test backward compatibility with config_path."""
        manager = TenantManager(config_path="old/path.yaml")

        assert manager.yaml_path == "old/path.yaml"
        assert manager.config_path == "old/path.yaml"

    def test_load_raises_error_with_repository(self, mock_repo):
        """Test load() raises error when repository is set."""
        manager = TenantManager(repository=mock_repo)

        with pytest.raises(RuntimeError, match="async_load"):
            manager.load()

    @pytest.mark.asyncio
    async def test_load_from_db(self, mock_repo):
        """Test loading tenants from database."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        assert len(manager._tenants) == 1
        assert "test-1" in manager._tenants
        assert manager._apikey_index["auth-key-1"] == "test-1"
        assert manager._apikey_pool["test-1"] == ["llm-key-1"]

    @pytest.mark.asyncio
    async def test_tenant_apikey_pool_loaded_from_db(self, mock_repo):
        """Test that TenantConfig.apikey_pool is populated from database."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        tenant = manager.get_by_id("test-1")
        assert tenant is not None
        # Verify apikey_pool field is populated (not empty)
        assert tenant.apikey_pool == ["llm-key-1"]
        # Also verify internal dictionary matches
        assert manager._apikey_pool["test-1"] == tenant.apikey_pool

    @pytest.mark.asyncio
    async def test_async_load_from_db(self, mock_repo):
        """Test async_load with repository."""
        manager = TenantManager(repository=mock_repo)
        await manager.async_load()

        assert len(manager._tenants) == 1
        assert "test-1" in manager._tenants

    @pytest.mark.asyncio
    async def test_async_load_from_yaml(self):
        """Test async_load without repository (YAML mode)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("tenants:\n")
            f.write("  - tenant_id: yaml-tenant\n")
            f.write("    apikey: yaml-key\n")
            f.write("    base_url_template: https://api.example.com\n")
            f.write("    apikey_pool: ['pool-key-1', 'pool-key-2']\n")
            f.write("    selection:\n")
            f.write("      strategy: static\n")
            f.write("    decisions: []\n")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(yaml_path=temp_path)
            await manager.async_load()

            assert len(manager._tenants) == 1
            assert "yaml-tenant" in manager._tenants
            assert manager._apikey_pool["yaml-tenant"] == ["pool-key-1", "pool-key-2"]
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_reload_clears_and_reloads(self, mock_repo):
        """Test reload clears existing data."""
        manager = TenantManager(repository=mock_repo)
        manager._tenants["old"] = TenantConfig(
            tenant_id="old",
            apikey="old-key",
            base_url_template="https://api.example.com",
        )
        manager._apikey_index["old-key"] = "old"
        manager._apikey_pool["old"] = ["old-pool-key"]

        await manager.reload()

        assert "old" not in manager._tenants
        assert "old-key" not in manager._apikey_index
        assert "old" not in manager._apikey_pool
        assert "test-1" in manager._tenants

    @pytest.mark.asyncio
    async def test_reload_yaml_mode(self):
        """Test reload in YAML mode."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("tenants:\n")
            f.write("  - tenant_id: reload-test\n")
            f.write("    apikey: reload-key\n")
            f.write("    base_url_template: https://api.example.com\n")
            f.write("    selection:\n")
            f.write("      strategy: static\n")
            f.write("    decisions: []\n")
            f.flush()
            temp_path = f.name

        try:
            manager = TenantManager(yaml_path=temp_path)
            manager._tenants["old"] = TenantConfig(
                tenant_id="old",
                apikey="old-key",
                base_url_template="https://api.example.com",
            )

            await manager.reload()

            assert "old" not in manager._tenants
            assert "reload-test" in manager._tenants
        finally:
            Path(temp_path).unlink()

    def test_create_raises_error_with_repository(self, mock_repo):
        """Test create() raises error when repository is set."""
        manager = TenantManager(repository=mock_repo)
        tenant = TenantConfig(
            tenant_id="new",
            apikey="key",
            base_url_template="https://api.example.com",
        )

        with pytest.raises(RuntimeError, match="async_create"):
            manager.create(tenant)

    @pytest.mark.asyncio
    async def test_async_create(self, mock_repo):
        """Test async_create with repository."""
        manager = TenantManager(repository=mock_repo)
        tenant = TenantConfig(
            tenant_id="new-tenant",
            apikey="new-auth-key",
            base_url_template="https://api.example.com",
            apikey_pool=["llm-key-1", "llm-key-2"],
        )

        created = await manager.async_create(tenant)

        assert created.tenant_id == "new-tenant"
        assert created.created_at is not None
        assert created.updated_at is not None
        mock_repo.create_tenant.assert_called_once()
        # Should add both pool keys
        assert mock_repo.add_apikey_to_pool.call_count == 2

    @pytest.mark.asyncio
    async def test_async_create_duplicate_tenant_id(self, mock_repo):
        """Test async_create with duplicate tenant_id."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        tenant = TenantConfig(
            tenant_id="test-1",  # Same as existing
            apikey="different-key",
            base_url_template="https://api.example.com",
        )

        with pytest.raises(ValueError, match="tenant_id"):
            await manager.async_create(tenant)

    @pytest.mark.asyncio
    async def test_async_create_duplicate_apikey(self, mock_repo):
        """Test async_create with duplicate apikey."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        tenant = TenantConfig(
            tenant_id="new-tenant",
            apikey="auth-key-1",  # Same as existing
            base_url_template="https://api.example.com",
        )

        with pytest.raises(ValueError, match="apikey"):
            await manager.async_create(tenant)

    def test_update_raises_error_with_repository(self, mock_repo):
        """Test update() raises error when repository is set."""
        manager = TenantManager(repository=mock_repo)
        manager._tenants["test"] = TenantConfig(
            tenant_id="test",
            apikey="key",
            base_url_template="https://api.example.com",
        )

        with pytest.raises(RuntimeError, match="async_update"):
            manager.update("test", {"name": "Updated"})

    @pytest.mark.asyncio
    async def test_async_update(self, mock_repo):
        """Test async_update with repository."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        updated = await manager.async_update("test-1", {"name": "Updated Name"})

        assert updated is not None
        assert updated.name == "Updated Name"
        mock_repo.update_tenant.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_update_with_decisions_dict(self, mock_repo):
        """Test async_update with decisions as dict list (from API request)."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        # Decisions as dict list (simulating API request input)
        decisions_dict = [
            {
                "name": "custom_route",
                "priority": 100,
                "rules": {"type": "keyword", "name": "custom_keyword"},
                "model_refs": [{"model": "custom-model", "weight": 1.0}],
            }
        ]

        updated = await manager.async_update("test-1", {"decisions": decisions_dict})

        assert updated is not None
        mock_repo.update_tenant.assert_called_once()
        # Verify decisions passed correctly (as dict, not calling model_dump)
        call_args = mock_repo.update_tenant.call_args[0]
        assert "decisions" in call_args[1]

    @pytest.mark.asyncio
    async def test_async_update_with_decisions_objects(self, mock_repo):
        """Test async_update with decisions as Decision objects."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        # Decisions as Decision objects
        decisions_objs = [
            Decision(
                name="custom_route",
                priority=100,
                rules=RuleNode(type=RuleType.KEYWORD, name="custom_keyword"),
                model_refs=[ModelRef(model="custom-model", weight=1.0)],
            )
        ]

        updated = await manager.async_update("test-1", {"decisions": decisions_objs})

        assert updated is not None
        mock_repo.update_tenant.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_update_apikey_pool(self, mock_repo):
        """Test async_update with apikey_pool (delete + re-add)."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        updated = await manager.async_update("test-1", {
            "apikey_pool": ["new-pool-key-1", "new-pool-key-2"],
        })

        assert updated is not None
        assert manager._apikey_pool["test-1"] == ["new-pool-key-1", "new-pool-key-2"]
        mock_repo.delete_apikey_pool.assert_called_once_with("test-1")
        assert mock_repo.add_apikey_to_pool.call_count == 2

    @pytest.mark.asyncio
    async def test_async_update_not_found(self, mock_repo):
        """Test async_update with non-existent tenant."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        updated = await manager.async_update("nonexistent", {"name": "Updated"})

        assert updated is None

    def test_delete_raises_error_with_repository(self, mock_repo):
        """Test delete() raises error when repository is set."""
        manager = TenantManager(repository=mock_repo)
        manager._tenants["test"] = TenantConfig(
            tenant_id="test",
            apikey="key",
            base_url_template="https://api.example.com",
        )

        with pytest.raises(RuntimeError, match="async_delete"):
            manager.delete("test")

    @pytest.mark.asyncio
    async def test_async_delete(self, mock_repo):
        """Test async_delete with repository."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        result = await manager.async_delete("test-1")

        assert result is True
        assert "test-1" not in manager._tenants
        assert "auth-key-1" not in manager._apikey_index
        mock_repo.delete_tenant.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_delete_not_found(self, mock_repo):
        """Test async_delete with non-existent tenant."""
        manager = TenantManager(repository=mock_repo)
        await manager._load_from_db()

        result = await manager.async_delete("nonexistent")

        assert result is False

    def test_save_raises_error_with_repository(self, mock_repo):
        """Test save() raises error when repository is set."""
        manager = TenantManager(repository=mock_repo)

        with pytest.raises(RuntimeError, match="Database mode"):
            manager.save()

    def test_get_apikey_pool(self):
        """Test get_apikey_pool method."""
        manager = TenantManager()
        manager._tenants["test"] = TenantConfig(
            tenant_id="test",
            apikey="key",
            base_url_template="https://api.example.com",
        )
        manager._apikey_pool["test"] = ["pool-key-1", "pool-key-2"]

        pool = manager.get_apikey_pool("test")
        assert pool == ["pool-key-1", "pool-key-2"]

    def test_get_apikey_pool_empty(self):
        """Test get_apikey_pool with no pool."""
        manager = TenantManager()
        manager._tenants["test"] = TenantConfig(
            tenant_id="test",
            apikey="key",
            base_url_template="https://api.example.com",
        )

        pool = manager.get_apikey_pool("test")
        assert pool == []


class TestTenantManagerYamlBackwardCompat:
    """Test backward compatibility for YAML mode."""

    def test_yaml_mode_unchanged(self) -> None:
        """Test YAML mode still works as before."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            # Use config_path (deprecated parameter)
            manager = TenantManager(config_path=temp_path)

            tenant = TenantConfig(
                tenant_id="tenant1",
                apikey="sk-test-key-123",
                name="Test Tenant",
                enabled=True,
                base_url_template="http://api.example.com/{model}/v1",
                timeout=60.0,
                apikey_pool=["llm-key-1"],
            )

            created = manager.create(tenant)

            assert created.tenant_id == "tenant1"
            assert created.apikey_pool == ["llm-key-1"]
            assert manager._apikey_pool["tenant1"] == ["llm-key-1"]

            # Load in new manager
            manager2 = TenantManager(yaml_path=temp_path)
            manager2.load()

            found = manager2.get_by_id("tenant1")
            assert found is not None
            assert found.apikey_pool == ["llm-key-1"]
            assert manager2.get_apikey_pool("tenant1") == ["llm-key-1"]
        finally:
            Path(temp_path).unlink()
