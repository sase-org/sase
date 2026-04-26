"""Tests for the per-group fold registry."""

from __future__ import annotations

from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry


def test_default_registry_has_no_collapsed_groups() -> None:
    registry = AgentGroupFoldRegistry()
    assert registry.collapsed == set()
    assert registry.is_collapsed(("proj", "cl")) is False


def test_collapse_returns_true_only_on_first_change() -> None:
    registry = AgentGroupFoldRegistry()
    key = ("proj", "cl")
    assert registry.collapse(key) is True
    assert registry.is_collapsed(key) is True
    # Second collapse: idempotent — no change.
    assert registry.collapse(key) is False


def test_expand_returns_true_only_when_undoing_a_collapse() -> None:
    registry = AgentGroupFoldRegistry()
    key = ("proj", "cl")
    assert registry.expand(key) is False  # was already expanded
    registry.collapse(key)
    assert registry.expand(key) is True
    assert registry.is_collapsed(key) is False
    assert registry.expand(key) is False  # already expanded


def test_collapse_one_group_does_not_touch_siblings() -> None:
    registry = AgentGroupFoldRegistry()
    a = ("projA", "cl")
    b = ("projB", "cl")
    registry.collapse(a)
    assert registry.is_collapsed(a) is True
    assert registry.is_collapsed(b) is False


def test_collapse_keys_returns_change_flag_aggregate() -> None:
    registry = AgentGroupFoldRegistry()
    a = ("projA", "cl")
    b = ("projB", "cl")
    assert registry.collapse_keys([a, b]) is True
    # Re-collapsing the same set: no further change.
    assert registry.collapse_keys([a, b]) is False


def test_expand_keys_returns_change_flag_aggregate() -> None:
    registry = AgentGroupFoldRegistry()
    a = ("projA", "cl")
    b = ("projB", "cl")
    registry.collapse_keys([a, b])
    assert registry.expand_keys([a, b]) is True
    assert registry.expand_keys([a, b]) is False


def test_clear_unknown_drops_keys_no_longer_in_known_set() -> None:
    registry = AgentGroupFoldRegistry()
    stale = ("projA", "cl-old")
    live = ("projB", "cl-new")
    registry.collapse(stale)
    registry.collapse(live)
    registry.clear_unknown([live])
    assert registry.is_collapsed(stale) is False
    assert registry.is_collapsed(live) is True


def test_clear_unknown_with_empty_known_drops_everything() -> None:
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA", "cl"))
    registry.collapse(("projB", "cl"))
    registry.clear_unknown([])
    assert registry.collapsed == set()


def test_l1_and_l0_keys_coexist_independently() -> None:
    """L0 (length-2) and L1 (length-3) keys are tracked separately."""
    registry = AgentGroupFoldRegistry()
    l0 = ("proj", "cl")
    l1 = ("proj", "cl", "coder")
    registry.collapse(l1)
    assert registry.is_collapsed(l1) is True
    assert registry.is_collapsed(l0) is False
