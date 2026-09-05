"""Ordered-fallback model-alias resolution and validation tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import (
    resolve_model_alias,
    resolve_model_alias_with_effort,
    validate_model_alias_selector_value,
)
from sase.llm_provider.load_balancing import parse_model_alias_selector
from sase.llm_provider.model_alias_policy import (
    XLARGE_MODEL_ALIAS_NAME,
    implicit_alias_targets,
)
from sase.llm_provider.registry import resolve_model_provider_with_effort
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_ordered_fallback_selects_first_available_without_cursor_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "fallback": (
                        {
                            "model": (
                                "claude/claude-fable-5@high || codex/gpt-5.6-sol@medium"
                            ),
                            "description": "Test fallback.",
                        }
                    ),
                }
            },
        },
    )
    llm_config._get_model_aliases_for_token.cache_clear()
    available: set[str] = {"claude/claude-fable-5"}
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target in available,
    )

    from sase.llm_provider import load_balancing

    locked_state = MagicMock(side_effect=AssertionError("fallback read cursor state"))
    monkeypatch.setattr(load_balancing, "_locked_state", locked_state)

    first = resolve_model_alias_with_effort("@fallback", consume=True)
    assert (first.target, first.effort) == ("claude/claude-fable-5", "high")
    assert resolve_model_alias("@fallback", consume=True) == "claude/claude-fable-5"

    available.clear()
    available.add("codex/gpt-5.6-sol")
    second = resolve_model_alias_with_effort("@fallback", consume=True)
    assert (second.target, second.effort) == ("codex/gpt-5.6-sol", "medium")

    available.clear()
    assert resolve_model_alias("@fallback", consume=True) == ("claude/claude-fable-5")
    locked_state.assert_not_called()


def test_nested_pool_fails_closed_and_validation_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "outer": {
                        "model": "@inner | claude/opus",
                        "description": "Outer pool.",
                    },
                    "inner": {
                        "model": "codex/o3 | claude/sonnet",
                        "description": "Inner pool.",
                    },
                }
            },
        },
    )
    assert resolve_model_alias("@outer") == "@outer"
    assert (
        "nested load-balanced pool '@inner'"
        in validate_model_alias_selector_value("outer", "@inner | claude/opus")[0]
    )


def test_nested_fallback_and_mixed_selectors_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "outer": {
                        "model": "@inner || claude/opus",
                        "description": "Outer fallback.",
                    },
                    "inner": {
                        "model": "codex/o3 || claude/sonnet",
                        "description": "Inner fallback.",
                    },
                    "mixed": {
                        "model": "claude/opus | codex/o3 || claude/sonnet",
                        "description": "Mixed selector.",
                    },
                }
            },
        },
    )

    assert resolve_model_alias("@outer") == "@outer"
    assert (
        "nested ordered fallback '@inner'"
        in (validate_model_alias_selector_value("outer", "@inner || claude/opus")[0])
    )
    assert resolve_model_alias("@mixed") == "@mixed"
    assert (
        "cannot mix"
        in validate_model_alias_selector_value(
            "mixed", "claude/opus | codex/o3 || claude/sonnet"
        )[0]
    )


def test_fallback_members_support_alias_chains_and_explicit_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "primary": {
                        "model": "missing-provider/frontier@xhigh",
                        "description": "Primary.",
                    },
                    "fallback": {
                        "model": "@primary || codex/gpt-5.6-sol@medium",
                        "description": "Fallback.",
                    },
                }
            },
        },
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: False,
    )

    assert resolve_model_provider_with_effort("@fallback") == (
        "missing-provider",
        "frontier",
        "xhigh",
    )


def test_fallback_validation_reports_cycles_and_depth_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = {f"hop_{index}": f"@hop_{index + 1}" for index in range(17)}
    chain["hop_17"] = "claude/opus"
    chain.update({"cycle_a": "@cycle_b", "cycle_b": "@cycle_a"})
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    alias: {"model": target, "description": alias}
                    for alias, target in chain.items()
                }
            },
        },
    )

    cycle_errors = validate_model_alias_selector_value(
        "owner", "@cycle_a || codex/gpt-5.6-sol"
    )
    depth_errors = validate_model_alias_selector_value(
        "owner", "@hop_0 || codex/gpt-5.6-sol"
    )

    assert "creates an alias cycle" in cycle_errors[0]
    assert "exceeds the alias resolution depth limit" in depth_errors[0]


def test_launch_and_temporary_overrides_suspend_ordered_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "fallback": {
                        "model": "claude/claude-fable-5 || codex/gpt-5.6-sol",
                        "description": "Fallback.",
                    }
                }
            },
        },
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    assert (
        resolve_model_alias("@fallback", {"fallback": "codex/o3"}, consume=True)
        == "codex/o3"
    )

    override = MagicMock(provider="claude", model="opus")
    monkeypatch.setattr(
        llm_config,
        "_active_alias_overrides",
        lambda: {"fallback": override},
    )
    assert resolve_model_alias("@fallback", consume=True) == "claude/opus"


def test_shipped_xlarge_pool_uses_last_resort_grok(
    real_model_alias_defaults: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped `@xlarge` round-robins Fable/Astra, with Grok as last resort."""
    selector = parse_model_alias_selector(
        implicit_alias_targets()[XLARGE_MODEL_ALIAS_NAME]
    )
    assert selector is not None
    assert selector.members == (
        "claude/claude-fable-5@xhigh",
        "codex/gpt-6-astra@xhigh",
    )
    assert selector.fallback_members == ("grok/grok-4.6@xhigh",)

    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"builtin": {}}},
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    for _ in range(4):
        selected = resolve_model_alias("@xlarge", consume=True)
        assert not selected.startswith("grok/")

    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )
    only_codex = resolve_model_alias_with_effort("@xlarge", consume=True)
    assert (only_codex.target, only_codex.effort) == ("codex/gpt-6-astra", "xhigh")

    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("grok/"),
    )
    diverted = resolve_model_alias_with_effort("@xlarge", consume=True)
    assert (diverted.target, diverted.effort) == ("grok/grok-4.6", "xhigh")
