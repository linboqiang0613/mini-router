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
        "INSERT INTO mini_router_config (config_data, version) VALUES (%s, 1) "
        "ON DUPLICATE KEY UPDATE config_data = %s, version = version + 1",
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