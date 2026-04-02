"""Tenant manager for CRUD operations and persistence."""

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from mini_router.tenant.types import TenantConfig


class TenantManager:
    """Manages tenant configurations with CRUD operations and YAML persistence."""

    def __init__(self, config_path: str = "config/tenants.yaml") -> None:
        """Initialize TenantManager.

        Args:
            config_path: Path to the YAML file for tenant storage.
        """
        self.config_path = config_path
        self._tenants: dict[str, TenantConfig] = {}
        self._apikey_index: dict[str, str] = {}

    def load(self) -> None:
        """Load tenants from the YAML file."""
        path = Path(self.config_path)

        if not path.exists():
            # File doesn't exist, start with empty state
            self._tenants = {}
            self._apikey_index = {}
            return

        with path.open() as f:
            data = yaml.safe_load(f)

        if data is None or "tenants" not in data:
            # Empty file or no tenants key
            self._tenants = {}
            self._apikey_index = {}
            return

        # Load tenants
        self._tenants = {}
        self._apikey_index = {}

        for tenant_data in data.get("tenants", []):
            tenant = TenantConfig(**tenant_data)
            self._tenants[tenant.tenant_id] = tenant
            self._apikey_index[tenant.apikey] = tenant.tenant_id

    def save(self) -> None:
        """Save tenants to the YAML file."""
        path = Path(self.config_path)

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Convert tenants to list of dicts (use mode='json' for proper enum serialization)
        tenants_data = [tenant.model_dump(mode="json") for tenant in self._tenants.values()]

        data = {"tenants": tenants_data}

        with path.open("w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def get_by_apikey(self, apikey: str) -> TenantConfig | None:
        """Get a tenant by API key.

        Args:
            apikey: The API key to look up.

        Returns:
            TenantConfig if found, None otherwise.
        """
        tenant_id = self._apikey_index.get(apikey)
        if tenant_id is None:
            return None
        return self._tenants.get(tenant_id)

    def get_by_id(self, tenant_id: str) -> TenantConfig | None:
        """Get a tenant by ID.

        Args:
            tenant_id: The tenant ID to look up.

        Returns:
            TenantConfig if found, None otherwise.
        """
        return self._tenants.get(tenant_id)

    def list_all(self) -> list[TenantConfig]:
        """List all tenants.

        Returns:
            List of all TenantConfig objects.
        """
        return list(self._tenants.values())

    def create(self, tenant: TenantConfig) -> TenantConfig:
        """Create a new tenant.

        Args:
            tenant: The tenant configuration to create.

        Returns:
            The created TenantConfig with timestamps set.

        Raises:
            ValueError: If tenant_id or apikey already exists.
        """
        # Check for duplicate tenant_id
        if tenant.tenant_id in self._tenants:
            raise ValueError(f"Tenant with tenant_id '{tenant.tenant_id}' already exists")

        # Check for duplicate apikey
        if tenant.apikey in self._apikey_index:
            raise ValueError(f"Tenant with apikey '{tenant.apikey}' already exists")

        # Set timestamps
        now = datetime.now()
        tenant.created_at = now
        tenant.updated_at = now

        # Add to storage
        self._tenants[tenant.tenant_id] = tenant
        self._apikey_index[tenant.apikey] = tenant.tenant_id

        # Persist to file
        self.save()

        return tenant

    def update(self, tenant_id: str, updates: dict[str, Any]) -> TenantConfig | None:
        """Update a tenant with partial updates.

        Args:
            tenant_id: The tenant ID to update.
            updates: Dictionary of fields to update.

        Returns:
            Updated TenantConfig if found, None otherwise.
        """
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return None

        # Handle apikey change - need to update index
        if "apikey" in updates and updates["apikey"] != tenant.apikey:
            new_apikey = updates["apikey"]
            # Check for duplicate apikey
            if new_apikey in self._apikey_index and self._apikey_index[new_apikey] != tenant_id:
                raise ValueError(f"Tenant with apikey '{new_apikey}' already exists")
            # Remove old index entry
            del self._apikey_index[tenant.apikey]
            # Add new index entry
            self._apikey_index[new_apikey] = tenant_id

        # Apply updates
        for key, value in updates.items():
            if hasattr(tenant, key):
                setattr(tenant, key, value)

        # Update timestamp
        tenant.updated_at = datetime.now()

        # Persist to file
        self.save()

        return tenant

    def delete(self, tenant_id: str) -> bool:
        """Delete a tenant.

        Args:
            tenant_id: The tenant ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return False

        # Remove from index
        del self._apikey_index[tenant.apikey]

        # Remove from storage
        del self._tenants[tenant_id]

        # Persist to file
        self.save()

        return True
