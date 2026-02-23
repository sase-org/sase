"""Tests for AncestorsChildrenPanel sibling logic."""

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.widgets.ancestors_children_panel import AncestorsChildrenPanel
from conftest import _ChangeSpecFactory


def _find_siblings_and_keys(
    current_name: str,
    current_status: str,
    sibling_specs: list[tuple[str, str]],
    hide_reverted: bool = False,
) -> tuple[AncestorsChildrenPanel, list[str], dict[str, str]]:
    """Helper to call _find_siblings and _assign_sibling_keys directly.

    Args:
        current_name: Name of the currently selected ChangeSpec.
        current_status: Status of the currently selected ChangeSpec.
        sibling_specs: List of (name, status) tuples for other ChangeSpecs.
        hide_reverted: Whether to hide reverted/archived siblings.

    Returns:
        Tuple of (panel, sibling_names, sibling_keys).
    """
    current = _ChangeSpecFactory.create(name=current_name, status=current_status)
    all_cs: list[ChangeSpec] = [current] + [
        _ChangeSpecFactory.create(name=n, status=s) for n, s in sibling_specs
    ]
    panel = AncestorsChildrenPanel.__new__(AncestorsChildrenPanel)
    panel._hidden_reverted_sibling_count = 0
    siblings = panel._find_siblings(current, all_cs, hide_reverted)
    keys = panel._assign_sibling_keys(siblings)
    return panel, siblings, keys


def test_non_suffixed_sibling_sorts_first() -> None:
    """Non-suffixed sibling (suffix_num=0) should sort before suffixed ones."""
    _, siblings, _ = _find_siblings_and_keys(
        current_name="pat_no_last_7_days__2",
        current_status="Reverted",
        sibling_specs=[
            ("pat_no_last_7_days__1", "Reverted"),
            ("pat_no_last_7_days", "Ready"),
        ],
    )
    assert siblings == ["pat_no_last_7_days", "pat_no_last_7_days__1"]


def test_hide_reverted_keeps_ready_sibling_from_suffixed() -> None:
    """With hide_reverted=True, a Ready (non-suffixed) sibling should still be shown."""
    _, siblings, _ = _find_siblings_and_keys(
        current_name="foo__1",
        current_status="Reverted",
        sibling_specs=[
            ("foo", "Ready"),
            ("foo__2", "Reverted"),
        ],
        hide_reverted=True,
    )
    assert siblings == ["foo"]
