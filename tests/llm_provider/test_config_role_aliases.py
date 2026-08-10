"""Tests for implicit LLM provider role aliases."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sase.llm_provider.config import (
    default_model_alias_name,
    implicit_model_alias_fallback,
    implicit_model_alias_fallback_effort,
    implicit_model_alias_fallback_reference,
    implicit_model_alias_value,
    resolve_model_alias,
    resolve_model_alias_with_effort,
    role_model_directive_value,
)
from sase.llm_provider.load_balancing import parse_model_alias_selector
from sase.llm_provider.model_alias_policy import (
    CHEAP_MODEL_ALIAS_NAME,
    CHEAPER_MODEL_ALIAS_NAME,
    CHEAPEST_MODEL_ALIAS_NAME,
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMARTEST_MODEL_ALIAS_NAME,
    implicit_alias_targets,
    role_alias_fallbacks,
)
from sase.llm_provider.registry import resolve_model_provider
from tests._model_alias_defaults_fixture import (
    FROZEN_TARGET_DETAILS,
    FROZEN_TARGETS,
    frozen_selector_member,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_role_alias_helpers() -> None:
    """The role-alias name/directive helpers return the documented strings."""
    fallbacks = role_alias_fallbacks()
    targets = implicit_alias_targets()

    assert default_model_alias_name() == "default"
    assert role_model_directive_value("small_phase_worker") == "@small_phase_worker"
    assert role_model_directive_value("default") == "@default"
    assert implicit_model_alias_fallback("big_epic_lander") == "smartest"
    assert implicit_model_alias_fallback("epic_lander") == "default"
    assert implicit_model_alias_fallback("xsmall_phase_worker") == "cheaper"
    assert implicit_model_alias_fallback("small_phase_worker") == "cheap"
    assert "medium_phase_worker" not in fallbacks
    assert implicit_model_alias_fallback("medium_phase_worker") is None
    assert implicit_model_alias_fallback_reference("medium_phase_worker") is None
    assert implicit_model_alias_fallback_effort("medium_phase_worker") is None
    assert (
        implicit_model_alias_value("medium_phase_worker")
        == FROZEN_TARGETS[MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME]
    )
    assert (
        parse_model_alias_selector(targets[MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME])
        is None
    )
    assert implicit_model_alias_fallback("large_phase_worker") == "smart"
    assert implicit_model_alias_fallback("xlarge_phase_worker") == "smartest"
    assert implicit_model_alias_fallback("smart") == "default"
    assert implicit_model_alias_fallback("smartest") is None
    assert (
        implicit_model_alias_value("smartest")
        == FROZEN_TARGETS[SMARTEST_MODEL_ALIAS_NAME]
    )
    assert parse_model_alias_selector(targets[SMARTEST_MODEL_ALIAS_NAME]) is None
    assert implicit_model_alias_value("cheap") == FROZEN_TARGETS[CHEAP_MODEL_ALIAS_NAME]
    cheap_selector = parse_model_alias_selector(targets[CHEAP_MODEL_ALIAS_NAME])
    assert cheap_selector is not None
    assert cheap_selector.mode == "round_robin"
    assert (
        implicit_model_alias_value("cheaper")
        == FROZEN_TARGETS[CHEAPER_MODEL_ALIAS_NAME]
    )
    cheaper_selector = parse_model_alias_selector(targets[CHEAPER_MODEL_ALIAS_NAME])
    assert cheaper_selector is not None
    assert cheaper_selector.mode == "round_robin"
    assert (
        implicit_model_alias_value("cheapest")
        == FROZEN_TARGETS[CHEAPEST_MODEL_ALIAS_NAME]
    )
    cheapest_selector = parse_model_alias_selector(targets[CHEAPEST_MODEL_ALIAS_NAME])
    assert cheapest_selector is not None
    assert cheapest_selector.mode == "round_robin"
    assert implicit_model_alias_value("coder") is None
    assert implicit_model_alias_value("claude_coder") is None
    assert implicit_model_alias_value("codex_coder") is None
    assert implicit_model_alias_fallback("codex_coder") is None
    assert implicit_model_alias_fallback_reference("codex_coder") is None
    assert implicit_model_alias_fallback_effort("codex_coder") is None
    assert implicit_model_alias_value("fakey_coder") is None
    assert implicit_model_alias_fallback("fakey_coder") is None
    assert implicit_model_alias_fallback("default") is None


def test_default_alias_resolves_to_configured_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured ``default`` resolves through its explicit provider/model."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    assert resolve_model_alias("default") == "codex/gpt-5.6-sol"
    assert resolve_model_provider("default") == ("codex", "gpt-5.6-sol")


def test_default_alias_falls_back_to_provider_tier_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent a configured ``default``, ``@default`` is the provider tier default."""
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_model_alias("default") == "claude/opus"
    assert resolve_model_provider("default") == ("claude", "opus")


def test_medium_phase_worker_uses_concrete_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    resolved = resolve_model_alias_with_effort("medium_phase_worker")

    assert (resolved.target, resolved.effort) == FROZEN_TARGET_DETAILS[
        MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME
    ]


def test_medium_phase_worker_ignores_default_with_outer_effort_winning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol@medium"}},
        },
    )

    resolved = resolve_model_alias_with_effort("@medium_phase_worker")
    outer = resolve_model_alias_with_effort("@medium_phase_worker@low")

    target, _effort = FROZEN_TARGET_DETAILS[MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME]
    assert (resolved.target, resolved.effort) == FROZEN_TARGET_DETAILS[
        MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME
    ]
    assert (outer.target, outer.effort) == (target, "low")


def test_alias_reference_effort_overrides_target_and_chain_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "default": "codex/gpt-5.6-sol",
                    "focused": "claude/opus@high",
                    "chained": "@focused",
                },
            },
        },
    )

    default = resolve_model_alias_with_effort("@default@medium")
    focused = resolve_model_alias_with_effort("@focused")
    focused_outer = resolve_model_alias_with_effort("@focused@medium")
    chained = resolve_model_alias_with_effort("@chained")
    chained_outer = resolve_model_alias_with_effort("@chained@low")

    assert (default.target, default.effort) == ("codex/gpt-5.6-sol", "medium")
    assert (focused.target, focused.effort) == ("claude/opus", "high")
    assert (focused_outer.target, focused_outer.effort) == (
        "claude/opus",
        "medium",
    )
    assert (chained.target, chained.effort) == ("claude/opus", "high")
    assert (chained_outer.target, chained_outer.effort) == ("claude/opus", "low")


def test_retired_coder_alias_is_not_implicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``coder`` is just a bare model token unless the user configures it."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    assert resolve_model_alias("coder") == "coder"


def test_retired_provider_coder_alias_is_not_implicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol@high"}},
        },
    )

    assert resolve_model_alias("claude_coder") == "claude_coder"
    assert resolve_model_alias("codex_coder") == "codex_coder"


def test_configured_provider_coder_alias_is_ordinary_user_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "codex_coder": {
                        "model": "codex/o3",
                        "description": "Explicit legacy alias.",
                    }
                }
            },
        },
    )

    assert resolve_model_alias("codex_coder") == "codex/o3"


def test_epic_execution_role_aliases_follow_size_specific_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Epic execution roles use their normal or threshold-sized fallback."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    assert resolve_model_alias("epic_lander") == "codex/gpt-5.6-sol"
    assert (
        resolve_model_alias("medium_phase_worker")
        == FROZEN_TARGET_DETAILS[MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME][0]
    )
    for alias in ("smartest", "big_epic_lander", "xlarge_phase_worker"):
        resolved = resolve_model_alias_with_effort(alias)
        assert (resolved.target, resolved.effort) == FROZEN_TARGET_DETAILS[
            SMARTEST_MODEL_ALIAS_NAME
        ]
    assert resolve_model_alias("large_phase_worker") == "codex/gpt-5.6-sol"
    small = resolve_model_alias_with_effort("small_phase_worker")
    xsmall = resolve_model_alias_with_effort("xsmall_phase_worker")
    cheap = resolve_model_alias_with_effort("cheap")
    cheaper = resolve_model_alias_with_effort("cheaper")
    assert (small.target, small.effort) == frozen_selector_member(
        CHEAP_MODEL_ALIAS_NAME, 0
    )
    assert (xsmall.target, xsmall.effort) == frozen_selector_member(
        CHEAPER_MODEL_ALIAS_NAME, 0
    )
    assert (cheap.target, cheap.effort) == frozen_selector_member(
        CHEAP_MODEL_ALIAS_NAME, 0
    )
    assert (cheaper.target, cheaper.effort) == frozen_selector_member(
        CHEAPER_MODEL_ALIAS_NAME, 0
    )
    assert (
        resolve_model_alias("cheapest")
        == frozen_selector_member(CHEAPEST_MODEL_ALIAS_NAME, 0)[0]
    )


def test_configured_smartest_alias_shadows_implicit_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "default": "claude/sonnet",
                    "smartest": "codex/gpt-5.6-sol",
                }
            },
        },
    )

    for alias in ("smartest", "big_epic_lander", "xlarge_phase_worker"):
        resolved = resolve_model_alias_with_effort(alias)
        assert (resolved.target, resolved.effort) == ("codex/gpt-5.6-sol", None)


def test_smartest_target_and_effort_do_not_depend_on_provider_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: False,
    )

    for alias in ("@smartest", "@big_epic_lander", "@xlarge_phase_worker"):
        resolved = resolve_model_alias_with_effort(alias, consume=True)
        assert (resolved.target, resolved.effort) == FROZEN_TARGET_DETAILS[
            SMARTEST_MODEL_ALIAS_NAME
        ]


def test_stale_phase_worker_builtin_does_not_control_medium_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "default": "codex/gpt-5.6-sol",
                    "phase_worker": "claude/sonnet",
                }
            },
        },
    )

    small = resolve_model_alias_with_effort("small_phase_worker")
    assert (small.target, small.effort) == frozen_selector_member(
        CHEAP_MODEL_ALIAS_NAME, 0
    )
    assert (
        resolve_model_alias("medium_phase_worker")
        == FROZEN_TARGET_DETAILS[MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME][0]
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )
    assert resolve_model_alias("large_phase_worker") == "codex/gpt-5.6-sol"


def test_configured_phase_size_alias_shadows_default_only_for_that_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "medium_phase_worker": "claude/sonnet",
                    "large_phase_worker": "codex/o3",
                }
            },
        },
    )

    small = resolve_model_alias_with_effort("small_phase_worker")
    assert (small.target, small.effort) == frozen_selector_member(
        CHEAP_MODEL_ALIAS_NAME, 0
    )
    assert resolve_model_alias("medium_phase_worker") == "claude/sonnet"
    assert resolve_model_alias("large_phase_worker") == "codex/o3"


def test_big_epic_lander_uses_smartest_independently_of_epic_lander(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The large-epic role does not inherit a normal-epic override."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "default": "codex/gpt-5.6-sol",
                    "epic_lander": "claude/sonnet",
                }
            },
        },
    )
    assert resolve_model_alias("epic_lander") == "claude/sonnet"
    big_lander = resolve_model_alias_with_effort("big_epic_lander")
    assert (big_lander.target, big_lander.effort) == FROZEN_TARGET_DETAILS[
        SMARTEST_MODEL_ALIAS_NAME
    ]


def test_configured_big_epic_lander_shadows_implicit_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "epic_lander": "claude/sonnet",
                    "big_epic_lander": "codex/o3",
                }
            },
        },
    )

    assert resolve_model_alias("big_epic_lander") == "codex/o3"
    assert resolve_model_alias("epic_lander") == "claude/sonnet"


def test_big_epic_lander_honors_launch_and_temporary_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    temporary = MagicMock(provider="codex", model="o3")
    monkeypatch.setattr(
        "sase.llm_provider.config._active_alias_overrides",
        lambda: {"big_epic_lander": temporary},
    )

    assert resolve_model_alias("@big_epic_lander") == "codex/o3"
    assert (
        resolve_model_alias(
            "@big_epic_lander",
            {"big_epic_lander": "claude/sonnet"},
        )
        == "claude/sonnet"
    )


def test_custom_phase_worker_alias_is_available_for_explicit_use_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-configured role alias wins over the implicit ``@default`` fallback."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"default": "codex/gpt-5.6-sol"},
                "custom": {
                    "phase_worker": {
                        "model": "claude/sonnet",
                        "description": "Explicit custom phase role.",
                    }
                },
            },
        },
    )

    assert resolve_model_alias("phase_worker") == "claude/sonnet"
    assert (
        resolve_model_alias("medium_phase_worker")
        == FROZEN_TARGET_DETAILS[MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME][0]
    )
    assert resolve_model_alias("coder") == "coder"
