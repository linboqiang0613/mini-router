# mini_router/database/repository.py
"""Config repository for database CRUD operations."""

import json
import structlog
from typing import Any

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

    def _parse_json_field(self, value: Any) -> Any:
        """Parse JSON field from MySQL (returns string, need to convert to dict/list)."""
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return value

    # === Global Config Operations ===

    async def get_global_config(self) -> dict[str, Any] | None:
        """Get global router configuration.

        Returns:
            Dict with config_data (parsed from JSON) and version, or None if not found
        """
        row = await self.db.fetch_one(
            "SELECT config_data, version FROM mini_router_config LIMIT 1"
        )
        if row:
            row["config_data"] = self._parse_json_field(row["config_data"])
            return row
        return None

    async def save_global_config(self, config_data: dict[str, Any]) -> None:
        """Save global router configuration.

        Args:
            config_data: Full router config as dict
        """
        await self.db.execute(
            "UPDATE mini_router_config SET config_data = %s, version = version + 1",
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

    async def get_all_tenants(self) -> list[dict[str, Any]]:
        """Get all enabled tenants.

        Returns:
            List of tenant dicts with decisions parsed from JSON
        """
        rows = await self.db.fetch_all(
            "SELECT * FROM mini_router_tenant WHERE enabled = TRUE"
        )
        for row in rows:
            row["decisions"] = self._parse_json_field(row.get("decisions"))
        return rows

    async def get_tenant_by_id(self, tenant_id: str) -> dict[str, Any] | None:
        """Get tenant by tenant_id.

        Args:
            tenant_id: Tenant identifier

        Returns:
            Tenant dict with decisions parsed, or None
        """
        row = await self.db.fetch_one(
            "SELECT * FROM mini_router_tenant WHERE tenant_id = %s",
            (tenant_id,)
        )
        if row:
            row["decisions"] = self._parse_json_field(row.get("decisions"))
        return row

    async def get_tenant_by_apikey(self, apikey: str) -> dict[str, Any] | None:
        """Get tenant by authentication API key.

        Args:
            apikey: Authentication API key

        Returns:
            Tenant dict with decisions parsed, or None
        """
        row = await self.db.fetch_one(
            "SELECT * FROM mini_router_tenant WHERE apikey = %s",
            (apikey,)
        )
        if row:
            row["decisions"] = self._parse_json_field(row.get("decisions"))
        return row

    async def create_tenant(self, tenant_data: dict[str, Any]) -> None:
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
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

    async def update_tenant(self, tenant_id: str, updates: dict[str, Any]) -> None:
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
                update_fields.append("decisions = %s")
                params.append(json.dumps(value) if value else None)
            else:
                update_fields.append(f"{key} = %s")
                params.append(value)

        if not update_fields:
            return

        # Add version increment
        update_fields.append("version = version + 1")
        params.append(tenant_id)

        sql = "UPDATE mini_router_tenant SET " + ", ".join(update_fields) + " WHERE tenant_id = %s"
        await self.db.execute(sql, tuple(params))
        logger.info("tenant_updated", tenant_id=tenant_id)

    async def delete_tenant(self, tenant_id: str) -> None:
        """Delete tenant.

        Args:
            tenant_id: Tenant identifier
        """
        await self.db.execute(
            "DELETE FROM mini_router_tenant WHERE tenant_id = %s",
            (tenant_id,)
        )
        # Also delete API key pool entries
        await self.db.execute(
            "DELETE FROM mini_router_apikey_pool WHERE tenant_id = %s",
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

    async def bump_tenant_version(self, tenant_id: str) -> None:
        """Increment the version number for a tenant.

        Used when only apikey_pool changes so that sync detects the update.

        Args:
            tenant_id: Tenant identifier
        """
        await self.db.execute(
            "UPDATE mini_router_tenant SET version = version + 1 WHERE tenant_id = %s",
            (tenant_id,)
        )

    # === API Key Pool Operations ===

    async def get_apikey_pool(self, tenant_id: str) -> list[dict[str, Any]]:
        """Get API key pool for tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            List of API key pool entries
        """
        rows = await self.db.fetch_all(
            """
            SELECT * FROM mini_router_apikey_pool
            WHERE tenant_id = %s
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
            VALUES (%s, %s, %s, TRUE)
            """,
            (tenant_id, apikey, order)
        )
        logger.info("apikey_added_to_pool", tenant_id=tenant_id, order=order)

    async def delete_apikey_pool(self, tenant_id: str) -> None:
        """Delete all API key pool entries for a tenant.

        Args:
            tenant_id: Tenant identifier
        """
        await self.db.execute(
            "DELETE FROM mini_router_apikey_pool WHERE tenant_id = %s",
            (tenant_id,)
        )
        logger.info("apikey_pool_deleted", tenant_id=tenant_id)

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
            SET is_active = %s
            WHERE tenant_id = %s AND apikey_order = %s
            """,
            (is_active, tenant_id, order)
        )
        logger.info(
            "apikey_status_updated",
            tenant_id=tenant_id,
            order=order,
            is_active=is_active,
        )