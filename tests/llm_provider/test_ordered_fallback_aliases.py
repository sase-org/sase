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
                "builtin": {
                    "fallback": (
                        "claude/claude-fable-5@high || codex/gpt-5.6-sol@medium"
                    )
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
                "builtin": {
                    "outer": "@inner | claude/opus",
                    "inner": "codex/o3 | claude/sonnet",
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
                "builtin": {
                    "outer": "@inner || claude/opus",
                    "inner": "codex/o3 || claude/sonnet",
                    "mixed": "claude/opus | codex/o3 || claude/sonnet",
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
                "builtin": {
                    "primary": "missing-provider/frontier@xhigh",
                    "fallback": "@primary || codex/gpt-5.6-sol@medium",
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
        {"provider": "claude", "model_aliases": {"builtin": chain}},
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
                "builtin": {"fallback": ("claude/claude-fable-5 || codex/gpt-5.6-sol")}
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


@pytest.mark.parametrize(
    ("available", "expected_target"),
    [
        (
            {"claude/opus", "codex/gpt-5.6-sol", "grok/grok-4.6"},
            "claude/opus",
        ),
        (
            {"codex/gpt-5.6-sol", "grok/grok-4.6"},
            "codex/gpt-5.6-sol",
        ),
        (
            {"grok/grok-4.6"},
            "grok/grok-4.6",
        ),
    ],
)
def test_shipped_smartest_ordered_fallback_selects_by_availability(
    real_model_alias_defaults: None,
    monkeypatch: pytest.MonkeyPatch,
    available: set[str],
    expected_target: str,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"builtin": {}}},
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target in available,
    )

    resolved = resolve_model_alias_with_effort("@smartest", consume=True)
    assert (resolved.target, resolved.effort) == (expected_target, "max")
