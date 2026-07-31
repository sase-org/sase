"""Tests for alias resolution in :mod:`sase.llm_provider.alias_view`.

Phase 2 (epic sase-5e) aggregation helper: covers kind/provenance
classification, deterministic ordering, and temporary-override merging.
"""

from __future__ import annotations

import pytest

from sase.llm_provider import (
    AliasView,
    BucketView,
    build_alias_views,
    build_models_panel_rows,
    clear_alias_override,
    is_user_owned,
    set_alias_override,
    split_bucket_members,
    split_models_panel_rows,
)
from sase.llm_provider.temporary_override import TemporaryLLMOverride
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
    assert by_name["smartest"].implicit_value == (
        "claude/claude-fable-5 || codex/gpt-5.6-sol"
    )
    assert by_name["smartest"].selector_mode == "fallback"
    assert [member.value for member in by_name["smartest"].selector_members] == [
        "claude/claude-fable-5",
        "codex/gpt-5.6-sol",
    ]
    assert [member.selected for member in by_name["smartest"].selector_members] == [
        True,
        False,
    ]
    assert by_name["cheap"].kind == "role"
    assert by_name["cheaper"].kind == "role"
    assert by_name["cheap"].implicit_value == ("claude/opus@medium | codex/gpt-5.5")
    assert by_name["cheap"].selector_mode == "round_robin"
    assert [member.value for member in by_name["cheap"].selector_members] == [
        "claude/opus@medium",
        "codex/gpt-5.5",
    ]
    assert by_name["cheaper"].implicit_value == (
        "claude/sonnet | codex/gpt-5.3-codex-spark"
    )
    assert by_name["cheaper"].selector_mode == "round_robin"
    assert [member.value for member in by_name["cheaper"].selector_members] == [
        "claude/sonnet",
        "codex/gpt-5.3-codex-spark",
    ]
    assert by_name["cheapest"].kind == "role"
    assert by_name["cheapest"].implicit_value == (
        "claude/haiku || codex/gpt-5.3-codex-spark"
    )
    assert by_name["cheapest"].selector_mode == "fallback"
    assert [member.value for member in by_name["cheapest"].selector_members] == [
        "claude/haiku",
        "codex/gpt-5.3-codex-spark",
    ]
    assert by_name["claude_coder"].kind == "provider_coder"
    assert by_name["codex_coder"].kind == "provider_coder"

    myalias = by_name["myalias"]
    assert myalias.kind == "user"
    assert myalias.configured is True
    assert myalias.configured_value == "claude/opus"


def test_explicit_empty_overrides_skips_authoritative_override_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    patch_available_providers(monkeypatch)
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.get_active_alias_overrides",
        lambda _now=None: (_ for _ in ()).throw(AssertionError("must not load")),
    )

    views = build_alias_views(overrides={})

    assert views
    assert all(view.override is None for view in views)


def test_injected_override_mapping_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    patch_available_providers(monkeypatch)
    override = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3@medium",
        created_at=1.0,
        expires_at=None,
        source="test",
        effort="medium",
    )

    coder = {
        view.name: view for view in build_alias_views(overrides={"coder": override})
    }["coder"]

    assert coder.override is override
    assert (coder.provider, coder.model, coder.effort) == ("codex", "o3", "medium")


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


def test_custom_builtin_shadows_and_bucket_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"smartest": "claude/opus"},
                "custom": {
                    "coder": {
                        "model": "claude/sonnet",
                        "description": "Wrong location.",
                    },
                    "codex_coder": {
                        "model": "codex/o3",
                        "description": "Also misplaced.",
                    },
                    "blogger": {
                        "model": "claude/opus",
                        "description": "Legitimate custom alias.",
                    },
                    "pair_programmer": {
                        "model": "claude/opus",
                        "description": "Custom coder-bucket member.",
                        "bucket": "coders",
                    },
                },
            },
        },
    )
    patch_available_providers(monkeypatch)

    views = build_alias_views()
    by_name = {view.name: view for view in views}

    assert by_name["coder"].kind == "role"
    assert by_name["coder"].configured_source == "custom"
    assert by_name["coder"].is_custom_builtin_shadow is True
    assert by_name["codex_coder"].kind == "provider_coder"
    assert by_name["codex_coder"].is_custom_builtin_shadow is True
    assert by_name["blogger"].kind == "user"
    assert by_name["blogger"].is_custom_builtin_shadow is False
    assert by_name["pair_programmer"].is_user_owned is True
    assert by_name["smartest"].configured_source == "builtin"
    assert by_name["smartest"].is_custom_builtin_shadow is False

    coders = next(
        row
        for row in build_models_panel_rows(views)
        if isinstance(row, BucketView) and row.name == "coders"
    )
    assert coders.custom_builtin_shadow_names == ("coder", "codex_coder")
    assert coders.custom_builtin_shadow_count == 2
    assert coders.user_member_count == 1

    builtin, user = split_models_panel_rows(build_models_panel_rows(views))
    assert coders in builtin.rows
    assert builtin.alias_count == sum(
        row.alias_count if isinstance(row, BucketView) else 1 for row in builtin.rows
    )
    assert user.alias_count == 1
    assert [row.name for row in user.rows] == ["blogger"]


def test_ownership_partition_preserves_top_and_bucket_order() -> None:
    default = AliasView(
        name="default",
        kind="default",
        configured=False,
        configured_value=None,
        provider="claude",
        model="opus",
        override=None,
    )
    misplaced = AliasView(
        name="smart",
        kind="role",
        configured=True,
        configured_value="claude/opus",
        provider="claude",
        model="opus",
        override=None,
        configured_source="custom",
    )
    coder = AliasView(
        name="coder",
        kind="role",
        configured=False,
        configured_value=None,
        provider="claude",
        model="opus",
        override=None,
    )
    pair_programmer = AliasView(
        name="pair_programmer",
        kind="user",
        configured=True,
        configured_value="claude/opus",
        provider="claude",
        model="opus",
        override=None,
        bucket="coders",
    )
    researcher = AliasView(
        name="researcher",
        kind="user",
        configured=True,
        configured_value="codex/o3",
        provider="codex",
        model="o3",
        override=None,
        bucket="research",
    )
    plain = AliasView(
        name="plain",
        kind="user",
        configured=True,
        configured_value="claude/opus",
        provider="claude",
        model="opus",
        override=None,
    )
    coders = BucketView("coders", None, (coder, pair_programmer))
    research = BucketView("research", None, (researcher,))
    rows = [default, coders, misplaced, research, plain]

    assert default.is_user_owned is False
    assert misplaced.is_user_owned is False
    assert is_user_owned(misplaced) is False
    assert coders.is_user_owned is False
    assert coders.user_member_count == 1
    assert research.is_user_owned is True
    assert plain.is_user_owned is True

    builtin, user = split_models_panel_rows(rows)
    assert [*builtin.rows, *user.rows] == rows
    assert (builtin.alias_count, builtin.bucket_count) == (4, 1)
    assert (user.alias_count, user.bucket_count) == (2, 1)

    bucket_builtin, bucket_user = split_bucket_members(coders)
    assert [*bucket_builtin.rows, *bucket_user.rows] == list(coders.members)
    assert (bucket_builtin.alias_count, bucket_builtin.bucket_count) == (1, 0)
    assert (bucket_user.alias_count, bucket_user.bucket_count) == (1, 0)


@pytest.mark.parametrize(
    ("configured_value", "expected"),
    [
        ("@default", "default"),
        ("@default@medium", "default"),
        ("@default@turbo", "default@turbo"),
        ("claude/opus", None),
        (None, None),
    ],
)
def test_alias_view_references(
    configured_value: str | None,
    expected: str | None,
) -> None:
    view = AliasView(
        name="coder",
        kind="role",
        configured=configured_value is not None,
        configured_value=configured_value,
        provider="claude",
        model="opus",
        override=None,
    )

    assert view.references == expected


@pytest.mark.parametrize(
    ("configured_value", "expected"),
    [
        ("@default@high", "high"),
        ("claude/opus@high", None),
    ],
)
def test_alias_view_reference_effort_is_only_for_alias_edges(
    configured_value: str,
    expected: str | None,
) -> None:
    view = AliasView(
        name="coder",
        kind="role",
        configured=True,
        configured_value=configured_value,
        provider="claude",
        model="opus",
        override=None,
    )

    assert view.reference_effort == expected


def test_big_epic_alias_view_exposes_smartest_implicit_fallback() -> None:
    view = AliasView(
        name="big_epic_lander",
        kind="role",
        configured=False,
        configured_value=None,
        provider="claude",
        model="opus",
        override=None,
    )

    assert view.implicit_fallback == "smartest"


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


def test_active_override_clears_alias_borne_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"coder": "claude/opus@medium"},
            },
        },
    )
    patch_available_providers(monkeypatch)

    set_alias_override("coder", "codex/o3", None, source="test")
    try:
        coder = {view.name: view for view in build_alias_views()}["coder"]
    finally:
        clear_alias_override("coder")

    assert (coder.provider, coder.model, coder.effort) == ("codex", "o3", None)


def test_active_override_surfaces_its_own_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"coder": "claude/opus@high"},
            },
        },
    )
    patch_available_providers(monkeypatch)

    set_alias_override("coder", "codex/o3@medium", None, source="test")
    try:
        coder = {view.name: view for view in build_alias_views()}["coder"]
    finally:
        clear_alias_override("coder")

    assert (coder.provider, coder.model, coder.effort) == ("codex", "o3", "medium")


def test_non_default_override_wins_effective_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {}},
    )
    patch_available_providers(monkeypatch)

    set_alias_override("coder", "codex/o3", 3600.0, source="test")
    try:
        coder = {v.name: v for v in build_alias_views()}["coder"]
    finally:
        clear_alias_override("coder")

    assert coder.is_overridden is True
    assert coder.override is not None
    assert coder.provider == "codex"
    assert coder.model == "o3"


def test_default_override_is_surfaced_on_default_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {}},
    )
    patch_available_providers(monkeypatch)

    set_alias_override("default", "codex/o3", None, source="test")
    try:
        views = {v.name: v for v in build_alias_views()}
    finally:
        clear_alias_override("default")

    default = views["default"]
    assert default.is_overridden is True
    assert default.provider == "codex"
    assert default.model == "o3"
    smart = views["smart"]
    assert smart.override is None
    assert smart.provider == "codex"
    assert smart.model == "o3"
