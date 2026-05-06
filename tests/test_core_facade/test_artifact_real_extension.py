"""Smoke tests for the real artifact Rust extension facade."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core import artifact_facade
from sase.core.artifact_wire import (
    ARTIFACT_FILE_TYPE_CHAT,
    ARTIFACT_FILE_TYPE_METADATA_KEY,
    ARTIFACT_FILE_TYPE_MISC,
    ARTIFACT_FILE_TYPE_PLAN,
    ARTIFACT_KIND_AGENT,
    ARTIFACT_KIND_CHANGESPEC,
    ARTIFACT_KIND_FILE,
    ARTIFACT_LINK_CREATED,
    ARTIFACT_LINK_PARENT,
    ARTIFACT_LINK_RELATED,
    ARTIFACT_LINK_WORKER,
    ARTIFACT_PROVENANCE_MANUAL,
    ARTIFACT_ROOT_ID,
    ARTIFACT_SOURCE_DIRECTORY,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactLinkUpsertWire,
    ArtifactLinkWire,
    ArtifactNodeRemoveWire,
    ArtifactNodeUpsertWire,
    ArtifactNodeWire,
    ArtifactPageRequestWire,
    ArtifactPayloadWire,
    ArtifactQueryWire,
    ArtifactRebuildRequestWire,
    ArtifactSummaryRequestWire,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def test_artifact_facade_real_extension_smoke(tmp_path: Path) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    required = {
        "artifact_add",
        "artifact_remove",
        "artifact_rebuild",
        "artifact_upsert_path",
        "artifact_list",
        "artifact_search",
        "artifact_show",
        "artifact_show_paged",
        "artifact_summary",
        "artifact_graph",
        "artifact_export",
        "artifact_doctor",
    }
    missing = sorted(name for name in required if not hasattr(rust_module, name))
    if missing:
        pytest.skip(f"sase_core_rs is too old: missing {missing}")

    index_path = tmp_path / "artifacts.sqlite"
    child_path = tmp_path / "example.md"
    child_path.write_text("artifact body")

    child_node = ArtifactNodeWire(
        id=str(child_path),
        kind=ARTIFACT_KIND_FILE,
        display_title="example.md",
        subtitle=str(tmp_path),
        provenance=ARTIFACT_PROVENANCE_MANUAL,
        search_text=f"example.md {child_path}",
    )
    add_result = artifact_facade.artifact_add(
        index_path,
        ArtifactNodeUpsertWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            node=child_node,
        ),
    )
    assert add_result.affected_node_ids == [str(child_path)]

    link = ArtifactLinkWire(
        id=f"parent:{child_path}->/",
        link_type=ARTIFACT_LINK_PARENT,
        source_id=str(child_path),
        target_id=ARTIFACT_ROOT_ID,
        provenance=ARTIFACT_PROVENANCE_MANUAL,
    )
    artifact_facade.artifact_add(
        index_path,
        ArtifactLinkUpsertWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            link=link,
        ),
    )
    payload = ArtifactPayloadWire(
        artifact_id=str(child_path),
        payload_type="summary",
        provenance=ARTIFACT_PROVENANCE_MANUAL,
        payload={"body": "artifact body", "tags": ["smoke"]},
    )
    artifact_facade.artifact_add(index_path, payload)

    listed = artifact_facade.artifact_list(
        index_path,
        ArtifactQueryWire(kinds=(ARTIFACT_KIND_FILE,)),
    )
    assert child_node in listed
    searched = artifact_facade.artifact_search(
        index_path,
        ArtifactQueryWire(text="example", kinds=(ARTIFACT_KIND_FILE,)),
    )
    assert child_node in searched
    detail = artifact_facade.artifact_show(index_path, str(child_path))
    assert detail.node == child_node
    assert detail.payloads == [payload]
    paged = artifact_facade.artifact_show_paged(index_path, str(child_path))
    assert paged.node == child_node
    assert paged.children_page is not None
    assert paged.children_page.summary.group_key == "children"
    assert artifact_facade.artifact_graph(index_path).node_count >= 1
    assert artifact_facade.artifact_export(index_path, output_format="dot").startswith(
        "digraph artifact_graph"
    )
    assert "flowchart TD" in artifact_facade.artifact_export(
        index_path,
        output_format="mermaid",
    )
    assert artifact_facade.artifact_doctor(index_path).ok is True

    upserted_path = tmp_path / "nested" / "path.md"
    upserted_path.parent.mkdir()
    upserted_path.write_text("artifact body")
    path_result = artifact_facade.artifact_upsert_path(index_path, upserted_path)
    assert str(upserted_path) in path_result.affected_node_ids
    assert (
        artifact_facade.artifact_show(index_path, str(upserted_path))
        .path_to_root[-1]
        .id
        == ARTIFACT_ROOT_ID
    )

    rebuild_result = artifact_facade.artifact_rebuild(
        index_path,
        ArtifactRebuildRequestWire(
            workspace_root=str(tmp_path),
            beads_dir=str(tmp_path / "sdd/beads"),
            include_sources=(ARTIFACT_SOURCE_DIRECTORY,),
        ),
    )
    assert rebuild_result.operation == "rebuild"
    assert rebuild_result.errors == []

    removed = artifact_facade.artifact_remove(
        index_path,
        ArtifactNodeRemoveWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            id=str(upserted_path),
        ),
    )
    assert removed.nodes_removed == 1


def test_artifact_facade_real_extension_file_type_query_and_doctor_issue(
    tmp_path: Path,
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    required = {"artifact_add", "artifact_list", "artifact_doctor"}
    missing = sorted(name for name in required if not hasattr(rust_module, name))
    if missing:
        pytest.skip(f"sase_core_rs is too old: missing {missing}")

    index_path = tmp_path / "artifacts.sqlite"
    plan_path = tmp_path / "plan.md"
    legacy_path = tmp_path / "legacy.log"
    plan_node = ArtifactNodeWire(
        id=str(plan_path),
        kind=ARTIFACT_KIND_FILE,
        display_title="plan.md",
        provenance=ARTIFACT_PROVENANCE_MANUAL,
        search_text="typed plan",
        metadata={ARTIFACT_FILE_TYPE_METADATA_KEY: ARTIFACT_FILE_TYPE_PLAN},
    )
    legacy_node = ArtifactNodeWire(
        id=str(legacy_path),
        kind=ARTIFACT_KIND_FILE,
        display_title="legacy.log",
        provenance=ARTIFACT_PROVENANCE_MANUAL,
        search_text="legacy file",
    )
    orphan_dir = ArtifactNodeWire(
        id="manual-empty-dir",
        kind="directory",
        display_title="manual-empty-dir",
        provenance=ARTIFACT_PROVENANCE_MANUAL,
    )

    for node in (plan_node, legacy_node, orphan_dir):
        artifact_facade.artifact_add(
            index_path,
            ArtifactNodeUpsertWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                node=node,
            ),
        )
        artifact_facade.artifact_add(
            index_path,
            ArtifactLinkUpsertWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                link=ArtifactLinkWire(
                    id=f"parent:{node.id}->/",
                    link_type=ARTIFACT_LINK_PARENT,
                    source_id=node.id,
                    target_id=ARTIFACT_ROOT_ID,
                    provenance=ARTIFACT_PROVENANCE_MANUAL,
                ),
            ),
        )

    assert artifact_facade.artifact_list(
        index_path,
        ArtifactQueryWire(file_types=(ARTIFACT_FILE_TYPE_PLAN,)),
    ) == [plan_node]
    assert artifact_facade.artifact_list(
        index_path,
        ArtifactQueryWire(file_types=(ARTIFACT_FILE_TYPE_MISC,)),
    ) == [legacy_node]

    doctor = artifact_facade.artifact_doctor(index_path)
    assert doctor.ok is False
    assert any(
        issue.issue_type == "orphan_directory"
        and issue.artifact_id == "manual-empty-dir"
        for issue in doctor.issues
    )


def test_artifact_facade_real_extension_paged_detail_high_degree(
    tmp_path: Path,
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    required = {"artifact_add", "artifact_show", "artifact_show_paged"}
    missing = sorted(name for name in required if not hasattr(rust_module, name))
    if missing:
        pytest.skip(f"sase_core_rs is too old: missing {missing}")

    index_path = tmp_path / "artifacts.sqlite"
    parent = ArtifactNodeWire(
        id="parent",
        kind="directory",
        display_title="parent",
        provenance=ARTIFACT_PROVENANCE_MANUAL,
    )
    artifact_facade.artifact_add(
        index_path,
        ArtifactNodeUpsertWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            node=parent,
        ),
    )
    artifact_facade.artifact_add(
        index_path,
        ArtifactLinkUpsertWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            link=ArtifactLinkWire(
                id="parent:parent->/",
                link_type=ARTIFACT_LINK_PARENT,
                source_id="parent",
                target_id=ARTIFACT_ROOT_ID,
                provenance=ARTIFACT_PROVENANCE_MANUAL,
            ),
        ),
    )

    for index in range(25):
        child = ArtifactNodeWire(
            id=f"child-{index:02}",
            kind=ARTIFACT_KIND_FILE,
            display_title=f"child-{index:02}",
            provenance=ARTIFACT_PROVENANCE_MANUAL,
        )
        artifact_facade.artifact_add(
            index_path,
            ArtifactNodeUpsertWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                node=child,
            ),
        )
        artifact_facade.artifact_add(
            index_path,
            ArtifactLinkUpsertWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                link=ArtifactLinkWire(
                    id=f"parent:{child.id}->parent",
                    link_type=ARTIFACT_LINK_PARENT,
                    source_id=child.id,
                    target_id="parent",
                    provenance=ARTIFACT_PROVENANCE_MANUAL,
                ),
            ),
        )

    paged = artifact_facade.artifact_show_paged(
        index_path,
        "parent",
        ArtifactPageRequestWire(relation="children", offset=10, limit=5),
    )
    assert paged.children_page is not None
    assert paged.children_page.summary.total_count == 25
    assert paged.children_page.summary.loaded_count == 5
    assert [node.id for node in paged.children_page.nodes] == [
        "child-10",
        "child-11",
        "child-12",
        "child-13",
        "child-14",
    ]
    assert len(artifact_facade.artifact_show(index_path, "parent").children) == 25


def test_artifact_facade_real_extension_batched_summary(tmp_path: Path) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    required = {"artifact_add", "artifact_summary"}
    missing = sorted(name for name in required if not hasattr(rust_module, name))
    if missing:
        pytest.skip(f"sase_core_rs is too old: missing {missing}")

    index_path = tmp_path / "artifacts.sqlite"
    agent = ArtifactNodeWire(
        id="agent-1",
        kind=ARTIFACT_KIND_AGENT,
        display_title="agent one",
        provenance=ARTIFACT_PROVENANCE_MANUAL,
    )
    changespec = ArtifactNodeWire(
        id="cl-one",
        kind=ARTIFACT_KIND_CHANGESPEC,
        display_title="cl one",
        provenance=ARTIFACT_PROVENANCE_MANUAL,
    )
    chat = ArtifactNodeWire(
        id=str(tmp_path / "chat.json"),
        kind=ARTIFACT_KIND_FILE,
        display_title="chat.json",
        provenance=ARTIFACT_PROVENANCE_MANUAL,
        metadata={ARTIFACT_FILE_TYPE_METADATA_KEY: ARTIFACT_FILE_TYPE_CHAT},
    )
    for node in (agent, changespec, chat):
        artifact_facade.artifact_add(
            index_path,
            ArtifactNodeUpsertWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                node=node,
            ),
        )

    for link_type, source_id, target_id in (
        (ARTIFACT_LINK_CREATED, agent.id, chat.id),
        (ARTIFACT_LINK_PARENT, chat.id, agent.id),
        (ARTIFACT_LINK_RELATED, agent.id, changespec.id),
        (ARTIFACT_LINK_WORKER, changespec.id, agent.id),
    ):
        artifact_facade.artifact_add(
            index_path,
            ArtifactLinkUpsertWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                link=ArtifactLinkWire(
                    id=f"{link_type}:{source_id}->{target_id}",
                    link_type=link_type,
                    source_id=source_id,
                    target_id=target_id,
                    provenance=ARTIFACT_PROVENANCE_MANUAL,
                ),
            ),
        )

    summaries = artifact_facade.artifact_summary(
        index_path,
        ArtifactSummaryRequestWire(artifact_ids=(agent.id, "missing")),
    )

    assert summaries[0].artifact_id == agent.id
    assert summaries[0].state == "ok"
    assert summaries[0].total_linked_count == 2
    assert summaries[0].file_type_counts[0].artifact_type == ARTIFACT_FILE_TYPE_CHAT
    assert summaries[0].kind_counts[0].artifact_type == ARTIFACT_KIND_CHANGESPEC
    assert summaries[1].state == "missing"
    assert summaries[1].total_linked_count == 0


def test_artifact_facade_real_extension_rejects_invalid_requests(
    tmp_path: Path,
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "artifact_rebuild"):
        pytest.skip("sase_core_rs is too old: missing artifact_rebuild")

    index_path = tmp_path / "artifacts.sqlite"
    bad_node = ArtifactNodeWire(
        id=str(tmp_path / "bad.md"),
        kind=ARTIFACT_KIND_FILE,
        display_title="bad.md",
        provenance="sideways",
    )

    with pytest.raises(ValueError, match="unsupported artifact provenance"):
        artifact_facade.artifact_add(
            index_path,
            ArtifactNodeUpsertWire(
                schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
                node=bad_node,
            ),
        )
    with pytest.raises(ValueError, match="unsupported artifact export format"):
        artifact_facade.artifact_export(index_path, output_format="svg")
    with pytest.raises(ValueError, match="unsupported artifact schema_version"):
        artifact_facade.artifact_list(index_path, ArtifactQueryWire(schema_version=999))
    with pytest.raises(ValueError, match="unsupported artifact stale_cleanup"):
        artifact_facade.artifact_rebuild(
            index_path,
            ArtifactRebuildRequestWire(stale_cleanup="delete"),
        )
    with pytest.raises(ValueError, match="unsupported artifact source_kind"):
        artifact_facade.artifact_rebuild(
            index_path,
            ArtifactRebuildRequestWire(include_sources=("unknown_source",)),
        )
