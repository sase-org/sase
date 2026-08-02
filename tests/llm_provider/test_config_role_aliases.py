"""Tests for implicit LLM provider role aliases."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sase.llm_provider.config import (
    coder_model_alias_for_provider,
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
from sase.llm_provider.model_alias_config import is_provider_coder_alias
from sase.llm_provider.model_alias_policy import (
    implicit_alias_targets,
    role_alias_fallbacks,
)
from sase.llm_provider.registry import resolve_model_provider
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_role_alias_helpers() -> None:
    """The role-alias name/directive helpers return the documented strings."""
    fallbacks = role_alias_fallbacks()
    targets = implicit_alias_targets()

    assert default_model_alias_name() == "default"
    assert coder_model_alias_for_provider("codex") == "codex_coder"
    assert coder_model_alias_for_provider(" claude ") == "claude_coder"
    assert role_model_directive_value("small_phase_worker") == "@small_phase_worker"
    assert role_model_directive_value("default") == "@default"
    assert implicit_model_alias_fallback("big_epic_lander") == "smartest"
    assert implicit_model_alias_fallback("epic_lander") == "default"
    assert implicit_model_alias_fallback("xsmall_phase_worker") == "cheaper"
    assert implicit_model_alias_fallback("small_phase_worker") == "cheap"
    assert implicit_model_alias_fallback("medium_phase_worker") == "default"
    assert (
        implicit_model_alias_fallback_reference("medium_phase_worker")
        == (fallbacks["medium_phase_worker"])
    )
    assert implicit_model_alias_fallback_effort("medium_phase_worker") == "high"
    assert implicit_model_alias_value("medium_phase_worker") is None
    # Pins the shape (not the literal string) so a bad YAML edit still fails:
    # medium_phase_worker must keep carrying a high-effort overlay.
    assert fallbacks["medium_phase_worker"] == "@default@high"
    assert implicit_model_alias_fallback("large_phase_worker") == "smart"
    assert implicit_model_alias_fallback("xlarge_phase_worker") == "smartest"
    assert implicit_model_alias_fallback("smart") == "default"
    assert implicit_model_alias_fallback("smartest") is None
    assert implicit_model_alias_value("smartest") == targets["smartest"]
    assert parse_model_alias_selector(targets["smartest"]) is None
    assert implicit_model_alias_value("cheap") == targets["cheap"]
    cheap_selector = parse_model_alias_selector(targets["cheap"])
    assert cheap_selector is not None
    assert cheap_selector.mode == "round_robin"
    assert implicit_model_alias_value("cheaper") == targets["cheaper"]
    cheaper_selector = parse_model_alias_selector(targets["cheaper"])
    assert cheaper_selector is not None
    assert cheaper_selector.mode == "round_robin"
    assert implicit_model_alias_value("cheapest") == targets["cheapest"]
    cheapest_selector = parse_model_alias_selector(targets["cheapest"])
    assert cheapest_selector is not None
    assert cheapest_selector.mode == "round_robin"
    assert implicit_model_alias_fallback("codex_coder") == "coder"
    assert implicit_model_alias_fallback_reference("codex_coder") == "@coder"
    assert implicit_model_alias_fallback_effort("codex_coder") is None
    assert implicit_model_alias_fallback("default") is None


def test_fakey_coder_alias_still_resolves_despite_picker_hiding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hiding fakey from pickers must not affect ``@fakey_coder`` resolution.

    Uses the real registered-provider list so the bundled ``fakey`` provider
    participates, matching production.
    """
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert is_provider_coder_alias("fakey_coder") is True
    assert resolve_model_alias("fakey_coder") == "claude/opus"
    assert resolve_model_provider("fakey_coder") == ("claude", "opus")


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


def test_medium_phase_worker_follows_provider_default_at_high_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    resolved = resolve_model_alias_with_effort("medium_phase_worker")

    assert (resolved.target, resolved.effort) == ("claude/opus", "high")


def test_medium_phase_worker_follows_configured_default_with_outer_effort_winning(
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

    assert (resolved.target, resolved.effort) == ("codex/gpt-5.6-sol", "high")
    assert (outer.target, outer.effort) == ("codex/gpt-5.6-sol", "low")


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

    for role in ("epic_lander", "medium_phase_worker"):
        assert resolve_model_alias(role) == "codex/gpt-5.6-sol"
    for alias in ("smartest", "big_epic_lander", "xlarge_phase_worker"):
        resolved = resolve_model_alias_with_effort(alias)
        assert (resolved.target, resolved.effort) == ("claude/opus", "max")
    assert resolve_model_alias("large_phase_worker") == "codex/gpt-5.6-sol"
    small = resolve_model_alias_with_effort("small_phase_worker")
    xsmall = resolve_model_alias_with_effort("xsmall_phase_worker")
    cheap = resolve_model_alias_with_effort("cheap")
    cheaper = resolve_model_alias_with_effort("cheaper")
    assert (small.target, small.effort) == ("claude/sonnet", "xhigh")
    assert (xsmall.target, xsmall.effort) == ("claude/sonnet", "medium")
    assert (cheap.target, cheap.effort) == ("claude/sonnet", "xhigh")
    assert (cheaper.target, cheaper.effort) == ("claude/sonnet", "medium")
    assert resolve_model_alias("cheapest") == "claude/haiku"


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
        assert (resolved.target, resolved.effort) == ("claude/opus", "max")


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
    assert (small.target, small.effort) == ("claude/sonnet", "xhigh")
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

    small = resolve_model_alias_with_effort("small_phase_worker")
    assert (small.target, small.effort) == ("claude/sonnet", "xhigh")
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
    assert (big_lander.target, big_lander.effort) == ("claude/opus", "max")


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
