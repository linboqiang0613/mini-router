# Context Length Signal Design

**Date**: 2026-04-01
**Author**: Claude Code
**Status**: Approved

## Summary

Add a `ContextLengthClassifier` signal to route requests based on conversation token count. This enables routing to appropriate models based on context length and prevents requests from failing due to exceeding model max_tokens limits.

## Requirements

- Calculate token count from `ChatRequest.messages` using HuggingFace tokenizer
- Output binary labels: `short` / `long` based on configurable threshold
- Support max_tokens filtering at Selection layer
- Parallel execution with other classifiers (no blocking)
- Thread-safe for concurrent requests

## Architecture

### Component Integration

```
UnifiedClassifier
  ├── KeywordClassifier (local)
  ├── IntentClassifier (API)
  ├── PIIClassifier (API)
  ├── SecurityClassifier (API)
  ├── ComplexityClassifier (API)
  └── ContextLengthClassifier (local tokenizer)  ← NEW
```

### Data Flow

1. Router receives `ChatRequest` with `messages`
2. **ContextLengthClassifier receives messages as concatenated text**: All message contents are joined with role prefixes (e.g., "user: ...\nassistant: ...\nuser: ...")
3. ContextLengthClassifier calculates total token count using HuggingFace tokenizer
4. Output label (`short`/`long`) based on threshold comparison and store `token_count` in metadata
5. Decision engine matches rules based on label
6. Selection layer filters candidates by `max_tokens` using `token_count` from SignalMatches.context_length.metadata

### Input Format for ContextLengthClassifier

Since Classifier interface receives `text: str`, messages must be formatted before passing:

```python
def _format_messages_for_tokenizer(messages: list[ChatMessage]) -> str:
    """Format messages into single text string for token counting."""
    formatted = []
    for msg in messages:
        formatted.append(f"{msg.role}: {msg.content}")
    return "\n".join(formatted)
```

This format matches typical chat template structure, ensuring accurate token count calculation.

## Configuration

### ModelsConfig

```yaml
models:
  base_url: "http://localhost:8000/v1"
  tokenizer_path: "/path/to/Qwen3-tokenizer"  # NEW: HuggingFace tokenizer directory
  classifier:
    context_length:                           # NEW: classifier config
      enabled: true
      threshold: 10000                        # NEW: <10000 = short, >=10000 = long
      timeout: 5.0
      fallback_label: "short"                 # default on error
```

### ModelRef

```yaml
decisions:
  - name: route_to_short_context
    priority: 10
    rules:
      type: signal
      signal: context_length
      condition: "short"
    model_refs:
      - model: Qwen3-7B
        weight: 1.0
        max_tokens: 8192                      # NEW: optional max limit

  - name: route_to_long_context
    priority: 5
    rules:
      type: signal
      signal: context_length
      condition: "long"
    model_refs:
      - model: Qwen3-72B
        weight: 1.0
        max_tokens: 32768                     # NEW: optional max limit
```

## Implementation Details

### ContextLengthClassifier

```python
class ContextLengthClassifier(Classifier):
    """Token-based context length classifier using HuggingFace tokenizer."""

    def __init__(
        self,
        tokenizer_path: str,
        threshold: int = 10000,
        fallback_label: str = "short",
    ) -> None:
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        self.threshold = threshold
        self._fallback_label = fallback_label

    @property
    def name(self) -> str:
        return "context_length"

    async def classify(self, text: str) -> SignalMatches:
        """Calculate token count and return short/long label."""
        try:
            token_count = len(self.tokenizer.encode(text))
            label = "long" if token_count >= self.threshold else "short"
            return SignalMatches(
                context_length=TaskResult(
                    task=TaskType.CONTEXT_LENGTH,
                    label=label,
                    confidence=1.0,
                    metadata={"token_count": token_count},
                )
            )
        except Exception as e:
            logger.error("context_length_classifier_error", error=str(e))
            return SignalMatches(
                context_length=TaskResult(
                    task=TaskType.CONTEXT_LENGTH,
                    label=self._fallback_label,
                    confidence=0.0,
                    metadata={"fallback": True},
                )
            )
```

### Selection Layer Filtering

Selection layer retrieves `token_count` from `SignalMatches.context_length.metadata`:

```python
def _filter_by_max_tokens(
    candidates: list[ModelRef],
    signals: SignalMatches
) -> list[ModelRef]:
    """Filter candidates by max_tokens constraint."""
    # Get token_count from context_length result
    token_count = None
    if signals.context_length and signals.context_length.metadata:
        token_count = signals.context_length.metadata.get("token_count")

    if token_count is None:
        return candidates  # No token info, skip filtering

    filtered = [
        m for m in candidates
        if m.max_tokens is None or m.max_tokens >= token_count
    ]

    if not filtered:
        logger.warning(
            "all_models_exceed_max_tokens",
            token_count=token_count,
            candidates=[m.model for m in candidates],
            fallback="using_first_candidate",
        )
        return [candidates[0]]

    return filtered
```

### Concurrent Safety

HuggingFace fast tokenizer (Rust-based) `encode()` method is thread-safe:
- Read-only operation, no internal state modification
- Multiple concurrent requests do not interfere
- Tokenizer instance loaded once at initialization, reused for all requests

## File Changes

| File | Changes |
|------|---------|
| `pyproject.toml` | Add `transformers>=5.0` dependency |
| `mini_router/signal_layer/types.py` | Add `TaskType.CONTEXT_LENGTH`, `SignalMatches.context_length` field |
| `mini_router/config/config.py` | Add `ModelsConfig.tokenizer_path`, `ClassifierConfig.context_length`, `ModelRef.max_tokens` |
| `mini_router/signal_layer/classifier.py` | Add `ContextLengthClassifier` class |
| `mini_router/router/router.py` | Initialize `ContextLengthClassifier` in `_initialize_components()` |
| `mini_router/decision/engine.py` | Add context_length signal evaluation in `_evaluate_signal_rule()` |
| `mini_router/algorithm/selector.py` | Add `_filter_by_max_tokens()` in selection logic |
| `tests/unit/test_classifier.py` | Add tests for ContextLengthClassifier |
| `tests/unit/test_selector.py` | Add tests for max_tokens filtering |

## Testing

### Unit Tests

- ContextLengthClassifier token calculation accuracy
- Threshold boundary cases (exactly at threshold)
- Fallback behavior on tokenizer error
- Selection layer max_tokens filtering
- All-filtered fallback to first candidate

### Integration Tests

- Full routing flow: short text → short model pool
- Full routing flow: long text → long model pool
- Concurrent request handling

## Dependencies

```toml
[project.dependencies]
transformers = ">=5.0"  # HuggingFace tokenizer with fast tokenizer support
```

## Open Questions

None. Design approved by user on 2026-04-01.