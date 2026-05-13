# mini_router/config/loader.py
"""Configuration loader with environment-based file selection.

Design:
- config_prd.yaml only contains database connection config
- When database.enabled=true, models/signals/decisions are loaded from mini_router_config table
- server.py handles the database config loading after connection is established
"""

import os
from pathlib import Path
from typing import Any

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

    Raises:
        FileNotFoundError: If no config file found
    """
    env = os.environ.get("MINI_ROUTER_ENV", "dev")
    config_file = f"config/config_{env}.yaml"
    path = Path(config_file)

    if path.exists():
        logger.info("config_path_resolved", path=str(path), env=env)
        return path

    # Fallback to default config.yaml if env-specific file not found
    fallback = Path("config.yaml")
    if fallback.exists():
        logger.warning(
            "config_file_not_found_using_fallback",
            requested=str(path),
            fallback=str(fallback),
        )
        return fallback

    # No config file found
    logger.error(
        "no_config_file_found",
        attempted=str(path),
        fallback=str(fallback),
    )
    raise FileNotFoundError(f"No config file found: {path} or {fallback}")


def load_config() -> RouterConfig:
    """Load router configuration from environment-specific file.

    This function loads the base configuration from YAML file.
    When database is enabled, the actual models/signals/decisions config
    should be loaded from database by server.py after connection.

    Returns:
        RouterConfig instance with database field populated
    """
    config_path = get_config_path()
    logger.info("loading_base_config", path=str(config_path))

    # Load YAML config using RouterConfig's method
    router_config = RouterConfig.from_yaml(config_path)

    # Extract database config from YAML if present
    with config_path.open() as f:
        raw_data = yaml.safe_load(f)

    db_config_raw = raw_data.get("database", {})
    if db_config_raw:
        # Create DatabaseConfig from YAML and merge with env password
        db_config = DatabaseConfig(**db_config_raw)
        db_config = get_database_config(db_config)
        # Attach to router config
        router_config.database = db_config
        logger.info(
            "database_config_loaded",
            enabled=db_config.enabled,
            host=db_config.host,
            database=db_config.database,
        )
    else:
        # No database in YAML, use default with env password
        router_config.database = get_database_config()
        logger.info("database_config_default")

    return router_config


async def load_config_from_db(repository: Any) -> RouterConfig | None:
    """Load router configuration from database.

    Called by server.py after database connection is established.
    Reads models/signals/decisions from mini_router_config.config_data.

    Args:
        repository: ConfigRepository instance

    Returns:
        RouterConfig from database, or None if database is empty
    """
    config_data = await repository.get_global_config()
    if config_data and config_data.get("config_data"):
        router_config = RouterConfig.from_dict(config_data["config_data"])
        logger.info(
            "config_loaded_from_db",
            version=config_data.get("version"),
        )
        return router_config

    logger.warning("no_config_in_db")
    return None