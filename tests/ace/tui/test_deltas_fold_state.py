"""Tests for DELTAS-specific fold-state normalization."""

from __future__ import annotations

from sase.ace.tui.models.fold_state import (
    FoldLevel,
    cycle_deltas_fold_level,
    normalize_deltas_fold_level,
)


def test_normalize_deltas_fold_level_maps_to_two_states() -> None:
    assert normalize_deltas_fold_level(FoldLevel.COLLAPSED) == FoldLevel.COLLAPSED
    assert normalize_deltas_fold_level(FoldLevel.EXPANDED) == FoldLevel.FULLY_EXPANDED
    assert (
        normalize_deltas_fold_level(FoldLevel.FULLY_EXPANDED)
        == FoldLevel.FULLY_EXPANDED
    )


def test_cycle_deltas_fold_level_toggles_between_two_states() -> None:
    assert cycle_deltas_fold_level(FoldLevel.COLLAPSED) == FoldLevel.FULLY_EXPANDED
    assert cycle_deltas_fold_level(FoldLevel.EXPANDED) == FoldLevel.COLLAPSED
    assert cycle_deltas_fold_level(FoldLevel.FULLY_EXPANDED) == FoldLevel.COLLAPSED
