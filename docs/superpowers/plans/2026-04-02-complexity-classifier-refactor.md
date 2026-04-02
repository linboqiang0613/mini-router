# Complexity Classifier Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor ComplexityClassifier to use improved prompt with financial/banking scenarios coverage, and simplify classification from 3 levels to 2 levels (simple/complex).

**Architecture:** Update prompt with structured dimensions for complexity judgment, modify _parse_response() to only return simple/complex, update helper methods to remove medium handling, update config and tests.

**Tech Stack:** Python 3.11+, Pydantic v2, asyncio

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `mini_router/signal_layer/classifier.py` | Modify | Update ComplexityClassifier PROMPT and _parse_response() |
| `mini_router/signal_layer/types.py` | Modify | Update get_complexity_level(), is_complex(), is_simple() |
| `mini_router/router/router.py` | Modify | Update default fallback from "medium" to "complex" |
| `config.yaml` | Modify | Update fallback_label and decision conditions |
| `tests/conftest.py` | Modify | Update test fixture fallback_label |
| `tests/unit/test_classifier.py` | Modify | Update tests for new behavior |

---

## Task 1: Update ComplexityClassifier PROMPT and _parse_response()

**Files:**
- Modify: `mini_router/signal_layer/classifier.py:217-256`

- [ ] **Step 1: Update the PROMPT and _parse_response() in ComplexityClassifier**

Replace the entire `ComplexityClassifier` class (lines 217-256) with:

```python
class ComplexityClassifier(MLClassifierBase):
    """Complexity analysis using ML API."""

    PROMPT = (
        "你是一个查询复杂度分析专家。请分析用户查询的复杂度，仅返回 \"simple\" 或 \"complex\"。\n\n"
        "## 判断维度\n\n"
        "### 判定为 \"complex\" 的条件（满足任一即可）：\n\n"
        "1. **多步骤任务**：需要分解为多个子任务，如\"帮我设计一个订单系统并写出数据库表结构\"\n"
        "2. **深度推理**：需要逻辑推理、因果分析、方案对比，如\"分析这次股市波动的原因\"\n"
        "3. **专业领域知识**：涉及金融、银行、法律等专业领域，需要专业知识才能准确回答\n"
        "4. **数据处理复杂**：涉及复杂计算、数据分析、多维度统计，如\"计算这只债券的久期和凸性\"\n"
        "5. **业务流程理解**：需要理解跨系统业务流程，如\"贷款审批流程中风险控制环节有哪些\"\n"
        "6. **模糊意图**：用户意图不明确，需要澄清或深度理解上下文\n"
        "7. **高影响决策**：涉及重要决策建议，错误回答可能导致严重后果\n\n"
        "### 判定为 \"simple\" 的条件：\n\n"
        "1. **单一明确任务**：用户意图清晰，只需一个回答\n"
        "2. **常识性问题**：无需专业背景即可回答\n"
        "3. **简单信息查询**：查事实、查定义、查用法\n"
        "4. **格式转换**：翻译、改写、总结简单内容\n\n"
        "## 重要提示\n\n"
        "- 不要仅根据问题长度判断复杂度\n"
        "- \"帮我重构 Linux 系统\"看似简单实则复杂，需要判定为 complex\n"
        "- \"今天天气怎么样\"虽长但简单，需判定为 simple\n\n"
        "## 输出格式\n\n"
        "仅返回一个词：simple 或 complex，不要有任何其他内容。"
    )

    def __init__(
        self,
        config: ClassifierModelConfig,
        client: OpenAIClient,
        fallback_label: str = "complex",  # Safe default
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
        # Only simple and complex, default to complex (safe strategy)
        if label in ("simple", "easy", "low"):
            return "simple"
        else:
            return "complex"

    def _get_field_name(self) -> str:
        return "complexity"
```

- [ ] **Step 2: Commit the changes**

```bash
git add mini_router/signal_layer/classifier.py
git commit -m "refactor(signal): improve ComplexityClassifier prompt and remove medium level"
```

---

## Task 2: Update get_complexity_level() and helper methods in types.py

**Files:**
- Modify: `mini_router/signal_layer/types.py:66-79`

- [ ] **Step 1: Update get_complexity_level(), is_complex(), and is_simple() methods**

Replace the methods (lines 66-79) with:

```python
    def get_complexity_level(self) -> str:
        """Get the complexity level (simple/complex)."""
        if self.complexity is None:
            return "complex"  # Default to complex (safe strategy)
        label = self.complexity.label.lower()
        # Backward compatibility: medium treated as complex
        if label in ("simple", "easy", "low"):
            return "simple"
        return "complex"

    def is_complex(self) -> bool:
        """Check if the query is complex."""
        return self.get_complexity_level() == "complex"

    def is_simple(self) -> bool:
        """Check if the query is simple."""
        return self.get_complexity_level() == "simple"
```

- [ ] **Step 2: Commit the changes**

```bash
git add mini_router/signal_layer/types.py
git commit -m "refactor(types): update complexity helpers to remove medium level"
```

---

## Task 3: Update default fallback in router.py

**Files:**
- Modify: `mini_router/router/router.py:113`

- [ ] **Step 1: Update the default fallback from "medium" to "complex"**

Change line 113 from:
```python
complexity_fallback = classifier_config.complexity.fallback_label or "medium"
```

To:
```python
complexity_fallback = classifier_config.complexity.fallback_label or "complex"
```

- [ ] **Step 2: Commit the changes**

```bash
git add mini_router/router/router.py
git commit -m "refactor(router): change complexity default fallback to complex"
```

---

## Task 4: Update config.yaml

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Update complexity fallback_label**

Change line 37 from:
```yaml
      fallback_label: "medium"
```

To:
```yaml
      fallback_label: "complex"
```

- [ ] **Step 2: Update catch_all decision to remove medium condition**

Replace lines 165-181 with:

```yaml
  # 最终兜底: 无条件匹配所有请求
  - name: "catch_all"
    priority: -100
    rules:
      type: "or"
      children:
        - type: "signal"
          signal: "complexity"
          condition: "simple"
        - type: "signal"
          signal: "complexity"
          condition: "complex"
    model_refs:
      - model: "qwen3.5-plus"
        weight: 1.0
```

- [ ] **Step 3: Commit the changes**

```bash
git add config.yaml
git commit -m "chore: update config.yaml complexity fallback and remove medium condition"
```

---

## Task 5: Update test fixtures in conftest.py

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Update complexity fallback_label in basic_config fixture**

Find the complexity classifier config in basic_config fixture and change:
```python
fallback_label="medium",
```

To:
```python
fallback_label="complex",
```

- [ ] **Step 2: Commit the changes**

```bash
git add tests/conftest.py
git commit -m "test: update complexity fallback_label in test fixtures"
```

---

## Task 6: Update tests in test_classifier.py

**Files:**
- Modify: `tests/unit/test_classifier.py`

- [ ] **Step 1: Update test_complexity_default_fallback_is_medium**

Find and rename the test `test_complexity_default_fallback_is_medium` to `test_complexity_default_fallback_is_complex` and update the assertion:

```python
def test_complexity_default_fallback_is_complex(self):
    """Test that complexity classifier defaults to 'complex' fallback."""
    from mini_router.signal_layer.classifier import ComplexityClassifier
    assert ComplexityClassifier._get_default_fallback() == "complex"
```

- [ ] **Step 2: Update test_complexity_parse_response_normalizes_labels**

Update the test to remove medium case:

```python
def test_complexity_parse_response_normalizes_labels(self):
    """Test that complexity classifier normalizes labels correctly."""
    from mini_router.signal_layer.classifier import ComplexityClassifier

    # Create a minimal mock config
    config = ClassifierModelConfig(model="test", enabled=True)

    # Test normalization
    assert parse_complexity_response("Simple") == "simple"
    assert parse_complexity_response("EASY") == "simple"
    assert parse_complexity_response("low") == "simple"
    assert parse_complexity_response("Complex") == "complex"
    assert parse_complexity_response("HARD") == "complex"
    assert parse_complexity_response("difficult") == "complex"
    # Unknown labels should return "complex" (safe default)
    assert parse_complexity_response("unknown") == "complex"
    assert parse_complexity_response("medium") == "complex"  # medium now maps to complex
```

Note: If `parse_complexity_response` is not a standalone function, test the `_parse_response` method directly on a classifier instance.

- [ ] **Step 3: Run tests to verify**

```bash
pytest tests/unit/test_classifier.py -v -k complexity
```

Expected: All complexity-related tests pass

- [ ] **Step 4: Commit the changes**

```bash
git add tests/unit/test_classifier.py
git commit -m "test: update complexity classifier tests for new behavior"
```

---

## Task 7: Run full test suite and verify

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/unit/ -v
```

Expected: All tests PASS

- [ ] **Step 2: Run with coverage**

```bash
pytest tests/unit/ --cov=mini_router --cov-report=term-missing
```

Expected: Coverage report shows changes covered

- [ ] **Step 3: Commit if any fixes needed**

If any tests failed and needed fixes:

```bash
git add -A
git commit -m "fix: resolve test failures after complexity refactor"
```

---

## Task 8: Final commit and push

- [ ] **Step 1: Review all commits**

```bash
git log --oneline -10
```

- [ ] **Step 2: Push to remote**

```bash
git push origin refactor/signal-layer-unified-classifier
```

---

## Self-Review Checklist

1. **Spec coverage**:
   - New PROMPT with financial/banking scenarios: Task 1 ✓
   - Remove medium level: Task 1, 2 ✓
   - Default fallback to "complex": Task 1, 3, 4, 5 ✓
   - Update helper methods: Task 2 ✓
   - Update config: Task 4 ✓
   - Update tests: Task 6 ✓

2. **Placeholder scan**: No TBD, TODO, or vague descriptions ✓

3. **Type consistency**: All types and method signatures match across tasks ✓