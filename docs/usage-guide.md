# Mini-Router 使用指南

本文档说明如何安装、配置和启动 mini-router 服务。

---

## 一、安装

### 1.1 从源码安装

```bash
# 进入项目目录
cd src/mini-router-python

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
# usage: mini-router-server [-h] [--host HOST] [--port PORT] [--config CONFIG] [--reload]
#
# Mini-Router HTTP Server
#
# options:
#   --host HOST     Host to bind to
#   --port PORT     Port to bind to
#   --config CONFIG Path to config file (YAML)
#   --reload        Enable auto-reload for development
```

---

## 二、配置本地模型

### 2.1 配置文件结构

Mini-Router 使用 YAML 配置文件，主要包含以下部分：

```yaml
# 服务配置
server:
  host: "0.0.0.0"
  port: 8080

# 模型配置 - 连接本地部署的 LLM
models:
  base_url: "http://localhost:8000/v1"  # 本地模型 API 地址
  api_key: ""                            # 本地部署通常无需 API Key
  timeout: 120.0

  # 分类器配置 (用于信号层)
  classifier:
    intent:
      model: "local-model"    # 使用本地模型进行意图分类
      enabled: true
    complexity:
      model: "local-model"
      enabled: true
    pii:
      model: "local-model"
      enabled: true
    security:
      model: "local-model"
      enabled: true

# 信号规则 (关键词匹配)
signals:
  keyword_rules:
    - name: "code_related"
      keywords: ["code", "python", "debug"]
      operator: "any"
      case_sensitive: false

# 决策规则 (路由策略)
decisions:
  - name: "route_to_code_model"
    priority: 10
    rules:
      type: "keyword"
      name: "code_related"
    model_refs:
      - model: "codellama"
        weight: 1.0

# 模型选择策略
selection:
  strategy: "latency_aware"  # 或 priority, weighted

# 缓存配置
cache:
  enabled: true
  max_entries: 10000
```

### 2.2 本地模型部署方式

Mini-Router 需要连接一个 OpenAI-compatible API。以下是几种常见的本地部署方式：

#### 方式一：使用 vLLM

```bash
# 安装 vLLM
pip install vllm

# 启动 vLLM 服务 (OpenAI-compatible API)
vllm serve meta-llama/Llama-3-8b \
  --host 0.0.0.0 \
  --port 8000 \
  --api-key token-abc123

# 配置 mini-router 连接
models:
  base_url: "http://localhost:8000/v1"
  api_key: "token-abc123"
```

#### 方式二：使用 Ollama

```bash
# 安装 Ollama (macOS/Linux)
# 参考: https://ollama.ai

# 拉取模型
ollama pull llama3

# Ollama 默认在 localhost:11434 提供 API
# 但需要 OpenAI-compatible 适配层
```

#### 方式三：使用 LM Studio

LM Studio 提供本地模型服务，默认端口 1234：

```yaml
models:
  base_url: "http://localhost:1234/v1"
  api_key: ""
```

#### 方式四：使用推理框架 (TGI, TensorRT-LLM 等)

```bash
# TGI 示例
text-generation-launcher \
  --model-id meta-llama/Llama-3-8b \
  --port 8000

# 配置
models:
  base_url: "http://localhost:8000/v1"
```

### 2.3 完整配置示例 (本地部署)

创建配置文件 `config/local.yaml`：

```yaml
# 本地部署配置示例
server:
  host: "0.0.0.0"
  port: 8080

models:
  # 连接本地 vLLM/Ollama/LM Studio 服务
  base_url: "http://localhost:8000/v1"
  api_key: ""
  timeout: 120.0

  classifier:
    # 使用本地模型进行分类
    # 如果模型名称与实际部署不一致，请修改
    intent:
      model: "llama-3-8b"
      enabled: true
    complexity:
      model: "llama-3-8b"
      enabled: true
    pii:
      model: "llama-3-8b"
      enabled: false  # 可关闭部分分类器以减少延迟
    security:
      model: "llama-3-8b"
      enabled: false

  embedder:
    model: "text-embedding"
    enabled: false  # 语义缓存需要嵌入模型

signals:
  keyword_rules:
    - name: "code_related"
      keywords: ["code", "programming", "function", "debug", "error", "python", "java", "golang"]
      operator: "any"
      case_sensitive: false

    - name: "math_related"
      keywords: ["calculate", "math", "equation", "solve", "compute"]
      operator: "any"
      case_sensitive: false

    - name: "simple_query"
      keywords: ["what is", "hello", "hi", "thanks"]
      operator: "any"
      case_sensitive: false

decisions:
  # 代码相关问题路由到代码模型
  - name: "route_to_code_model"
    priority: 10
    rules:
      type: "keyword"
      name: "code_related"
    model_refs:
      - model: "codellama-70b"
        weight: 1.0
      - model: "llama-3-8b"
        weight: 0.5

  # 数学问题路由到数学模型
  - name: "route_to_math_model"
    priority: 5
    rules:
      type: "keyword"
      name: "math_related"
    model_refs:
      - model: "llama-3-8b"
        weight: 1.0

  # 简单问题使用轻量模型
  - name: "route_simple_query"
    priority: 3
    rules:
      type: "keyword"
      name: "simple_query"
    model_refs:
      - model: "llama-3-8b"
        weight: 1.0

  # 兜底路由
  - name: "default_route"
    priority: 1
    rules:
      type: "or"
      children:
        - type: "keyword"
          name: "code_related"
        - type: "keyword"
          name: "math_related"
    model_refs:
      - model: "llama-3-8b"
        weight: 1.0

selection:
  strategy: "latency_aware"
  latency_aware:
    tpot_percentile: 50
    ttft_percentile: 90
    min_observations: 3
    fallback_to_weight: true
    weight_blend: 0.3

cache:
  enabled: true
  similarity_threshold: 0.95
  max_entries: 10000
```

---

## 三、启动服务

### 3.1 使用默认配置启动

```bash
# 默认监听 0.0.0.0:8080
mini-router-server

# 或指定端口
mini-router-server --port 9000
```

### 3.2 使用配置文件启动

```bash
# 使用本地配置
mini-router-server --config config/local.yaml

# 开发模式 (自动重载)
mini-router-server --config config/local.yaml --reload
```

### 3.3 直接运行模块

```bash
# 不安装直接运行
python -m mini_router.server --config config.yaml

# 或使用 uvicorn
uvicorn mini_router.server:app --host 0.0.0.0 --port 8080
```

---

## 四、测试接口

服务启动后，可通过以下方式测试：

### 4.1 健康检查

```bash
curl http://localhost:8080/healthz
# {"status": "healthy", "version": "0.1.0"}

curl http://localhost:8080/readyz
# {"status": "ready", "version": "0.1.0"}
```

### 4.2 路由决策

```bash
# 只获取路由决策，不调用模型
curl -X POST http://localhost:8080/v1/route \
  -H "Content-Type: application/json" \
  -d '{"query": "写一个 Python 函数计算斐波那契数列"}'

# 响应:
# {
#   "selected_model": "codellama-70b",
#   "decision_name": "route_to_code_model",
#   "matched_rules": ["code_related"],
#   "confidence": 0.8,
#   "cache_hit": false,
#   "action": "route"
# }
```

### 4.3 Chat Completions (流式)

```bash
# 流式调用 - 自动路由并调用模型
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello, how are you?"}],
    "stream": true
  }'

# SSE 流式响应:
# data: {"id":"chatcmpl-xxx","model":"llama-3-8b","choices":[{"delta":{"content":"Hello"}}]}
# data: {"id":"chatcmpl-xxx","model":"llama-3-8b","choices":[{"delta":{"content":"!"}}]}
# data: [DONE]
```

### 4.4 Chat Completions (非流式)

```bash
# 非流式调用
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is 2+2?"}],
    "stream": false
  }'

# JSON 响应:
# {
#   "id": "chatcmpl-xxx",
#   "model": "llama-3-8b",
#   "choices": [{"message": {"content": "The answer is 4"}}]
# }
```

### 4.5 查看延迟统计

```bash
# 查看所有模型延迟
curl http://localhost:8080/v1/latency

# 查看特定模型延迟
curl http://localhost:8080/v1/latency/llama-3-8b
```

### 4.6 手动上报延迟

如果使用 `/v1/route` 模式（只返回路由决策，不调用模型），需要手动上报延迟：

```bash
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "model": "codellama-70b",
    "latency_seconds": 1.5,
    "tpot": 0.05,
    "ttft": 0.3
  }'
```

---

## 五、API 端点列表

| 端点 | 方法 | 说明 |
|------|------|------|
| `/healthz` | GET | 健康检查 |
| `/readyz` | GET | 就绪检查 |
| `/v1/route` | POST | 路由决策（不调用模型） |
| `/v1/chat/completions` | POST | OpenAI-compatible Chat（流式/非流式） |
| `/v1/feedback` | POST | 上报延迟反馈 |
| `/v1/latency` | GET | 获取所有模型延迟统计 |
| `/v1/latency/{model}` | GET | 获取特定模型延迟统计 |
| `/v1/config` | GET | 获取当前配置 |
| `/v1/cache` | POST | 设置缓存条目 |
| `/v1/cache` | DELETE | 清空缓存 |

---

## 六、常见问题

### Q1: 本地模型名称如何确定？

模型名称需要与实际部署的 API 返回的模型名称一致。可以通过以下方式查询：

```bash
curl http://localhost:8000/v1/models
```

返回的 `id` 字段即为模型名称。

### Q2: 分类器延迟过高怎么办？

分类器调用会增加路由延迟（100-500ms）。可以：
1. 禁用部分分类器（设置 `enabled: false`）
2. 使用更轻量的分类模型
3. 仅依赖关键词规则进行快速路由

### Q3: 如何关闭语义缓存？

```yaml
cache:
  enabled: false
```

或使用精确缓存（Memory Cache）而非语义缓存。

### Q4: latency_aware 策略无数据怎么办？

配置 `fallback_to_weight: true`，在无延迟数据时回退到权重选择：

```yaml
selection:
  strategy: "latency_aware"
  latency_aware:
    fallback_to_weight: true
    min_observations: 3
```

---

## 七、开发调试

### 7.1 运行单元测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/unit/test_router.py

# 带覆盖率
pytest --cov=mini_router tests/
```

### 7.2 运行 Demo

```bash
# CLI demo
mini-router

# 或
python -m mini_router.cli
```

### 7.3 代码风格检查

```bash
# Ruff lint
ruff check mini_router/

# 自动修复
ruff check --fix mini_router/

# 类型检查
mypy mini_router/
```