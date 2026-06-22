#!/usr/bin/env python3
"""YAML to MySQL configuration migration script.

Usage:
    python scripts/yaml_to_mysql.py --config config.yaml --tenants config/tenants.yaml

Both `migrate_config` and `migrate_tenants` delegate to the canonical YAML loaders
(`load_yaml_config` and `TenantManager.load`) so the latest input validation rules
are applied before anything touches the database. Legacy yaml inputs (global
decisions/selection, tenants missing decisions/selection) fail loud here for the
same reason they fail loud at server startup.
"""

import argparse
import asyncio
import json
from pathlib import Path

from mini_router.database import DatabaseConfig


async def migrate_config(config_path: str, db_config: DatabaseConfig) -> None:
    """Migrate the global config YAML into mini_router_config.

    Uses load_yaml_config so legacy `decisions` / `selection` keys are rejected
    before any database round-trip.
    """
    from mini_router.config.loader import load_yaml_config
    from mini_router.database import DatabaseConnection

    # Validation first — runs before we open any DB connection.
    router_config = load_yaml_config(config_path)
    config_dict = router_config.model_dump(mode="json", exclude={"database"})
    config_json = json.dumps(config_dict)

    db = DatabaseConnection(db_config)
    await db.connect()
    try:
        await db.execute(
            "INSERT INTO mini_router_config (config_data, version) VALUES (%s, 1) "
            "ON DUPLICATE KEY UPDATE config_data = %s, version = version + 1",
            (config_json, config_json),
        )
        print(f"Migrated global config from {config_path}")
    finally:
        await db.close()


async def migrate_tenants(tenants_path: str, db_config: DatabaseConfig) -> None:
    """Migrate tenant configs into mini_router_tenant + mini_router_apikey_pool.

    Uses TenantManager.load so legacy tenant entries (missing decisions or
    selection) are rejected before any database round-trip.
    """
    from mini_router.database import ConfigRepository, DatabaseConnection
    from mini_router.tenant.manager import TenantManager

    # Validation first — runs before we open any DB connection.
    manager = TenantManager(yaml_path=tenants_path)
    manager.load()
    tenants = manager.list_all()

    if not tenants:
        print(f"No tenants found in {tenants_path}")
        return

    db = DatabaseConnection(db_config)
    await db.connect()
    try:
        repo = ConfigRepository(db)
        for tenant in tenants:
            await repo.create_tenant(tenant.model_dump(mode="json"))
            for i, key in enumerate(tenant.apikey_pool):
                await repo.add_apikey_to_pool(tenant.tenant_id, key, i)
            print(f"Migrated tenant: {tenant.tenant_id}")
        print(f"Migrated {len(tenants)} tenants from {tenants_path}")
    finally:
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

    ds_config = DatabaseConfig(**db_config)

    async def run():
        if Path(args.config).exists():
            await migrate_config(args.config, ds_config)
        else:
            print(f"Config file not found: {args.config}")

        if Path(args.tenants).exists():
            await migrate_tenants(args.tenants, ds_config)
        else:
            print(f"Tenants file not found: {args.tenants}")

    asyncio.run(run())


if __name__ == "__main__":
    main()
