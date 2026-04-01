# Signal 和 Decision 配置详解

本文档详细介绍 `config.yaml` 中 Signal 和 Decision 的配置方法。

---

## 一、Signal（信号层）

Signal 负责从请求中提取信息，分为两类：

### 1. 关键词规则 (keyword_rules)

**本地匹配，无需调用大模型**

```yaml
signals:
  keyword_rules:
    - name: "code_related"                              # 规则名称
      keywords: ["code", "debug", "python"]             # 关键词列表
      operator: "any"                                    # 匹配方式
      case_sensitive: false                             # 是否区分大小写
```

| 字段 | 说明 | 可选值 |
|------|------|--------|
| `name` | 规则名称，在 decision 中引用 | 自定义字符串 |
| `keywords` | 关键词列表 | 字符串数组 |
| `operator` | 匹配方式 | `any` (任一匹配), `all` (全部匹配) |
| `case_sensitive` | 大小写敏感 | `true`, `false` |

**示例：**

```yaml
# operator: "any" - 任一关键词匹配即可
keywords: ["code", "debug"]
# "How do I debug this?" → 匹配 (有 debug)

# operator: "all" - 所有关键词都要匹配
keywords: ["code", "debug"]
# "How do I debug this code?" → 匹配 (两个都有)
# "How do I debug?" → 不匹配 (只有 debug)
```

---

### 2. ML 分类器

**调用大模型 API 进行分类**

```yaml
models:
  classifier:
    intent:
      model: "qwen3.5-plus"    # 模型名称
      enabled: true             # 是否启用
    pii:
      model: "qwen3.5-plus"
      enabled: true
    security:
      model: "qwen3.5-plus"
      enabled: true
    complexity:
      model: "qwen3.5-plus"
      enabled: true
```

| 分类器 | 功能 | 输出值 |
|--------|------|--------|
| `intent` | 意图分类 | 自定义标签 |
| `pii` | 个人信息检测 | `detected` / `none` |
| `security` | 安全威胁检测 | `safe` / 威胁类型 |
| `complexity` | 复杂度分析 | `simple` / `medium` / `complex` |

---

## 二、Decision（决策层）

Decision 根据 Signal 结果决定路由，按 **priority 从高到低** 评估。

### 基本结构

```yaml
decisions:
  - name: "decision_name"      # 决策名称
    priority: 10               # 优先级 (数字越大越先评估)
    rules:                     # 规则树
      type: "keyword"
      name: "code_related"
    model_refs:                # 目标模型
      - model: "codellama-70b"
        weight: 1.0
    action: "route"            # 动作
    reject_message: "..."      # reject 时的消息
```

---

### 规则类型 (rules.type)

#### 1. keyword 规则

引用 `keyword_rules` 中定义的规则：

```yaml
rules:
  type: "keyword"
  name: "code_related"      # 对应 signals.keyword_rules 中的 name
```

#### 2. signal 规则

引用 ML 分类器结果：

```yaml
rules:
  type: "signal"
  signal: "pii"             # 分类器名称: pii / security / intent / complexity
  condition: "detected"     # 匹配条件
```

| signal | condition 可选值 |
|--------|------------------|
| `pii` | `detected` |
| `security` | `detected` |
| `intent` | 自定义标签 |
| `complexity` | `simple` / `medium` / `complex` |

#### 3. 复合规则 (AND/OR/NOT)

**AND - 所有子规则都要匹配：**

```yaml
rules:
  type: "and"
  children:
    - type: "keyword"
      name: "code_related"
    - type: "keyword"
      name: "math_related"
```

**OR - 任一子规则匹配：**

```yaml
rules:
  type: "or"
  children:
    - type: "keyword"
      name: "code_related"
    - type: "keyword"
      name: "math_related"
```

**NOT - 取反：**

```yaml
rules:
  type: "not"
  children:
    - type: "keyword"
      name: "code_related"
```

---

### 动作类型 (action)

| action | 说明 | 必需字段 |
|--------|------|----------|
| `route` | 路由到模型 | `model_refs` |
| `reject` | 拒绝请求 | `reject_message` |

---

### model_refs 字段

```yaml
model_refs:
  - model: "qwen3-max"      # 模型名称
    weight: 1.0             # 权重 (用于加权选择)
```

多个模型时，按权重随机选择。

---

## 三、完整示例

### 示例 1：关键词路由

```yaml
# 1. 定义信号
signals:
  keyword_rules:
    - name: "code_related"
      keywords: ["code", "debug", "programming"]
      operator: "any"

# 2. 定义决策
decisions:
  - name: "route_to_code_model"
    priority: 10
    rules:
      type: "keyword"
      name: "code_related"      # 引用上面的规则
    model_refs:
      - model: "codellama-70b"
        weight: 1.0
```

**流程：** 用户输入 "How do I debug?" → 匹配 keyword `code_related` → 路由到 `codellama-70b`

---

### 示例 2：复杂度路由

```yaml
# 1. 启用 complexity 分类器
models:
  classifier:
    complexity:
      model: "qwen3.5-plus"
      enabled: true

# 2. 定义决策
decisions:
  - name: "route_complex_query"
    priority: 50
    rules:
      type: "signal"
      signal: "complexity"
      condition: "complex"      # 复杂度高时匹配
    model_refs:
      - model: "qwen3-max"
        weight: 1.0
```

**流程：** 用户输入复杂问题 → complexity 分类器返回 `complex` → 路由到 `qwen3-max`

---

### 示例 3：安全拦截

```yaml
# 1. 启用 security 分类器
models:
  classifier:
    security:
      model: "qwen3.5-plus"
      enabled: true

# 2. 定义决策
decisions:
  - name: "block_security_threat"
    priority: 100               # 高优先级
    rules:
      type: "signal"
      signal: "security"
      condition: "detected"
    model_refs: []
    action: "reject"
    reject_message: "Security threat detected. Request blocked."
```

**流程：** 检测到安全威胁 → 返回 reject 响应

---

### 示例 4：复合规则

```yaml
decisions:
  - name: "complex_code_query"
    priority: 60
    rules:
      type: "and"               # 同时满足两个条件
      children:
        - type: "keyword"
          name: "code_related"
        - type: "signal"
          signal: "complexity"
          condition: "complex"
    model_refs:
      - model: "gpt-4"
        weight: 1.0
```

**流程：** 问题包含代码关键词 **且** 复杂度高 → 路由到 `gpt-4`

---

## 四、评估流程

```
请求到来
    ↓
┌─────────────────────────────────────┐
│ Signal 层                           │
│ 1. KeywordClassifier (本地匹配)     │
│    → keyword_rules: {code: True}   │
│                                     │
│ 2. MLClassifier (调用大模型)        │
│    → complexity: "medium"          │
│    → pii: "none"                   │
│    → security: "safe"              │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Decision 层 (按 priority 排序)      │
│                                     │
│ priority=100: block_pii            │
│   → pii == "detected"? No          │
│                                     │
│ priority=99: block_security        │
│   → security == "detected"? No     │
│                                     │
│ priority=50: route_complex_query   │
│   → complexity == "complex"? No    │
│                                     │
│ priority=10: route_to_code_model   │
│   → keyword "code_related"? Yes!   │
│   → 返回: codellama-70b            │
└─────────────────────────────────────┘
    ↓
返回路由结果
```

---

## 五、配置字段速查表

### signals.keyword_rules

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✓ | 规则名称 |
| `keywords` | [string] | ✓ | 关键词列表 |
| `operator` | string | | `any` 或 `all`，默认 `any` |
| `case_sensitive` | bool | | 默认 `false` |

### models.classifier

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | ✓ | 模型名称 |
| `enabled` | bool | | 是否启用，默认 `true` |

### decisions

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✓ | 决策名称 |
| `priority` | int | ✓ | 优先级，数字越大越先评估 |
| `rules` | object | ✓ | 规则树 |
| `model_refs` | [object] | | 目标模型列表 |
| `action` | string | | `route` 或 `reject`，默认 `route` |
| `reject_message` | string | | reject 时的消息 |

### decisions[].rules

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | ✓ | `keyword` / `signal` / `and` / `or` / `not` |
| `name` | string | | keyword 规则名称 (type=keyword) |
| `signal` | string | | 分类器名称 (type=signal) |
| `condition` | string | | 匹配条件 (type=signal) |
| `children` | [object] | | 子规则列表 (type=and/or/not) |

### decisions[].model_refs

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | ✓ | 模型名称 |
| `weight` | float | | 权重，默认 1.0 |