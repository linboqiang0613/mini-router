-- Strip obsolete `decisions` and `selection` keys from
-- mini_router_config.config_data JSON.
--
-- Background:
--   These two fields were moved from global config to per-tenant config.
--   Legacy rows that were inserted before commit 2db4336 may still carry
--   stale values inside the global config_data JSON blob. The new code
--   path (load_config_from_db with reject-extra-fields) will refuse to
--   load a config that still contains them.
--
-- This is one-shot cleanup; safe to skip if your DB has never run a
-- pre-2db4336 version of mini-router.
--
-- Apply:
UPDATE mini_router_config
SET config_data = JSON_REMOVE(
        config_data,
        '$.decisions',
        '$.selection'
    )
WHERE JSON_CONTAINS_PATH(config_data, 'one', '$.decisions', '$.selection');
--
-- Rollback:
--   None practical — original values can be reconstructed from each tenant's
--   `decisions` / `selection` columns in mini_router_tenant.
