-- Mini-Router MySQL Database Initialization Script
-- Execute this script before starting the service in production mode

-- 1. 全局配置表
CREATE TABLE IF NOT EXISTS `mini_router_config` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `config_data` JSON NOT NULL COMMENT '完整路由配置',
    `version` INT NOT NULL DEFAULT 1 COMMENT '配置版本号',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Mini-Router 全局配置表';

-- 2. 租户配置表
CREATE TABLE IF NOT EXISTS `mini_router_tenant` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `tenant_id` VARCHAR(64) NOT NULL COMMENT '租户唯一标识',
    `apikey` VARCHAR(128) NOT NULL COMMENT '认证 API Key',
    `name` VARCHAR(128) DEFAULT NULL COMMENT '租户名称',
    `enabled` BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否启用',
    `base_url_template` VARCHAR(256) NOT NULL COMMENT 'LLM API URL模板',
    `timeout` FLOAT NOT NULL DEFAULT 120.0 COMMENT '请求超时时间',
    `apikey_pool_mode` VARCHAR(20) DEFAULT 'round_robin' COMMENT 'Key池模式',
    `decisions` JSON DEFAULT NULL COMMENT '租户路由规则',
    `selection` JSON DEFAULT NULL COMMENT '租户模型选择策略',
    `version` INT NOT NULL DEFAULT 1 COMMENT '版本号',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY `uk_tenant_id` (`tenant_id`),
    INDEX `idx_apikey` (`apikey`),
    INDEX `idx_version` (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Mini-Router 租户配置表';

-- 3. API Key 池表
CREATE TABLE IF NOT EXISTS `mini_router_apikey_pool` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `tenant_id` VARCHAR(64) NOT NULL COMMENT '关联租户ID',
    `apikey` VARCHAR(128) NOT NULL COMMENT 'LLM调用 API Key',
    `apikey_order` INT NOT NULL DEFAULT 0 COMMENT 'Key顺序',
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否可用',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX `idx_tenant` (`tenant_id`),
    UNIQUE KEY `uk_tenant_order` (`tenant_id`, `apikey_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Mini-Router API Key池';

-- 4. 插入默认全局配置（需要根据实际配置修改）
-- INSERT INTO `mini_router_config` (`config_data`, `version`)
-- VALUES ('{"server":{"host":"0.0.0.0","port":8080},"models":{...}}', 1);
