"""Database configuration module."""

import os
from typing import Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class DatabaseConfig(BaseModel):
    """Database connection configuration.

    Supports MySQL-compatible databases.
    """

    enabled: bool = Field(default=False, description="Whether database storage is enabled")
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=3306, description="Database port")
    user: str = Field(default="root", description="Database user")
    password: str = Field(default="", description="Database password (from env)")
    database: str = Field(default="mini_router", description="Database name")
    min_connections: int = Field(default=2, description="Minimum connection pool size")
    max_connections: int = Field(default=10, description="Maximum connection pool size")
    charset: str = Field(default="utf8mb4", description="Character set")


def get_database_config(
    config: Optional[DatabaseConfig] = None,
) -> DatabaseConfig:
    """Get database configuration with unified loading logic.

    Configuration priority (highest to lowest):
    1. Provided config object
    2. Environment variable MINI_ROUTER_DB_ACCESS (password, strip "BEE_" prefix)
    3. DatabaseConfig model defaults

    Args:
        config: Optional DatabaseConfig from YAML file

    Returns:
        DatabaseConfig instance
    """
    # Extract password from environment variable
    db_access = os.environ.get("MINI_ROUTER_DB_ACCESS", "")

    # Strip "BEE_" prefix (first 4 characters) - matches CoPaw convention
    if db_access.startswith("BEE_"):
        password = db_access[4:]
        logger.info("database_password_loaded", prefix_removed=True)
    else:
        password = db_access

    return DatabaseConfig(
        enabled=config.enabled if config else False,
        host=config.host if config else "localhost",
        port=config.port if config else 3306,
        user=config.user if config else "root",
        password=password,
        database=config.database if config else "mini_router",
        min_connections=config.min_connections if config else 2,
        max_connections=config.max_connections if config else 10,
        charset=config.charset if config else "utf8mb4",
    )