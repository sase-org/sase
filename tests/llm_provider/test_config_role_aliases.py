"""Tests for implicit LLM provider role aliases."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sase.llm_provider.config import (
    SMARTEST_MODEL_ALIAS_DEFAULT,
    coder_model_alias_for_provider,
    default_model_alias_name,
    implicit_model_alias_fallback,
    implicit_model_alias_value,
    resolve_model_alias,
    role_model_directive_value,
)
from sase.llm_provider.registry import resolve_model_provider
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_role_alias_helpers() -> None:
    """The role-alias name/directive helpers return the documented strings."""
    assert default_model_alias_name() == "default"
    assert coder_model_alias_for_provider("codex") == "codex_coder"
    assert coder_model_alias_for_provider(" claude ") == "claude_coder"
    assert role_model_directive_value("small_phase_worker") == "@small_phase_worker"
    assert role_model_directive_value("default") == "@default"
    assert implicit_model_alias_fallback("big_epic_lander") == "smartest"
    assert implicit_model_alias_fallback("epic_lander") == "default"
    assert implicit_model_alias_fallback("small_phase_worker") == "cheaper"
    assert implicit_model_alias_fallback("medium_phase_worker") == "default"
    assert implicit_model_alias_fallback("large_phase_worker") == "smartest"
    assert implicit_model_alias_fallback("smartest") is None
    assert implicit_model_alias_value("smartest") == SMARTEST_MODEL_ALIAS_DEFAULT
    assert SMARTEST_MODEL_ALIAS_DEFAULT == (
        "claude/claude-fable-5 || codex/gpt-5.6-sol"
    )
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


def test_coder_alias_chains_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``coder`` defaults to ``@default`` when not explicitly configured."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    assert resolve_model_alias("coder") == "codex/gpt-5.6-sol"
    assert resolve_model_provider("coder") == ("codex", "gpt-5.6-sol")


def test_provider_coder_alias_chains_to_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``<provider>_coder`` defaults to ``@coder`` -> ``@default`` when unset."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    # codex is a registered provider, so codex_coder is an implicit alias.
    assert resolve_model_alias("codex_coder") == "codex/gpt-5.6-sol"
    assert resolve_model_provider("codex_coder") == ("codex", "gpt-5.6-sol")


def test_provider_coder_alias_follows_configured_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unconfigured ``<provider>_coder`` inherits a configured ``coder``.

    Regression: the implicit provider-coder fallback must reference ``@coder``
    itself, not ``coder``'s resolved fallback. Otherwise configuring ``coder``
    once fails to flow through to the provider-specific coder lanes and they
    skip straight to ``@default``.
    """
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "default": "codex/gpt-5.6-sol",
                    "coder": "claude/sonnet",
                }
            },
        },
    )

    # codex_coder is unconfigured, so it inherits @coder (claude/sonnet) rather
    # than skipping straight to @default (codex/gpt-5.6-sol).
    assert resolve_model_alias("codex_coder") == "claude/sonnet"
    assert resolve_model_provider("codex_coder") == ("claude", "sonnet")


def test_configured_provider_coder_shadows_generic_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ``<provider>_coder`` still wins over the generic ``coder``."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "default": "codex/gpt-5.6-sol",
                    "coder": "claude/sonnet",
                    "codex_coder": "codex/o3",
                }
            },
        },
    )

    assert resolve_model_alias("codex_coder") == "codex/o3"
    assert resolve_model_provider("codex_coder") == ("codex", "o3")


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

    assert resolve_model_alias("epic_creator") == "epic_creator"
    for role in ("epic_lander", "medium_phase_worker"):
        assert resolve_model_alias(role) == "codex/gpt-5.6-sol"
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("claude/"),
    )
    assert resolve_model_alias("smartest") == "claude/claude-fable-5"
    assert resolve_model_alias("big_epic_lander") == "claude/claude-fable-5"
    assert resolve_model_alias("large_phase_worker") == "claude/claude-fable-5"
    assert resolve_model_alias("small_phase_worker") == "claude/opus"
    assert resolve_model_alias("cheaper") == "claude/opus"
    assert resolve_model_alias("cheapest") == "claude/sonnet"


def test_configured_smartest_alias_shadows_implicit_fallback(
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

    assert resolve_model_alias("smartest") == "codex/gpt-5.6-sol"
    assert resolve_model_alias("big_epic_lander") == "codex/gpt-5.6-sol"


@pytest.mark.parametrize(
    ("available_providers", "expected"),
    [
        ({"claude"}, "claude/claude-fable-5"),
        ({"codex"}, "codex/gpt-5.6-sol"),
        ({"claude", "codex"}, "claude/claude-fable-5"),
        (set(), "claude/claude-fable-5"),
    ],
)
def test_smartest_provider_availability_matrix(
    monkeypatch: pytest.MonkeyPatch,
    available_providers: set[str],
    expected: str,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.split("/", 1)[0] in available_providers,
    )

    assert resolve_model_alias("smartest", consume=True) == expected
    assert resolve_model_alias("big_epic_lander", consume=True) == expected
    assert resolve_model_alias("large_phase_worker", consume=True) == expected


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

    assert resolve_model_alias("small_phase_worker") == "claude/opus"
    assert resolve_model_alias("medium_phase_worker") == "codex/gpt-5.6-sol"
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

    assert resolve_model_alias("small_phase_worker") == "claude/opus"
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
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    assert resolve_model_alias("epic_lander") == "claude/sonnet"
    assert resolve_model_alias("big_epic_lander") == "codex/gpt-5.6-sol"


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
    assert resolve_model_alias("medium_phase_worker") == "codex/gpt-5.6-sol"
    assert resolve_model_alias("coder") == "codex/gpt-5.6-sol"  # still @default
