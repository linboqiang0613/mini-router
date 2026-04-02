# LLM 请求路由系统设计文档

## 摘要

本文档阐述了 LLM（大型语言模型）请求路由系统的设计理念与实现方案。随着大模型技术的快速发展，企业面临着模型选型、成本控制、性能优化等多重挑战。智能路由系统作为模型服务架构的关键组件，能够根据请求特征动态选择最优模型，实现性能、成本与质量的平衡。

---

## 一、为什么需要路由

### 1.1 多模型并存的现状

当前 LLM 生态呈现多模型并存的格局：

| 模型类型 | 代表模型 | 特点 | 适用场景 |
|---------|---------|------|---------|
| 通用大模型 | GPT-4, Claude-3, Qwen-Max | 能力全面，成本较高 | 复杂推理、多任务场景 |
| 代码专用模型 | Codellama, DeepSeek-Coder | 代码生成能力强 | 编程任务 |
| 数学专用模型 | Llama-Math, WizardMath | 数学推理准确 | 数学计算 |
| 轻量级模型 | GPT-3.5, Qwen-Turbo | 响应快，成本低 | 简单问答、日常对话 |
| 垂直领域模型 | 医疗、法律、金融模型 | 领域知识丰富 | 专业场景 |

### 1.2 路由系统的核心价值

#### 1.2.1 成本优化

不同模型的定价差异显著：

```
复杂模型 (GPT-4):     $0.03 / 1K tokens
中等模型 (GPT-3.5):   $0.002 / 1K tokens
轻量模型 (本地部署):  硬件成本分摊

成本差异: 15x - 100x
```

通过路由系统，将简单请求导向低成本模型，可将整体推理成本降低 **60%-80%**。

#### 1.2.2 性能优化

- **延迟优化**：简单请求使用轻量模型，TTFT（Time To First Token）可降低 50%-70%
- **负载均衡**：根据模型实时负载动态分配，避免单点过载
- **资源利用**：最大化利用已部署的模型资源

#### 1.2.3 质量保障

- **专家路由**：代码问题路由到代码专家模型，提升专业领域准确率
- **复杂度匹配**：复杂问题使用强模型，确保输出质量
- **安全防护**：自动检测并拦截恶意请求、PII 泄露风险

#### 1.2.4 架构灵活性

- **模型热切换**：无需修改应用代码即可切换底层模型
- **A/B 测试**：支持模型对比实验
- **渐进式升级**：平滑引入新模型

---

## 二、路由的架构设计

### 2.1 整体架构

Mini-Router 采用分层架构设计，遵循单一职责原则，各层独立演进：

```
┌─────────────────────────────────────────────────────────────────┐
│                         API Gateway                              │
│                    /v1/route, /v1/chat/completions               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Signal Layer                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Keyword     │  │  ML          │  │  Embedding   │          │
│  │  Classifier  │  │  Classifier  │  │  Matcher     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│  输出: SignalMatches {keywords, intent, pii, security, ...}      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Decision Layer                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Rule Engine                                              │   │
│  │  - 规则树评估 (AND/OR/NOT)                                │   │
│  │  - 优先级排序                                             │   │
│  │  - 动作判定 (route/reject)                                │   │
│  └──────────────────────────────────────────────────────────┘   │
│  输出: DecisionResult {decision_name, model_refs, action}        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Algorithm Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Static      │  │  RoundRobin  │  │  LatencyAware│          │
│  │  Selector    │  │  Selector    │  │  Selector    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│  输出: selected_model                                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Proxy Layer                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  ChatProxy                                                │   │
│  │  - 请求转发                                               │   │
│  │  - 响应流式返回                                           │   │
│  │  - 延迟统计                                               │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Cache Layer                               │
│  ┌──────────────┐  ┌──────────────┐                              │
│  │  Memory      │  │  Semantic    │                              │
│  │  Cache       │  │  Cache       │                              │
│  └──────────────┘  └──────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 架构设计原则

| 原则 | 说明 | 实现 |
|------|------|------|
| **单一职责** | 每层只负责一个核心功能 | Signal 层只提取信号，Decision 层只做规则匹配 |
| **开放封闭** | 对扩展开放，对修改封闭 | 新增分类器/选择器无需修改现有代码 |
| **依赖倒置** | 高层模块不依赖低层实现 | 通过接口/抽象类解耦 |
| **配置驱动** | 行为由配置决定，而非硬编码 | YAML 配置定义规则和策略 |

---

## 三、信号层（Signal Layer）

### 3.1 设计目标

信号层负责从原始请求中提取结构化信息，为后续决策提供数据支撑。核心目标：

1. **信息提取**：从非结构化文本中提取可量化特征
2. **安全检测**：识别潜在风险（PII、恶意请求）
3. **特征工程**：为 ML 模型选择提供输入

### 3.2 组件设计

#### 3.2.1 关键词分类器（Keyword Classifier）

**原理**：基于规则的关键词匹配，无外部依赖，延迟极低（<1ms）。

```python
class KeywordClassifier:
    def __init__(self, rules: list[KeywordRule]):
        self.rules = {rule.name: rule for rule in rules}

    def classify(self, text: str) -> dict[str, bool]:
        results = {}
        for name, rule in self.rules.items():
            if rule.operator == Operator.ANY:
                results[name] = any(kw in text for kw in rule.keywords)
            else:  # ALL
                results[name] = all(kw in text for kw in rule.keywords)
        return results
```

**配置示例**：
```yaml
keyword_rules:
  - name: "code_related"
    keywords: ["code", "programming", "debug", "python", "java"]
    operator: "any"          # 任一关键词匹配即命中
    case_sensitive: false    # 不区分大小写
```

**适用场景**：
- 领域识别（代码、数学、翻译）
- 快速预过滤
- 低延迟要求的初步分类

#### 3.2.2 ML 分类器（ML Classifier）

**原理**：调用 LLM API 进行智能分类，准确率高但存在延迟（100-500ms）。

```python
class MLClassifier:
    def __init__(self, config: ClassifierConfig, client: OpenAIClient):
        self.config = config
        self.client = client

    async def classify_complexity(self, text: str) -> TaskResult:
        response = await self.client.chat_completion(
            model=self.config.complexity.model,
            messages=[
                {"role": "system", "content": COMPLEXITY_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=20,
        )
        label = self._normalize_label(response["choices"][0]["message"]["content"])
        return TaskResult(task=TaskType.COMPLEXITY, label=label)
```

**支持的分类任务**：

| 分类器 | 功能 | 输出 | 典型延迟 |
|--------|------|------|---------|
| `intent` | 意图识别 | 自定义标签 | 200-400ms |
| `complexity` | 复杂度分析 | simple/complex | 150-300ms |
| `pii` | 隐私检测 | detected/none | 100-200ms |
| `security` | 安全检测 | safe/威胁类型 | 100-200ms |
| `context_length` | 上下文长度 | short/long | <10ms (本地) |

**配置示例**：
```yaml
classifier:
  complexity:
    model: "qwen3.5-plus"
    enabled: true
  pii:
    model: "qwen3.5-plus"
    enabled: true
  security:
    model: "qwen3.5-plus"
    enabled: true
```

**优化策略**：
- **并行调用**：多个分类任务并行执行，总延迟取决于最慢的任务
- **缓存结果**：相同查询复用分类结果
- **条件执行**：根据关键词预判，跳过不必要的分类

#### 3.2.3 语义匹配器（Embedding Matcher）

**原理**：基于向量相似度的语义匹配，适用于模糊匹配场景。

```python
class SemanticMatcher:
    def __init__(self, embedder: Embedder, threshold: float = 0.85):
        self.embedder = embedder
        self.threshold = threshold

    async def match(self, query: str, examples: list[str]) -> bool:
        query_embedding = await self.embedder.embed(query)
        for example in examples:
            example_embedding = await self.embedder.embed(example)
            if cosine_similarity(query_embedding, example_embedding) >= self.threshold:
                return True
        return False
```

**适用场景**：
- 意图模糊匹配
- 相似问题识别
- 语义缓存命中

#### 3.2.4 上下文长度分类器（Context Length Classifier）

**原理**：使用 HuggingFace tokenizer 在本地计算 token 数量，无需调用外部 API，延迟极低。

```python
class ContextLengthClassifier:
    def __init__(self, tokenizer_path: str, threshold: int = 10000):
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        self.threshold = threshold

    async def classify(self, text: str) -> SignalMatches:
        token_count = len(self.tokenizer.encode(text))
        label = "long" if token_count >= self.threshold else "short"
        return SignalMatches(
            context_length=TaskResult(
                task=TaskType.CONTEXT_LENGTH,
                label=label,
                metadata={"token_count": token_count}
            )
        )
```

**配置示例**：
```yaml
models:
  tokenizer_path: "~/Qwen3-tokenizer"  # HuggingFace tokenizer 路径
  
  classifier:
    context_length:
      enabled: true
      threshold: 10000  # token 阈值

decisions:
  - name: "route_long_context"
    priority: 90
    rules:
      type: "signal"
      signal: "context_length"
      condition: "long"
    model_refs:
      - model: "qwen3-max"
        weight: 1.0
        max_tokens: 32768  # 支持 max_tokens 过滤
```

**特点**：
- **本地计算**：无需调用 API，延迟 < 10ms
- **精确统计**：使用与模型一致的 tokenizer
- **max_tokens 过滤**：可自动过滤不满足 token 需求的模型

### 3.3 信号聚合

所有分类结果聚合为 `SignalMatches` 对象：

```python
@dataclass
class SignalMatches:
    keyword_rules: dict[str, bool]      # 关键词匹配结果
    embedding_rules: dict[str, bool]    # 语义匹配结果
    intent: TaskResult | None           # 意图分类
    pii: TaskResult | None              # PII 检测
    security: TaskResult | None         # 安全检测
    complexity: TaskResult | None       # 复杂度分析
    context_length: TaskResult | None   # 上下文长度 (NEW)
```

---

## 四、决策层（Decision Layer）

### 4.1 设计目标

决策层基于信号层输出，通过规则引擎匹配预定义策略，确定：
1. 请求是否应被拦截（安全、隐私）
2. 应路由到哪些候选模型
3. 执行什么动作（路由/拒绝）

### 4.2 规则引擎设计

#### 4.2.1 规则树结构

支持嵌套的布尔逻辑，实现复杂条件表达：

```yaml
rules:
  type: "and"
  children:
    - type: "keyword"
      name: "code_related"
    - type: "or"
      children:
        - type: "signal"
          signal: "complexity"
          condition: "complex"
        - type: "signal"
          signal: "complexity"
          condition: "medium"
```

**等价逻辑**：`code_related AND (complexity == "complex" OR complexity == "medium")`

#### 4.2.2 规则类型

| 类型 | 说明 | 配置示例 |
|------|------|---------|
| `keyword` | 关键词匹配 | `{type: "keyword", name: "code_related"}` |
| `signal` | ML 分类结果 | `{type: "signal", signal: "complexity", condition: "complex"}` |
| `embedding` | 语义匹配 | `{type: "embedding", name: "greeting"}` |
| `and` | 逻辑与 | `{type: "and", children: [...]}` |
| `or` | 逻辑或 | `{type: "or", children: [...]}` |
| `not` | 逻辑非 | `{type: "not", children: [...]}` |

#### 4.2.3 规则评估算法

```python
class RuleEvaluator:
    def evaluate(self, rule: RuleNode, signals: SignalMatches) -> tuple[bool, list[str]]:
        if rule.type == RuleType.KEYWORD:
            matched = signals.has_keyword_match(rule.name)
            return matched, [rule.name] if matched else []

        elif rule.type == RuleType.SIGNAL:
            matched = self._evaluate_signal_rule(rule, signals)
            return matched, [rule.signal] if matched else []

        elif rule.type == RuleType.AND:
            all_matched = True
            matched_rules = []
            for child in rule.children:
                matched, rules = self.evaluate(child, signals)
                if not matched:
                    all_matched = False
                matched_rules.extend(rules)
            return all_matched, matched_rules if all_matched else []

        elif rule.type == RuleType.OR:
            any_matched = False
            matched_rules = []
            for child in rule.children:
                matched, rules = self.evaluate(child, signals)
                if matched:
                    any_matched = True
                    matched_rules.extend(rules)
            return any_matched, matched_rules
```

### 4.3 决策配置

#### 4.3.1 决策结构

```yaml
decisions:
  - name: "block_pii"              # 决策名称
    priority: 100                   # 优先级（越高越先评估）
    rules:
      type: "signal"
      signal: "pii"
      condition: "detected"
    model_refs: []                  # 拦截无需模型
    action: "reject"                # 动作类型
    reject_message: "检测到隐私信息，请移除后重试"
```

#### 4.3.2 优先级机制

决策按 `priority` 降序评估，首个匹配的决策生效：

```
priority=100: 安全拦截（最高优先）
priority=99:  PII 拦截
priority=50:  复杂度路由
priority=10:  领域专项路由
priority=1:   兜底路由（最低优先）
```

**设计原则**：安全 > 性能 > 功能 > 兜底

### 4.4 动作类型

| 动作 | 说明 | 必需字段 |
|------|------|---------|
| `route` | 路由到模型 | `model_refs` |
| `reject` | 拒绝请求 | `reject_message` |

---

## 五、执行调用层（Algorithm & Proxy Layer）

### 5.1 算法层（Algorithm Layer）

#### 5.1.1 设计目标

从决策层确定的候选模型中，选择一个最优模型。核心考量：
- **性能**：选择延迟最低的模型
- **负载**：避免过载模型
- **成本**：优先选择成本更低的模型
- **质量**：确保输出质量达标

#### 5.1.2 选择策略

##### 静态选择（Static Selector）

基于权重的概率选择：

```python
class StaticSelector:
    async def select(self, context: SelectionContext) -> SelectionResult:
        candidates = context.candidate_models
        total_weight = sum(c.weight for c in candidates)

        # 加权随机选择
        r = random.random() * total_weight
        cumulative = 0.0
        for candidate in candidates:
            cumulative += candidate.weight
            if r <= cumulative:
                return SelectionResult(selected_model=candidate.model)
```

**配置示例**：
```yaml
model_refs:
  - model: "gpt-4"
    weight: 0.3      # 30% 流量
  - model: "gpt-3.5"
    weight: 0.7      # 70% 流量
```

##### 延迟感知选择（Latency Aware Selector）

基于实时延迟统计的智能选择：

```python
class LatencyAwareSelector:
    async def select(self, context: SelectionContext) -> SelectionResult:
        scored_candidates = []

        for candidate in context.candidate_models:
            # 获取延迟百分位数
            latency = await tracker.get_latency_percentile(
                candidate.model,
                context.latency_percentile
            )
            if latency:
                scored_candidates.append((candidate.model, latency))

        # 计算归一化分数（越低越好）
        min_latency = min(s[1] for s in scored_candidates)
        final_scores = [
            (model, latency / min_latency)
            for model, latency in scored_candidates
        ]

        # 选择分数最低的模型
        final_scores.sort(key=lambda x: x[1])
        return SelectionResult(selected_model=final_scores[0][0])
```

**配置示例**：
```yaml
selection:
  strategy: "latency_aware"
  latency_aware:
    tpot_percentile: 50         # TPOT p50
    ttft_percentile: 90         # TTFT p90
    min_observations: 3         # 最小观测次数
    fallback_to_weight: true    # 无数据时回退
    weight_blend: 0.3           # 延迟与权重混合比例
```

#### 5.1.3 max_tokens 过滤

在选择模型前，根据上下文长度自动过滤不符合要求的模型：

```python
def _filter_by_max_tokens(
    candidates: list[ModelRef],
    signals: SignalMatches
) -> list[ModelRef]:
    """根据 token 数量过滤模型."""
    if not signals.context_length:
        return candidates
    
    token_count = signals.context_length.metadata.get("token_count")
    if token_count is None:
        return candidates
    
    # 过滤 max_tokens 足够的模型
    filtered = [
        m for m in candidates
        if m.max_tokens is None or m.max_tokens >= token_count
    ]
    
    # 如果全部过滤，返回第一个作为兜底
    return filtered if filtered else [candidates[0]]
```

**配置示例**：
```yaml
decisions:
  - name: "route_long_context"
    rules:
      type: "signal"
      signal: "context_length"
      condition: "long"
    model_refs:
      - model: "qwen3-max"
        weight: 1.0
        max_tokens: 32768  # 该模型支持的最大 token 数
      - model: "qwen3-plus"
        weight: 0.8
        max_tokens: 16384
```

**过滤逻辑**：
1. 从 `SignalMatches.context_length` 获取 token 数量
2. 过滤掉 `max_tokens < token_count` 的模型
3. 如果所有模型都被过滤，使用第一个模型作为兜底

### 5.2 代理层（Proxy Layer）

#### 5.2.1 设计目标

代理层负责：
1. 接收 OpenAI 格式的聊天请求
2. 调用选中的模型
3. 流式/非流式返回结果
4. 自动记录延迟统计

#### 5.2.2 流式代理实现

```python
class ChatProxy:
    async def chat_stream(
        self,
        request: ChatRequest
    ) -> AsyncGenerator[ChatChunk, None]:
        # 1. 提取查询
        query = self._extract_query(request.messages)

        # 2. 路由决策
        routing_result = await self.router.route(
            RoutingRequest(query=query)
        )
        selected_model = routing_result.selected_model

        # 3. 记录开始时间
        start_time = time.time()
        first_token_time = None

        # 4. 流式调用模型
        async for chunk in self.client.chat_completion_stream(
            model=selected_model,
            messages=[msg.model_dump() for msg in request.messages],
        ):
            if first_token_time is None:
                first_token_time = time.time()
            yield ChatChunk(model=selected_model, choices=...)

        # 5. 记录延迟
        total_latency = time.time() - start_time
        ttft = first_token_time - start_time if first_token_time else None

        await self.router.record_latency(
            model=selected_model,
            latency_seconds=total_latency,
            ttft=ttft,
        )
```

#### 5.2.3 SSE 流式响应格式

```
data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":"Hello"}}]}

data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":" World"}}]}

data: [DONE]
```

---

## 六、缓存层（Cache Layer）

### 6.1 设计目标

缓存层通过存储历史请求-响应对，实现：
1. **降低延迟**：命中缓存时直接返回，无需调用模型
2. **节约成本**：减少 API 调用次数
3. **提升吞吐**：减轻后端模型压力

### 6.2 缓存类型

#### 6.2.1 精确缓存（Memory Cache）

基于查询文本的精确匹配：

```python
class MemoryCache:
    def __init__(self, max_entries: int = 10000):
        self.cache: dict[str, CacheEntry] = {}
        self.max_entries = max_entries

    def get(self, query: str) -> CacheEntry | None:
        return self.cache.get(query)

    def set(self, query: str, entry: CacheEntry) -> None:
        if len(self.cache) >= self.max_entries:
            self._evict_lru()
        self.cache[query] = entry
```

**特点**：
- 延迟极低（<1ms）
- 命中率有限（完全相同的查询）
- 适用于 FAQ 类场景

#### 6.2.2 语义缓存（Semantic Cache）

基于向量相似度的模糊匹配：

```python
class SemanticCache:
    def __init__(self, embedder: Embedder, threshold: float = 0.95):
        self.embedder = embedder
        self.threshold = threshold
        self.entries: list[tuple[np.ndarray, CacheEntry]] = []

    async def get_similar(self, query: str) -> CacheEntry | None:
        query_embedding = await self.embedder.embed(query)

        for stored_embedding, entry in self.entries:
            similarity = cosine_similarity(query_embedding, stored_embedding)
            if similarity >= self.threshold:
                return entry

        return None
```

**特点**：
- 延迟较高（需计算 embedding，50-200ms）
- 命中率高（语义相似的查询可复用）
- 适用于对话类场景

**配置示例**：
```yaml
cache:
  enabled: true
  similarity_threshold: 0.95    # 相似度阈值
  max_entries: 10000            # 最大缓存条目
```

### 6.3 缓存策略

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| **LRU** | 最近最少使用淘汰 | 通用场景 |
| **TTL** | 基于时间的过期 | 时效性数据 |
| **语义 LRU** | 结合相似度与访问时间 | 对话场景 |

---

## 七、性能指标

### 7.1 关键指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| **路由延迟 P50** | 从请求到返回路由决策 | < 50ms |
| **路由延迟 P99** | 路由延迟 99 分位 | < 200ms |
| **缓存命中率** | 缓存命中比例 | > 30% |
| **模型选择准确率** | 选择合适模型的比例 | > 90% |

### 7.2 性能优化建议

1. **关键词预过滤**：先执行本地关键词匹配，减少 ML 分类调用
2. **并行分类**：多个 ML 分类任务并行执行
3. **延迟观测**：持续监控各模型延迟，动态调整选择策略
4. **缓存预热**：预加载高频查询的缓存

---

## 八、最佳实践

### 8.1 规则设计

1. **安全优先**：安全拦截规则置于最高优先级
2. **避免过度匹配**：规则应精确，避免误杀
3. **保持简洁**：规则树深度不宜超过 3 层

### 8.2 模型配置

1. **明确职责**：每个决策的候选模型应职责相近
2. **合理权重**：权重配置应考虑模型能力和成本
3. **监控延迟**：定期检查模型延迟，调整策略

### 8.3 运维建议

1. **日志采集**：记录路由决策日志，便于问题排查
2. **指标监控**：监控缓存命中率、路由延迟等关键指标
3. **A/B 测试**：新规则上线前进行灰度测试

---

## 附录

### A. 配置文件完整示例

```yaml
# 服务配置
server:
  host: "0.0.0.0"
  port: 8080

# 模型配置
models:
  base_url: "https://api.example.com/v1"
  api_key: "${API_KEY}"
  tokenizer_path: "~/Qwen3-tokenizer"  # HuggingFace tokenizer 路径
  timeout: 120.0

  classifier:
    complexity:
      model: "qwen3.5-plus"
      enabled: true
    pii:
      model: "qwen3.5-plus"
      enabled: true
    security:
      model: "qwen3.5-plus"
      enabled: true
    context_length:          # 上下文长度分类器
      enabled: true
      threshold: 10000       # token 阈值

# 信号规则
signals:
  keyword_rules:
    - name: "code_related"
      keywords: ["code", "programming", "debug", "python", "java"]
      operator: "any"
      case_sensitive: false

# 决策规则
decisions:
  - name: "block_pii"
    priority: 100
    rules:
      type: "signal"
      signal: "pii"
      condition: "detected"
    action: "reject"
    reject_message: "检测到隐私信息"

  - name: "route_long_context"
    priority: 90
    rules:
      type: "signal"
      signal: "context_length"
      condition: "long"
    model_refs:
      - model: "qwen3-max"
        weight: 1.0
        max_tokens: 32768

  - name: "route_to_code_model"
    priority: 10
    rules:
      type: "keyword"
      name: "code_related"
    model_refs:
      - model: "codellama-70b"
        weight: 1.0
      - model: "deepseek-coder"
        weight: 0.8

# 选择策略
selection:
  strategy: "latency_aware"
  latency_aware:
    tpot_percentile: 50
    ttft_percentile: 90
    min_observations: 3

# 缓存配置
cache:
  enabled: true
  similarity_threshold: 0.95
  max_entries: 10000
```

### B. API 接口列表

#### 核心 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/route` | POST | 路由决策 |
| `/v1/chat/completions` | POST | OpenAI 兼容聊天（需租户认证） |
| `/v1/feedback` | POST | 延迟反馈 |
| `/v1/latency` | GET | 延迟统计 |
| `/v1/config` | GET | 配置查询 |
| `/healthz` | GET | 健康检查 |
| `/readyz` | GET | 就绪检查 |

#### 租户管理 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/tenants` | GET | 列出所有租户 |
| `/v1/tenants` | POST | 创建租户 |
| `/v1/tenants/{tenant_id}` | GET | 获取租户详情 |
| `/v1/tenants/{tenant_id}` | PUT | 更新租户 |
| `/v1/tenants/{tenant_id}` | DELETE | 删除租户 |

---

## 九、多租户支持

### 9.1 设计目标

多租户模块支持：
1. **租户隔离**：每个租户独立的 API Key 和路由规则
2. **灵活配置**：租户级别的 base_url_template 和 decisions
3. **API Key 认证**：基于 Bearer Token 的身份验证

### 9.2 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                         API Gateway                              │
│                    Authorization: Bearer <apikey>                │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Tenant Module                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  TenantManager                                            │   │
│  │  - 租户 CRUD 操作                                         │   │
│  │  - API Key 索引                                          │   │
│  │  - YAML 持久化                                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│  输出: TenantConfig {tenant_id, apikey, base_url_template, ...}  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        ChatProxy                                 │
│  - 使用租户的 decisions 进行路由                                 │
│  - 使用租户的 base_url_template 构建请求 URL                    │
│  - 使用租户的 apikey 调用上游 API                               │
└─────────────────────────────────────────────────────────────────┘
```

### 9.3 租户配置结构

```yaml
# config/tenants.yaml
tenants:
  - tenant_id: "tenant-001"
    apikey: "sk-tenant-001-key"
    name: "租户 A"
    enabled: true
    base_url_template: "http://api-a.com/llm/{model}/v1"
    timeout: 120.0
    decisions:
      - name: "default_route"
        priority: 0
        rules:
          type: "or"
          children: []
        model_refs:
          - model: "qwen3-max"
            weight: 1.0
```

### 9.4 API Key 认证流程

```python
# 1. 提取 API Key
apikey = extract_apikey(authorization_header)  # "Bearer sk-xxx" -> "sk-xxx"

# 2. 查找租户
tenant = tenant_manager.get_by_apikey(apikey)

# 3. 验证租户
if not tenant:
    raise AuthenticationError("Invalid API key")
if not tenant.enabled:
    raise TenantDisabledError("Tenant is disabled")

# 4. 使用租户配置进行路由
base_url = build_base_url(tenant.base_url_template, selected_model)
response = await client.chat_completion(
    base_url=base_url,
    api_key=tenant.apikey,
    model=selected_model,
    messages=messages
)
```

### 9.5 动态 base_url

每个租户可以配置独立的 `base_url_template`：

```yaml
base_url_template: "http://api.example.com/llm/{model}/v1"
```

`{model}` 占位符会被实际选中的模型名称替换：

```python
# 如果 model = "qwen3-max"
# 则 URL = "http://api.example.com/llm/qwen3-max/v1"
```