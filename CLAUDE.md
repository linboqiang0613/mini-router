# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build, Test, and Lint Commands

```bash
# Install package with dev dependencies
pip install -e ".[dev]"

# Run all unit tests
python -m pytest tests/unit/ -v

# Run a specific test file
python -m pytest tests/unit/test_router.py -v

# Run a specific test
python -m pytest tests/unit/test_router.py::test_route_code_query -v

# Lint with ruff
ruff check mini_router/

# Format with ruff
ruff format mini_router/

# Type check with mypy
mypy mini_router/

# Start the HTTP server
mini-router-server --config config.yaml

# Run the CLI demo
mini-router
```

## Architecture Overview

Mini-Router implements a **Signal-Decision-Algorithm-Plugin** four-layer architecture for routing LLM requests to appropriate models.

### Layer Flow

1. **Signal Layer** (`mini_router/signal_layer/`) - Extracts structured signals from queries
   - `Classifier`: Abstract base class for all classifiers
   - `KeywordClassifier`: Fast keyword matching (no external API calls)
   - `MLClassifierBase`: Base for ML classifiers with timeout and fallback support
   - Specialized classifiers: `IntentClassifier`, `PIIClassifier`, `SecurityClassifier`, `ComplexityClassifier`
   - `UnifiedClassifier`: Composes multiple classifiers, runs them in parallel

   Each ML classifier has configurable `timeout` and `fallback_label`:
   - `timeout`: Max wait time for API call (1-60 seconds)
   - `fallback_label`: Default result when timeout/error occurs (safety-first defaults for PII/Security)

2. **Decision Layer** (`mini_router/decision/`) - Evaluates rule trees against signals
   - `Engine`: Evaluates decisions by priority (highest first)
   - `RuleEvaluator`: Handles AND/OR/NOT logic trees
   - Returns `DecisionResult` with candidate models or rejection

3. **Algorithm Layer** (`mini_router/algorithm/`) - Selects one model from candidates
   - `StaticSelector`: Weight-based probabilistic selection
   - `RoundRobinSelector`: Round-robin distribution
   - `LatencyAwareSelector`: Selects lowest-latency model based on recorded feedback

4. **Plugin Layer** (`mini_router/plugin/`) - Caching and metrics
   - `MemoryCache`: Exact-match caching
   - `SemanticCache`: Similarity-based caching using embeddings
   - `LatencyTracker`: Tracks TPOT/TTFT/latency percentiles for model selection

### Core Entry Points

- **Router** (`router/router.py`): Main orchestrator - coordinates all layers
- **Server** (`server.py`): FastAPI HTTP server with `/v1/route`, `/v1/chat/completions`, `/v1/feedback` endpoints
- **ChatProxy** (`proxy/chat_proxy.py`): OpenAI-compatible proxy that routes, calls model, and records latency

### Configuration

Configuration is YAML-driven (`config.yaml`). Key structures:
- `models.classifier`: ML classifier configs with `model`, `enabled`, `timeout`, `fallback_label` fields
- `signals.keyword_rules`: Keyword matching rules (ANY/ALL operators)
- `decisions`: Priority-sorted rules with `RuleNode` trees (AND/OR/NOT/KEYWORD/SIGNAL)
- `selection.strategy`: Selection method (`priority`, `weighted`, `latency_aware`)
- `cache`: Enable semantic caching with similarity threshold

**Safety-first defaults**: PII and Security classifiers default to `fallback_label: "detected"` on timeout/error, ensuring requests are blocked when detection fails. Complexity defaults to `"medium"` (neutral).

### Key Types

- `RouterConfig`: Root config (Pydantic model with `from_yaml()` method)
- `ClassifierModelConfig`: Per-classifier config with `timeout`, `fallback_label`
- `RuleNode`: Recursive rule tree structure
- `SignalMatches`: Aggregated classification results
- `RoutingRequest` / `RoutingResult`: Router input/output

### Routing Flow

```
Request → Cache Check → Signal Extraction → Decision Evaluation → Model Selection → Response
                     ↓
              If cache hit: return cached response directly
```

When adding new features:
- New classifiers: inherit from `Classifier` (or `MLClassifierBase` for API-based), implement `classify()` and `name`
- New selection strategies: add to `algorithm/selector.py` and register in `Registry`
- New rule types: add to `config/config.py` `RuleType` enum and `decision/engine.py` evaluator

## Testing Patterns

Tests use `pytest` with `pytest-asyncio`. Fixture `basic_config` in `tests/conftest.py` provides a minimal RouterConfig for testing. Most tests mock the OpenAI client to avoid real API calls.

## Line Length and Style

- Max line length: 100 characters (per ruff config)
- Python version: 3.11+
- Uses structlog for logging (not standard logging module)