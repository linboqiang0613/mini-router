"""Tests for server database integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mini_router.server import app


class TestServerDatabaseIntegration:
    """Test server database integration."""

    @pytest.mark.asyncio
    async def test_lifespan_yaml_mode(self):
        """Test lifespan in YAML mode (database disabled)."""
        from mini_router.server import lifespan, _config, _router, _tenant_manager
        from mini_router.server import _database_connection, _repository, _sync_service

        # Reset global state
        import mini_router.server as server_module
        server_module._config = None
        server_module._router = None
        server_module._tenant_manager = None
        server_module._chat_proxy = None
        server_module._database_connection = None
        server_module._repository = None
        server_module._sync_service = None

        mock_config = MagicMock()
        mock_config.database = None
        mock_config.decisions = []

        with patch("mini_router.server.load_config", return_value=mock_config):
            with patch("mini_router.server.TenantManager") as mock_tm:
                mock_tm_instance = MagicMock()
                mock_tm_instance.list_all.return_value = []
                mock_tm.return_value = mock_tm_instance

                with patch("mini_router.server.Router") as mock_router:
                    mock_router_instance = MagicMock()
                    mock_router.return_value = mock_router_instance

                    # Lifespan should work without database
                    async with lifespan(app):
                        pass  # Should not raise

                    # Verify YAML mode was used
                    mock_tm.assert_called_once_with()
                    mock_tm_instance.load.assert_called_once()
                    mock_router.assert_called_once_with(mock_config)

    @pytest.mark.asyncio
    async def test_lifespan_database_mode(self):
        """Test lifespan with database enabled."""
        from mini_router.server import lifespan
        import mini_router.server as server_module

        # Reset global state
        server_module._config = None
        server_module._router = None
        server_module._tenant_manager = None
        server_module._chat_proxy = None
        server_module._database_connection = None
        server_module._repository = None
        server_module._sync_service = None

        mock_config = MagicMock()
        mock_config.database = MagicMock()
        mock_config.database.enabled = True
        mock_config.database.host = "localhost"
        mock_config.database.database = "test"
        mock_config.decisions = []

        with patch("mini_router.server.load_config", return_value=mock_config):
            with patch("mini_router.server.DatabaseConnection") as mock_db:
                mock_conn = MagicMock()
                mock_conn.connect = AsyncMock()
                mock_conn.close = AsyncMock()
                mock_db.return_value = mock_conn

                with patch("mini_router.server.ConfigRepository") as mock_repo:
                    mock_repo_instance = MagicMock()
                    mock_repo.return_value = mock_repo_instance

                    with patch("mini_router.server.TenantManager") as mock_tm:
                        mock_tm_instance = MagicMock()
                        mock_tm_instance.async_load = AsyncMock()
                        mock_tm_instance.list_all.return_value = []
                        mock_tm.return_value = mock_tm_instance

                        with patch("mini_router.server.Router") as mock_router:
                            mock_router_instance = MagicMock()
                            mock_router.return_value = mock_router_instance

                            with patch("mini_router.server.ConfigSyncService") as mock_sync:
                                mock_sync_instance = MagicMock()
                                mock_sync_instance.start = AsyncMock()
                                mock_sync_instance.stop = AsyncMock()
                                mock_sync.return_value = mock_sync_instance

                                async with lifespan(app):
                                    pass  # Should initialize and shutdown cleanly

                                # Verify database mode was used
                                mock_db.assert_called_once_with(mock_config.database)
                                mock_conn.connect.assert_called_once()
                                mock_repo.assert_called_once_with(mock_conn)
                                mock_tm.assert_called_once_with(repository=mock_repo_instance)
                                mock_tm_instance.async_load.assert_called_once()
                                mock_router.assert_called_once_with(mock_config, repository=mock_repo_instance)
                                mock_sync.assert_called_once()
                                mock_sync_instance.start.assert_called_once()

                                # Verify shutdown
                                mock_sync_instance.stop.assert_called_once()
                                mock_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_without_database(self):
        """Test shutdown cleanup without database."""
        from mini_router.server import lifespan
        import mini_router.server as server_module

        # Reset global state
        server_module._config = None
        server_module._router = None
        server_module._tenant_manager = None
        server_module._chat_proxy = None
        server_module._database_connection = None
        server_module._repository = None
        server_module._sync_service = None

        mock_config = MagicMock()
        mock_config.database = None
        mock_config.decisions = []

        with patch("mini_router.server.load_config", return_value=mock_config):
            with patch("mini_router.server.TenantManager") as mock_tm:
                mock_tm_instance = MagicMock()
                mock_tm_instance.list_all.return_value = []
                mock_tm.return_value = mock_tm_instance

                with patch("mini_router.server.Router") as mock_router:
                    mock_router_instance = MagicMock()
                    mock_router.return_value = mock_router_instance

                    async with lifespan(app):
                        pass

                    # Verify shutdown was clean - no database-related cleanup
                    assert server_module._database_connection is None
                    assert server_module._repository is None
                    assert server_module._sync_service is None


class TestServerHealthEndpoints:
    """Test server health endpoints."""

    def test_health_endpoint(self):
        """Test /healthz endpoint."""
        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_ready_endpoint(self):
        """Test /readyz endpoint."""
        from fastapi.testclient import TestClient
        # Need to mock the router for this test
        with patch("mini_router.server.get_router") as mock_get_router:
            mock_router = MagicMock()
            mock_get_router.return_value = mock_router

            from mini_router.server import app as test_app
            client = TestClient(test_app)
            response = client.get("/readyz")
            assert response.status_code == 200
            assert response.json()["status"] == "ready"