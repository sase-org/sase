"""Tests for ChangeSpecGraphIndex + ancestors panel index path."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.models.changespec_graph_index import (
    build_changespec_graph_index,
)
from sase.ace.tui.widgets.ancestors_children_panel import AncestorsChildrenPanel


def _cs(
    name: str,
    *,
    parent: str | None = None,
    status: str = "Ready",
) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description="d",
        parent=parent,
        cl=None,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path="/home/u/.sase/projects/demo/demo.gp",
        line_number=1,
    )


def test_index_builds_children_status_and_terminal_counts() -> None:
    specs = [
        _cs("root"),
        _cs("c1", parent="root", status="Draft"),
        _cs("c2", parent="root", status="Reverted"),
        _cs("g1", parent="c1", status="Submitted"),
    ]
    idx = build_changespec_graph_index(specs)

    assert idx.status_by_name["root"] == "Ready"
    assert {c.name for c in idx.get_children("root")} == {"c1", "c2"}
    assert {c.name for c in idx.get_children("c1")} == {"g1"}
    assert idx.terminal_count == 1
    assert idx.submitted_count == 1


def test_index_groups_siblings_by_base_name() -> None:
    specs = [
        _cs("foo", status="Ready"),
        _cs("foo__1", status="Reverted"),
        _cs("foo__2", status="Reverted"),
    ]
    idx = build_changespec_graph_index(specs)
    family = idx.siblings_by_base_name["foo"]
    # Sorted ascending by suffix number, plain "foo" first (suffix 0).
    assert [cs.name for cs in family] == ["foo", "foo__1", "foo__2"]


class _FakePanel(AncestorsChildrenPanel):
    """Minimal subclass that skips Static.update so we never touch a screen."""

    def __init__(self) -> None:
        # Skip Static.__init__ — we never mount; just reset state buckets.
        self._ancestors = []
        self._ancestor_statuses = {}
        self._descendant_tree = []
        self._ancestor_keys = {}
        self._children_keys = {}
        self._hidden_ancestor_count = 0
        self._hidden_descendant_count = 0
        self._siblings = []
        self._sibling_statuses = {}
        self._sibling_keys = {}
        self._hidden_reverted_sibling_count = 0
        self._refresh_calls = 0

    def _refresh_content(self) -> None:  # type: ignore[override]
        self._refresh_calls += 1


def test_update_relationships_from_index_avoids_per_row_rebuilds() -> None:
    specs = [_cs("root")]
    for i in range(1, 101):
        specs.append(_cs(f"c{i}", parent="root"))
    idx = build_changespec_graph_index(specs)
    panel = _FakePanel()

    real = build_changespec_graph_index
    with patch(
        "sase.ace.tui.widgets.ancestors_children_panel.build_changespec_graph_index",
        side_effect=real,
    ) as spy:
        for cs in specs[1:]:
            panel.update_relationships_from_index(cs, idx)
    # Selecting 100 different ChangeSpecs should not rebuild the children
    # map / status map / siblings map: the index is reused as-is.
    assert spy.call_count == 0
    assert panel._refresh_calls == 100
