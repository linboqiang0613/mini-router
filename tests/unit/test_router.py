"""Tests for main router."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from mini_router.config.config import (
    Decision,
    DecisionAction,
    KeywordRule,
    ModelRef,
    Operator,
    RouterConfig,
    RuleNode,
    RuleType,
)
from mini_router.request_log_context import bind_request_log_context, reset_request_log_context
from mini_router.router.router import Router, RoutingRequest


class TestRouter:
    """Tests for Router."""

    @pytest.mark.asyncio
    async def test_basic_routing(
        self, basic_config: RouterConfig, basic_tenant
    ) -> None:
        """Test basic routing flow."""
        router = Router(basic_config)

        result = await router.route(
            RoutingRequest(query="How do I debug this code?"),
            decisions=basic_tenant.decisions,
            selection=basic_tenant.selection,
        )

        assert result.cache_hit is False
        assert result.selected_model == "codellama-70b"
        assert result.decision_name == "route_to_code_model"
        assert "code_related" in result.matched_rules

    @pytest.mark.asyncio
    async def test_no_matching_decision(
        self, basic_config: RouterConfig, basic_tenant
    ) -> None:
        """Test when no decision matches."""
        router = Router(basic_config)

        result = await router.route(
            RoutingRequest(query="What is the weather today?"),
            decisions=basic_tenant.decisions,
            selection=basic_tenant.selection,
        )

        assert result.selected_model is None
        assert result.decision_name is None

    @pytest.mark.asyncio
    async def test_reject_action(self) -> None:
        """Test reject action."""
        reject_decisions = [
            Decision(
                name="reject_blocked",
                priority=100,
                rules=RuleNode(type=RuleType.KEYWORD, name="blocked"),
                model_refs=[],
                action=DecisionAction.REJECT,
                reject_message="Content blocked",
            ),
        ]
        config = RouterConfig(
            models={
                "base_url": "http://localhost:8000/v1",
            },
            signals={
                "keyword_rules": [
                    KeywordRule(
                        name="blocked",
                        keywords=["blocked_word"],
                        operator=Operator.ANY,
                    ),
                ],
            },
            cache={"enabled": False},
        )

        router = Router(config)
        result = await router.route(
            RoutingRequest(query="This contains blocked_word"),
            decisions=reject_decisions,
        )

        assert result.action == DecisionAction.REJECT
        assert result.reject_message == "Content blocked"

    @pytest.mark.asyncio
    async def test_cache_set_and_hit(
        self, basic_config: RouterConfig, basic_tenant
    ) -> None:
        """Test cache set and hit."""
        # Enable cache for this test
        basic_config.cache.enabled = True

        router = Router(basic_config)

        # Set cache
        await router.set_cache("cached query", "cached response")

        # Should get cache hit
        result = await router.route(
            RoutingRequest(query="cached query"),
            decisions=basic_tenant.decisions,
            selection=basic_tenant.selection,
        )
        assert result.cache_hit is True
        assert result.cache_response == "cached response"

    @pytest.mark.asyncio
    async def test_clear_cache(
        self, basic_config: RouterConfig, basic_tenant
    ) -> None:
        """Test cache clearing."""
        basic_config.cache.enabled = True
        router = Router(basic_config)

        await router.set_cache("query", "response")
        router.clear_cache()

        result = await router.route(
            RoutingRequest(query="query"),
            decisions=basic_tenant.decisions,
            selection=basic_tenant.selection,
        )
        assert result.cache_hit is False

    @pytest.mark.asyncio
    async def test_priority_ordering(self) -> None:
        """Test that higher priority decisions are evaluated first."""
        priority_decisions = [
            Decision(
                name="urgent_route",
                priority=100,
                rules=RuleNode(type=RuleType.KEYWORD, name="urgent"),
                model_refs=[ModelRef(model="urgent-model", weight=1.0)],
            ),
            Decision(
                name="code_route",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code"),
                model_refs=[ModelRef(model="code-model", weight=1.0)],
            ),
        ]
        config = RouterConfig(
            models={"base_url": "http://localhost:8000/v1"},
            signals={
                "keyword_rules": [
                    KeywordRule(name="code", keywords=["code"], operator=Operator.ANY),
                    KeywordRule(name="urgent", keywords=["urgent"], operator=Operator.ANY),
                ],
            },
            cache={"enabled": False},
        )

        router = Router(config)

        # Both keywords match, but urgent has higher priority
        result = await router.route(
            RoutingRequest(query="urgent code request"),
            decisions=priority_decisions,
        )
        assert result.decision_name == "urgent_route"

    @pytest.mark.asyncio
    async def test_request_routed_log_includes_request_id(self) -> None:
        """Routing logs should include the active request_id when present."""
        log_decisions = [
            Decision(
                name="code_route",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code"),
                model_refs=[ModelRef(model="code-model", weight=1.0)],
            ),
        ]
        config = RouterConfig(
            models={"base_url": "http://localhost:8000/v1"},
            signals={
                "keyword_rules": [
                    KeywordRule(name="code", keywords=["code"], operator=Operator.ANY),
                ],
            },
            cache={"enabled": False},
        )
        router = Router(config)
        token = bind_request_log_context(request_id="req-router")

        try:
            with pytest.MonkeyPatch.context() as m:
                mock_info = MagicMock()
                m.setattr("mini_router.router.router.logger.info", mock_info)
                await router.route(
                    RoutingRequest(query="code request"),
                    decisions=log_decisions,
                )
        finally:
            reset_request_log_context(token)

        routed_call = next(
            call for call in mock_info.call_args_list if call.args[0] == "request_routed"
        )
        assert routed_call.kwargs["request_id"] == "req-router"


class TestRouterSignalLayerInit:
    """Tests for Router signal layer initialization."""

    def test_router_creates_unified_classifier(self, basic_config: RouterConfig) -> None:
        """Test Router creates UnifiedClassifier with classifiers list."""
        from mini_router.router.router import Router
        router = Router(basic_config)
        from mini_router.signal_layer.classifier import UnifiedClassifier
        assert isinstance(router.classifier, UnifiedClassifier)

    def test_router_includes_keyword_classifier(self, basic_config: RouterConfig) -> None:
        """Test Router includes KeywordClassifier in unified classifier."""
        from mini_router.router.router import Router
        router = Router(basic_config)
        # Check that keyword classifier is present
        classifier_names = [c.name for c in router.classifier.classifiers]
        assert "keyword" in classifier_names


class TestRouterTenantDecisions:
    """Tests for Router with tenant-specific decisions."""

    @pytest.mark.asyncio
    async def test_route_with_tenant_decisions(self, basic_config: RouterConfig) -> None:
        """Test routing with tenant-specific decisions overrides default."""
        router = Router(basic_config)

        # Create tenant-specific decisions that route to a different model
        tenant_decisions = [
            Decision(
                name="tenant_code_route",
                priority=100,
                rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
                model_refs=[ModelRef(model="tenant-specific-model", weight=1.0)],
            ),
        ]

        # Route with tenant decisions
        result = await router.route(
            RoutingRequest(query="How do I debug this code?"),
            decisions=tenant_decisions,
        )

        assert result.cache_hit is False
        assert result.selected_model == "tenant-specific-model"
        assert result.decision_name == "tenant_code_route"

    @pytest.mark.asyncio
    async def test_route_without_tenant_decisions_uses_default(
        self, basic_config: RouterConfig, basic_tenant
    ) -> None:
        """Test routing with tenant decisions matching basic_tenant fixture."""
        router = Router(basic_config)

        # Route with the basic_tenant decisions (mirror of former basic_config.decisions)
        result = await router.route(
            RoutingRequest(query="How do I debug this code?"),
            decisions=basic_tenant.decisions,
            selection=basic_tenant.selection,
        )

        assert result.cache_hit is False
        assert result.selected_model == "codellama-70b"  # From basic_tenant
        assert result.decision_name == "route_to_code_model"

    @pytest.mark.asyncio
    async def test_tenant_decisions_priority_ordering(self) -> None:
        """Test tenant decisions are evaluated by priority."""
        config = RouterConfig(
            models={"base_url": "http://localhost:8000/v1"},
            signals={
                "keyword_rules": [
                    KeywordRule(name="code", keywords=["code"], operator=Operator.ANY),
                    KeywordRule(name="urgent", keywords=["urgent"], operator=Operator.ANY),
                ],
            },
            decisions=[  # Default decisions (should be ignored)
                Decision(
                    name="default_route",
                    priority=1,
                    rules=RuleNode(type=RuleType.KEYWORD, name="code"),
                    model_refs=[ModelRef(model="default-model", weight=1.0)],
                ),
            ],
            cache={"enabled": False},
        )

        router = Router(config)

        # Tenant decisions with different priority
        tenant_decisions = [
            Decision(
                name="tenant_urgent",
                priority=100,
                rules=RuleNode(type=RuleType.KEYWORD, name="urgent"),
                model_refs=[ModelRef(model="tenant-urgent-model", weight=1.0)],
            ),
            Decision(
                name="tenant_code",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code"),
                model_refs=[ModelRef(model="tenant-code-model", weight=1.0)],
            ),
        ]

        # Both keywords match, but urgent has higher priority
        result = await router.route(
            RoutingRequest(query="urgent code request"),
            decisions=tenant_decisions,
        )

        assert result.decision_name == "tenant_urgent"
        assert result.selected_model == "tenant-urgent-model"

    @pytest.mark.asyncio
    async def test_empty_tenant_decisions_returns_no_match(
        self, basic_config: RouterConfig
    ) -> None:
        """Test that empty tenant decisions list results in no match."""
        router = Router(basic_config)

        # Empty tenant decisions
        result = await router.route(
            RoutingRequest(query="How do I debug this code?"),
            decisions=[],
        )

        assert result.selected_model is None
        assert result.decision_name is None
        assert result.confidence == 0.0


class TestRouterReloadConfig:
    """Test Router.reload_config method."""

    @pytest.fixture
    def mock_repo(self):
        """Create mock repository."""
        repo = MagicMock()
        repo.get_global_config = AsyncMock(return_value={
            "config_data": {
                "server": {"host": "0.0.0.0", "port": 8080},
                "models": {"base_url": "https://api.new.com"},
                "decisions": [],
            },
            "version": 10,
        })
        return repo

    @pytest.mark.asyncio
    async def test_reload_config_updates_config(self, mock_repo):
        """Test reload_config updates Router.config."""
        old_config = RouterConfig()
        router = Router(old_config, repository=mock_repo)

        await router.reload_config()

        assert router.config.models.base_url == "https://api.new.com"
        mock_repo.get_global_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_reload_config_without_repository_logs_warning(self):
        """Test reload_config logs warning when no repository."""
        config = RouterConfig()
        router = Router(config, repository=None)

        await router.reload_config()

        # Should not raise, just log warning
        assert router.config == config  # unchanged

    @pytest.mark.asyncio
    async def test_reload_config_when_config_not_found(self, mock_repo):
        """Test reload_config when database returns None."""
        mock_repo.get_global_config = AsyncMock(return_value=None)

        config = RouterConfig()
        router = Router(config, repository=mock_repo)

        await router.reload_config()

        # Should not crash, config unchanged
        assert router.config == config

    @pytest.mark.asyncio
    async def test_reload_config_handles_exception(self, mock_repo):
        """Test reload_config handles exception gracefully."""
        mock_repo.get_global_config = AsyncMock(side_effect=Exception("DB error"))

        config = RouterConfig()
        router = Router(config, repository=mock_repo)

        await router.reload_config()

        # Should not crash, config unchanged
        assert router.config == config
