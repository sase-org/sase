"""Tests for DELTAS-specific fold-state cycling."""

from __future__ import annotations

from sase.ace.tui.models.fold_state import (
    FoldLevel,
    cycle_deltas_fold_level,
)


def test_cycle_deltas_fold_level_uses_three_states() -> None:
    assert cycle_deltas_fold_level(FoldLevel.COLLAPSED) == FoldLevel.EXPANDED
    assert cycle_deltas_fold_level(FoldLevel.EXPANDED) == FoldLevel.FULLY_EXPANDED
    assert cycle_deltas_fold_level(FoldLevel.FULLY_EXPANDED) == FoldLevel.COLLAPSED
