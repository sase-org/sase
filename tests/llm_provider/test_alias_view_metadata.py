"""Tests for alias-view metadata and ownership partitioning."""

from __future__ import annotations

import pytest

from sase.llm_provider import (
    AliasView,
    BucketView,
    build_alias_views,
    build_models_panel_rows,
    is_user_owned,
    split_bucket_members,
    split_models_panel_rows,
)
from tests.llm_provider._provider_config_helpers import (
    mock_provider_config,
    patch_available_providers,
)


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
                    "small_worker": {
                        "model": "claude/sonnet",
                        "description": "Wrong location.",
                    },
                    "blogger": {
                        "model": "claude/opus",
                        "description": "Legitimate custom alias.",
                    },
                    "phase_reviewer": {
                        "model": "claude/opus",
                        "description": "Custom phase bucket member.",
                        "bucket": "worker",
                    },
                },
            },
        },
    )
    patch_available_providers(monkeypatch)

    views = build_alias_views()
    by_name = {view.name: view for view in views}

    assert by_name["small_worker"].kind == "role"
    assert by_name["small_worker"].configured_source == "custom"
    assert by_name["small_worker"].is_custom_builtin_shadow is True
    assert by_name["blogger"].kind == "user"
    assert by_name["blogger"].is_custom_builtin_shadow is False
    assert by_name["phase_reviewer"].is_user_owned is True
    assert by_name["smartest"].configured_source == "builtin"
    assert by_name["smartest"].is_custom_builtin_shadow is False

    workers = next(
        row
        for row in build_models_panel_rows(views)
        if isinstance(row, BucketView) and row.name == "worker"
    )
    assert workers.custom_builtin_shadow_names == ("small_worker",)
    assert workers.custom_builtin_shadow_count == 1
    assert workers.user_member_count == 1

    builtin, user = split_models_panel_rows(build_models_panel_rows(views))
    assert workers in builtin.rows
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
    worker = AliasView(
        name="small_worker",
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
        bucket="worker",
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
    workers = BucketView("worker", None, (worker, pair_programmer))
    research = BucketView("research", None, (researcher,))
    rows = [default, workers, misplaced, research, plain]

    assert default.is_user_owned is False
    assert misplaced.is_user_owned is False
    assert is_user_owned(misplaced) is False
    assert workers.is_user_owned is False
    assert workers.user_member_count == 1
    assert research.is_user_owned is True
    assert plain.is_user_owned is True

    builtin, user = split_models_panel_rows(rows)
    assert [*builtin.rows, *user.rows] == rows
    assert (builtin.alias_count, builtin.bucket_count) == (4, 1)
    assert (user.alias_count, user.bucket_count) == (2, 1)

    bucket_builtin, bucket_user = split_bucket_members(workers)
    assert [*bucket_builtin.rows, *bucket_user.rows] == list(workers.members)
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
        name="medium_worker",
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
        name="medium_worker",
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
