"""Tests for PatchGraphIndex and relation-layout hot paths."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.patch import Patch
from sase.ace.tui.models.patch_graph_index import (
    build_patch_graph_index,
)
from sase.ace.tui.relations import build_patches_relation_index
from sase.ace.tui.widgets.artifacts.patch_entry import patch_row_target
from sase.core.artifact_relation_layout import build_relation_view


def _cs(
    name: str,
    *,
    parent: str | None = None,
    status: str = "Ready",
) -> Patch:
    return Patch(
        name=name,
        description="d",
        parent=parent,
        cl=None,
        status=status,
        file_path="/home/u/.sase/projects/demo/demo.sase",
        line_number=1,
    )


def test_index_builds_children_status_and_terminal_counts() -> None:
    specs = [
        _cs("root"),
        _cs("c1", parent="root", status="Draft"),
        _cs("c2", parent="root", status="Reverted"),
        _cs("g1", parent="c1", status="Submitted"),
    ]
    idx = build_patch_graph_index(specs)

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
    idx = build_patch_graph_index(specs)
    family = idx.siblings_by_base_name["foo"]
    # Sorted ascending by suffix number, plain "foo" first (suffix 0).
    assert [cs.name for cs in family] == ["foo", "foo__1", "foo__2"]


def test_update_relationships_from_index_avoids_per_row_rebuilds() -> None:
    specs = [_cs("root")]
    for i in range(1, 101):
        specs.append(_cs(f"c{i}", parent="root"))
    graph_index = build_patch_graph_index(specs)
    contract = compile_builtin_contract("patches", label="Patch", icon="", accent="")
    relation_index = build_patches_relation_index(
        specs,
        graph_index,
        contract=contract,
    )

    with patch(
        "sase.core.artifact_relations.build_relation_index",
        side_effect=AssertionError("layout must not build relation indexes"),
    ) as spy:
        for cs in specs[1:]:
            build_relation_view(
                index=relation_index,
                origin=patch_row_target(cs),
                relations=contract.relations,
            )
    # Selecting 100 different Patches should reuse the prebuilt relation
    # index; layout must only traverse it.
    assert spy.call_count == 0
