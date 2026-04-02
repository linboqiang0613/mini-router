# 多租户 API Key 认证与路由设计

## 概述

为 mini-router 添加多租户支持，实现：
1. 调用方通过 `Authorization` Header 传递 apikey
2. Router 验证 apikey 并识别租户身份
3. 不同租户使用独立的路由决策规则
4. Router 调用大模型时透传租户的 apikey

## 需求总结

| 决策项 | 选择 |
|--------|------|
| apikey 用途 | 身份验证 + 透传大模型 |
| 传递方式 | HTTP Header `Authorization: Bearer <apikey>` |
| 路由隔离 | 每租户独立 decisions |
| 配置管理 | 运行时 API + 文件持久化 |
| 存储格式 | YAML 文件 |
| URL 模式 | 动态模板 `{model}` 占位符 |

## 数据模型

### 租户配置文件

存储位置：`config/tenants.yaml`

```yaml
tenants:
  - tenant_id: "tenant-a"
    apikey: "sk-tenant-a-xxx"
    name: "租户A"
    enabled: true
    base_url_template: "http://open-llm.com/llm/{model}/v1"
    timeout: 120.0
    decisions:
      - name: "route_to_code_model"
        priority: 10
        rules:
          type: "keyword"
          name: "code_related"
        model_refs:
          - model: "codellama-70b"
            weight: 1.0
      - name: "default_route"
        priority: 0
        rules:
          type: "or"
          children: [...]
        model_refs:
          - model: "qwen3.5-plus"
            weight: 1.0
```

### Pydantic 模型定义

```python
class TenantConfig(BaseModel):
    tenant_id: str
    apikey: str
    name: str | None = None
    enabled: bool = True
    base_url_template: str  # 例如: "http://open-llm.com/llm/{model}/v1"
    timeout: float = 120.0
    decisions: list[Decision] = Field(default_factory=list)
```

### URL 生成逻辑

```python
def build_base_url(template: str, model: str) -> str:
    return template.replace("{model}", model)
```

示例：
- 模板：`http://open-llm.com/llm/{model}/v1`
- 选中模型：`codellama-70b`
- 实际 URL：`http://open-llm.com/llm/codellama-70b/v1/chat/completions`

## 请求处理流程

```
请求到达 /v1/chat/completions
         │
         ▼
┌─────────────────────┐
│ 提取 Authorization   │
│ Header 中的 apikey   │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ 根据 apikey 查找租户  │
│ (TenantManager)      │
└─────────────────────┘
         │
    ┌────┴────┐
    ▼         ▼
 未找到      找到
    │         │
    ▼         ▼
返回 401   检查 enabled
 Unauthorized    │
            ┌────┴────┐
            ▼         ▼
          已禁用     已启用
            │         │
            ▼         ▼
        返回 403   继续处理
        Forbidden    │
                     ▼
              ┌─────────────────┐
              │ 使用租户的       │
              │ decisions 路由   │
              └─────────────────┘
                     │
                     ▼
              ┌─────────────────┐
              │ 选定模型后，     │
              │ 构建实际 URL     │
              │ base_url_template│
              └─────────────────┘
                     │
                     ▼
              ┌─────────────────┐
              │ 调用大模型 API   │
              │ 透传 apikey      │
              └─────────────────┘
```

## 租户管理 API

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/tenants` | 列出所有租户 |
| GET | `/v1/tenants/{tenant_id}` | 获取单个租户详情 |
| POST | `/v1/tenants` | 创建租户 |
| PUT | `/v1/tenants/{tenant_id}` | 更新租户配置 |
| DELETE | `/v1/tenants/{tenant_id}` | 删除租户 |

### 创建租户请求示例

```bash
POST /v1/tenants
Content-Type: application/json

{
  "tenant_id": "tenant-c",
  "apikey": "sk-tenant-c-xxx",
  "name": "租户C",
  "enabled": true,
  "base_url_template": "http://open-llm.com/llm/{model}/v1",
  "timeout": 120.0,
  "decisions": [
    {
      "name": "default_route",
      "priority": 0,
      "rules": {"type": "or", "children": [...]},
      "model_refs": [{"model": "qwen3.5-plus", "weight": 1.0}]
    }
  ]
}
```

### 更新租户请求示例

```bash
PUT /v1/tenants/tenant-c
Content-Type: application/json

{
  "name": "租户C-更新",
  "enabled": false,
  "timeout": 60.0
}
```

### TenantManager 组件

```python
class TenantManager:
    def __init__(self, config_path: str = "config/tenants.yaml"):
        self.config_path = config_path
        self._tenants: dict[str, TenantConfig] = {}  # tenant_id -> TenantConfig
        self._apikey_index: dict[str, str] = {}      # apikey -> tenant_id

    def load(self) -> None: ...
    def save(self) -> None: ...
    def get_by_apikey(self, apikey: str) -> TenantConfig | None: ...
    def get_by_id(self, tenant_id: str) -> TenantConfig | None: ...
    def list_all(self) -> list[TenantConfig]: ...
    def create(self, tenant: TenantConfig) -> None: ...
    def update(self, tenant_id: str, updates: dict) -> TenantConfig | None: ...
    def delete(self, tenant_id: str) -> bool: ...
```

## 错误处理

### 错误响应格式

```json
{
  "error": {
    "type": "authentication_error",
    "message": "Invalid or missing API key",
    "code": "invalid_api_key"
  }
}
```

### 错误场景

| 场景 | HTTP 状态码 | 错误类型 | 说明 |
|------|------------|----------|------|
| 缺少 Authorization Header | 401 | `authentication_error` | 请求未携带 apikey |
| apikey 无效（未找到租户） | 401 | `authentication_error` | apikey 不在租户列表中 |
| 租户已禁用 | 403 | `permission_denied` | 租户存在但 enabled=false |
| 无匹配的决策规则 | 404 | `routing_error` | 租户配置中没有匹配的 decision |
| 大模型 API 调用失败 | 502 | `upstream_error` | 透传上游错误信息 |
| 租户配置文件损坏 | 500 | `internal_error` | YAML 解析失败等 |

### 全局配置兼容

在 `config.yaml` 中可选配置默认租户：

```yaml
default_tenant:
  apikey: null  # 无需认证
  base_url_template: "http://open-llm.com/llm/{model}/v1"
  decisions: [...]
```

- 若配置了 `default_tenant`：无 apikey 时使用默认租户
- 若未配置：无 apikey 直接返回 401

## 文件结构变更

### 新增文件

```
mini_router/
├── tenant/
│   ├── __init__.py
│   ├── manager.py      # TenantManager 类
│   └── types.py        # TenantConfig 等类型定义
└── config/
    └── tenants.yaml    # 租户配置文件
```

### 需修改的现有文件

| 文件 | 变更内容 |
|------|----------|
| `server.py` | 添加认证中间件、租户管理 API 端点 |
| `proxy/chat_proxy.py` | 从请求提取 apikey、使用租户配置路由、动态构建 URL |
| `client/openai_client.py` | 支持每次调用时动态传入 base_url 和 api_key |
| `router/router.py` | 支持传入租户的 decisions 进行路由 |

### OpenAIClient 接口变更

```python
# 改造后
class OpenAIClient:
    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout
        self.client = httpx.AsyncClient(...)

    async def chat_completion(
        self,
        base_url: str,           # 每次调用传入
        api_key: str,            # 每次调用传入
        model: str,
        messages: list[dict],
        **kwargs,
    ) -> dict[str, Any]:
        ...

    async def chat_completion_stream(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        **kwargs,
    ) -> AsyncGenerator[dict[str, Any], None]:
        ...
```

### Router 接口变更

```python
class Router:
    async def route(
        self,
        request: RoutingRequest,
        decisions: list[Decision] | None = None,  # 可覆盖默认 decisions
    ) -> RoutingResult:
        actual_decisions = decisions or self.config.decisions
        ...
```

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         调用方                                   │
│         Authorization: Bearer sk-tenant-a-xxx                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Server                              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 认证中间件                                                  │ │
│  │ 1. 提取 Authorization Header                               │ │
│  │ 2. TenantManager.get_by_apikey()                           │ │
│  │ 3. 验证租户状态                                             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ ChatProxy                                                   │ │
│  │ 1. 提取 query from messages                                │ │
│  │ 2. Router.route(decisions=tenant.decisions)                │ │
│  │ 3. build_base_url(tenant.base_url_template, model)         │ │
│  │ 4. OpenAIClient.chat_completion(base_url, api_key, ...)    │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      TenantManager                               │
│  - load() / save() 持久化到 config/tenants.yaml                 │
│  - get_by_apikey() 查找租户                                      │
│  - CRUD 操作                                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    外部大模型 API                                 │
│         http://open-llm.com/llm/{model}/v1/chat/completions     │
└─────────────────────────────────────────────────────────────────┘
```