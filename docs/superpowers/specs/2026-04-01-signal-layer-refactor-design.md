# Signal Layer 重构设计文档

日期：2026-04-01

---

## 一、背景与目标

### 当前问题

Signal Layer 存在以下设计问题：

1. **接口与实现不一致**：`Classifier(ABC)` 定义接口返回 `SignalMatches`，但 `KeywordClassifier` 返回 `dict[str, bool]`，`MLClassifier` 返回 `TaskResult | None`
2. **MLClassifier 职责过重**：一个类包含 4 个分类方法，硬编码 prompt，违反开放封闭原则（OCP）
3. **UnifiedClassifier if-elif 分发**：`_run_ml_task` 方法硬编码分发逻辑，难扩展
4. **TaskType 缺失 KEYWORD**：`SignalMatches` 有 `keyword_rules` 字段，但 `TaskType` 无对应枚举值
5. **缺乏兜底机制**：ML 分类器调用 API 时无独立超时控制，异常时仅返回 `None`

### 重构目标

1. 统一 `Classifier` 接口，所有子类返回 `SignalMatches`
2. 拆分 `MLClassifier` 为 4 个独立类，每个类只负责一种分类任务
3. 简化 `UnifiedClassifier`，消除 if-elif 分发逻辑
4. 扩展 `TaskType` 新增 `KEYWORD`
5. 为 ML 分类器添加独立超时控制 + 可配置兜底值

---

## 二、整体架构

### 重构后的目录结构

```
signal_layer/
├── __init__.py           # 导出所有公共类
├── classifier.py         # Classifier(ABC) + MLClassifierBase + 5个具体子类 + UnifiedClassifier
├── embedder.py           # 不动
├── types.py              # TaskType(新增KEYWORD) + TaskResult + SignalMatches
```

### 类职责划分

| 类 | 职责 | 输入 | 输出 |
|---|-----|------|------|
| `Classifier(ABC)` | 定义统一接口 | `text: str` | `SignalMatches` |
| `KeywordClassifier` | 关键词匹配（本地） | `text: str` | `SignalMatches(keyword_rules={...})` |
| `IntentClassifier` | Intent 分类（API） | `text: str` | `SignalMatches(intent=TaskResult)` |
| `PIIClassifier` | PII 检测（API） | `text: str` | `SignalMatches(pii=TaskResult)` |
| `SecurityClassifier` | Security 检测（API） | `text: str` | `SignalMatches(security=TaskResult)` |
| `ComplexityClassifier` | Complexity 分析（API） | `text: str` | `SignalMatches(complexity=TaskResult)` |
| `UnifiedClassifier` | 组合所有分类器 | `text: str` | `SignalMatches`（合并结果） |

### 数据流

```
text → UnifiedClassifier.classify(text)
         │
         ├─→ KeywordClassifier.classify(text)   → SignalMatches(keyword_rules)
         ├─→ IntentClassifier.classify(text)    → SignalMatches(intent)
         ├─→ PIIClassifier.classify(text)       → SignalMatches(pii)
         ├─→ SecurityClassifier.classify(text)  → SignalMatches(security)
         └─→ ComplexityClassifier.classify(text) → SignalMatches(complexity)
         │
         └─→ 合并所有 SignalMatches → 最终 SignalMatches
```

---

## 三、Classifier 接口设计

### Classifier 基类

```python
class Classifier(ABC):
    """所有分类器的统一接口。"""

    @abstractmethod
    async def classify(self, text: str) -> SignalMatches:
        """
        对文本进行分类，返回 SignalMatches。

        每个子类只填充自己负责的字段：
        - KeywordClassifier → keyword_rules
        - IntentClassifier → intent
        - PIIClassifier → pii
        - SecurityClassifier → security
        - ComplexityClassifier → complexity
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """分类器名称，用于日志和调试。"""
        pass
```

### KeywordClassifier

```python
class KeywordClassifier(Classifier):
    """关键词匹配分类器（本地执行，无延迟）。"""

    def __init__(self, rules: list[KeywordRule]) -> None:
        self.rules = {rule.name: rule for rule in rules}

    @property
    def name(self) -> str:
        return "keyword"

    async def classify(self, text: str) -> SignalMatches:
        """执行关键词匹配，返回 keyword_rules 字段。"""
        results: dict[str, bool] = {}

        for name, rule in self.rules.items():
            keywords = rule.keywords
            search_text = text

            if not rule.case_sensitive:
                keywords = [k.lower() for k in keywords]
                search_text = text.lower()

            if rule.operator == Operator.ANY:
                results[name] = any(kw in search_text for kw in keywords)
            else:  # ALL
                results[name] = all(kw in search_text for kw in keywords)

        return SignalMatches(keyword_rules=results)
```

### MLClassifierBase（ML 分类器基类）

提取 ML 分类器的公共逻辑：超时控制、兜底机制、API 调用。

```python
class MLClassifierBase(Classifier):
    """ML 分类器基类，提供超时控制和兜底机制。"""

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        task_type: TaskType,
        prompt: str,
        fallback_label: str | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.task_type = task_type
        self.prompt = prompt
        self._fallback_label = fallback_label

    @property
    def name(self) -> str:
        return self.task_type.value

    @abstractmethod
    def _parse_response(self, content: str) -> str:
        """解析 API 返回内容，提取标签。"""
        pass

    @abstractmethod
    def _get_field_name(self) -> str:
        """返回 SignalMatches 中对应的字段名。"""
        pass

    async def classify(self, text: str) -> SignalMatches:
        """
        调用 API 进行分类，支持超时控制和兜底。

        流程：
        1. 检查是否启用
        2. 调用 API（带超时）
        3. 解析响应
        4. 异常/超时时返回兜底值（confidence=0.0）
        """
        if not self.config.enabled:
            return SignalMatches()

        try:
            result = await asyncio.wait_for(
                self._call_api(text),
                timeout=self.config.timeout
            )
            return SignalMatches(
                **{self._get_field_name(): result}
            )
        except asyncio.TimeoutError as e:
            logger.warning(
                f"{self.name}_classifier_timeout",
                timeout=self.config.timeout,
                fallback=self._fallback_label,
            )
            return self._create_fallback_result()
        except Exception as e:
            logger.error(
                f"{self.name}_classifier_error",
                error=str(e),
                error_type=type(e).__name__,
                fallback=self._fallback_label,
            )
            return self._create_fallback_result()

    async def _call_api(self, text: str) -> TaskResult:
        """调用 OpenAI API。"""
        response = await self.client.chat_completion(
            model=self.config.model,
            messages=[
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": text},
            ],
            max_tokens=50,
        )

        content = response["choices"][0]["message"]["content"]
        label = self._parse_response(content)

        return TaskResult(
            task=self.task_type,
            label=label,
            confidence=1.0,
        )

    def _create_fallback_result(self) -> SignalMatches:
        """创建兜底结果。"""
        if self._fallback_label is None:
            return SignalMatches()

        return SignalMatches(
            **{self._get_field_name(): TaskResult(
                task=self.task_type,
                label=self._fallback_label,
                confidence=0.0,
                metadata={"fallback": True},
            )}
        )
```

### 具体子类

#### IntentClassifier

```python
class IntentClassifier(MLClassifierBase):
    """Intent 分类器。"""

    PROMPT = (
        "Classify the intent of the following text. "
        "Respond with just the intent label."
    )

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        fallback_label: str | None = None,
    ) -> None:
        super().__init__(
            config=config,
            client=client,
            task_type=TaskType.INTENT,
            prompt=self.PROMPT,
            fallback_label=fallback_label,
        )

    def _parse_response(self, content: str) -> str:
        return content.strip()

    def _get_field_name(self) -> str:
        return "intent"
```

#### PIIClassifier

```python
class PIIClassifier(MLClassifierBase):
    """PII 检测分类器。"""

    PROMPT = (
        "Detect if the following text contains PII "
        "(personally identifiable information). "
        "Respond with 'detected' or 'none'."
    )

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        fallback_label: str = "detected",  # 安全优先默认值
    ) -> None:
        super().__init__(
            config=config,
            client=client,
            task_type=TaskType.PII,
            prompt=self.PROMPT,
            fallback_label=fallback_label,
        )

    def _parse_response(self, content: str) -> str:
        return content.strip().lower()

    def _get_field_name(self) -> str:
        return "pii"
```

#### SecurityClassifier

```python
class SecurityClassifier(MLClassifierBase):
    """Security 检测分类器。"""

    PROMPT = (
        "Detect if the following text contains security threats "
        "(jailbreak, injection, malicious content). "
        "Respond with 'safe' or the threat type."
    )

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        fallback_label: str = "detected",  # 安全优先默认值
    ) -> None:
        super().__init__(
            config=config,
            client=client,
            task_type=TaskType.SECURITY,
            prompt=self.PROMPT,
            fallback_label=fallback_label,
        )

    def _parse_response(self, content: str) -> str:
        return content.strip()

    def _get_field_name(self) -> str:
        return "security"
```

#### ComplexityClassifier

```python
class ComplexityClassifier(MLClassifierBase):
    """Complexity 分析分类器。"""

    PROMPT = (
        "Analyze the complexity of the following query. "
        "Consider factors like: length, number of tasks, reasoning required, "
        "domain knowledge needed, and ambiguity. "
        "Respond with exactly one of: 'simple', 'medium', or 'complex'. "
        "simple: short, single task, straightforward\n"
        "medium: moderate length, may need some reasoning\n"
        "complex: long, multiple tasks, requires deep reasoning or domain expertise"
    )

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        fallback_label: str = "medium",  # 中性默认值
    ) -> None:
        super().__init__(
            config=config,
            client=client,
            task_type=TaskType.COMPLEXITY,
            prompt=self.PROMPT,
            fallback_label=fallback_label,
        )

    def _parse_response(self, content: str) -> str:
        label = content.strip().lower()
        # 标准化标签
        if label in ("simple", "easy", "low"):
            return "simple"
        elif label in ("complex", "hard", "high", "difficult"):
            return "complex"
        else:
            return "medium"

    def _get_field_name(self) -> str:
        return "complexity"
```

---

## 四、UnifiedClassifier 简化

```python
class UnifiedClassifier(Classifier):
    """
    组合所有分类器的入口类。

    职责：
    1. 持有所有 Classifier 实例
    2. 并行执行分类任务
    3. 合并所有 SignalMatches 结果
    """

    def __init__(self, classifiers: list[Classifier]) -> None:
        self.classifiers = classifiers

    @property
    def name(self) -> str:
        return "unified"

    async def classify(self, text: str) -> SignalMatches:
        """
        并行执行所有分类器，合并结果。

        流程：
        1. 并行调用所有 classifier.classify(text)
        2. 合并所有 SignalMatches
        """
        # 并行执行
        results = await asyncio.gather(
            *[c.classify(text) for c in self.classifiers],
            return_exceptions=True,  # 单个失败不影响其他
        )

        # 合并结果
        final_matches = SignalMatches()
        for classifier, result in zip(self.classifiers, results):
            if isinstance(result, Exception):
                logger.error(
                    "classifier_failed",
                    classifier=classifier.name,
                    error=str(result),
                )
                continue
            if isinstance(result, SignalMatches):
                final_matches = self._merge_matches(final_matches, result)

        return final_matches

    def _merge_matches(
        self,
        base: SignalMatches,
        new: SignalMatches,
    ) -> SignalMatches:
        """合并两个 SignalMatches。"""
        # 合并 keyword_rules
        base.keyword_rules.update(new.keyword_rules)

        # 合并 ML 结果（非 None 时覆盖）
        if new.intent is not None:
            base.intent = new.intent
        if new.pii is not None:
            base.pii = new.pii
        if new.security is not None:
            base.security = new.security
        if new.complexity is not None:
            base.complexity = new.complexity

        return base
```

**简化点**：
- 消除了 `_run_ml_task` 的 if-elif 分发逻辑
- 通过 `classifiers: list[Classifier]` 统一处理所有分类器
- 使用 `asyncio.gather(return_exceptions=True)` 确保单个失败不影响整体

---

## 五、TaskType 扩展

```python
class TaskType(str, Enum):
    """分类任务类型，包含所有 Signal 类型。"""

    KEYWORD = "keyword"       # 新增：关键词匹配
    INTENT = "intent"
    PII = "pii"
    SECURITY = "security"
    COMPLEXITY = "complexity"
```

**说明**：
- 新增 `KEYWORD` 类型，统一所有 Signal 的类型表示
- `SignalMatches.keyword_rules` 对应 `TaskType.KEYWORD`

---

## 六、配置扩展

### ClassifierModelConfig 新增字段

```python
class ClassifierModelConfig(BaseModel):
    """单个分类器模型的配置。"""

    model: str = Field("glm-5", description="API 调用的模型名称")
    enabled: bool = Field(True, description="是否启用该分类器")
    timeout: float = Field(10.0, description="单个分类任务的超时秒数", ge=1.0, le=60.0)
    fallback_label: str | None = Field(
        None,
        description="超时/异常时的默认标签。None 表示不返回兜底值"
    )
```

### fallback_label 默认值策略

| 分类器 | fallback_label 默认值 | 理由 |
|--------|---------------------|------|
| Intent | `None` | 不影响安全决策，可缺失 |
| PII | `"detected"` | 安全优先，宁可误报 |
| Security | `"detected"` | 安全优先，宁可误报 |
| Complexity | `"medium"` | 中性值，不影响路由选择 |

### 配置示例 (config.yaml)

```yaml
models:
  classifier:
    intent:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 5.0
      fallback_label: null

    pii:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 10.0
      fallback_label: "detected"

    security:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 10.0
      fallback_label: "detected"

    complexity:
      model: "qwen3.5-plus"
      enabled: true
      timeout: 8.0
      fallback_label: "medium"
```

---

## 七、Router 初始化改动

### Router._initialize_components

```python
def _initialize_components(self) -> None:
    """初始化所有路由组件。"""

    # === Signal Layer ===
    classifiers: list[Classifier] = []

    # 1. KeywordClassifier（始终添加）
    keyword_classifier = KeywordClassifier(self.config.signals.keyword_rules)
    classifiers.append(keyword_classifier)

    # 2. OpenAI Client
    client = OpenAIClient(
        base_url=self.config.models.base_url,
        api_key=self.config.models.api_key,
        timeout=self.config.models.timeout,
    )
    self._client = client

    # 3. ML Classifiers（根据配置添加）
    classifier_config = self.config.models.classifier

    # Intent
    if classifier_config.intent and classifier_config.intent.enabled:
        intent_fallback = classifier_config.intent.fallback_label
        classifiers.append(IntentClassifier(
            config=classifier_config.intent,
            client=client,
            fallback_label=intent_fallback,
        ))

    # PII（安全优先默认值）
    if classifier_config.pii and classifier_config.pii.enabled:
        pii_fallback = classifier_config.pii.fallback_label or "detected"
        classifiers.append(PIIClassifier(
            config=classifier_config.pii,
            client=client,
            fallback_label=pii_fallback,
        ))

    # Security（安全优先默认值）
    if classifier_config.security and classifier_config.security.enabled:
        security_fallback = classifier_config.security.fallback_label or "detected"
        classifiers.append(SecurityClassifier(
            config=classifier_config.security,
            client=client,
            fallback_label=security_fallback,
        ))

    # Complexity（中性默认值）
    if classifier_config.complexity and classifier_config.complexity.enabled:
        complexity_fallback = classifier_config.complexity.fallback_label or "medium"
        classifiers.append(ComplexityClassifier(
            config=classifier_config.complexity,
            client=client,
            fallback_label=complexity_fallback,
        ))

    # 4. UnifiedClassifier
    self.classifier = UnifiedClassifier(classifiers)

    # === 其他层（保持不变）===
    # Embedder, Decision, Algorithm, Cache...
```

### Router.route 改动

```python
async def route(self, request: RoutingRequest) -> RoutingResult:
    """路由请求。"""

    # 1. Check cache（保持不变）
    # ...

    # 2. Extract signals（简化）
    signals = await self.classifier.classify(request.query)

    # 3. Evaluate decisions（保持不变）
    # ...
```

**改动点**：
- `UnifiedClassifier.classify(text)` 无需传入 `tasks: list[TaskType]` 参数
- 删除 `_get_classification_tasks()` 方法

---

## 八、不改动的部分

| 组件 | 原因 |
|------|------|
| `SignalMatches` 业务逻辑方法 | 保留原有代码，暂不动 |
| `embedder.py` | 不是本次负责范围 |
| `Decision Layer` | 无需改动，仍使用 `SignalMatches` 的方法 |
| `config.py` 其他配置 | 仅扩展 `ClassifierModelConfig`，其他不变 |

---

## 九、测试要点

1. **单元测试**：
   - 每个 Classifier 子类的 `classify()` 返回正确的 `SignalMatches`
   - 超时场景返回兜底值，`confidence=0.0`
   - 异常场景返回兜底值或空 `SignalMatches`

2. **集成测试**：
   - `UnifiedClassifier` 正确合并多个结果
   - 并行执行，单个失败不影响其他

3. **配置测试**：
   - `fallback_label` 配置正确加载
   - 未配置时使用安全默认值

---

## 十、风险与注意事项

1. **向后兼容**：
   - `Router.route()` 不再需要 `_get_classification_tasks()` 方法
   - `UnifiedClassifier.classify()` 签名变更（无需 `tasks` 参数）

2. **超时设置**：
   - 单个分类器默认 10s，总延迟取决于最慢的分类器
   - 建议根据实际 API 响应时间调整 `timeout` 配置

3. **兜底值策略**：
   - PII/Security 默认 `"detected"`，可能导致误报
   - 可通过配置 `fallback_label: null` 关闭兜底机制

---

## 十一、实施步骤

1. 修改 `types.py`：新增 `TaskType.KEYWORD`
2. 修改 `config.py`：扩展 `ClassifierModelConfig`
3. 重写 `classifier.py`：
   - 定义 `Classifier(ABC)` 和 `MLClassifierBase`
   - 实现 5 个具体子类
   - 简化 `UnifiedClassifier`
4. 修改 `router.py`：
   - 更新 `_initialize_components()`
   - 简化 `route()` 调用
   - 删除 `_get_classification_tasks()`
5. 更新 `signal_layer/__init__.py`：导出新类
6. 编写单元测试
7. 更新 `config.yaml` 示例