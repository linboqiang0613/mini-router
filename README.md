# Mini-Router (Python)

Python 实现的 vLLM Semantic Router 核心组件。

## 概述

Mini-router 实现了 Signal-Decision-Algorithm-Plugin 四层架构，提供轻量级的路由实现，支持 OpenAI 兼容 API 的模型集成。

**这是一个完全独立的包，不依赖父项目 (semantic-router) 的任何代码。**

## 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Router                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Signal Layer (mini_router/signal_layer/)                 │  │
│  │  • KeywordClassifier - 关键词规则匹配                      │  │
│  │  • MLClassifier - Intent/PII/Security 分类 (OpenAI API)   │  │
│  │  • Embedder - 语义嵌入生成                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              ↓                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Decision Layer (mini_router/decision/)                   │  │
│  │  • Engine - 布尔规则评估 (AND/OR/NOT)                      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              ↓                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Algorithm Layer (mini_router/algorithm/)                 │  │
│  │  • StaticSelector - 权重模型选择                           │  │
│  │  • RoundRobinSelector - 轮询模型选择                       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              ↓                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Plugin Layer (mini_router/plugin/)                       │  │
│  │  • MemoryCache - 内存缓存                                  │  │
│  │  • SemanticCache - 语义相似度缓存                          │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## 安装

```bash
cd src/mini-router-python
pip install -e ".[dev]"
```

## 快速开始

### 1. 启动 HTTP 服务

```bash
# 启动服务 (默认端口 8080)
mini-router-server

# 指定端口和配置文件
mini-router-server --port 8080 --config config.yaml

# 开发模式 (自动重载)
mini-router-server --reload

# 查看帮助
mini-router-server --help
```

### 2. 调用 API

```bash
# 路由请求
curl -X POST http://localhost:8080/v1/route \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I debug this code?"}'

# 响应示例
# {
#   "selected_model": "codellama-70b",
#   "decision_name": "route_to_code_model",
#   "matched_rules": ["code_related"],
#   "confidence": 0.56,
#   "cache_hit": false,
#   "action": "route"
# }

# 健康检查
curl http://localhost:8080/healthz

# 设置缓存
curl -X POST http://localhost:8080/v1/cache \
  -H "Content-Type: application/json" \
  -d '{"query": "What is 2+2?", "response": "The answer is 4"}'

# 清除缓存
curl -X DELETE http://localhost:8080/v1/cache

# 查看配置
curl http://localhost:8080/v1/config
```

### 3. 运行 Demo

```bash
# 安装后直接运行
mini-router

# 或者
python -m mini_router.cli
```

### 4. 编程使用

```python
import asyncio

from mini_router.config.config import (
    Decision, KeywordRule, ModelRef, Operator,
    RouterConfig, RuleNode, RuleType
)
from mini_router.router.router import Router, RoutingRequest


async def main():
    # 创建配置
    config = RouterConfig(
        models={
            "base_url": "http://localhost:8000/v1",  # 模型服务地址
            "classifier": {
                "intent": {"model": "intent-classifier", "enabled": True},
                "pii": {"model": "pii-classifier", "enabled": True},
                "security": {"model": "security-classifier", "enabled": True},
            },
        },
        signals={
            "keyword_rules": [
                KeywordRule(
                    name="code_related",
                    keywords=["code", "debug", "programming"],
                    operator=Operator.ANY,
                    case_sensitive=False,
                ),
            ],
        },
        decisions=[
            Decision(
                name="route_to_code_model",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
                model_refs=[
                    ModelRef(model="codellama-70b", weight=1.0),
                ],
            ),
        ],
        cache={"enabled": True},
    )

    # 创建路由器
    router = Router(config)

    # 路由请求
    result = await router.route(RoutingRequest(query="How do I debug this code?"))

    print(f"Selected Model: {result.selected_model}")
    print(f"Decision: {result.decision_name}")
    print(f"Confidence: {result.confidence}")


asyncio.run(main())
```

## 配置说明

### 模型配置

```python
models={
    "base_url": "http://localhost:8000/v1",  # OpenAI 兼容 API 地址
    "api_key": "",  # API Key (本地部署可留空)
    "classifier": {
        "intent": {"model": "intent-classifier", "enabled": True},
        "pii": {"model": "pii-classifier", "enabled": False},
        "security": {"model": "security-classifier", "enabled": False},
    },
    "embedder": {"model": "text-embedding-model", "enabled": True},
}
```

### 关键词规则

```python
keyword_rules=[
    KeywordRule(
        name="code_related",           # 规则名称
        keywords=["code", "debug"],    # 关键词列表
        operator=Operator.ANY,         # ANY: 任一匹配, ALL: 全部匹配
        case_sensitive=False,          # 是否区分大小写
    ),
]
```

### 决策规则

```python
decisions=[
    # 简单规则
    Decision(
        name="route_to_code_model",
        priority=10,  # 优先级，数字越大越先评估
        rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
        model_refs=[ModelRef(model="codellama-70b", weight=1.0)],
    ),

    # 复合规则 (AND)
    Decision(
        name="code_and_debug",
        priority=20,
        rules=RuleNode(
            type=RuleType.AND,
            children=[
                RuleNode(type=RuleType.KEYWORD, name="code"),
                RuleNode(type=RuleType.KEYWORD, name="debug"),
            ],
        ),
        model_refs=[ModelRef(model="code-debug-model", weight=1.0)],
    ),

    # 复合规则 (OR)
    Decision(
        name="code_or_math",
        priority=15,
        rules=RuleNode(
            type=RuleType.OR,
            children=[
                RuleNode(type=RuleType.KEYWORD, name="code_related"),
                RuleNode(type=RuleType.KEYWORD, name="math_related"),
            ],
        ),
        model_refs=[ModelRef(model="general-model", weight=1.0)],
    ),

    # 信号规则 (PII/Security)
    Decision(
        name="block_pii",
        priority=100,
        rules=RuleNode(type=RuleType.SIGNAL, signal="pii", condition="detected"),
        action=DecisionAction.REJECT,
        reject_message="PII detected in request",
    ),
]
```

### 缓存配置

```python
cache={
    "enabled": True,
    "similarity_threshold": 0.95,  # 语义缓存相似度阈值
    "max_entries": 10000,          # 最大缓存条目数
}
```

## 运行测试

```bash
cd src/mini-router-python
python -m pytest tests/unit/ -v
```

## 项目结构

```
src/mini-router-python/
├── mini_router/              # 主包
│   ├── __init__.py
│   ├── cli.py                # CLI 入口 / Demo
│   ├── server.py             # HTTP API 服务
│   ├── config/
│   │   └── config.py         # 配置类型定义
│   ├── signal_layer/
│   │   ├── classifier.py     # 分类器实现
│   │   ├── embedder.py       # 嵌入器实现
│   │   └── types.py          # 信号类型
│   ├── decision/
│   │   ├── engine.py         # 决策引擎
│   │   └── types.py          # 决策类型
│   ├── algorithm/
│   │   ├── selector.py       # 模型选择器
│   │   └── types.py          # 选择类型
│   ├── plugin/
│   │   └── cache.py          # 缓存实现
│   └── router/
│       └── router.py         # 主路由
├── tests/
│   ├── conftest.py           # Pytest 配置
│   └── unit/                 # 单元测试
├── pyproject.toml
└── README.md
```

## HTTP API 接口

### 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/healthz` | 健康检查 |
| GET | `/readyz` | 就绪检查 |
| POST | `/v1/route` | 路由请求 |
| POST | `/v1/cache` | 设置缓存 |
| DELETE | `/v1/cache` | 清除缓存 |
| GET | `/v1/config` | 获取配置 |

### POST /v1/route

**请求体:**
```json
{
  "query": "How do I debug this code?",
  "user_id": "user-123",        // 可选
  "metadata": {}                // 可选
}
```

**响应:**
```json
{
  "selected_model": "codellama-70b",
  "decision_name": "route_to_code_model",
  "matched_rules": ["code_related"],
  "confidence": 0.56,
  "cache_hit": false,
  "cache_response": null,
  "action": "route",
  "reject_message": null
}
```

### OpenAPI 文档

服务启动后访问:
- Swagger UI: http://localhost:8080/docs
- ReDoc: http://localhost:8080/redoc
- OpenAPI JSON: http://localhost:8080/openapi.json

## API 参考

### Router

```python
from mini_router.router.router import Router, RoutingRequest

class Router:
    def __init__(self, config: RouterConfig) -> None: ...

    async def route(self, request: RoutingRequest) -> RoutingResult: ...
    async def set_cache(self, query: str, response: str) -> None: ...
    def clear_cache(self) -> None: ...
```

### RoutingRequest

```python
@dataclass
class RoutingRequest:
    query: str                    # 用户查询
    user_id: str | None = None    # 用户 ID (可选)
    metadata: dict = {}           # 额外元数据
```

### RoutingResult

```python
@dataclass
class RoutingResult:
    selected_model: str | None    # 选中的模型
    decision_name: str | None     # 匹配的决策名称
    matched_rules: list[str]      # 匹配的规则列表
    confidence: float             # 置信度
    cache_hit: bool               # 是否命中缓存
    cache_response: str | None    # 缓存响应
    signals: SignalMatches | None # 信号匹配结果
    action: DecisionAction        # 动作类型 (route/reject)
    reject_message: str | None    # 拒绝消息
```

## 与 Go 版本的对比

| 特性 | Go 版本 | Python 版本 |
|------|---------|-------------|
| 关键词分类 | ✓ | ✓ |
| ML 分类 (Intent/PII/Security) | Rust Candle | OpenAI API |
| 语义缓存 | ✓ | ✓ |
| 规则引擎 (AND/OR/NOT) | ✓ | ✓ |
| 模型选择 (Static/RoundRobin) | ✓ | ✓ |
| HTTP API | ✓ | ✓ |
| Envoy ExtProc gRPC | ✓ | ✗ (规划中) |

## 下一步

1. **添加 YAML 配置文件支持**: 从配置文件加载 RouterConfig
2. **Envoy ExtProc gRPC**: 实现与 Envoy 的集成
3. **更多选择策略**: KNN, Latency-aware 等选择算法
4. **可观测性**: Prometheus 指标、结构化日志