# tests/unit/test_config_sync.py
"""Tests for ConfigSyncService."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mini_router.database.sync import ConfigSyncService


class TestConfigSyncService:
    """Test ConfigSyncService."""

    @pytest.fixture
    def mock_components(self):
        """Create mock components."""
        repo = MagicMock()
        repo.get_global_version = AsyncMock(return_value=1)
        repo.get_tenant_versions = AsyncMock(return_value={"t1": 5})

        tenant_manager = MagicMock()
        tenant_manager.reload = AsyncMock()

        router = MagicMock()
        router.reload_config = AsyncMock()

        return repo, tenant_manager, router

    def test_init(self, mock_components):
        """Test initialization."""
        repo, tm, router = mock_components
        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
            global_poll_interval=120,
            tenant_poll_interval=10,
        )

        assert sync.global_poll_interval == 120
        assert sync.tenant_poll_interval == 10
        assert sync._running == False
        assert sync._global_version == 0
        assert sync._tenant_versions == {}

    def test_init_with_env_vars(self, mock_components):
        """Test initialization with environment variables."""
        repo, tm, router = mock_components

        with patch.dict("os.environ", {
            "MINI_ROUTER_GLOBAL_POLL_INTERVAL": "60",
            "MINI_ROUTER_TENANT_POLL_INTERVAL": "5",
        }):
            sync = ConfigSyncService(
                repository=repo,
                tenant_manager=tm,
                router=router,
            )
            # Should read from env vars
            assert sync.global_poll_interval == 60
            assert sync.tenant_poll_interval == 5

    @pytest.mark.asyncio
    async def test_poll_global_version_change(self, mock_components):
        """Test global config poll detects version change."""
        repo, tm, router = mock_components
        repo.get_global_version = AsyncMock(side_effect=[2, 2])

        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
            global_poll_interval=0.1,  # Fast for testing
        )

        # Set initial version
        sync._global_version = 1

        # Run one poll iteration
        sync._running = True
        await sync._poll_global_once()
        sync._running = False

        # Should have called reload_config
        router.reload_config.assert_called_once()
        assert sync._global_version == 2

    @pytest.mark.asyncio
    async def test_poll_global_no_change(self, mock_components):
        """Test global config poll with no version change."""
        repo, tm, router = mock_components
        repo.get_global_version = AsyncMock(return_value=1)

        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
        )
        sync._global_version = 1
        sync._running = True

        await sync._poll_global_once()
        sync._running = False

        # Should NOT have called reload_config
        router.reload_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_tenant_version_change(self, mock_components):
        """Test tenant config poll detects version change."""
        repo, tm, router = mock_components
        # DB returns different version snapshot
        repo.get_tenant_versions = AsyncMock(side_effect=[
            {"t1": 15},  # first call: new version detected, triggers reload
            {"t1": 15},  # second call: poll after reload, no change
        ])

        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
            tenant_poll_interval=0.1,
        )

        sync._tenant_versions = {"t1": 10}
        sync._running = True

        await sync._poll_tenant_once()
        sync._running = False

        tm.reload.assert_called_once()
        assert sync._tenant_versions == {"t1": 15}

    @pytest.mark.asyncio
    async def test_poll_tenant_no_change(self, mock_components):
        """Test tenant config poll with no version change."""
        repo, tm, router = mock_components
        repo.get_tenant_versions = AsyncMock(return_value={"t1": 10})

        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
        )
        sync._tenant_versions = {"t1": 10}
        sync._running = True

        await sync._poll_tenant_once()
        sync._running = False

        tm.reload.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_tenant_new_tenant(self, mock_components):
        """Test tenant config poll detects newly added tenant."""
        repo, tm, router = mock_components
        repo.get_tenant_versions = AsyncMock(return_value={"t1": 1, "t2": 1})

        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
        )
        sync._tenant_versions = {"t1": 1}
        sync._running = True

        await sync._poll_tenant_once()
        sync._running = False

        tm.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_poll_tenant_deleted_tenant(self, mock_components):
        """Test tenant config poll detects deleted/disabled tenant."""
        repo, tm, router = mock_components
        repo.get_tenant_versions = AsyncMock(return_value={"t1": 5})

        sync = ConfigSyncService(
            repository=repo,
            tenant_manager=tm,
            router=router,
        )
        sync._tenant_versions = {"t1": 5, "t2": 3}
        sync._running = True

        await sync._poll_tenant_once()
        sync._running = False

        tm.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_creates_tasks(self, mock_components):
        """Test start creates polling tasks."""
        repo, tm, router = mock_components
        sync = ConfigSyncService(repo, tm, router)

        await sync.start()

        assert sync._running == True
        assert sync._global_task is not None
        assert sync._tenant_task is not None

        await sync.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, mock_components):
        """Test stop cancels polling tasks."""
        repo, tm, router = mock_components
        sync = ConfigSyncService(repo, tm, router)

        await sync.start()
        await sync.stop()

        assert sync._running == False