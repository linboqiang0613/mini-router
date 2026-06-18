"""Pytest configuration and fixtures."""

import pytest
from unittest.mock import MagicMock

from mini_router.config.config import (
    ClassifierConfig,
    ClassifierModelConfig,
    Decision,
    KeywordRule,
    ModelRef,
    Operator,
    RouterConfig,
    RuleNode,
    RuleType,
    SelectionConfig,
    SignalsConfig,
)
from mini_router.tenant.types import TenantConfig


@pytest.fixture(autouse=True)
def mock_httpx_async_client():
    """Mock httpx.AsyncClient to avoid proxy issues in tests."""
    with pytest.MonkeyPatch.context() as m:
        m.setattr("httpx.AsyncClient", MagicMock)
        yield


@pytest.fixture
def basic_config() -> RouterConfig:
    """Create a basic router configuration for testing."""
    return RouterConfig(
        models={
            "base_url": "http://localhost:8000/v1",
            "classifier": ClassifierConfig(
                intent=ClassifierModelConfig(
                    model="intent-classifier",
                    enabled=True,
                    timeout=10.0,
                    fallback_label=None,
                ),
                pii=ClassifierModelConfig(
                    model="pii-classifier",
                    enabled=False,
                    timeout=10.0,
                    fallback_label="detected",
                ),
                security=ClassifierModelConfig(
                    model="security-classifier",
                    enabled=False,
                    timeout=10.0,
                    fallback_label="detected",
                ),
                complexity=ClassifierModelConfig(
                    model="complexity-classifier",
                    enabled=False,
                    timeout=10.0,
                    fallback_label="complex",
                ),
                context_length=ClassifierModelConfig(
                    model="context-length-classifier",
                    enabled=False,  # Disabled by default for existing tests
                    timeout=5.0,
                    fallback_label="short",
                    threshold=10000,
                ),
            ),
        },
        signals=SignalsConfig(
            keyword_rules=[
                KeywordRule(
                    name="code_related",
                    keywords=["code", "debug", "programming"],
                    operator=Operator.ANY,
                    case_sensitive=False,
                ),
                KeywordRule(
                    name="math_related",
                    keywords=["calculate", "math", "equation"],
                    operator=Operator.ANY,
                    case_sensitive=False,
                ),
            ],
        ),
        decisions=[
            Decision(
                name="route_to_code_model",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
                model_refs=[
                    ModelRef(model="codellama-70b", weight=1.0),
                ],
            ),
            Decision(
                name="route_to_math_model",
                priority=5,
                rules=RuleNode(type=RuleType.KEYWORD, name="math_related"),
                model_refs=[
                    ModelRef(model="llama-3-math", weight=1.0),
                ],
            ),
        ],
        cache={"enabled": False},
    )


@pytest.fixture
def basic_tenant() -> TenantConfig:
    """Tenant config carrying the routing decisions previously embedded in
    basic_config.decisions, plus a default SelectionConfig.

    Used by tests that exercise Router.route(decisions=tenant.decisions, ...).
    """
    return TenantConfig(
        tenant_id="t-test",
        apikey="sk-test",
        name="Test Tenant",
        enabled=True,
        base_url_template="http://localhost:8000/v1",
        timeout=120.0,
        decisions=[
            Decision(
                name="route_to_code_model",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
                model_refs=[
                    ModelRef(model="codellama-70b", weight=1.0),
                ],
            ),
            Decision(
                name="route_to_math_model",
                priority=5,
                rules=RuleNode(type=RuleType.KEYWORD, name="math_related"),
                model_refs=[
                    ModelRef(model="llama-3-math", weight=1.0),
                ],
            ),
        ],
        selection=SelectionConfig(),
    )