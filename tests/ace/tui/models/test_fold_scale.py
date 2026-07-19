"""Tests for kind-specific Agents-tab summary fold scales."""

import pytest

from sase.ace.tui.models.fold_scale import (
    CLAN_FOLD_SCALE,
    FAMILY_FOLD_SCALE,
    TRIBE_FOLD_SCALE,
    cycle_fold_level_backward,
    cycle_fold_level_forward,
    effective_fold_level,
    fold_level_at_position,
    fold_scale_position,
    resolve_summary_fold_scale,
    toggle_fold_level,
)
from sase.ace.tui.models.fold_state import FoldLevel


@pytest.mark.parametrize(
    ("level", "scale", "expected"),
    [
        (FoldLevel.COLLAPSED, FAMILY_FOLD_SCALE, FoldLevel.EXPANDED),
        (FoldLevel.EXHAUSTIVE, FAMILY_FOLD_SCALE, FoldLevel.FULLY_EXPANDED),
        (FoldLevel.EXHAUSTIVE, CLAN_FOLD_SCALE, FoldLevel.FULLY_EXPANDED),
        (FoldLevel.EXHAUSTIVE, TRIBE_FOLD_SCALE, FoldLevel.EXHAUSTIVE),
    ],
)
def test_effective_fold_level_clamps_to_kind_scale(
    level: FoldLevel,
    scale: tuple[FoldLevel, ...],
    expected: FoldLevel,
) -> None:
    assert effective_fold_level(level, scale) is expected


def test_family_scale_cycles_and_positions_relative_to_two_levels() -> None:
    assert fold_scale_position(FoldLevel.COLLAPSED, FAMILY_FOLD_SCALE) == (1, 2)
    assert (
        cycle_fold_level_forward(FoldLevel.COLLAPSED, FAMILY_FOLD_SCALE)
        is FoldLevel.FULLY_EXPANDED
    )
    assert (
        cycle_fold_level_forward(FoldLevel.FULLY_EXPANDED, FAMILY_FOLD_SCALE)
        is FoldLevel.EXPANDED
    )
    assert (
        cycle_fold_level_backward(FoldLevel.EXPANDED, FAMILY_FOLD_SCALE)
        is FoldLevel.FULLY_EXPANDED
    )
    assert (
        toggle_fold_level(FoldLevel.EXPANDED, FAMILY_FOLD_SCALE)
        is FoldLevel.FULLY_EXPANDED
    )


def test_tribe_scale_cycles_all_four_levels_in_both_directions() -> None:
    level = FoldLevel.COLLAPSED
    forward: list[FoldLevel] = []
    for _ in range(4):
        level = cycle_fold_level_forward(level, TRIBE_FOLD_SCALE)
        forward.append(level)
    assert forward == [
        FoldLevel.EXPANDED,
        FoldLevel.FULLY_EXPANDED,
        FoldLevel.EXHAUSTIVE,
        FoldLevel.COLLAPSED,
    ]
    assert (
        cycle_fold_level_backward(FoldLevel.COLLAPSED, TRIBE_FOLD_SCALE)
        is FoldLevel.EXHAUSTIVE
    )


def test_empty_fold_scale_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        effective_fold_level(FoldLevel.COLLAPSED, ())


@pytest.mark.parametrize(
    ("scale", "expected"),
    [
        (FAMILY_FOLD_SCALE, FAMILY_FOLD_SCALE),
        (CLAN_FOLD_SCALE, CLAN_FOLD_SCALE),
        (TRIBE_FOLD_SCALE, TRIBE_FOLD_SCALE),
    ],
)
def test_direct_positions_resolve_exactly_within_each_scale(
    scale: tuple[FoldLevel, ...],
    expected: tuple[FoldLevel, ...],
) -> None:
    assert (
        tuple(
            fold_level_at_position(position, scale)
            for position in range(1, len(scale) + 1)
        )
        == expected
    )


def test_direct_positions_reject_zero_negative_and_out_of_range() -> None:
    assert fold_level_at_position(0, FAMILY_FOLD_SCALE) is None
    assert fold_level_at_position(-1, CLAN_FOLD_SCALE) is None
    assert fold_level_at_position(3, FAMILY_FOLD_SCALE) is None
    assert fold_level_at_position(5, TRIBE_FOLD_SCALE) is None


def test_family_direct_level_one_is_expanded_not_global_collapsed() -> None:
    assert fold_level_at_position(1, FAMILY_FOLD_SCALE) is FoldLevel.EXPANDED


def test_summary_selection_resolves_kind_specific_scale() -> None:
    family = type("Family", (), {"is_family_container_row": True})()
    clan = type("Clan", (), {"is_family_container_row": False})()

    assert (
        resolve_summary_fold_scale(whole_panel_focused=False, agent=family)
        == FAMILY_FOLD_SCALE
    )
    assert (
        resolve_summary_fold_scale(whole_panel_focused=False, agent=clan)
        == CLAN_FOLD_SCALE
    )
    assert (
        resolve_summary_fold_scale(whole_panel_focused=True, agent=family)
        == TRIBE_FOLD_SCALE
    )
    assert resolve_summary_fold_scale(whole_panel_focused=False, agent=None) is None
    assert (
        resolve_summary_fold_scale(
            whole_panel_focused=False,
            group_focused=True,
            agent=clan,
        )
        is None
    )
