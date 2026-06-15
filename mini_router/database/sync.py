# mini_router/database/sync.py
"""Config sync service for polling database changes."""

import asyncio
import os
import structlog

from mini_router.database.repository import ConfigRepository

logger = structlog.get_logger()


class ConfigSyncService:
    """Configuration sync service.

    Polls database for version changes and triggers reloads.
    """

    def __init__(
        self,
        repository: ConfigRepository,
        tenant_manager: any,  # TenantManager (avoid circular import)
        router: any,  # Router (avoid circular import)
        global_poll_interval: int = 120,
        tenant_poll_interval: int = 10,
    ) -> None:
        """Initialize sync service.

        Args:
            repository: Config repository
            tenant_manager: Tenant manager instance
            router: Router instance
            global_poll_interval: Global config poll interval (seconds), default 120
            tenant_poll_interval: Tenant config poll interval (seconds), default 10
        """
        self.repository = repository
        self.tenant_manager = tenant_manager
        self.router = router

        # Use environment variables if set
        env_global = os.environ.get("MINI_ROUTER_GLOBAL_POLL_INTERVAL")
        env_tenant = os.environ.get("MINI_ROUTER_TENANT_POLL_INTERVAL")

        self.global_poll_interval = int(env_global) if env_global else global_poll_interval
        self.tenant_poll_interval = int(env_tenant) if env_tenant else tenant_poll_interval

        self._running = False
        self._global_version = 0
        self._tenant_versions: dict[str, int] = {}
        self._global_task: asyncio.Task | None = None
        self._tenant_task: asyncio.Task | None = None

        logger.info(
            "sync_service_initialized",
            global_interval=self.global_poll_interval,
            tenant_interval=self.tenant_poll_interval,
        )

    async def start(self) -> None:
        """Start polling tasks."""
        if self._running:
            return

        self._running = True

        # Initialize version tracking
        self._global_version = await self.repository.get_global_version()
        self._tenant_versions = await self.repository.get_tenant_versions()

        logger.info(
            "sync_service_started",
            initial_global_version=self._global_version,
            initial_tenant_count=len(self._tenant_versions),
        )

        # Create polling tasks
        self._global_task = asyncio.create_task(self._poll_global_loop())
        self._tenant_task = asyncio.create_task(self._poll_tenant_loop())

    async def stop(self) -> None:
        """Stop polling tasks."""
        self._running = False

        if self._global_task:
            self._global_task.cancel()
            try:
                await self._global_task
            except asyncio.CancelledError:
                pass
            self._global_task = None

        if self._tenant_task:
            self._tenant_task.cancel()
            try:
                await self._tenant_task
            except asyncio.CancelledError:
                pass
            self._tenant_task = None

        logger.info("sync_service_stopped")

    async def _poll_global_loop(self) -> None:
        """Global config polling loop."""
        while self._running:
            await asyncio.sleep(self.global_poll_interval)
            if not self._running:
                break
            await self._poll_global_once()

    async def _poll_global_once(self) -> None:
        """Single global config poll."""
        try:
            version = await self.repository.get_global_version()
            if version > self._global_version:
                logger.info(
                    "global_config_changed",
                    old_version=self._global_version,
                    new_version=version,
                )
                self._global_version = version
                await self.router.reload_config()
        except Exception as e:
            logger.error(
                "global_poll_error",
                error=str(e),
                error_type=type(e).__name__,
            )

    async def _poll_tenant_loop(self) -> None:
        """Tenant config polling loop."""
        while self._running:
            await asyncio.sleep(self.tenant_poll_interval)
            if not self._running:
                break
            await self._poll_tenant_once()

    async def _poll_tenant_once(self) -> None:
        """Single tenant config poll.

        Compares per-tenant version snapshots so that any change — create,
        update, delete, or disable — is detected reliably across instances.
        """
        try:
            db_versions = await self.repository.get_tenant_versions()
            if db_versions != self._tenant_versions:
                logger.info(
                    "tenant_config_changed",
                    old_keys=list(self._tenant_versions.keys()),
                    new_keys=list(db_versions.keys()),
                )
                self._tenant_versions = db_versions
                await self.tenant_manager.reload()
        except Exception as e:
            logger.error(
                "tenant_poll_error",
                error=str(e),
                error_type=type(e).__name__,
            )