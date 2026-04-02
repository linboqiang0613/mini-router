"""Tests for TenantManager."""

import tempfile
from datetime import datetime
from pathlib import Path

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