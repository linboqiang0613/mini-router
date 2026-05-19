# tests/unit/test_database_config.py
"""Tests for DatabaseConfig."""

import os
import pytest

from mini_router.database.config import DatabaseConfig, get_database_config


class TestDatabaseConfig:
    """Test DatabaseConfig class."""

    def test_default_values(self):
        """Test default configuration values."""
        config = DatabaseConfig()
        assert config.enabled == False
        assert config.host == "localhost"
        assert config.port == 3306
        assert config.user == "root"
        assert config.password == ""
        assert config.database == "mini_router"
        assert config.min_connections == 2
        assert config.max_connections == 10
        assert config.charset == "utf8mb4"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = DatabaseConfig(
            enabled=True,
            host="mysql.prod.internal",
            port=3307,
            user="app_user",
            password="secret",
            database="router_db",
            min_connections=5,
            max_connections=20,
        )
        assert config.enabled == True
        assert config.host == "mysql.prod.internal"
        assert config.port == 3307
        assert config.user == "app_user"
        assert config.password == "secret"
        assert config.database == "router_db"
        assert config.min_connections == 5
        assert config.max_connections == 20


class TestGetDatabaseConfig:
    """Test get_database_config function."""

    def test_with_config_object(self):
        """Test loading from config object."""
        config = DatabaseConfig(
            enabled=True,
            host="custom.host",
            database="custom_db",
        )
        result = get_database_config(config)
        assert result.enabled == True
        assert result.host == "custom.host"
        assert result.database == "custom_db"

    def test_without_config_uses_defaults(self):
        """Test default values when no config provided."""
        result = get_database_config()
        assert result.enabled == False
        assert result.host == "localhost"
        assert result.database == "mini_router"

    def test_password_from_env_strip_bee_prefix(self):
        """Test password extraction with BEE_ prefix."""
        os.environ["MINI_ROUTER_DB_ACCESS"] = "BEE_secret_password"
        result = get_database_config()
        assert result.password == "secret_password"
        del os.environ["MINI_ROUTER_DB_ACCESS"]

    def test_password_from_env_without_prefix(self):
        """Test password without BEE_ prefix."""
        os.environ["MINI_ROUTER_DB_ACCESS"] = "plain_password"
        result = get_database_config()
        assert result.password == "plain_password"
        del os.environ["MINI_ROUTER_DB_ACCESS"]

    def test_password_from_env_empty(self):
        """Test empty password."""
        os.environ["MINI_ROUTER_DB_ACCESS"] = ""
        result = get_database_config()
        assert result.password == ""
        del os.environ["MINI_ROUTER_DB_ACCESS"]

    def test_password_from_env_short_prefix(self):
        """Test password shorter than 4 chars."""
        os.environ["MINI_ROUTER_DB_ACCESS"] = "BEE"
        result = get_database_config()
        assert result.password == "BEE"
        del os.environ["MINI_ROUTER_DB_ACCESS"]