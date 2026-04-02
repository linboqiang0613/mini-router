# Mini-Router 请求处理流程

本文档详细说明请求到达 mini-router 后的完整处理流程。

## 两种请求模式

### 模式一：路由决策（`POST /v1/route`）

只返回路由决策，不调用模型。

```
用户请求 → Router → 返回选中的模型名
                   ↓
            用户自己调用模型
```

**请求示例：**
```bash
curl -X POST http://localhost:8080/v1/route \
  -H "Content-Type: application/json" \
  -d '{"query": "写一个 Python 函数"}'
```

**响应示例：**
```json
{
  "selected_model": "codellama-70b",
  "decision_name": "route_to_code_model",
  "matched_rules": ["code_related"],
  "confidence": 0.8,
  "cache_hit": false,
  "action": "route"
}
```

### 模式二：代理调用（`POST /v1/chat/completions`）

Router 完成路由 + 调用模型 + 返回结果。

```
用户请求 → Router → 调用模型 → 返回模型响应
```

**请求示例：**
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "写一个 Python 函数"}],
    "stream": true
  }'
```

---

## 完整流程图（代理模式）

```
POST /v1/chat/completions
Authorization: Bearer sk-tenant-001-key
{"messages": [{"role": "user", "content": "写一个 Python 函数"}]}
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  租户认证                                                        │
│                                                                 │
│  1. 提取 API Key: "sk-tenant-001-key"                          │
│  2. 查找租户: TenantManager.get_by_apikey()                    │
│  3. 验证租户状态: enabled = true                                │
│                                                                 │
│  → TenantConfig {tenant_id, base_url_template, decisions, ...}  │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  ChatProxy.chat_stream()                                        │
│                                                                 │
│  1. 提取查询: 从最后一条 user message 提取 "写一个 Python 函数"  │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Router.route() - Signal 层 (使用租户的 decisions)              │
│                                                                 │
│  ┌─────────────────────────────────────────┐                   │
│  │ KeywordClassifier (本地匹配)            │                   │
│  │ - code_related: ["code", "python"] ✓   │                   │
│  │ - math_related: []                      │                   │
│  │ - translation: []                       │                   │
│  └─────────────────────────────────────────┘                   │
│                                                                 │
│  ┌─────────────────────────────────────────┐                   │
│  │ MLClassifier (调用大模型 API)           │                   │
│  │ - complexity: "complex"                 │                   │
│  │ - pii: "none"                           │                   │
│  │ - security: "safe"                      │                   │
│  └─────────────────────────────────────────┘                   │
│                                                                 │
│  ┌─────────────────────────────────────────┐                   │
│  │ ContextLengthClassifier (本地计算)      │                   │
│  │ - token_count: 156                     │                   │
│  │ - label: "short"                       │                   │
│  └─────────────────────────────────────────┘                   │
│                                                                 │
│  → SignalMatches {                                              │
│       keyword_rules: {code_related: true},                      │
│       complexity: "complex",                                    │
│       context_length: {label: "short", token_count: 156},       │
│       pii: false,                                               │
│       security: false                                           │
│     }                                                           │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Decision 层 - Engine.evaluate() (使用租户的 decisions)         │
│                                                                 │
│  按 priority 从高到低评估:                                       │
│                                                                 │
│  priority=100: block_pii                                        │
│    → pii == "detected"? No, 跳过                                │
│                                                                 │
│  priority=99: block_security_threat                             │
│    → security == "detected"? No, 跳过                           │
│                                                                 │
│  priority=90: route_long_context                                │
│    → context_length == "long"? No, 跳过                         │
│                                                                 │
│  priority=50: route_complex_query                               │
│    → complexity == "complex"? Yes! ✓                            │
│                                                                 │
│  → DecisionResult {                                             │
│       decision: route_complex_query,                            │
│       model_refs: [qwen3-max]                                   │
│     }                                                           │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Algorithm 层 - Model Selection                                 │
│                                                                 │
│  1. max_tokens 过滤:                                            │
│     - token_count = 156                                         │
│     - qwen3-max.max_tokens = 32768 >= 156 ✓                    │
│                                                                 │
│  2. 选择策略:                                                    │
│     SelectionMethod: LATENCY_AWARE (配置决定)                   │
│                                                                 │
│  → 选择 qwen3-max                                               │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  OpenAIClient.chat_completion_stream()                          │
│                                                                 │
│  使用租户配置构建请求:                                           │
│    base_url = build_base_url(tenant.base_url_template, model)   │
│    api_key = tenant.apikey                                      │
│                                                                 │
│  转发请求到上游 API:                                             │
│    POST {base_url}/chat/completions                             │
│    Headers: Authorization: Bearer {tenant.apikey}               │
│    {                                                            │
│      "model": "qwen3-max",                                      │
│      "messages": [...],                                         │
│      "stream": true                                             │
│    }                                                            │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  SSE 流式返回                                                    │
│                                                                 │
│  data: {"choices":[{"delta":{"content":"def "}}]}               │
│  data: {"choices":[{"delta":{"content":"hello"}}]}              │
│  data: {"choices":[{"delta":{"content":"_world"}}]}             │
│  ...                                                            │
│  data: [DONE]                                                   │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  自动记录延迟                                                    │
│                                                                 │
│  - TTFT: 0.3s (首 token 时间)                                   │
│  - Total latency: 2.5s                                          │
│  - TPOT: 0.02s (平均每 token 时间)                              │
│                                                                 │
│  → 更新 LatencyTracker                                          │
│  → 影响后续 latency_aware 选择                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 各层职责总结

| 层 | 职责 | 输入 | 输出 |
|---|------|------|------|
| **Signal** | 从请求提取信息 | 原始文本 | SignalMatches (关键词匹配、分类结果) |
| **Decision** | 规则匹配，确定候选模型 | SignalMatches | DecisionResult (候选模型列表) |
| **Algorithm** | 从候选模型中选择一个 | 候选模型 + 延迟统计 | 选中的模型 |
| **Proxy** | 调用模型并返回结果 | 选中的模型 + 原始请求 | 流式/非流式响应 |
| **Metrics** | 记录延迟统计 | 响应时间、token 数 | 更新延迟缓存 |

---

## 关键配置影响

```yaml
# 影响是否调用 ML 分类器
models:
  classifier:
    intent: {enabled: true}     # 调用大模型分类意图
    complexity: {enabled: true} # 调用大模型分类复杂度

# 影响模型选择策略
selection:
  strategy: "latency_aware"     # 使用延迟感知选择
  # strategy: "priority"        # 使用权重选择

  latency_aware:
    tpot_percentile: 50         # TPOT 百分位数
    ttft_percentile: 90         # TTFT 百分位数
    min_observations: 3         # 最小观测次数
    fallback_to_weight: true    # 无数据时回退到权重
    weight_blend: 0.3           # 权重混合因子
```

---

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/route` | POST | 路由决策，返回选中的模型 |
| `/v1/chat/completions` | POST | OpenAI 兼容的聊天接口（需租户认证），支持流式 |
| `/v1/feedback` | POST | 上报延迟反馈 |
| `/v1/latency` | GET | 获取所有模型延迟统计 |
| `/v1/latency/{model}` | GET | 获取单个模型延迟统计 |
| `/v1/config` | GET | 获取当前配置 |
| `/v1/tenants` | GET | 列出所有租户 |
| `/v1/tenants` | POST | 创建租户 |
| `/v1/tenants/{tenant_id}` | GET | 获取租户详情 |
| `/v1/tenants/{tenant_id}` | PUT | 更新租户 |
| `/v1/tenants/{tenant_id}` | DELETE | 删除租户 |
| `/healthz` | GET | 健康检查 |
| `/readyz` | GET | 就绪检查 |

---

## 延迟感知选择原理

### 延迟类型

| 类型 | 全称 | 说明 |
|------|------|------|
| **TPOT** | Time Per Output Token | 生成每个 token 的平均时间 |
| **TTFT** | Time To First Token | 首个 token 的延迟 |
| **Latency** | Total Latency | 请求总延迟 |

### 选择算法

1. 获取每个候选模型的延迟百分位数（如 p50）
2. 计算归一化分数：`score = latency / min_latency`
3. 选择分数最低（延迟最小）的模型
4. 支持与权重混合：`final_score = latency_score * (1 - blend) + weight_score * blend`

### 数据来源

- **代理模式**：自动记录，无需手动上报
- **路由决策模式**：需要调用 `/v1/feedback` 手动上报

```bash
# 手动上报延迟
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "model": "codellama-70b",
    "latency_seconds": 1.5,
    "tpot": 0.02,
    "ttft": 0.3
  }'
```

---

## 完整请求示例

以下是一个完整的请求处理示例，展示了从租户认证到模型调用的全过程。

### 请求

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-dev-team-001-abc123xyz" \
  -d '{
    "messages": [{"role": "user", "content": "帮我写一个 Python 函数"}],
    "stream": true
  }'
```

### 处理流程详解

```
请求: "帮我写一个 Python 函数"
Authorization: Bearer sk-dev-team-001-abc123xyz

┌─────────────────────────────────────────────────────────────────┐
│ Step 1: 租户认证                                                 │
│                                                                 │
│ 根据 apikey 查找租户:                                            │
│   tenant_id: "dev-team-001"                                     │
│   base_url_template: "https://api.openai.com/v1"                │
│   decisions: [租户专属规则]                                      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Signal 层 (使用全局 config.yaml)                         │
│                                                                 │
│ signals.keyword_rules:                                          │
│   - name: "code_related"                                        │
│     keywords: ["code", "python", "debug", ...]                  │
│   → 匹配结果: code_related = true                               │
│                                                                 │
│ models.classifier.complexity:                                   │
│   model: "gpt-4o-mini"                                          │
│   → 分类结果: complexity = "simple"                             │
│                                                                 │
│ models.classifier.context_length:                               │
│   tokenizer_path: "~/Qwen3-tokenizer"                           │
│   threshold: 10000                                              │
│   → 计算结果: token_count = 50, label = "short"                 │
│                                                                 │
│ → SignalMatches {                                               │
│     keyword_rules: {code_related: true},                        │
│     complexity: "simple",                                       │
│     context_length: {label: "short", token_count: 50}           │
│   }                                                             │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Decision 层 (使用租户 tenant.decisions)                  │
│                                                                 │
│ 租户 "dev-team-001" 的 decisions:                               │
│                                                                 │
│ priority=100: block_pii                                         │
│   → pii == "detected"? No, 跳过                                 │
│                                                                 │
│ priority=90: route_long_context                                 │
│   → context_length == "long"? No, 跳过                          │
│                                                                 │
│ priority=10: route_code                                         │
│   → keyword "code_related"? Yes! ✓                              │
│                                                                 │
│ → DecisionResult {                                              │
│     decision: route_code,                                       │
│     model_refs: [{model: "gpt-4o", weight: 1.0}]                │
│   }                                                             │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Proxy 层 (使用租户配置)                                  │
│                                                                 │
│ base_url = tenant.base_url_template                             │
│           = "https://api.openai.com/v1"                         │
│                                                                 │
│ api_key = tenant.apikey                                         │
│         = "sk-dev-team-001-abc123xyz"                           │
│                                                                 │
│ → 调用 POST https://api.openai.com/v1/chat/completions          │
│   Headers: Authorization: Bearer sk-dev-team-001-abc123xyz      │
│   Body: {model: "gpt-4o", messages: [...]}                      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: 流式返回                                                 │
│                                                                 │
│ data: {"choices":[{"delta":{"content":"def "}}]}                │
│ data: {"choices":[{"delta":{"content":"hello"}}]}               │
│ data: {"choices":[{"delta":{"content":"_world"}}]}              │
│ data: [DONE]                                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 响应

```
data: {"id":"chatcmpl-xxx","model":"gpt-4o","choices":[{"delta":{"content":"def "}}]}

data: {"id":"chatcmpl-xxx","model":"gpt-4o","choices":[{"delta":{"content":"hello"}}]}

data: {"id":"chatcmpl-xxx","model":"gpt-4o","choices":[{"delta":{"content":"_world"}}]}

data: [DONE]
```