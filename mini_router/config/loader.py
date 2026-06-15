# mini_router/config/loader.py
"""Configuration loader with two modes:

YAML mode (--config=<path>):
  - Load router config from specified YAML file
  - Load tenants from tenants.yaml (or path-derived tenant file)
  - Classic single-instance mode

Database mode (--config empty, default):
  - Load database connection info from envs_{env}.yaml (--env parameter)
  - Load router config from mini_router_config table
  - Load tenants from mini_router_tenant table
  - Production multi-instance mode
"""

import os
from pathlib import Path
from typing import Any

import structlog
import yaml

from mini_router.config.config import RouterConfig
from mini_router.database.config import DatabaseConfig, get_database_config

logger = structlog.get_logger()


def get_envs_config_path(env: str = "dev") -> Path:
    """Get envs config file path for database mode.

    Args:
        env: Environment name (dev/prd), default "dev"

    Returns:
        Path to config/envs_{env}.yaml
    """
    path = Path(f"config/envs_{env}.yaml")
    if not path.exists():
        raise FileNotFoundError(f"Envs config file not found: {path}")
    return path


def load_envs_config(env: str = "dev") -> dict[str, Any]:
    """Load envs config (database connection info only).

    Args:
        env: Environment name (dev/prd)

    Returns:
        Dict with 'server' and 'database' keys
    """
    path = get_envs_config_path(env)
    logger.info("loading_envs_config", path=str(path), env=env)

    with path.open() as f:
        data = yaml.safe_load(f)

    return data


def load_yaml_config(config_path: str) -> RouterConfig:
    """Load router configuration from YAML file (YAML mode).

    Args:
        config_path: Path to config YAML file

    Returns:
        RouterConfig instance loaded from YAML
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    logger.info("loading_yaml_config", path=str(path))

    with path.open() as f:
        raw_config = yaml.safe_load(f) or {}

    if "decisions" in raw_config:
        raise ValueError(
            "YAML mode no longer accepts global 'decisions' in config.yaml; "
            "move routing decisions into tenant configuration."
        )

    if "selection" in raw_config:
        raise ValueError(
            "YAML mode no longer accepts global 'selection' in config.yaml; "
            "move selection strategy into tenant configuration."
        )

    router_config = RouterConfig.from_dict(raw_config)

    # YAML mode does not use database
    router_config.database = None
    return router_config


def load_database_config(env: str = "dev") -> DatabaseConfig:
    """Load database connection config from envs file.

    Args:
        env: Environment name (dev/prd)

    Returns:
        DatabaseConfig instance
    """
    envs_data = load_envs_config(env)
    db_config_raw = envs_data.get("database", {})

    if not db_config_raw:
        raise ValueError(f"No database config in envs_{env}.yaml")

    db_config = DatabaseConfig(**db_config_raw)
    db_config = get_database_config(db_config)

    logger.info(
        "database_config_loaded",
        host=db_config.host,
        database=db_config.database,
    )
    return db_config


async def load_config_from_db(repository: Any) -> RouterConfig:
    """Load router configuration from database.

    Called by server.py after database connection is established.
    Reads models/signals/decisions from mini_router_config.config_data.

    Args:
        repository: ConfigRepository instance

    Returns:
        RouterConfig from database

    Raises:
        ValueError: If database has no global config
    """
    config_data = await repository.get_global_config()

    if not config_data or not config_data.get("config_data"):
        raise ValueError("Database has no global config in mini_router_config table")

    router_config = RouterConfig.from_dict(config_data["config_data"])
    logger.info(
        "config_loaded_from_db",
        version=config_data.get("version"),
    )
    return router_config
