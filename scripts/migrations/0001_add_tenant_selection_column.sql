-- Add per-tenant `selection` (model selection strategy) column.
--
-- Background:
--   Routing policy (decisions + selection) was moved out of global config
--   into per-tenant config in main commit 2db4336. The schema followed:
--   `selection JSON` column added to mini_router_tenant.
--
-- Apply:
ALTER TABLE mini_router_tenant
    ADD COLUMN selection JSON DEFAULT NULL COMMENT '租户模型选择策略'
    AFTER decisions;
--
-- Rollback (only safe if no tenant has been written to with selection yet):
--   ALTER TABLE mini_router_tenant DROP COLUMN selection;
