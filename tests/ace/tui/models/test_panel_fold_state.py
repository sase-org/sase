"""Tests for metadata-panel fold levels and per-section overrides."""

from sase.ace.tui.models.fold_state import FoldLevel, SectionFoldStateManager


def test_section_overrides_inherit_cycle_toggle_and_clear() -> None:
    manager = SectionFoldStateManager()

    assert manager.effective_level("errors", FoldLevel.EXPANDED) is FoldLevel.EXPANDED
    assert manager.get_override("errors") is None

    assert manager.cycle("errors", FoldLevel.EXPANDED) is FoldLevel.FULLY_EXPANDED
    assert manager.effective_level("errors", FoldLevel.COLLAPSED) is (
        FoldLevel.FULLY_EXPANDED
    )
    assert manager.toggle("errors", FoldLevel.COLLAPSED) is FoldLevel.COLLAPSED
    assert manager.snapshot() == {"errors": FoldLevel.COLLAPSED}

    manager.clear()
    assert manager.snapshot() == {}
    assert manager.effective_level("errors", FoldLevel.EXPANDED) is FoldLevel.EXPANDED
