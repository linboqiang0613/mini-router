# Mini-Router 使用指南

本文档说明如何安装、配置和启动 mini-router 服务。

---

## 一、安装

### 1.1 从源码安装

```bash
# 进入项目目录
cd mini-router

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .venv\Scripts\activate  # Windows

# 安装依赖
pip install -e .

# 或安装开发依赖
pip install -e ".[dev]"
```

安装后会生成两个命令行工具：
- `mini-router` - 运行 CLI demo
- `mini-router-server` - 启动 HTTP 服务

### 1.2 验证安装

```bash
# 查看帮助
mini-router-server --help

# 输出:
# usage: mini-router-server [-h] [--host HOST] [--port PORT] [--config CONFIG] [--env ENV]
#
# Mini-Router HTTP Server
#
# options:
#   --host HOST     Host to bind to
#   --port PORT     Port to bind to
#   --config CONFIG Path to config YAML file. If provided, uses YAML mode.
#                   If empty (default), uses database mode with config sync.
#   --env ENV       Environment for database mode (dev/prd). Default: dev.
#                   Ignored if --config is provided.
```

---

## 二、启动模式

Mini-Router 支持两种启动模式：

| 模式 | 配置来源 | 适用场景 | 多实例支持 |
|------|----------|----------|------------|
| **YAML 模式** | 本地 YAML 文件 | 开发调试、单实例部署 | ❌ |
| **数据库模式** | MySQL 数据库 | 生产环境、多实例部署 | ✅ |

### 2.1 YAML 模式（单实例）

使用 `--config` 参数指定配置文件路径，配置从本地 YAML 文件加载：

```bash
# 使用默认配置文件
mini-router-server --config config.yaml

# 使用自定义配置文件
mini-router-server --config my_config.yaml
```

**配置文件结构：**

- `config.yaml` - 全局路由配置（models/signals/decisions/cache）
- `config/tenants.yaml` - 租户配置（apikey/decisions/base_url_template）

**特点：**
- 配置修改需要重启服务
- 不支持多实例部署（配置不一致）
- 适合本地开发调试

### 2.2 数据库模式（多实例）

不指定 `--config` 参数（默认），配置从 MySQL 数据库加载：

```bash
# 设置数据库密码环境变量
export MINI_ROUTER_DB_ACCESS="your_password"
# 或使用 BEE_ 前缀（自动去除）
export MINI_ROUTER_DB_ACCESS="BEE_your_password"

# 启动服务（默认 dev 环境）
mini-router-server

# 或指定生产环境
mini-router-server --env prd
```

**环境配置文件：**

数据库模式使用 `--env` 参数选择环境配置文件：

| 环境 | 配置文件 | 内容 |
|------|----------|------|
| `dev` | `config/envs_dev.yaml` | 数据库连接信息（localhost） |
| `prd` | `config/envs_prd.yaml` | 数据库连接信息（生产服务器） |

**配置文件示例（envs_prd.yaml）：**

```yaml
# 仅包含数据库连接配置，不包含路由规则
server:
  host: "0.0.0.0"
  port: 8080

database:
  host: "1.94.232.185"
  port: 3306
  user: "root"
  database: "mini_router"
  min_connections: 2
  max_connections: 10
```

**特点：**
- 支持配置热更新（轮询检测版本变化）
- 多实例部署时配置一致
- 租户配置也从数据库加载
- 数据库连接失败时抛出错误（不回退到 YAML）

### 2.3 环境变量说明

| 环境变量 | 说明 | 示例 |
|----------|------|------|
| `MINI_ROUTER_DB_ACCESS` | 数据库密码，支持 `BEE_` 前缀自动去除 | `BEE_619589959` → `619589959` |

**BEE_ 前缀说明：**
- 兼容 CoPaw 系统的密码格式
- 如果密码以 `BEE_` 开头，会自动去除前缀
- 例如：`BEE_619589959` 实际密码为 `619589959`

### 2.4 使用启动脚本

项目提供了便捷的启动脚本：

**开发环境（YAML 模式）：**

```bash
./scripts/start_dev.sh
# 使用 config.yaml 配置，不连接数据库
```

**开发环境（数据库模式）：**

```bash
export MINI_ROUTER_DB_ACCESS="your_password"
./scripts/start_dev_db.sh
# 连接 localhost 数据库
```

**生产环境（数据库模式）：**

```bash
export MINI_ROUTER_DB_ACCESS="BEE_your_password"
./scripts/start_prd.sh
# 连接生产数据库，使用 envs_prd.yaml 配置
```

---

## 三、数据库配置说明

### 3.1 数据库表结构

数据库模式使用以下表存储配置：

| 表名 | 说明 |
|------|------|
| `mini_router_config` | 全局路由配置（models/signals/decisions） |
| `mini_router_tenant` | 租户配置（apikey/decisions/base_url_template） |
| `mini_router_apikey_pool` | 租户 API Key 池 |

**初始化脚本：**

```bash
# 连接数据库
mysql -h host -u root -p mini_router

# 执行初始化脚本
source scripts/init_db.sql
```

### 3.2 全局配置表

```sql
CREATE TABLE mini_router_config (
    id INT PRIMARY KEY AUTO_INCREMENT,
    config_data JSON NOT NULL,  -- RouterConfig JSON
    version INT DEFAULT 1,      -- 版本号，每次更新自增
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

**config_data 示例：**

```json
{
  "models": {
    "base_url": "https://api.example.com/v1",
    "timeout": 120.0,
    "classifier": {...}
  },
  "signals": {"keyword_rules": [...]},
  "decisions": [...],
  "selection": {"strategy": "latency_aware"},
  "cache": {"enabled": true}
}
```

### 3.3 租户配置表

```sql
CREATE TABLE mini_router_tenant (
    tenant_id VARCHAR(64) PRIMARY KEY,
    apikey VARCHAR(128) NOT NULL,
    name VARCHAR(128),
    enabled BOOLEAN DEFAULT TRUE,
    base_url_template VARCHAR(256) NOT NULL,
    timeout FLOAT DEFAULT 120.0,
    apikey_pool_mode VARCHAR(32) DEFAULT 'round_robin',
    decisions JSON,             -- 租户专属路由规则
    version INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### 3.4 API Key 池表

```sql
CREATE TABLE mini_router_apikey_pool (
    tenant_id VARCHAR(64) NOT NULL,
    apikey VARCHAR(128) NOT NULL,
    apikey_order INT NOT NULL,  -- Key 顺序（0=优先）
    is_active BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (tenant_id, apikey_order)
);
```

### 3.5 配置同步机制

数据库模式使用版本号轮询检测配置变化：

| 配置类型 | 轮询间隔 | 说明 |
|----------|----------|------|
| 全局配置 | 120 秒 | 检测 `mini_router_config.version` 变化 |
| 租户配置 | 10 秒 | 检测 `mini_router_tenant.version` 最大值变化 |

当检测到版本变化时，自动重新加载配置，无需重启服务。

---

## 四、API 接口说明

### 4.1 路由决策接口

**POST /v1/route**

获取路由决策，不调用 LLM。支持两种模式：

**无认证（使用全局配置）：**

```bash
curl -X POST http://localhost:8080/v1/route \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "写一个 Python 函数计算斐波那契数列"}]}'

# 响应:
{
  "selected_model": "qwen3.5-plus",
  "decision_name": "default_route",
  "matched_rules": ["complexity"],
  "confidence": 1.0,
  "action": "route"
}
```

**带认证（使用租户配置）：**

```bash
curl -X POST http://localhost:8080/v1/route \
  -H "Authorization: Bearer sk-tenant-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "写一个 Python 函数计算斐波那契数列"}]}'

# 响应（使用租户专属路由规则）:
{
  "selected_model": "qwen3-max",
  "decision_name": "route_complex_query",
  "matched_rules": ["complexity"],
  "confidence": 1.0,
  "action": "route"
}
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `query` | 用户查询文本 |
| `user_id` | 可选，用户标识 |
| `metadata` | 可选，元数据字典 |

### 4.2 Chat Completions 接口

**POST /v1/chat/completions**

OpenAI-compatible 接口，需要租户认证：

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer sk-tenant-key" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

**认证说明：**

- Authorization header 格式：`Bearer sk-tenant-key`
- 租户 API Key 从 `mini_router_tenant.apikey` 或 `config/tenants.yaml` 加载
- 认证成功后使用租户专属配置（decisions/base_url_template/apikey_pool）

**错误响应：**

| 状态码 | 说明 |
|--------|------|
| 401 | API Key 无效或缺失 |
| 403 | 租户已禁用 |

### 4.3 其他接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/healthz` | GET | 健康检查 |
| `/readyz` | GET | 就绪检查 |
| `/v1/config` | GET | 获取当前路由配置 |
| `/v1/tenants` | GET | 列出所有租户 |
| `/v1/tenants/{id}` | GET | 获取租户详情 |
| `/v1/latency` | GET | 获取延迟统计 |
| `/v1/feedback` | POST | 上报延迟反馈 |

---

## 五、多租户配置

### 5.1 租户专属路由规则

每个租户可以配置独立的 `decisions`，优先级高于全局配置：

**数据库模式（mini_router_tenant.decisions）：**

```json
[
  {"name": "block_pii", "rules": {"type": "signal", "signal": "pii"}, "action": "reject"},
  {"name": "route_complex", "rules": {"type": "signal", "signal": "complexity"}, "model_refs": [{"model": "strong-model"}]},
  {"name": "default", "priority": 0, "model_refs": [{"model": "default-model"}]}
]
```

**YAML 模式（config/tenants.yaml）：**

```yaml
tenants:
  - tenant_id: "tenant-001"
    apikey: "sk-tenant-key"
    base_url_template: "https://api.example.com/llm/{model}/v1"
    decisions:
      - name: "block_pii"
        rules: {type: "signal", signal: "pii"}
        action: "reject"
      - name: "default_route"
        priority: 0
        model_refs:
          - model: "qwen3.5-plus"
            weight: 1.0
```

### 5.2 API Key 池配置

租户可以配置 API Key 池用于调用 LLM：

**数据库模式：**

```sql
INSERT INTO mini_router_apikey_pool VALUES
('tenant-001', 'sk-llm-key-1', 0, TRUE),
('tenant-001', 'sk-llm-key-2', 1, TRUE),
('tenant-001', 'sk-llm-key-3', 2, TRUE);
```

**YAML 模式：**

```yaml
tenants:
  - tenant_id: "tenant-001"
    apikey_pool:
      - "sk-llm-key-1"
      - "sk-llm-key-2"
      - "sk-llm-key-3"
    apikey_pool_mode: "round_robin"  # 或 "fallback"
```

**选择模式说明：**

| 模式 | 行为 |
|------|------|
| `round_robin` | 每次请求轮询切换 Key |
| `fallback` | 优先第一个 Key，429 时降级到下一个 |

---

## 六、端到端测试

### 6.1 运行 E2E 测试

```bash
# 设置数据库密码
export MINI_ROUTER_DB_ACCESS="BEE_619589959"

# 运行测试
source .venv/bin/activate
python scripts/e2e_test.py
```

**测试内容：**

1. 数据库连接
2. 全局配置加载
3. 租户配置加载
4. API Key 池操作
5. 版本追踪
6. 配置重新加载

### 6.2 手动测试

```bash
# 启动服务（数据库模式）
export MINI_ROUTER_DB_ACCESS="your_password"
mini-router-server --env prd

# 测试健康检查
curl http://localhost:8080/healthz

# 测试路由决策（全局）
curl -X POST http://localhost:8080/v1/route \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'

# 测试路由决策（租户）
curl -X POST http://localhost:8080/v1/route \
  -H "Authorization: Bearer sk-tenant-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'

# 测试 Chat Completions
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer sk-tenant-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

---

## 七、常见问题

### Q1: 如何选择启动模式？

| 场景 | 推荐模式 |
|------|----------|
| 本地开发调试 | YAML 模式 (`--config config.yaml`) |
| 单实例部署 | YAML 模式 |
| 多实例部署 | 数据库模式（默认） |
| 需要配置热更新 | 数据库模式 |

### Q2: 数据库连接失败怎么办？

数据库模式下，连接失败会抛出错误并退出服务。请检查：

1. `config/envs_{env}.yaml` 中的数据库地址是否正确
2. `MINI_ROUTER_DB_ACCESS` 环境变量是否设置
3. 数据库是否已创建表结构（执行 `scripts/init_db.sql`）

### Q3: 如何切换数据库环境？

使用 `--env` 参数：

```bash
# 开发环境（localhost）
mini-router-server --env dev

# 生产环境
mini-router-server --env prd
```

### Q4: 租户路由规则不生效？

请确保：

1. `/v1/route` 或 `/v1/chat/completions` 请求携带了正确的 Authorization header
2. 租户的 `apikey` 与 header 中的 Bearer token 匹配
3. 租户的 `enabled` 字段为 `TRUE`

### Q5: 如何更新数据库中的配置？

直接修改数据库表后，更新 `version` 字段：

```sql
-- 更新全局配置
UPDATE mini_router_config 
SET config_data = '...', version = version + 1;

-- 更新租户配置
UPDATE mini_router_tenant 
SET decisions = '...', version = version + 1 
WHERE tenant_id = 'xxx';
```

服务会在下次轮询时自动检测版本变化并重新加载。

---

## 八、开发调试

### 8.1 运行单元测试

```bash
pytest tests/

# 带覆盖率
pytest --cov=mini_router tests/
```

### 8.2 运行 Demo

```bash
mini-router
# 或
python -m mini_router.cli
```

### 8.3 代码风格检查

```bash
ruff check mini_router/
ruff check --fix mini_router/
mypy mini_router/
```
