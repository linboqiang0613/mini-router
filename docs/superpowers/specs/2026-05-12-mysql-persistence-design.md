# Mini-Router MySQL 持久化设计

## 概述

将 mini-router 的配置存储从 YAML 文件迁移到 MySQL 数据库，支持生产环境多实例部署时的配置同步。

---

## 目标

1. **多实例配置同步**：多个 mini-router 实例共享同一 MySQL 数据库，配置变更后秒级同步
2. **配置持久化**：租户配置和全局路由配置持久化到 MySQL
3. **环境区分**：支持 dev/prd 环境配置文件分离
4. **实时生效**：配置变更后 10 秒内同步到所有实例

---

## 决策汇总

| 决策点 | 最终方案 |
|-----|---------|
| 表结构 | 三张表：`mini_router_config` + `mini_router_tenant` + `mini_router_apikey_pool` |
| 版本检测 | 每张表独立版本号，变化后全量刷新租户内存 |
| 轮询间隔 | 分开轮询：全局配置 120s，租户配置 10s |
| 环境区分 | 环境变量 `MINI_ROUTER_ENV=dev/prd`，加载对应 `config_{env}.yaml` |
| 数据库配置来源 | config.yaml（基础配置）+ 环境变量（密码） |
| 密码前缀 | `"BEE_"`（去掉前4字符得到真实密码，与 CoPaw 一致） |
| 连接库 | aiomysql 异步连接池 |
| 日志框架 | structlog（统一项目风格） |

---

## 环境配置方案

### 配置文件结构

```
config/
├── config_dev.yaml    # 开发环境配置（数据库可能 disabled 或本地 MySQL）
├── config_prd.yaml    # 生产环境配置（启用 MySQL，连接生产数据库）
└── tenants.yaml       # 保留（可选，用于本地开发 fallback）
```

### 环境变量控制

```bash
# 环境类型（决定加载哪个配置文件）
MINI_ROUTER_ENV=dev    # 加载 config_dev.yaml
MINI_ROUTER_ENV=prd    # 加载 config_prd.yaml
# 未设置时默认 dev

# 数据库密码（去掉 "BEE_" 前缀）
MINI_ROUTER_DB_ACCESS=BEE_your_password

# 轮询间隔（可选，有默认值）
MINI_ROUTER_GLOBAL_POLL_INTERVAL=120  # 全局配置轮询间隔（秒），默认 120
MINI_ROUTER_TENANT_POLL_INTERVAL=10   # 租户配置轮询间隔（秒），默认 10
```

### 配置文件格式

```yaml
# config_prd.yaml 示例
server:
  host: "0.0.0.0"
  port: 8080

database:
  enabled: true              # 是否启用数据库存储
  host: "mysql.prod.internal"
  port: 3306
  user: "mini_router"
  database: "mini_router"
  min_connections: 2
  max_connections: 10
  charset: "utf8mb4"

models:
  base_url: "https://api.llm.com/v1"
  timeout: 120.0
  # ... 其他配置

# config_dev.yaml 示例（本地开发）
database:
  enabled: false             # 禁用数据库，使用 YAML 文件存储
  # 或启用本地 MySQL 测试
  enabled: true
  host: "localhost"
  port: 3306
  user: "root"
  database: "mini_router_dev"
```

---

## 数据库表结构

### 1. 全局配置表 `mini_router_config`

```sql
CREATE TABLE `mini_router_config` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `config_data` JSON NOT NULL COMMENT '完整路由配置（server/models/signals/decisions/selection/cache）',
    `version` INT NOT NULL DEFAULT 1 COMMENT '配置版本号，每次更新+1',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Mini-Router 全局配置表';

-- 初始数据（通过迁移脚本插入）
INSERT INTO `mini_router_config` (`config_data`, `version`)
VALUES ('{"server":{"host":"0.0.0.0","port":8080},"models":{...},"decisions":[...]}', 1);
```

**说明：**
- 全局配置只有一行数据
- `config_data` 存储完整路由配置的 JSON 结构
- `version` 用于轮询检测变化

### 2. 租户配置表 `mini_router_tenant`

```sql
CREATE TABLE `mini_router_tenant` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `tenant_id` VARCHAR(64) NOT NULL COMMENT '租户唯一标识',
    `apikey` VARCHAR(128) NOT NULL COMMENT '认证 API Key（调用 /v1/chat/completions 时使用）',
    `name` VARCHAR(128) DEFAULT NULL COMMENT '租户名称',
    `enabled` BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否启用',
    `base_url_template` VARCHAR(256) NOT NULL COMMENT 'LLM API URL模板，支持 {model} 占位符',
    `timeout` FLOAT NOT NULL DEFAULT 120.0 COMMENT '请求超时时间（秒）',
    `apikey_pool_mode` VARCHAR(20) DEFAULT 'round_robin' COMMENT 'Key池模式：round_robin/fallback',
    `decisions` JSON DEFAULT NULL COMMENT '租户专属路由规则',
    `version` INT NOT NULL DEFAULT 1 COMMENT '租户配置版本号',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY `uk_tenant_id` (`tenant_id`),
    INDEX `idx_apikey` (`apikey`),
    INDEX `idx_version` (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Mini-Router 租户配置表';
```

**说明：**
- `apikey`：租户认证 Key，用于调用 mini-router API
- `apikey_pool_mode`：LLM 调用 Key 池的选择模式
- `decisions`：租户专属路由规则，JSON 格式存储

### 3. API Key 池表 `mini_router_apikey_pool`

```sql
CREATE TABLE `mini_router_apikey_pool` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `tenant_id` VARCHAR(64) NOT NULL COMMENT '关联租户ID',
    `apikey` VARCHAR(128) NOT NULL COMMENT 'LLM调用 API Key',
    `apikey_order` INT NOT NULL DEFAULT 0 COMMENT 'Key顺序（用于 round_robin）',
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否可用（fallback模式标记失效）',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX `idx_tenant` (`tenant_id`),
    UNIQUE KEY `uk_tenant_order` (`tenant_id`, `apikey_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Mini-Router LLM调用API Key池';
```

**说明：**
- 单独建表便于轮询选择和 fallback 标记
- `apikey_order`：Key 在池中的顺序
- `is_active`：fallback 模式下标记 Key 是否可用（429 降级后设为 false）

---

## 模块结构

### 新增文件

```
mini_router/
├── database/                      # 新增：数据库基础设施层
│   ├── __init__.py                # 导出 DatabaseConfig, DatabaseConnection, ConfigRepository
│   ├── config.py                  # DatabaseConfig 配置类
│   ├── connection.py              # DatabaseConnection 连接池管理
│   ├── repository.py              # ConfigRepository 数据表 CRUD
│   └── sync.py                    # ConfigSyncService 配置同步服务
├── config/
│   └── loader.py                  # 新增：配置加载器（支持环境变量选择配置文件）
└── tenant/
    └── manager.py                 # 改造：支持数据库存储和 reload()
```

### 改造文件

| 文件 | 改造内容 |
|-----|---------|
| `mini_router/config/config.py` | 新增 `DatabaseConfig` 字段到 RouterConfig |
| `mini_router/tenant/manager.py` | 支持从 repository 加载，增加 `reload()` 方法 |
| `mini_router/router/router.py` | 支持从 repository 加载全局配置，增加 `reload_config()` 方法 |
| `mini_router/server.py` | 启动时初始化数据库连接 + 轮询任务 |

---

## 核心类设计

### 1. DatabaseConfig（参考 CoPaw，删 TDSQL 别名）

```python
# mini_router/database/config.py

class DatabaseConfig(BaseModel):
    """数据库连接配置"""
    enabled: bool = False               # 是否启用数据库存储
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""                  # 从环境变量 MINI_ROUTER_DB_ACCESS 加载
    database: str = "mini_router"
    min_connections: int = 2
    max_connections: int = 10
    charset: str = "utf8mb4"


def get_database_config(
    config: DatabaseConfig | None = None,
) -> DatabaseConfig:
    """获取数据库配置

    加载优先级：
    1. config.yaml 中的 database 配置
    2. 环境变量 MINI_ROUTER_DB_ACCESS（密码，去掉 "BEE_" 前缀）
    3. 默认值
    """
    # 从环境变量加载密码
    db_access = os.environ.get("MINI_ROUTER_DB_ACCESS", "")
    # 去掉 "BEE_" 前缀（前4字符）
    password = db_access[4:] if len(db_access) > 4 else db_access

    return DatabaseConfig(
        enabled=config.enabled if config else False,
        host=config.host if config else "localhost",
        port=config.port if config else 3306,
        user=config.user if config else "root",
        password=password,
        database=config.database if config else "mini_router",
        min_connections=config.min_connections if config else 2,
        max_connections=config.max_connections if config else 10,
    )
```

### 2. DatabaseConnection（参考 CoPaw，删 TDSQL 别名，改 structlog）

```python
# mini_router/database/connection.py

class DatabaseConnection:
    """异步 MySQL 连接池管理"""

    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self._pool: Any = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._pool is not None

    async def connect(self) -> None:
        """创建连接池"""
        self._pool = await aiomysql.create_pool(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            db=self.config.database,
            charset=self.config.charset,
            minsize=self.config.min_connections,
            maxsize=self.config.max_connections,
            autocommit=True,
        )
        self._connected = True

    async def close(self) -> None:
        """关闭连接池"""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            self._connected = False

    async def execute(self, query: str, params: tuple | None = None) -> int:
        """执行查询，返回影响行数"""

    async def fetch_one(self, query: str, params: tuple | None = None) -> dict | None:
        """查询单行"""

    async def fetch_all(self, query: str, params: tuple | None = None) -> list[dict]:
        """查询所有行"""
```

### 3. ConfigRepository

```python
# mini_router/database/repository.py

class ConfigRepository:
    """配置表 CRUD 操作"""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db

    # === 全局配置 ===
    async def get_global_config(self) -> dict | None:
        """获取全局配置"""
        row = await self.db.fetch_one(
            "SELECT config_data, version FROM mini_router_config LIMIT 1"
        )
        return row

    async def save_global_config(self, config_data: dict) -> None:
        """保存全局配置（更新 version++）"""
        await self.db.execute(
            "UPDATE mini_router_config SET config_data = ?, version = version + 1",
            (json.dumps(config_data),)
        )

    async def get_global_version(self) -> int:
        """获取全局配置版本号"""
        row = await self.db.fetch_one("SELECT version FROM mini_router_config LIMIT 1")
        return row["version"] if row else 0

    # === 租户配置 ===
    async def get_all_tenants(self) -> list[dict]:
        """获取所有租户"""
        return await self.db.fetch_all(
            "SELECT * FROM mini_router_tenant WHERE enabled = TRUE"
        )

    async def get_tenant_by_id(self, tenant_id: str) -> dict | None:
        """根据 ID 获取租户"""

    async def get_tenant_by_apikey(self, apikey: str) -> dict | None:
        """根据认证 API Key 获取租户"""

    async def create_tenant(self, tenant_data: dict) -> None:
        """创建租户"""

    async def update_tenant(self, tenant_id: str, updates: dict) -> None:
        """更新租户（version++）"""

    async def delete_tenant(self, tenant_id: str) -> None:
        """删除租户"""

    async def get_tenant_max_version(self) -> int:
        """获取租户表最大版本号"""
        row = await self.db.fetch_one("SELECT MAX(version) as max_version FROM mini_router_tenant")
        return row["max_version"] if row else 0

    # === API Key 池 ===
    async def get_apikey_pool(self, tenant_id: str) -> list[dict]:
        """获取租户的 API Key 池"""

    async def add_apikey_to_pool(self, tenant_id: str, apikey: str, order: int) -> None:
        """添加 API Key 到池"""

    async def update_apikey_status(self, tenant_id: str, order: int, is_active: bool) -> None:
        """更新 API Key 状态（fallback 标记）"""
```

### 4. ConfigSyncService

```python
# mini_router/database/sync.py

class ConfigSyncService:
    """配置同步服务：轮询检测版本变化，通知业务层重载"""

    def __init__(
        self,
        repository: ConfigRepository,
        tenant_manager: TenantManager,
        router: Router,
        global_poll_interval: int = 120,   # 默认 120 秒
        tenant_poll_interval: int = 10,    # 默认 10 秒
    ) -> None:
        self.repository = repository
        self.tenant_manager = tenant_manager
        self.router = router
        self.global_poll_interval = global_poll_interval
        self.tenant_poll_interval = tenant_poll_interval
        self._running = False
        self._global_version = 0
        self._tenant_version = 0

    async def start(self) -> None:
        """启动轮询任务"""
        self._running = True
        # 启动两个独立的轮询任务
        asyncio.create_task(self._poll_global_loop())
        asyncio.create_task(self._poll_tenant_loop())

    async def stop(self) -> None:
        """停止轮询"""
        self._running = False

    async def _poll_global_loop(self) -> None:
        """全局配置轮询"""
        while self._running:
            await asyncio.sleep(self.global_poll_interval)
            version = await self.repository.get_global_version()
            if version > self._global_version:
                self._global_version = version
                await self.router.reload_config()

    async def _poll_tenant_loop(self) -> None:
        """租户配置轮询"""
        while self._running:
            await asyncio.sleep(self.tenant_poll_interval)
            version = await self.repository.get_tenant_max_version()
            if version > self._tenant_version:
                self._tenant_version = version
                await self.tenant_manager.reload()
```

### 5. TenantManager 改造

```python
# mini_router/tenant/manager.py 改造要点

class TenantManager:
    """租户管理器"""

    def __init__(
        self,
        repository: ConfigRepository | None = None,
        yaml_path: str = "config/tenants.yaml",
    ) -> None:
        self.repository = repository  # 数据库存储时使用
        self.yaml_path = yaml_path    # YAML 存储时使用
        self._tenants: dict[str, TenantConfig] = {}
        self._apikey_index: dict[str, str] = {}
        self._apikey_pool: dict[str, list[str]] = {}

    def load(self) -> None:
        """加载租户配置"""
        if self.repository:
            # 从数据库加载
            self._load_from_db()
        else:
            # 从 YAML 加载
            self._load_from_yaml()

    async def reload(self) -> None:
        """重新加载租户配置（轮询检测变化后调用）"""
        self._tenants.clear()
        self._apikey_index.clear()
        self._apikey_pool.clear()
        self.load()
        logger.info("tenant_config_reloaded", count=len(self._tenants))

    async def _load_from_db(self) -> None:
        """从数据库加载租户"""
        tenants = await self.repository.get_all_tenants()
        for t in tenants:
            tenant = TenantConfig(**t)
            self._tenants[tenant.tenant_id] = tenant
            self._apikey_index[tenant.apikey] = tenant.tenant_id
            # 加载 API Key 池
            pool = await self.repository.get_apikey_pool(tenant.tenant_id)
            self._apikey_pool[tenant.tenant_id] = [k["apikey"] for k in pool if k["is_active"]]
```

---

## 数据流

### 启动流程

```
server.py main()
│
├── 1. 加载配置文件
│   ├── 获取 MINI_ROUTER_ENV 环境变量（默认 dev）
│   ├── 加载 config/config_{env}.yaml
│   └── 获取 MINI_ROUTER_DB_ACCESS 环境变量（去掉 "BEE_" 前缀）
│
├── 2. 初始化数据库（如果 enabled=true）
│   ├── 创建 DatabaseConnection
│   ├── connect() 创建连接池
│   └── 创建 ConfigRepository
│
├── 3. 初始化 TenantManager
│   ├── 如果 database.enabled: 从 repository 加载
│   ├── 否则: 从 YAML 加载
│
├── 4. 初始化 Router
│   ├── 如果 database.enabled: 从 repository 加载全局配置
│   ├── 否则: 从 YAML 加载
│
├── 5. 初始化 ConfigSyncService（如果 database.enabled）
│   ├── 获取轮询间隔环境变量
│   ├── start() 启动轮询任务
│
└── 6. 启动 FastAPI 服务
```

### 运行时配置更新

```
客户端调用 PUT /v1/tenants/{tenant_id}
│
├── TenantManager.update()
│   ├── repository.update_tenant() → 更新数据库
│   └── version++ 自动触发（ON UPDATE CURRENT_TIMESTAMP）
│
└── 其他实例轮询检测
    ├── _poll_tenant_loop() 检测 version 变化
    └── tenant_manager.reload() → 全量重载所有租户
```

### 关闭流程

```
server shutdown
│
├── ConfigSyncService.stop()
├── DatabaseConnection.close()
└── uvicorn shutdown
```

---

## API 变化

### 租户 CRUD API（不变）

| API | 说明 |
|-----|-----|
| `GET /v1/tenants` | 列出所有租户 |
| `GET /v1/tenants/{tenant_id}` | 获取单个租户 |
| `POST /v1/tenants` | 创建租户 |
| `PUT /v1/tenants/{tenant_id}` | 更新租户 |
| `DELETE /v1/tenants/{tenant_id}` | 删除租户 |

**变化点：**
- TenantManager 内部从 YAML 操作改为 repository 操作
- API 接口和响应格式不变

### 新增 API（可选）

| API | 说明 |
|-----|-----|
| `GET /v1/config` | 获取全局配置（已存在） |
| `PUT /v1/config` | 更新全局配置（新增，可选） |

---

## 迁移方案

### 1. 数据库初始化

```sql
-- 执行建表 SQL
CREATE TABLE mini_router_config ...;
CREATE TABLE mini_router_tenant ...;
CREATE TABLE mini_router_apikey_pool ...;

-- 插入初始全局配置
INSERT INTO mini_router_config (config_data, version)
VALUES ('{"server":..., "models":..., "decisions":...}', 1);
```

### 2. 现有 YAML 配置迁移

```bash
# 迁移脚本：yaml_to_mysql.py
python scripts/yaml_to_mysql.py --config config.yaml --tenants config/tenants.yaml
```

迁移脚本逻辑：
1. 读取 config.yaml → 解析 JSON → INSERT 到 mini_router_config
2. 读取 tenants.yaml → 遍历租户 → INSERT 到 mini_router_tenant
3. 遍历 apikey_pool → INSERT 到 mini_router_apikey_pool

---

## 依赖变更

```toml
# pyproject.toml 新增
dependencies = [
    # ... 现有依赖
    "aiomysql>=0.2.0",  # 异步 MySQL 连接池
]
```

---

## 测试计划

### 单元测试

| 测试模块 | 测试内容 |
|---------|---------|
| `test_database_config.py` | DatabaseConfig 加载、环境变量解析 |
| `test_database_connection.py` | 连接池创建/关闭、execute/fetch 操作 |
| `test_config_repository.py` | CRUD 操作、版本号更新 |
| `test_config_sync.py` | 轮询逻辑、版本检测、reload 触发 |

### 集成测试

| 测试场景 | 验证内容 |
|---------|---------|
| 启动加载 | database.enabled=true/false 两种模式启动 |
| CRUD API | 创建/更新/删除租户，数据库持久化验证 |
| 配置同步 | 多实例轮询检测、reload 触发、内存一致性 |
| fallback | API Key 降级、is_active 状态更新 |

---

## 风险点

| 风险 | 缓解措施 |
|-----|---------|
| 数据库连接失败 | 优雅降级到 YAML 模式或启动失败（取决于配置） |
| 轮询数据库压力大 | 轮询间隔可配置，租户数少时开销可控 |
| 配置同步延迟 | 最多 10 秒延迟，可接受；紧急场景可手动触发 reload API |
| API Key 池顺序问题 | apikey_order 唯一约束保证顺序一致性 |

---

## 参考代码

参考 CoPaw 项目的数据库实现：
- `src/swe/database/connection.py` - 连接池管理
- `src/swe/database/config.py` - 数据库配置
- `src/swe/utils/tools.py` - 密码加密（空函数，使用前缀方式）

**改动说明：**
- 删除 TDSQL 别名（mini-router 无历史包袱）
- 改用 structlog 日志框架
- 环境变量命名改为 `MINI_ROUTER_*`