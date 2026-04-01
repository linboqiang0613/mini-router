"""CLI entry point for mini-router."""

import asyncio
import json

import structlog

from mini_router.config.config import Decision, KeywordRule, ModelRef, Operator, RouterConfig, RuleNode, RuleType
from mini_router.router.router import Router, RoutingRequest

logger = structlog.get_logger()


def create_demo_config() -> RouterConfig:
    """Create a demo configuration for testing."""
    return RouterConfig(
        models={
            "base_url": "http://localhost:8000/v1",
            "classifier": {
                "intent": {"model": "intent-classifier", "enabled": True},
                "pii": {"model": "pii-classifier", "enabled": True},
                "security": {"model": "security-classifier", "enabled": True},
            },
        },
        signals={
            "keyword_rules": [
                KeywordRule(
                    name="code_related",
                    keywords=["code", "programming", "function", "debug", "error"],
                    operator=Operator.ANY,
                    case_sensitive=False,
                ),
                KeywordRule(
                    name="math_related",
                    keywords=["calculate", "math", "equation", "solve"],
                    operator=Operator.ANY,
                    case_sensitive=False,
                ),
            ],
        },
        decisions=[
            Decision(
                name="route_to_code_model",
                priority=10,
                rules=RuleNode(type=RuleType.KEYWORD, name="code_related"),
                model_refs=[
                    ModelRef(model="codellama-70b", weight=1.0),
                    ModelRef(model="deepseek-coder", weight=0.8),
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
            Decision(
                name="default_route",
                priority=1,
                rules=RuleNode(type=RuleType.OR, children=[
                    RuleNode(type=RuleType.KEYWORD, name="code_related"),
                    RuleNode(type=RuleType.KEYWORD, name="math_related"),
                ]),
                model_refs=[
                    ModelRef(model="llama-3-70b", weight=1.0),
                ],
            ),
        ],
        selection={"strategy": "priority"},
        cache={"enabled": True, "similarity_threshold": 0.95},
    )


async def run_demo() -> None:
    """Run the demo."""
    print("=" * 60)
    print("Mini-Router Demo (Python)")
    print("=" * 60)
    print()

    # Create router with demo config
    config = create_demo_config()
    router = Router(config)

    # Demo queries
    queries = [
        "How do I debug this Python code?",
        "Calculate the square root of 144",
        "What is the weather today?",
    ]

    print("Routing Queries:")
    print("-" * 60)

    for query in queries:
        print(f"\nQuery: {query!r}")

        result = await router.route(RoutingRequest(query=query))

        if result.cache_hit:
            print(f"  Cache Hit: {result.cache_response}")
        elif result.action.value == "reject":
            print(f"  Rejected: {result.reject_message}")
        else:
            print(f"  Selected Model: {result.selected_model}")
            print(f"  Decision: {result.decision_name}")
            print(f"  Confidence: {result.confidence:.2f}")
            print(f"  Matched Rules: {result.matched_rules}")

    # Demo cache functionality
    print()
    print("=" * 60)
    print("Cache Demo")
    print("-" * 60)

    await router.set_cache("What is 2+2?", "The answer is 4")
    print("\nStored: 'What is 2+2?' -> 'The answer is 4'")

    # Test cache hit
    result = await router.route(RoutingRequest(query="What is 2+2?"))
    if result.cache_hit:
        print(f"Cache Hit: {result.cache_response}")

    # Print configuration summary
    print()
    print("=" * 60)
    print("Configuration Summary")
    print("-" * 60)
    config_dict = config.model_dump()
    print(json.dumps(config_dict, indent=2, default=str))


def main() -> None:
    """Main entry point."""
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()