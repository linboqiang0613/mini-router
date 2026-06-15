"""Tenant manager for CRUD operations and persistence."""

import structlog
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml

from mini_router.config.config import SelectionConfig
from mini_router.tenant.types import TenantConfig

if TYPE_CHECKING:
    from mini_router.database.repository import ConfigRepository

logger = structlog.get_logger()


class TenantManager:
    """Manages tenant configurations with CRUD operations.

    Supports two modes:
    - YAML mode (default): Load/save from YAML file (sync operations)
    - Database mode: Load/save from database (async operations)
    """

    def __init__(
        self,
        repository: "ConfigRepository | None" = None,
        yaml_path: str = "config/tenants.yaml",
        config_path: str | None = None,  # Deprecated, for backward compatibility
    ) -> None:
        """Initialize TenantManager.

        Args:
            repository: Optional ConfigRepository for database mode.
            yaml_path: Path to YAML file for YAML mode.
            config_path: Deprecated, use yaml_path instead.
        """
        self.repository = repository
        # Support deprecated config_path parameter for backward compatibility
        self.yaml_path = config_path if config_path else yaml_path
        self._tenants: dict[str, TenantConfig] = {}
        self._apikey_index: dict[str, str] = {}  # auth apikey -> tenant_id
        self._apikey_pool: dict[str, list[str]] = {}  # tenant_id -> list of LLM apikeys

    @property
    def config_path(self) -> str:
        """Deprecated: Use yaml_path instead."""
        return self.yaml_path

    def load(self) -> None:
        """Load tenants from YAML file (YAML mode only).

        For database mode, use async_load() instead.

        Raises:
            RuntimeError: If repository is set (database mode).
        """
        if self.repository:
            raise RuntimeError(
                "Database mode requires async operations. Use async_load() instead."
            )
        self._load_from_yaml()

    def _load_from_yaml(self) -> None:
        """Load tenants from YAML file (mutates self, for startup use)."""
        self._tenants, self._apikey_index, self._apikey_pool = self._build_from_yaml()

    def _build_from_yaml(self) -> tuple[dict[str, TenantConfig], dict[str, str], dict[str, list[str]]]:
        """Build tenant state from YAML without mutating self.

        Returns:
            Tuple of (tenants dict, apikey_index dict, apikey_pool dict)
        """
        path = Path(self.yaml_path)

        if not path.exists():
            return {}, {}, {}

        with path.open() as f:
            data = yaml.safe_load(f)

        if data is None or "tenants" not in data:
            return {}, {}, {}

        tenants: dict[str, TenantConfig] = {}
        apikey_index: dict[str, str] = {}
        apikey_pool: dict[str, list[str]] = {}

        for tenant_data in data.get("tenants", []):
            if "decisions" not in tenant_data:
                raise ValueError(
                    f"Tenant '{tenant_data.get('tenant_id', '<unknown>')}' is missing required "
                    "'decisions' in YAML mode"
                )
            if "selection" not in tenant_data:
                raise ValueError(
                    f"Tenant '{tenant_data.get('tenant_id', '<unknown>')}' is missing required "
                    "'selection' in YAML mode"
                )
            tenant = TenantConfig(**tenant_data)
            tenants[tenant.tenant_id] = tenant
            apikey_index[tenant.apikey] = tenant.tenant_id
            if tenant.apikey_pool:
                apikey_pool[tenant.tenant_id] = tenant.apikey_pool

        return tenants, apikey_index, apikey_pool

    async def _load_from_db(self) -> None:
        """Load tenants from database repository (mutates self, for startup use)."""
        self._tenants, self._apikey_index, self._apikey_pool = await self._build_from_db()

    async def _build_from_db(self) -> tuple[dict[str, TenantConfig], dict[str, str], dict[str, list[str]]]:
        """Build tenant state from database without mutating self.

        Returns:
            Tuple of (tenants dict, apikey_index dict, apikey_pool dict)
        """
        if not self.repository:
            raise RuntimeError("Repository not set. Cannot load from database.")

        tenants: dict[str, TenantConfig] = {}
        apikey_index: dict[str, str] = {}
        apikey_pool: dict[str, list[str]] = {}

        tenants_data = await self.repository.get_all_tenants()
        for t in tenants_data:
            pool_data = await self.repository.get_apikey_pool(t["tenant_id"])
            active_keys = [k["apikey"] for k in pool_data if k.get("is_active", True)]

            tenant = TenantConfig(
                tenant_id=t["tenant_id"],
                apikey=t["apikey"],
                apikey_pool=active_keys,
                apikey_pool_mode=t.get("apikey_pool_mode", "round_robin"),
                name=t.get("name"),
                enabled=t.get("enabled", True),
                base_url_template=t["base_url_template"],
                timeout=t.get("timeout", 120.0),
                decisions=t.get("decisions") or [],
                selection=t.get("selection") or SelectionConfig(),
                created_at=t.get("created_at"),
                updated_at=t.get("updated_at"),
            )
            tenants[tenant.tenant_id] = tenant
            apikey_index[tenant.apikey] = tenant.tenant_id
            apikey_pool[tenant.tenant_id] = active_keys

        logger.info("tenants_loaded_from_db", count=len(tenants))
        return tenants, apikey_index, apikey_pool

    async def async_load(self) -> None:
        """Load tenants from configured source (YAML or database).

        Use this for database mode. For YAML mode, load() is also available.
        """
        if self.repository:
            await self._load_from_db()
        else:
            self._load_from_yaml()

    async def reload(self) -> None:
        """Atomically reload all tenants from configured source.

        Builds new state in temporary dicts then swaps atomically so that
        concurrent requests never see an empty or partial tenant index.
        """
        if self.repository:
            new_tenants, new_index, new_pool = await self._build_from_db()
        else:
            new_tenants, new_index, new_pool = self._build_from_yaml()

        self._tenants = new_tenants
        self._apikey_index = new_index
        self._apikey_pool = new_pool

        logger.info("tenants_reloaded", count=len(self._tenants))

    def save(self) -> None:
        """Save tenants to the YAML file (YAML mode only).

        Raises:
            RuntimeError: If repository is set (database mode).
        """
        if self.repository:
            raise RuntimeError(
                "Database mode uses async operations. "
                "Use async_create/update/delete methods for persistence."
            )

        path = Path(self.yaml_path)

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

    def get_apikey_pool(self, tenant_id: str) -> list[str]:
        """Get API key pool for a tenant.

        Args:
            tenant_id: The tenant ID.

        Returns:
            List of LLM API keys for the tenant.
        """
        return self._apikey_pool.get(tenant_id, [])

    def create(self, tenant: TenantConfig) -> TenantConfig:
        """Create a new tenant (YAML mode).

        For database mode, use async_create() instead.

        Args:
            tenant: The tenant configuration to create.

        Returns:
            The created TenantConfig with timestamps set.

        Raises:
            RuntimeError: If repository is set (database mode).
            ValueError: If tenant_id or apikey already exists.
        """
        if self.repository:
            raise RuntimeError(
                "Database mode requires async operations. Use async_create() instead."
            )

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

        # Store apikey_pool
        if tenant.apikey_pool:
            self._apikey_pool[tenant.tenant_id] = tenant.apikey_pool

        # Persist to file
        self.save()

        return tenant

    async def async_create(self, tenant: TenantConfig) -> TenantConfig:
        """Create a new tenant (database mode).

        Args:
            tenant: The tenant configuration to create.

        Returns:
            The created TenantConfig with timestamps set.

        Raises:
            RuntimeError: If repository is not set (YAML mode).
            ValueError: If tenant_id or apikey already exists.
        """
        if not self.repository:
            raise RuntimeError(
                "YAML mode requires sync operations. Use create() instead."
            )

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

        # Prepare tenant data for database
        tenant_data = {
            "tenant_id": tenant.tenant_id,
            "apikey": tenant.apikey,
            "name": tenant.name,
            "enabled": tenant.enabled,
            "base_url_template": tenant.base_url_template,
            "timeout": tenant.timeout,
            "apikey_pool_mode": tenant.apikey_pool_mode,
            "decisions": [d.model_dump() for d in tenant.decisions] if tenant.decisions else None,
            "selection": tenant.selection.model_dump(mode="json"),
        }

        # Persist to database
        await self.repository.create_tenant(tenant_data)

        # Add API keys to pool
        for i, apikey in enumerate(tenant.apikey_pool):
            await self.repository.add_apikey_to_pool(tenant.tenant_id, apikey, i)

        # Add to in-memory storage
        self._tenants[tenant.tenant_id] = tenant
        self._apikey_index[tenant.apikey] = tenant.tenant_id
        if tenant.apikey_pool:
            self._apikey_pool[tenant.tenant_id] = list(tenant.apikey_pool)

        logger.info("tenant_created", tenant_id=tenant.tenant_id)

        return tenant

    def update(self, tenant_id: str, updates: dict[str, Any]) -> TenantConfig | None:
        """Update a tenant with partial updates (YAML mode).

        For database mode, use async_update() instead.

        Args:
            tenant_id: The tenant ID to update.
            updates: Dictionary of fields to update.

        Returns:
            Updated TenantConfig if found, None otherwise.

        Raises:
            RuntimeError: If repository is set (database mode).
            ValueError: If unknown field provided or apikey already exists.
        """
        if self.repository:
            raise RuntimeError(
                "Database mode requires async operations. Use async_update() instead."
            )

        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return None

        # Validate that all update fields are valid TenantConfig fields
        valid_fields = set(TenantConfig.model_fields.keys())
        unknown_fields = set(updates.keys()) - valid_fields
        if unknown_fields:
            raise ValueError(f"Unknown fields: {unknown_fields}")

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

        # Handle apikey_pool update
        if "apikey_pool" in updates:
            self._apikey_pool[tenant_id] = updates["apikey_pool"]

        # Merge updates and validate with Pydantic
        update_data = tenant.model_dump()
        update_data.update(updates)

        # Create new validated TenantConfig
        updated_tenant = TenantConfig(**update_data)
        updated_tenant.updated_at = datetime.now()

        # Update storage
        self._tenants[tenant_id] = updated_tenant

        # Persist to file
        self.save()

        return updated_tenant

    async def async_update(self, tenant_id: str, updates: dict[str, Any]) -> TenantConfig | None:
        """Update a tenant with partial updates (database mode).

        Args:
            tenant_id: The tenant ID to update.
            updates: Dictionary of fields to update.

        Returns:
            Updated TenantConfig if found, None otherwise.

        Raises:
            RuntimeError: If repository is not set (YAML mode).
            ValueError: If unknown field provided or apikey already exists.
        """
        if not self.repository:
            raise RuntimeError(
                "YAML mode requires sync operations. Use update() instead."
            )

        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return None

        # Validate that all update fields are valid TenantConfig fields
        valid_fields = set(TenantConfig.model_fields.keys())
        unknown_fields = set(updates.keys()) - valid_fields
        if unknown_fields:
            raise ValueError(f"Unknown fields: {unknown_fields}")

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

        # Prepare database updates
        db_updates = {}
        for key, value in updates.items():
            if key in ("tenant_id", "id", "created_at"):
                continue  # Skip immutable fields
            if key == "decisions":
                # value can be list[Decision] (from TenantConfig) or list[dict] (from API request)
                if value and isinstance(value[0], dict):
                    db_updates[key] = value  # Already dict list
                else:
                    db_updates[key] = [d.model_dump() for d in value] if value else None
            elif key == "selection":
                db_updates[key] = value if isinstance(value, dict) else value.model_dump(mode="json")
            elif key == "apikey_pool":
                # Handle apikey_pool separately
                continue
            else:
                db_updates[key] = value

        # Update database
        if db_updates:
            await self.repository.update_tenant(tenant_id, db_updates)

        # Handle apikey_pool update
        if "apikey_pool" in updates:
            # Delete existing pool entries then re-add to avoid duplicate key errors
            await self.repository.delete_apikey_pool(tenant_id)
            for i, apikey in enumerate(updates["apikey_pool"]):
                await self.repository.add_apikey_to_pool(tenant_id, apikey, i)
            self._apikey_pool[tenant_id] = list(updates["apikey_pool"])
            # Bump version so sync detects change on other instances
            if not db_updates:
                await self.repository.bump_tenant_version(tenant_id)

        # Merge updates and validate with Pydantic
        update_data = tenant.model_dump()
        update_data.update(updates)

        # Create new validated TenantConfig
        updated_tenant = TenantConfig(**update_data)
        updated_tenant.updated_at = datetime.now()

        # Update in-memory storage
        self._tenants[tenant_id] = updated_tenant

        logger.info("tenant_updated", tenant_id=tenant_id)

        return updated_tenant

    def delete(self, tenant_id: str) -> bool:
        """Delete a tenant (YAML mode).

        For database mode, use async_delete() instead.

        Args:
            tenant_id: The tenant ID to delete.

        Returns:
            True if deleted, False if not found.

        Raises:
            RuntimeError: If repository is set (database mode).
        """
        if self.repository:
            raise RuntimeError(
                "Database mode requires async operations. Use async_delete() instead."
            )

        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return False

        # Remove from index
        del self._apikey_index[tenant.apikey]

        # Remove from storage
        del self._tenants[tenant_id]

        # Remove from apikey_pool
        if tenant_id in self._apikey_pool:
            del self._apikey_pool[tenant_id]

        # Persist to file
        self.save()

        return True

    async def async_delete(self, tenant_id: str) -> bool:
        """Delete a tenant (database mode).

        Args:
            tenant_id: The tenant ID to delete.

        Returns:
            True if deleted, False if not found.

        Raises:
            RuntimeError: If repository is not set (YAML mode).
        """
        if not self.repository:
            raise RuntimeError(
                "YAML mode requires sync operations. Use delete() instead."
            )

        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            return False

        # Delete from database
        await self.repository.delete_tenant(tenant_id)

        # Remove from in-memory storage
        del self._apikey_index[tenant.apikey]
        del self._tenants[tenant_id]
        if tenant_id in self._apikey_pool:
            del self._apikey_pool[tenant_id]

        logger.info("tenant_deleted", tenant_id=tenant_id)

        return True
