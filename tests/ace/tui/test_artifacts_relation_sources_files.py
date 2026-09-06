"""Focused coverage for the files Artifacts relation source."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.relations import build_files_relation_index
from sase.ace.tui.widgets.artifacts.files_data import (
    FileVersion,
    FilesSnapshot,
    LogicalFile,
)
from sase.core.artifact_entry_target import ArtifactEntryTarget


def test_files_source_emits_row_to_version_family() -> None:
    versions = (
        FileVersion(
            version_id="v1",
            logical_id="doc",
            label="doc",
            kind="file",
            origin="ref",
            origins=frozenset({"ref"}),
            created_at=None,
            agents=(),
            projects=(),
        ),
        FileVersion(
            version_id="v2",
            logical_id="doc",
            label="doc",
            kind="file",
            origin="ref",
            origins=frozenset({"ref"}),
            created_at=None,
            agents=(),
            projects=(),
        ),
    )
    snapshot = FilesSnapshot(
        rows=(
            LogicalFile(
                logical_id="doc",
                label="doc",
                kind="file",
                versions=versions,
                agents=(),
                projects=(),
                origins=frozenset({"ref"}),
                latest_seen_at=None,
            ),
        ),
        project="alpha",
        complete=True,
        view_modes={},
        view_mode_counts={},
        origin_counts={},
    )
    contract = compile_builtin_contract("files", label="F", icon="x", accent="#0")
    index = build_files_relation_index(snapshot, contract=contract)
    row = ArtifactEntryTarget("files", ("doc",))
    v1 = ArtifactEntryTarget("files", ("doc", "v1"))
    assert {edge.target for edge in index.edges_for_relation(row, "versions")} == {
        v1,
        ArtifactEntryTarget("files", ("doc", "v2")),
    }
    assert index.edges_for_relation(v1, "versions")[0].target == row
    assert not any(edge.dangling for edge in index.edges)
