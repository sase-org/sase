"""Tests for the shared Artifacts grouping/bucketing model."""

from __future__ import annotations

from sase.ace.tui.models.artifact_groups import (
    build_grouped_rows,
    group_banner_target,
    is_group_banner_target,
)
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget


def _target(label: str) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id="files", parts=(label,))


def test_single_level_groups_cluster_interleaved_items() -> None:
    # "a" and "b" items are interleaved in the input; grouping must still
    # cluster every "a" under one banner and every "b" under another,
    # ordered by each group's first appearance, with input order preserved
    # within a group — mirroring Patches' walk_order clustering.
    items = ["a1", "b1", "a2", "a3", "b2"]

    def key_values(item: str) -> tuple[str, ...]:
        return (item[0],)

    result = build_grouped_rows(
        items,
        pane_id="files",
        mode_id="by_letter",
        keys=("letter",),
        key_values=key_values,
        label_for=lambda _level, value: value.upper(),
        target_for=_target,
    )
    kinds = [
        (row.kind, row.item or (row.banner.label if row.banner else None))
        for row in result.rows
    ]
    assert kinds == [
        ("banner", "A"),
        ("item", "a1"),
        ("item", "a2"),
        ("item", "a3"),
        ("banner", "B"),
        ("item", "b1"),
        ("item", "b2"),
    ]


def test_single_level_banner_counts_and_member_targets() -> None:
    items = ["a1", "a2", "b1"]
    result = build_grouped_rows(
        items,
        pane_id="files",
        mode_id="by_letter",
        keys=("letter",),
        key_values=lambda item: (item[0],),
        label_for=lambda _level, value: value.upper(),
        target_for=_target,
    )
    banner_a = result.rows[0].banner
    assert banner_a is not None
    assert banner_a.member_count == 2
    assert banner_a.member_targets == (_target("a1"), _target("a2"))
    assert result.known_group_keys == (("a",), ("b",))


def test_collapsed_banner_hides_members_but_keeps_counts() -> None:
    items = ["a1", "a2", "b1"]
    registry = GroupFoldRegistry()
    registry.collapse(("a",))
    result = build_grouped_rows(
        items,
        pane_id="files",
        mode_id="by_letter",
        keys=("letter",),
        key_values=lambda item: (item[0],),
        label_for=lambda _level, value: value.upper(),
        target_for=_target,
    )
    result = build_grouped_rows(
        items,
        pane_id="files",
        mode_id="by_letter",
        keys=("letter",),
        key_values=lambda item: (item[0],),
        label_for=lambda _level, value: value.upper(),
        target_for=_target,
        fold_registry=registry,
    )
    rows = result.rows
    # Banner A (collapsed), banner B, item b1 — a1/a2 hidden.
    assert [row.kind for row in rows] == ["banner", "banner", "item"]
    banner_a = rows[0].banner
    assert banner_a is not None
    assert banner_a.collapsed is True
    assert banner_a.member_count == 2
    assert banner_a.member_targets == (_target("a1"), _target("a2"))


def test_two_level_grouping_collapses_inner_level_independently() -> None:
    # (kind, tier) pairs; grouped two levels deep. "plan" has two distinct
    # tiers so its level-1 banners aren't suppressed (see the dedicated
    # singleton-suppression test below for the single-tier case).
    items = [
        ("doc", "gold"),
        ("doc", "gold"),
        ("doc", "silver"),
        ("plan", "gold"),
        ("plan", "silver"),
    ]

    def key_values(item: tuple[str, str]) -> tuple[str, ...]:
        return item

    def target_for(item: tuple[str, str]) -> ArtifactEntryTarget:
        return ArtifactEntryTarget(pane_id="plan", parts=item)

    registry = GroupFoldRegistry()
    registry.collapse(("doc", "silver"))
    result = build_grouped_rows(
        items,
        pane_id="plan",
        mode_id="by_kind",
        keys=("kind", "tier"),
        key_values=key_values,
        label_for=lambda level, value: value,
        target_for=target_for,
        fold_registry=registry,
    )
    shapes = [
        (row.kind, row.banner.level if row.banner else None, row.item)
        for row in result.rows
    ]
    assert shapes == [
        ("banner", 0, None),  # doc
        ("banner", 1, None),  # doc/gold
        ("item", None, ("doc", "gold")),
        ("item", None, ("doc", "gold")),
        ("banner", 1, None),  # doc/silver (collapsed)
        ("banner", 0, None),  # plan
        ("banner", 1, None),  # plan/gold
        ("item", None, ("plan", "gold")),
        ("banner", 1, None),  # plan/silver
        ("item", None, ("plan", "silver")),
    ]


def test_sub_level_banner_is_suppressed_when_parent_has_one_distinct_child() -> None:
    # "plan" has only one distinct tier ("gold") across its members, so a
    # tier banner there would never actually subdivide anything — suppress
    # it and render its members directly under the level-0 "plan" banner,
    # mirroring Patches' singleton sibling-root suppression.
    items = [("doc", "gold"), ("doc", "silver"), ("plan", "gold"), ("plan", "gold")]
    result = build_grouped_rows(
        items,
        pane_id="plan",
        mode_id="by_kind",
        keys=("kind", "tier"),
        key_values=lambda item: item,
        label_for=lambda _level, value: value,
        target_for=lambda item: ArtifactEntryTarget(pane_id="plan", parts=item),
    )
    shapes = [
        (row.kind, row.banner.level if row.banner else None, row.item)
        for row in result.rows
    ]
    assert shapes == [
        ("banner", 0, None),  # doc
        ("banner", 1, None),  # doc/gold
        ("item", None, ("doc", "gold")),
        ("banner", 1, None),  # doc/silver
        ("item", None, ("doc", "silver")),
        ("banner", 0, None),  # plan (no tier sub-banner: only one distinct tier)
        ("item", None, ("plan", "gold")),
        ("item", None, ("plan", "gold")),
    ]
    assert result.known_group_keys == (
        ("doc",),
        ("doc", "gold"),
        ("doc", "silver"),
        ("plan",),
    )


def test_collapsing_outer_level_hides_inner_banners_too() -> None:
    items = [("doc", "gold"), ("doc", "silver")]
    registry = GroupFoldRegistry()
    registry.collapse(("doc",))
    result = build_grouped_rows(
        items,
        pane_id="plan",
        mode_id="by_kind",
        keys=("kind", "tier"),
        key_values=lambda item: item,
        label_for=lambda _level, value: value,
        target_for=lambda item: ArtifactEntryTarget(pane_id="plan", parts=item),
        fold_registry=registry,
    )
    assert [row.kind for row in result.rows] == ["banner"]
    banner = result.rows[0].banner
    assert banner is not None
    assert banner.level == 0
    assert banner.member_count == 2


def test_empty_items_returns_no_rows() -> None:
    result = build_grouped_rows(
        [],
        pane_id="files",
        mode_id="by_letter",
        keys=("letter",),
        key_values=lambda item: (item,),
        label_for=lambda _level, value: value,
        target_for=_target,
    )
    assert result.rows == ()
    assert result.known_group_keys == ()


def test_no_keys_returns_flat_items_unchanged() -> None:
    items = ["x", "y"]
    result = build_grouped_rows(
        items,
        pane_id="files",
        mode_id="flat",
        keys=(),
        key_values=lambda item: (),
        label_for=lambda _level, value: value,
        target_for=_target,
    )
    assert [row.kind for row in result.rows] == ["item", "item"]
    assert [row.item_index for row in result.rows] == [0, 1]
    assert result.known_group_keys == ()


def test_group_banner_target_is_marked_and_distinguishable() -> None:
    target = group_banner_target("files", "by_kind", ("doc",))
    assert is_group_banner_target(target) is True
    assert is_group_banner_target(_target("real-row")) is False
    assert is_group_banner_target(None) is False
