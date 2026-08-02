"""Resolution precedence for per-alias temporary overrides (epic sase-5e phase 1).

An active temporary override on any alias, including ``default``, must win over
the configured/implicit lookup wherever that alias is resolved.
"""

from __future__ import annotations

import pytest

from sase.llm_provider.config import (
    resolve_model_alias,
    resolve_model_alias_with_effort,
)
from sase.llm_provider.registry import (
    resolve_model_provider,
    resolve_model_provider_with_effort,
)
from sase.llm_provider.temporary_override import (
    resolve_effective_default_provider_model,
    resolve_effective_default_provider_model_with_effort,
    set_alias_override,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_override_on_role_alias_changes_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "claude/opus"}},
        },
    )
    set_alias_override("coder", "codex/o3", None, source="panel")

    assert resolve_model_alias("coder") == "codex/o3"
    assert resolve_model_alias("@coder") == "codex/o3"
    assert resolve_model_provider("coder") == ("codex", "o3")


def test_override_beats_configured_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"coder": "claude/sonnet"}},
        },
    )

    # Baseline: the configured value resolves before any override.
    assert resolve_model_alias("coder") == "claude/sonnet"

    set_alias_override("coder", "codex/o3", None, source="panel")
    assert resolve_model_alias("coder") == "codex/o3"


def test_nondefault_override_effort_and_outer_suffix_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"coder": "claude/opus@high"}},
        },
    )
    set_alias_override("coder", "codex/gpt-5.6-sol@medium", None, source="panel")

    assert resolve_model_provider_with_effort("@coder") == (
        "codex",
        "gpt-5.6-sol",
        "medium",
    )
    assert resolve_model_provider_with_effort("@coder@xhigh") == (
        "codex",
        "gpt-5.6-sol",
        "xhigh",
    )


def test_stale_override_on_phase_worker_has_no_builtin_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "claude/opus"}},
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("claude/"),
    )

    set_alias_override("phase_worker", "codex/o3", None, source="panel")
    assert resolve_model_alias("@phase_worker") == "phase_worker"
    assert resolve_model_provider_with_effort("xsmall_phase_worker") == (
        "claude",
        "sonnet",
        "medium",
    )
    assert resolve_model_provider_with_effort("small_phase_worker") == (
        "claude",
        "sonnet",
        "xhigh",
    )
    assert resolve_model_provider("medium_phase_worker") == ("claude", "opus")
    assert resolve_model_provider("large_phase_worker") == ("claude", "opus")
    assert resolve_model_provider_with_effort("xlarge_phase_worker") == (
        "claude",
        "opus",
        "max",
    )


def test_size_specific_phase_override_is_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"medium_phase_worker": "claude/sonnet"}},
        },
    )

    set_alias_override("large_phase_worker", "codex/o3", None, source="panel")

    assert resolve_model_provider_with_effort("small_phase_worker") == (
        "claude",
        "sonnet",
        "xhigh",
    )
    assert resolve_model_provider("medium_phase_worker") == ("claude", "sonnet")
    assert resolve_model_provider("large_phase_worker") == ("codex", "o3")


def test_provider_coder_alias_override(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"default": "claude/opus", "coder": "claude/sonnet"}
            },
        },
    )

    set_alias_override("codex_coder", "codex/o3", None, source="panel")
    assert resolve_model_provider("codex_coder") == ("codex", "o3")


def test_generic_coder_override_supersedes_shipped_provider_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "claude/opus"}},
        },
    )
    set_alias_override("coder", "codex/o3@medium", None, source="panel")

    assert resolve_model_provider_with_effort("@claude_coder") == (
        "codex",
        "o3",
        "medium",
    )
    assert resolve_model_provider_with_effort("@codex_coder@xhigh") == (
        "codex",
        "o3",
        "xhigh",
    )
    assert resolve_model_provider("@smart") == ("claude", "opus")


def test_configured_provider_coder_beats_generic_temporary_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "coder": "claude/sonnet",
                    "codex_coder": "codex/gpt-5.6-sol",
                }
            },
        },
    )
    set_alias_override("coder", "claude/opus", None, source="panel")

    assert resolve_model_provider("codex_coder") == ("codex", "gpt-5.6-sol")


def test_nondefault_override_leaves_default_lane_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "claude/opus"}},
        },
    )

    set_alias_override("coder", "codex/o3", None, source="panel")

    # A coder override does not affect @default...
    assert resolve_model_alias("default") == "claude/opus"
    assert resolve_model_alias("@default") == "claude/opus"
    # ...and the no-%model launch lane is untouched (no default override set).
    assert resolve_effective_default_provider_model() == ("claude", "opus")


def test_default_override_propagates_to_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``default`` override drives direct and nested ``@default`` hops."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "claude/opus"}},
        },
    )

    set_alias_override("default", "codex/o3", None, source="panel")

    assert resolve_model_alias("default") == "codex/o3"
    assert resolve_model_alias("@default") == "codex/o3"
    assert resolve_model_provider("@coder") == ("codex", "o3")
    assert resolve_model_provider("@smart") == ("codex", "o3")
    assert resolve_model_provider_with_effort("@medium_phase_worker") == (
        "codex",
        "o3",
        "high",
    )
    assert resolve_effective_default_provider_model() == ("codex", "o3")


def test_default_override_effort_drives_no_directive_launch_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "claude/opus@high"}},
        },
    )
    set_alias_override("default", "codex/gpt-5.6-sol@medium", None, source="panel")

    assert resolve_effective_default_provider_model_with_effort() == (
        "codex",
        "gpt-5.6-sol",
        "medium",
    )
    assert resolve_model_provider_with_effort("@default") == (
        "codex",
        "gpt-5.6-sol",
        "medium",
    )
    assert resolve_model_provider_with_effort("@default@xhigh") == (
        "codex",
        "gpt-5.6-sol",
        "xhigh",
    )


def test_concrete_model_token_is_not_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain model token resolves to itself even with other overrides active."""
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    set_alias_override("coder", "codex/o3", None, source="panel")
    assert resolve_model_alias("some-bare-model") == "some-bare-model"


def test_override_clears_back_to_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider.temporary_override import clear_alias_override

    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"coder": "claude/sonnet"}},
        },
    )

    set_alias_override("coder", "codex/o3", None, source="panel")
    assert resolve_model_alias("coder") == "codex/o3"

    clear_alias_override("coder")
    assert resolve_model_alias("coder") == "claude/sonnet"


def test_launch_default_override_beats_machine_default_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    set_alias_override("default", "codex/o3", None, source="panel")

    assert resolve_effective_default_provider_model(
        model_alias_overrides={"default": "claude/sonnet"}
    ) == ("claude", "sonnet")


def test_launch_default_override_beats_machine_override_at_nested_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    set_alias_override("default", "codex/o3", None, source="panel")

    assert resolve_model_provider("@smart", {"default": "claude/sonnet"}) == (
        "claude",
        "sonnet",
    )


def test_default_override_does_not_move_pinned_or_selector_backed_lanes(
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
    set_alias_override("default", "codex/o3", None, source="panel")

    smartest = resolve_model_alias_with_effort("@smartest")
    big_lander = resolve_model_alias_with_effort("@big_epic_lander")
    xlarge = resolve_model_alias_with_effort("@xlarge_phase_worker")
    assert (smartest.target, smartest.effort) == ("claude/opus", "max")
    assert (big_lander.target, big_lander.effort) == ("claude/opus", "max")
    assert (xlarge.target, xlarge.effort) == ("claude/opus", "max")
    assert resolve_model_alias("@cheapest") == "claude/haiku"
    cheap = resolve_model_alias_with_effort("@cheap")
    small = resolve_model_alias_with_effort("@small_phase_worker")
    assert (cheap.target, cheap.effort) == ("claude/sonnet", "xhigh")
    assert (small.target, small.effort) == ("claude/sonnet", "xhigh")
