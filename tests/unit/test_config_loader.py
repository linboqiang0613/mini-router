"""Tests for config loader."""

from pathlib import Path

import pytest

from mini_router.config.loader import (
    get_envs_config_path,
    load_database_config,
    load_envs_config,
    load_yaml_config,
)


class TestEnvsConfig:
    """Tests for environment config loading."""

    def test_get_envs_config_path_missing(self) -> None:
        """Missing env config should raise."""
        with pytest.raises(FileNotFoundError, match="envs_missing.yaml"):
            get_envs_config_path("missing")

    def test_load_envs_config(self, tmp_path, monkeypatch) -> None:
        """Loads env-specific database config YAML."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        env_file = config_dir / "envs_dev.yaml"
        env_file.write_text(
            """
database:
  host: mysql.local
  port: 3306
  user: root
  database: mini_router
"""
        )

        monkeypatch.chdir(tmp_path)
        loaded = load_envs_config("dev")

        assert loaded["database"]["host"] == "mysql.local"

    def test_load_database_config_uses_env_password(self, tmp_path, monkeypatch) -> None:
        """Database password should come from MINI_ROUTER_DB_ACCESS."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        env_file = config_dir / "envs_dev.yaml"
        env_file.write_text(
            """
database:
  host: mysql.local
  port: 3306
  user: root
  database: mini_router
"""
        )

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MINI_ROUTER_DB_ACCESS", "BEE_secret123")
        config = load_database_config("dev")

        assert config.host == "mysql.local"
        assert config.password == "BEE_secret123"


class TestYamlConfig:
    """Tests for YAML router config loading."""

    def test_load_yaml_config_signal_only(self, tmp_path) -> None:
        """Signal-only global YAML config remains valid."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
models:
  base_url: https://api.example.com/v1
  timeout: 120.0
signals:
  keyword_rules:
    - name: code_related
      keywords: ["code", "debug"]
"""
        )

        config = load_yaml_config(str(config_file))

        assert config.models.base_url == "https://api.example.com/v1"
        assert len(config.signals.keyword_rules) == 1
        assert config.decisions == []
        assert config.database is None

    def test_load_yaml_config_rejects_global_decisions(self, tmp_path) -> None:
        """Global decisions are no longer allowed in YAML mode."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
models:
  base_url: https://api.example.com/v1
signals:
  keyword_rules: []
decisions: []
"""
        )

        with pytest.raises(ValueError, match="global 'decisions'"):
            load_yaml_config(str(config_file))

    def test_load_yaml_config_rejects_global_selection(self, tmp_path) -> None:
        """Global selection is no longer allowed in YAML mode."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
models:
  base_url: https://api.example.com/v1
signals:
  keyword_rules: []
selection:
  strategy: static
"""
        )

        with pytest.raises(ValueError, match="global 'selection'"):
            load_yaml_config(str(config_file))

    def test_load_yaml_config_missing_file(self, tmp_path) -> None:
        """Missing YAML config should raise."""
        missing = tmp_path / "missing.yaml"
        with pytest.raises(FileNotFoundError):
            load_yaml_config(str(missing))
