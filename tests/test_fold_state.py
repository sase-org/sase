"""Tests for FoldStateManager."""

from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager


def test_collapse_from_fully_expanded_to_expanded() -> None:
    """Test collapse retreats FULLY_EXPANDED -> EXPANDED."""
    mgr = FoldStateManager()
    mgr.expand("key1")
    mgr.expand("key1")
    assert mgr.collapse("key1") is True
    assert mgr.get("key1") == FoldLevel.EXPANDED


def test_expand_all_returns_false_when_all_fully_expanded() -> None:
    """Test expand_all returns False when no changes possible."""
    mgr = FoldStateManager()
    mgr.expand_all(["k1", "k2"])
    mgr.expand_all(["k1", "k2"])
    assert mgr.expand_all(["k1", "k2"]) is False


def test_collapse_all_collapses_fully_expanded_first() -> None:
    """Test collapse_all only collapses FULLY_EXPANDED keys when present."""
    mgr = FoldStateManager()
    # k1: FULLY_EXPANDED, k2: EXPANDED
    mgr.expand("k1")
    mgr.expand("k1")
    mgr.expand("k2")

    changed = mgr.collapse_all(["k1", "k2"])
    assert changed is True
    # k1 should go from FULLY_EXPANDED -> EXPANDED
    assert mgr.get("k1") == FoldLevel.EXPANDED
    # k2 should remain EXPANDED (only fully_expanded was collapsed)
    assert mgr.get("k2") == FoldLevel.EXPANDED


def test_collapse_all_collapses_expanded_when_no_fully_expanded() -> None:
    """Test collapse_all collapses EXPANDED keys when no FULLY_EXPANDED."""
    mgr = FoldStateManager()
    mgr.expand("k1")
    mgr.expand("k2")

    changed = mgr.collapse_all(["k1", "k2"])
    assert changed is True
    assert mgr.get("k1") == FoldLevel.COLLAPSED
    assert mgr.get("k2") == FoldLevel.COLLAPSED


def test_collapse_all_returns_false_when_all_collapsed() -> None:
    """Test collapse_all returns False when nothing to collapse."""
    mgr = FoldStateManager()
    assert mgr.collapse_all(["k1", "k2"]) is False
