"""Tests for SASE's built-in size model aliases."""

from __future__ import annotations

import pytest

from sase.llm_provider.config import (
    BUILTIN_MODEL_ALIAS_NAMES,
    DEFAULT_MODEL_FIELD,
    default_model_alias_name,
    get_big_epic_lander_model,
    get_default_model,
    get_epic_lander_model,
    implicit_model_alias_fallback,
    implicit_model_alias_fallback_effort,
    implicit_model_alias_fallback_reference,
    implicit_model_alias_value,
    launch_model_setting_override_key,
    resolve_model_alias,
    resolve_model_alias_with_effort,
    role_model_directive_value,
)
from sase.llm_provider.load_balancing import parse_model_alias_selector
from sase.llm_provider.model_alias_policy import (
    implicit_alias_targets,
    role_alias_fallbacks,
)
from sase.llm_provider.registry import resolve_model_provider
from tests._model_alias_defaults_fixture import (
    FROZEN_TARGETS,
    frozen_selector_member,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_size_alias_helpers() -> None:
    fallbacks = role_alias_fallbacks()
    targets = implicit_alias_targets()

    assert default_model_alias_name() == "default"
    assert not fallbacks
    assert set(targets) == set(BUILTIN_MODEL_ALIAS_NAMES)
    for alias in BUILTIN_MODEL_ALIAS_NAMES:
        assert role_model_directive_value(alias) == f"@{alias}"
        assert implicit_model_alias_fallback(alias) is None
        assert implicit_model_alias_fallback_reference(alias) is None
        assert implicit_model_alias_fallback_effort(alias) is None
        assert implicit_model_alias_value(alias) == FROZEN_TARGETS[alias]

    assert implicit_model_alias_value("default") is None
    assert implicit_model_alias_value("medium_worker") is None


def test_size_aliases_own_selector_targets() -> None:
    targets = implicit_alias_targets()

    for alias in ("xsmall", "small", "medium", "large"):
        selector = parse_model_alias_selector(targets[alias])
        assert selector is not None
        assert selector.mode == "round_robin"

    selector = parse_model_alias_selector(targets["xlarge"])
    assert selector is not None
    assert selector.mode == "fallback"


def test_configured_size_alias_resolves_to_configured_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"medium": "codex/gpt-5.6-sol"}},
        },
    )

    assert resolve_model_alias("medium") == "codex/gpt-5.6-sol"
    assert resolve_model_provider("medium") == ("codex", "gpt-5.6-sol")


def test_size_alias_resolves_through_shipped_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider.model_alias_resolution.select_model_alias_pool_member",
        lambda *_args, **_kwargs: 0,
    )

    resolved = resolve_model_alias_with_effort("@medium")

    assert (resolved.target, resolved.effort) == frozen_selector_member("medium", 0)


def test_size_alias_outer_effort_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider.model_alias_resolution.select_model_alias_pool_member",
        lambda *_args, **_kwargs: 0,
    )

    resolved = resolve_model_alias_with_effort("@medium@low")

    target, _effort = frozen_selector_member("medium", 0)
    assert (resolved.target, resolved.effort) == (target, "low")


def test_alias_reference_effort_overrides_target_and_chain_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"medium": "claude/opus@high"},
                "custom": {
                    "focused": {
                        "model": "@medium",
                        "description": "Focused custom alias.",
                    }
                },
            },
        },
    )

    medium = resolve_model_alias_with_effort("@medium")
    medium_outer = resolve_model_alias_with_effort("@medium@medium")
    focused = resolve_model_alias_with_effort("@focused")
    focused_outer = resolve_model_alias_with_effort("@focused@low")

    assert (medium.target, medium.effort) == ("claude/opus", "high")
    assert (medium_outer.target, medium_outer.effort) == ("claude/opus", "medium")
    assert (focused.target, focused.effort) == ("claude/opus", "high")
    assert (focused_outer.target, focused_outer.effort) == ("claude/opus", "low")


def test_retired_role_aliases_are_not_implicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    for alias in (
        "default",
        "epic_lander",
        "big_epic_lander",
        "medium_worker",
        "smart",
        "cheap",
        "coder",
        "claude_coder",
    ):
        assert resolve_model_alias(alias) == alias


def test_retired_builtin_config_is_ignored_but_custom_alias_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"medium_worker": "codex/o3"},
                "custom": {
                    "worker": {
                        "model": "claude/sonnet",
                        "description": "Explicit custom phase role.",
                    }
                },
            },
        },
    )

    assert resolve_model_alias("medium_worker") == "medium_worker"
    assert resolve_model_alias("worker") == "claude/sonnet"


def test_launch_model_setting_accessors_validate_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "default_model": "@medium",
            "epic_lander_model": "codex/o3",
            "big_epic_lander_model": "bad || || value",
        },
    )

    assert get_default_model() == "@medium"
    assert get_epic_lander_model() == "codex/o3"
    assert get_big_epic_lander_model() == "@xlarge"


def test_launch_setting_override_uses_namespaced_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    key = launch_model_setting_override_key(DEFAULT_MODEL_FIELD)

    assert key == "setting:default_model"
