# Complexity Classifier Refactor Design

**Date**: 2026-04-02
**Author**: Claude Code
**Status**: Approved

## Summary

Refactor `ComplexityClassifier` to use improved prompt with better coverage of financial/banking scenarios, and simplify classification from 3 levels (simple/medium/complex) to 2 levels (simple/complex).

## Requirements

- Improve prompt to cover financial and banking business scenarios
- Remove "medium" classification level, only keep "simple" and "complex"
- Complexity should NOT be judged solely by query length
- Default fallback to "complex" (safe strategy)

## Complexity Definition

Based on task characteristics:

**Simple**: Single, clear task with unambiguous user intent, no deep reasoning or domain knowledge required.

**Complex**: Multi-step tasks, requires reasoning/planning, involves professional domain knowledge, or ambiguous intent.

### Complex Criteria (any one qualifies):

1. **Multi-step task**: Needs to be decomposed into subtasks, e.g., "Design an order system and write the database schema"
2. **Deep reasoning**: Requires logical reasoning, causal analysis, comparison, e.g., "Analyze the cause of this stock market fluctuation"
3. **Domain expertise**: Involves finance, banking, law, etc., requires professional knowledge
4. **Complex data processing**: Complex calculations, data analysis, multi-dimensional statistics
5. **Business process understanding**: Needs understanding of cross-system business processes
6. **Ambiguous intent**: User intent is unclear, needs clarification or deep context understanding
7. **High-impact decisions**: Involves important decision advice where errors have serious consequences

### Simple Criteria:

1. **Single clear task**: Clear user intent, one answer needed
2. **Common knowledge**: No professional background needed
3. **Simple information query**: Fact-checking, definitions, usage
4. **Format conversion**: Translation, rewriting, summarizing simple content

## Implementation Details

### New PROMPT

```python
PROMPT = """你是一个查询复杂度分析专家。请分析用户查询的复杂度，仅返回 "simple" 或 "complex"。

## 判断维度

### 判定为 "complex" 的条件（满足任一即可）：

1. **多步骤任务**：需要分解为多个子任务，如"帮我设计一个订单系统并写出数据库表结构"
2. **深度推理**：需要逻辑推理、因果分析、方案对比，如"分析这次股市波动的原因"
3. **专业领域知识**：涉及金融、银行、法律等专业领域，需要专业知识才能准确回答
4. **数据处理复杂**：涉及复杂计算、数据分析、多维度统计，如"计算这只债券的久期和凸性"
5. **业务流程理解**：需要理解跨系统业务流程，如"贷款审批流程中风险控制环节有哪些"
6. **模糊意图**：用户意图不明确，需要澄清或深度理解上下文
7. **高影响决策**：涉及重要决策建议，错误回答可能导致严重后果

### 判定为 "simple" 的条件：

1. **单一明确任务**：用户意图清晰，只需一个回答
2. **常识性问题**：无需专业背景即可回答
3. **简单信息查询**：查事实、查定义、查用法
4. **格式转换**：翻译、改写、总结简单内容

## 重要提示

- 不要仅根据问题长度判断复杂度
- "帮我重构 Linux 系统"看似简单实则复杂，需要判定为 complex
- "今天天气怎么样"虽长但简单，需判定为 simple

## 输出格式

仅返回一个词：simple 或 complex，不要有任何其他内容。"""
```

### Code Changes

#### `mini_router/signal_layer/classifier.py`

Update `ComplexityClassifier`:

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

#### `mini_router/signal_layer/types.py`

Update `get_complexity_level()`:

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

#### `mini_router/router/router.py`

Update default fallback:

```python
complexity_fallback = classifier_config.complexity.fallback_label or "complex"
```

#### `config.yaml`

Update complexity classifier config:

```yaml
complexity:
  model: "qwen3.5-plus"
  enabled: true
  timeout: 8.0
  fallback_label: "complex"
```

Update decisions to remove "medium" conditions.

## File Changes Summary

| File | Changes |
|------|---------|
| `mini_router/signal_layer/classifier.py` | Update PROMPT, `_parse_response()`, default fallback_label |
| `mini_router/signal_layer/types.py` | Update `get_complexity_level()`, `is_complex()`, `is_simple()` |
| `mini_router/router/router.py` | Update default fallback |
| `config.yaml` | Update fallback_label and decision conditions |
| `tests/conftest.py` | Update test fixtures |
| `tests/unit/test_classifier.py` | Update tests for new behavior |

## Testing

- Verify prompt correctly classifies financial/banking scenarios as complex
- Verify short but complex queries (e.g., "重构 Linux 系统") are classified as complex
- Verify simple queries are correctly identified
- Verify fallback behavior returns "complex"

## Open Questions

None. Design approved by user on 2026-04-02.