"""Tests for alias resolution in :mod:`sase.llm_provider.alias_view`.

Phase 2 (epic sase-5e) aggregation helper: covers kind/provenance
classification, deterministic ordering, and effective model resolution.
"""

from __future__ import annotations

import pytest

from sase.llm_provider import build_alias_views
from sase.llm_provider.load_balancing import parse_model_alias_selector
from sase.llm_provider.model_alias_policy import implicit_alias_targets
from tests.llm_provider._provider_config_helpers import (
    mock_provider_config,
    patch_available_providers,
)


def test_includes_default_role_provider_coder_and_user_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "myalias": {
                        "model": "claude/opus",
                        "description": "Test alias.",
                    }
                }
            },
        },
    )
    patch_available_providers(monkeypatch)

    views = build_alias_views()
    by_name = {v.name: v for v in views}

    assert by_name["default"].kind == "default"
    assert by_name["default"].configured is False
    assert by_name["coder"].kind == "role"
    assert by_name["big_epic_lander"].kind == "role"
    assert by_name["big_epic_lander"].configured is False
    assert by_name["big_epic_lander"].implicit_fallback == "smartest"
    assert (
        by_name["big_epic_lander"].provider,
        by_name["big_epic_lander"].model,
    ) == ("claude", "claude-fable-5")
    assert by_name["task_worker"].kind == "role"
    assert by_name["task_worker"].implicit_fallback == "default"
    assert "phase_worker" not in by_name
    assert by_name["xsmall_phase_worker"].kind == "role"
    assert by_name["small_phase_worker"].kind == "role"
    assert by_name["medium_phase_worker"].kind == "role"
    assert by_name["medium_phase_worker"].configured is False
    assert by_name["medium_phase_worker"].implicit_fallback == "default"
    assert by_name["medium_phase_worker"].reference_effort == "high"
    assert by_name["large_phase_worker"].kind == "role"
    assert by_name["xlarge_phase_worker"].kind == "role"
    assert by_name["smart"].kind == "role"
    assert by_name["smart"].implicit_fallback == "default"
    assert by_name["smartest"].kind == "role"
    assert by_name["smartest"].configured is False
    assert by_name["smartest"].configured_source is None
    assert by_name["smartest"].implicit_fallback is None
    targets = implicit_alias_targets()

    smartest_selector = parse_model_alias_selector(targets["smartest"])
    assert smartest_selector is not None
    assert by_name["smartest"].implicit_value == targets["smartest"]
    # Pins the shape (ordered fallback), not the literal target strings, which
    # live solely in model_alias_defaults.yml.
    assert by_name["smartest"].selector_mode == smartest_selector.mode == "fallback"
    assert [member.value for member in by_name["smartest"].selector_members] == list(
        smartest_selector.members
    )
    assert [member.selected for member in by_name["smartest"].selector_members] == [
        True,
        False,
    ]
    assert by_name["cheap"].kind == "role"
    assert by_name["cheaper"].kind == "role"
    cheap_selector = parse_model_alias_selector(targets["cheap"])
    assert cheap_selector is not None
    assert by_name["cheap"].implicit_value == targets["cheap"]
    assert by_name["cheap"].selector_mode == cheap_selector.mode == "round_robin"
    assert [member.value for member in by_name["cheap"].selector_members] == list(
        cheap_selector.members
    )
    assert [
        (member.target, member.effort) for member in by_name["cheap"].selector_members
    ] == [
        ("claude/sonnet", "xhigh"),
        ("codex/gpt-5.5", None),
    ]
    cheaper_selector = parse_model_alias_selector(targets["cheaper"])
    assert cheaper_selector is not None
    assert by_name["cheaper"].implicit_value == targets["cheaper"]
    assert by_name["cheaper"].selector_mode == cheaper_selector.mode == "round_robin"
    assert [member.value for member in by_name["cheaper"].selector_members] == list(
        cheaper_selector.members
    )
    assert [
        (member.target, member.effort) for member in by_name["cheaper"].selector_members
    ] == [
        ("claude/sonnet", "medium"),
        ("codex/gpt-5.5", "medium"),
    ]
    assert by_name["cheapest"].kind == "role"
    cheapest_selector = parse_model_alias_selector(targets["cheapest"])
    assert cheapest_selector is not None
    assert by_name["cheapest"].implicit_value == targets["cheapest"]
    assert by_name["cheapest"].selector_mode == cheapest_selector.mode == "round_robin"
    assert [member.value for member in by_name["cheapest"].selector_members] == list(
        cheapest_selector.members
    )
    assert by_name["claude_coder"].kind == "provider_coder"
    assert by_name["codex_coder"].kind == "provider_coder"

    myalias = by_name["myalias"]
    assert myalias.kind == "user"
    assert myalias.configured is True
    assert myalias.configured_value == "claude/opus"


def test_fakey_coder_alias_hidden_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bundled fakey provider's implicit coder alias is hidden by default.

    Uses the real registered-provider list (not :func:`patch_available_providers`)
    so the bundled ``fakey`` provider participates, matching production.
    """
    mock_provider_config(monkeypatch, {"provider": "claude"})

    by_name = {v.name: v for v in build_alias_views()}

    assert "fakey_coder" not in by_name
    # Other provider-coder aliases remain visible and unaffected.
    assert "claude_coder" in by_name
    assert "codex_coder" in by_name


def test_configured_fakey_coder_alias_still_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-configured ``fakey_coder`` alias must still appear in the panel."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "fakey_coder": {
                        "model": "fakey/fakey-large",
                        "description": "Explicit fakey coder.",
                    }
                }
            },
        },
    )

    by_name = {v.name: v for v in build_alias_views()}

    assert by_name["fakey_coder"].configured is True
    assert by_name["fakey_coder"].configured_value == "fakey/fakey-large"


def test_default_is_first_and_groups_are_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "zeta": {"model": "claude/opus", "description": "Zeta alias."},
                    "alpha": {"model": "codex/o3", "description": "Alpha alias."},
                }
            },
        },
    )
    patch_available_providers(monkeypatch)

    names = [v.name for v in build_alias_views()]

    assert names[0] == "default"
    # role aliases follow default, in canonical order
    role_slice = names[1:15]
    assert role_slice == [
        "coder",
        "epic_lander",
        "big_epic_lander",
        "task_worker",
        "xsmall_phase_worker",
        "small_phase_worker",
        "medium_phase_worker",
        "large_phase_worker",
        "xlarge_phase_worker",
        "smartest",
        "smart",
        "cheap",
        "cheaper",
        "cheapest",
    ]
    # provider_coder aliases come next, alphabetically
    assert names.index("claude_coder") < names.index("codex_coder")
    assert names.index("codex_coder") < names.index("alpha")
    # user aliases come last, alphabetically
    assert names.index("alpha") < names.index("zeta")


def test_smartest_view_selects_codex_when_claude_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    patch_available_providers(monkeypatch)
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    smartest = {view.name: view for view in build_alias_views()}["smartest"]

    assert (smartest.provider, smartest.model) == ("codex", "gpt-5.6-sol")
    assert [member.selected for member in smartest.selector_members] == [
        False,
        True,
    ]


def test_configured_value_shadows_role_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"builtin": {"coder": "codex/o3"}}},
    )
    patch_available_providers(monkeypatch)

    coder = {v.name: v for v in build_alias_views()}["coder"]
    assert coder.kind == "role"
    assert coder.configured is True
    assert coder.configured_value == "codex/o3"


def test_unconfigured_provider_coder_follows_configured_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An implicit ``<provider>_coder`` row resolves through a configured ``coder``.

    This is what the Models panel displays for an unconfigured provider-coder
    alias: its effective provider/model must match the generic ``coder`` alias,
    not the ``@default`` target.
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
    patch_available_providers(monkeypatch)

    by_name = {v.name: v for v in build_alias_views()}
    codex_coder = by_name["codex_coder"]

    assert codex_coder.kind == "provider_coder"
    assert codex_coder.configured is False
    # Effective target follows @coder (claude/sonnet), not @default.
    assert codex_coder.provider == "claude"
    assert codex_coder.model == "sonnet"


def test_custom_alias_view_carries_source_and_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "blogger": {
                        "model": "claude/opus",
                        "description": "Draft blog posts.",
                        "bucket": "writing",
                    }
                }
            },
        },
    )
    patch_available_providers(monkeypatch)

    blogger = {v.name: v for v in build_alias_views()}["blogger"]

    assert blogger.kind == "user"
    assert blogger.configured is True
    assert blogger.configured_value == "claude/opus"
    assert blogger.configured_source == "custom"
    assert blogger.description == "Draft blog posts."
    assert blogger.bucket == "writing"


def test_alias_views_carry_direct_and_chain_inherited_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "direct": {
                        "model": "claude/opus@medium",
                        "description": "Direct effort.",
                    },
                    "chained": {
                        "model": "@direct@high",
                        "description": "Inherited effort.",
                    },
                }
            },
        },
    )
    patch_available_providers(monkeypatch)

    by_name = {view.name: view for view in build_alias_views()}
    assert (by_name["direct"].provider, by_name["direct"].model) == (
        "claude",
        "opus",
    )
    assert by_name["direct"].effort == "medium"
    assert by_name["chained"].effort == "high"


def test_pool_alias_view_uses_marked_next_member_for_all_badge_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "claude/opus@medium | codex/o3@high",
                        "description": "Pool.",
                    }
                }
            },
        },
    )
    patch_available_providers(monkeypatch)
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )

    first = {view.name: view for view in build_alias_views()}["pool"]
    first_next = next(member for member in first.selector_members if member.selected)
    assert (first.provider, first.model, first.effort) == (
        first_next.provider,
        "opus",
        first_next.effort,
    )

    from sase.llm_provider.config import resolve_model_alias

    resolve_model_alias("@pool", consume=True)
    second = {view.name: view for view in build_alias_views()}["pool"]
    second_next = next(member for member in second.selector_members if member.selected)
    assert (second.provider, second.model, second.effort) == (
        second_next.provider,
        "o3",
        second_next.effort,
    )
    assert second.effort == "high"
