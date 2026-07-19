"""Tests for kind-specific Agents-tab summary fold scales."""

import pytest

from sase.ace.tui.models.fold_scale import (
    CLAN_FOLD_SCALE,
    FAMILY_FOLD_SCALE,
    TRIBE_FOLD_SCALE,
    cycle_fold_level_backward,
    cycle_fold_level_forward,
    effective_fold_level,
    fold_scale_position,
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
