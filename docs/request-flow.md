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
{"messages": [{"role": "user", "content": "写一个 Python 函数"}]}
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
│  Router.route() - Signal 层                                     │
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
│  │ - complexity: "medium"                  │                   │
│  │ - pii: "none"                           │                   │
│  │ - security: "safe"                      │                   │
│  └─────────────────────────────────────────┘                   │
│                                                                 │
│  → SignalMatches {                                              │
│       keyword_rules: {code_related: true},                      │
│       complexity: "medium",                                     │
│       pii: false,                                               │
│       security: false                                           │
│     }                                                           │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Decision 层 - Engine.evaluate()                                │
│                                                                 │
│  按 priority 从高到低评估:                                       │
│                                                                 │
│  priority=100: block_pii                                        │
│    → pii == "detected"? No, 跳过                                │
│                                                                 │
│  priority=99: block_security_threat                             │
│    → security == "detected"? No, 跳过                           │
│                                                                 │
│  priority=50: route_complex_query                               │
│    → complexity == "complex"? No, 跳过                          │
│                                                                 │
│  priority=10: route_to_code_model                              │
│    → keyword "code_related"? Yes! ✓                             │
│                                                                 │
│  → DecisionResult {                                             │
│       decision: route_to_code_model,                            │
│       model_refs: [codellama-70b, deepseek-coder]               │
│     }                                                           │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Algorithm 层 - Model Selection                                 │
│                                                                 │
│  SelectionMethod: LATENCY_AWARE (配置决定)                      │
│                                                                 │
│  LatencyAwareSelector.select():                                 │
│    - codellama-70b: latency p50 = 1.2s                         │
│    - deepseek-coder: latency p50 = 0.8s                        │
│                                                                 │
│  → 选择 deepseek-coder (延迟更低)                               │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  OpenAIClient.chat_completion_stream()                          │
│                                                                 │
│  转发请求到 deepseek-coder:                                      │
│    POST {base_url}/chat/completions                             │
│    {                                                            │
│      "model": "deepseek-coder",                                 │
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
| `/v1/chat/completions` | POST | OpenAI 兼容的聊天接口，支持流式 |
| `/v1/feedback` | POST | 上报延迟反馈 |
| `/v1/latency` | GET | 获取所有模型延迟统计 |
| `/v1/latency/{model}` | GET | 获取单个模型延迟统计 |
| `/v1/config` | GET | 获取当前配置 |
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