"""Focused coverage for the patches Artifacts relation source."""

from __future__ import annotations

from sase.ace.patch import Patch
from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.models.patch_graph_index import build_patch_graph_index
from sase.ace.tui.relations import build_patches_relation_index
from sase.core.artifact_entry_target import ArtifactEntryTarget


def _patch(name: str, parent: str | None = None) -> Patch:
    return Patch(
        name=name,
        description="d",
        parent=parent,
        status="Ready",
        file_path="/tmp/demo.sase",
        line_number=1,
    )


def test_patches_source_emits_ancestors_children_and_siblings() -> None:
    patches = [_patch("root"), _patch("child", "root"), _patch("root__1")]
    contract = compile_builtin_contract("patches", label="P", icon="x", accent="#0")
    index = build_patches_relation_index(
        patches, build_patch_graph_index(patches), contract=contract
    )
    child = ArtifactEntryTarget("patches", (patches[1].project_name, "child"))
    root = ArtifactEntryTarget("patches", (patches[0].project_name, "root"))
    assert [edge.target.parts[-1] for edge in index.chain(child, "ancestors")] == [
        "root"
    ]
    assert [
        edge.target.parts[-1] for edge in index.edges_for_relation(root, "children")
    ] == ["child"]
    assert [
        edge.target.parts[-1] for edge in index.edges_for_relation(root, "siblings")
    ] == ["root__1"]
