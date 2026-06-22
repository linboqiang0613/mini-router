"""Smoke tests for scripts/yaml_to_mysql.py — verifying it reuses the
new loader so legacy yaml inputs fail loud instead of silently writing
stale data into the DB."""

import sys
from pathlib import Path

import pytest

# Let `scripts/` be importable as a top-level module
_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


class TestYamlToMysqlRejectsLegacyConfig:
    """yaml_to_mysql.migrate_config must reject yaml carrying global decisions/selection."""

    @pytest.mark.asyncio
    async def test_rejects_legacy_global_decisions(self, tmp_path):
        from yaml_to_mysql import migrate_config

        from mini_router.database.config import DatabaseConfig

        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            """
models:
  base_url: http://x
signals:
  keyword_rules: []
decisions: []
"""
        )

        with pytest.raises(ValueError, match="global 'decisions'"):
            await migrate_config(str(cfg), DatabaseConfig())

    @pytest.mark.asyncio
    async def test_rejects_legacy_global_selection(self, tmp_path):
        from yaml_to_mysql import migrate_config

        from mini_router.database.config import DatabaseConfig

        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            """
models:
  base_url: http://x
signals:
  keyword_rules: []
selection:
  strategy: static
"""
        )

        with pytest.raises(ValueError, match="global 'selection'"):
            await migrate_config(str(cfg), DatabaseConfig())
