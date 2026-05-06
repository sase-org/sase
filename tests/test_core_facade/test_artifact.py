"""Tests for the unified artifact graph wire mirror and strict facade."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sase.core import artifact_facade
from sase.core.artifact_wire import (
    ARTIFACT_FILE_TYPES,
    ARTIFACT_FILE_TYPE_CHAT,
    ARTIFACT_FILE_TYPE_DIFF,
    ARTIFACT_FILE_TYPE_METADATA_KEY,
    ARTIFACT_FILE_TYPE_MISC,
    ARTIFACT_FILE_TYPE_PLAN,
    ARTIFACT_FILE_TYPE_PROJECT,
    ARTIFACT_FILE_TYPE_PROMPT,
    ARTIFACT_KIND_FILE,
    ARTIFACT_LINK_PARENT,
    ARTIFACT_PROVENANCE_DERIVED,
    ARTIFACT_PROVENANCE_MANUAL,
    ARTIFACT_ROOT_ID,
    ARTIFACT_SOURCE_DIRECTORY,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDoctorOptionsWire,
    ArtifactGraphOptionsWire,
    ArtifactLinkUpsertWire,
    ArtifactLinkWire,
    ArtifactPayloadWire,
    artifact_doctor_from_dict,
    artifact_graph_from_dict,
    artifact_mutation_result_from_dict,
    ArtifactNodeRemoveWire,
    ArtifactNodeUpsertWire,
    ArtifactNodeWire,
    ArtifactPathUpsertRequestWire,
    ArtifactQueryWire,
    ArtifactRebuildRequestWire,
    artifact_path_upsert_request_to_dict,
    artifact_detail_from_dict,
    artifact_query_from_dict,
    artifact_query_to_dict,
    artifact_rebuild_request_to_dict,
    artifact_root_node,
    artifact_wire_to_json_dict,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _force_no_rust_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)
    real_import_module = importlib.import_module

    def fail(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == RUST_EXTENSION_MODULE_NAME:
            raise ImportError(f"No module named {name!r}")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fail)


def _node(node_id: str = "/tmp/example.md") -> ArtifactNodeWire:
    return ArtifactNodeWire(
        id=node_id,
        kind=ARTIFACT_KIND_FILE,
        display_title="example.md",
        subtitle=None,
        provenance=ARTIFACT_PROVENANCE_DERIVED,
        source_kind="agent",
        source_id="writer",
        source_version=None,
        search_text="example markdown",
        metadata={},
        created_at=None,
        updated_at="2026-05-05T12:00:00Z",
    )


def _mutation_result(operation: str = "upsert_node") -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_WIRE_SCHEMA_VERSION,
        "operation": operation,
        "nodes_added": 1,
        "nodes_updated": 0,
        "nodes_removed": 0,
        "links_added": 0,
        "links_updated": 0,
        "links_removed": 0,
        "tombstones_added": 0,
        "affected_node_ids": ["/tmp/example.md"],
        "affected_link_ids": [],
        "tombstone_ids": [],
        "errors": [],
    }


def test_schema_version_pinned() -> None:
    assert ARTIFACT_WIRE_SCHEMA_VERSION == 1


def test_python_file_type_constants_mirror_rust_contract() -> None:
    assert ARTIFACT_FILE_TYPE_METADATA_KEY == "artifact_type"
    assert ARTIFACT_FILE_TYPES == (
        ARTIFACT_FILE_TYPE_PLAN,
        ARTIFACT_FILE_TYPE_DIFF,
        ARTIFACT_FILE_TYPE_CHAT,
        ARTIFACT_FILE_TYPE_PROJECT,
        ARTIFACT_FILE_TYPE_PROMPT,
        ARTIFACT_FILE_TYPE_MISC,
    )
    assert ARTIFACT_FILE_TYPES == ("plan", "diff", "chat", "project", "prompt", "misc")


def test_node_wire_shape_matches_rust_snapshot() -> None:
    assert artifact_wire_to_json_dict(_node()) == {
        "id": "/tmp/example.md",
        "kind": "file",
        "display_title": "example.md",
        "subtitle": None,
        "provenance": "derived",
        "source_kind": "agent",
        "source_id": "writer",
        "source_version": None,
        "search_text": "example markdown",
        "metadata": {},
        "created_at": None,
        "updated_at": "2026-05-05T12:00:00Z",
    }


def test_query_options_and_detail_shapes_keep_nulls_and_lists() -> None:
    query = ArtifactQueryWire()
    assert artifact_query_to_dict(query) == {
        "schema_version": 1,
        "text": None,
        "kinds": [],
        "file_types": [],
        "link_types": [],
        "provenance": None,
        "source_kinds": [],
        "source_ids": [],
        "root_id": None,
        "include_tombstoned": False,
        "limit": 200,
        "offset": 0,
    }
    assert artifact_query_from_dict(artifact_query_to_dict(query)) == query

    typed_query = ArtifactQueryWire(kinds=("file",), file_types=("plan", "diff"))
    assert artifact_query_to_dict(typed_query)["file_types"] == ["plan", "diff"]
    assert artifact_query_from_dict(artifact_query_to_dict(typed_query)) == typed_query

    detail = artifact_detail_from_dict(
        {
            "schema_version": 1,
            "node": None,
            "payloads": [],
            "outbound_links": [],
            "inbound_links": [],
            "children": [],
            "path_to_root": [],
            "diagnostics": [],
        }
    )
    assert artifact_wire_to_json_dict(detail) == {
        "schema_version": 1,
        "node": None,
        "payloads": [],
        "outbound_links": [],
        "inbound_links": [],
        "children": [],
        "path_to_root": [],
        "diagnostics": [],
    }


def test_rebuild_and_path_upsert_request_shapes_keep_defaults() -> None:
    rebuild = ArtifactRebuildRequestWire()
    assert artifact_rebuild_request_to_dict(rebuild) == {
        "schema_version": 1,
        "projects_root": None,
        "workspace_root": None,
        "beads_dir": None,
        "include_sources": [],
        "exclude_sources": [],
        "target_path": None,
        "artifact_dir": None,
        "stale_cleanup": "none",
    }

    path_request = ArtifactPathUpsertRequestWire(
        provenance=ARTIFACT_PROVENANCE_DERIVED,
        source_kind=ARTIFACT_SOURCE_DIRECTORY,
        source_id="/tmp/example.md",
    )
    assert artifact_path_upsert_request_to_dict(path_request) == {
        "schema_version": 1,
        "kind": None,
        "display_title": None,
        "subtitle": None,
        "provenance": "derived",
        "source_kind": "directory",
        "source_id": "/tmp/example.md",
        "source_version": None,
        "search_text": None,
        "metadata": None,
    }


@pytest.mark.parametrize(
    ("wire_name", "converter", "payload"),
    [
        (
            "ArtifactQueryWire",
            artifact_query_from_dict,
            {"schema_version": 999},
        ),
        (
            "ArtifactDetailWire",
            artifact_detail_from_dict,
            {
                "schema_version": 999,
                "node": None,
                "payloads": [],
                "outbound_links": [],
                "inbound_links": [],
                "children": [],
                "path_to_root": [],
                "diagnostics": [],
            },
        ),
        (
            "ArtifactGraphWire",
            artifact_graph_from_dict,
            {
                "schema_version": 999,
                "root_id": ARTIFACT_ROOT_ID,
                "nodes": [],
                "links": [],
                "node_count": 0,
                "link_count": 0,
                "truncated": False,
                "limit": 500,
            },
        ),
        (
            "ArtifactMutationResultWire",
            artifact_mutation_result_from_dict,
            {**_mutation_result(), "schema_version": 999},
        ),
        (
            "ArtifactDoctorWire",
            artifact_doctor_from_dict,
            {"schema_version": 999, "ok": True, "issues": []},
        ),
    ],
)
def test_wire_converters_reject_schema_version_drift(
    wire_name: str,
    converter: Any,
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match=wire_name):
        converter(payload)


def test_facade_request_helpers_surface_typed_incremental_fields() -> None:
    rebuild = artifact_facade.artifact_rebuild_request(
        projects_root=Path("/tmp/projects"),
        target_path=Path("/tmp/projects/acme/acme.gp"),
        include_sources=("project_file", "changespec", "commit"),
        stale_cleanup="mark",
    )
    assert artifact_rebuild_request_to_dict(rebuild) == {
        "schema_version": 1,
        "projects_root": "/tmp/projects",
        "workspace_root": None,
        "beads_dir": None,
        "include_sources": ["project_file", "changespec", "commit"],
        "exclude_sources": [],
        "target_path": "/tmp/projects/acme/acme.gp",
        "artifact_dir": None,
        "stale_cleanup": "mark",
    }

    path_request = artifact_facade.artifact_path_upsert_request(
        provenance=ARTIFACT_PROVENANCE_DERIVED,
        source_kind=ARTIFACT_SOURCE_DIRECTORY,
        source_id="/tmp/example.md",
        metadata={"reason": "watcher"},
    )
    assert artifact_path_upsert_request_to_dict(path_request)["metadata"] == {
        "reason": "watcher"
    }


def test_root_node_shape_matches_rust_helper() -> None:
    assert artifact_wire_to_json_dict(artifact_root_node()) == {
        "id": "/",
        "kind": "root",
        "display_title": "/",
        "subtitle": "Artifact root",
        "provenance": "manual",
        "source_kind": None,
        "source_id": None,
        "source_version": None,
        "search_text": "root /",
        "metadata": {},
        "created_at": None,
        "updated_at": None,
    }


def test_artifact_facade_missing_extension_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_no_rust_extension(monkeypatch)
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        artifact_facade.artifact_list("/tmp/artifacts.sqlite")


def test_artifact_facade_missing_binding_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    with pytest.raises(AttributeError, match="artifact_list"):
        artifact_facade.artifact_list("/tmp/artifacts.sqlite")


def test_artifact_facade_rejects_mismatched_binding_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.artifact_doctor = lambda *args: {  # type: ignore[attr-defined]
        "schema_version": 999,
        "ok": True,
        "issues": [],
    }
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    with pytest.raises(ValueError, match="ArtifactDoctorWire schema_version 999"):
        artifact_facade.artifact_doctor("/tmp/artifacts.sqlite")


def test_artifact_facade_calls_expected_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[Any, ...]]] = []
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)

    def artifact_add(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_add", args))
        return _mutation_result()

    def artifact_remove(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_remove", args))
        return {**_mutation_result("remove_node"), "nodes_removed": 1}

    def artifact_list(*args: Any) -> list[dict[str, Any]]:
        calls.append(("artifact_list", args))
        return [artifact_wire_to_json_dict(_node())]

    def artifact_show(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_show", args))
        return {
            "schema_version": 1,
            "node": artifact_wire_to_json_dict(_node()),
            "payloads": [],
            "outbound_links": [],
            "inbound_links": [],
            "children": [],
            "path_to_root": [artifact_wire_to_json_dict(artifact_root_node())],
            "diagnostics": [],
        }

    def artifact_graph(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_graph", args))
        return {
            "schema_version": 1,
            "root_id": ARTIFACT_ROOT_ID,
            "nodes": [artifact_wire_to_json_dict(artifact_root_node())],
            "links": [],
            "node_count": 1,
            "link_count": 0,
            "truncated": False,
            "limit": 500,
        }

    def artifact_export(*args: Any) -> str:
        calls.append(("artifact_export", args))
        return "digraph artifact_graph {\n}\n"

    def artifact_doctor(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_doctor", args))
        return {"schema_version": 1, "ok": True, "issues": []}

    def artifact_rebuild(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_rebuild", args))
        return _mutation_result("rebuild")

    def artifact_upsert_path(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_upsert_path", args))
        return _mutation_result("upsert_path")

    fake.artifact_add = artifact_add  # type: ignore[attr-defined]
    fake.artifact_remove = artifact_remove  # type: ignore[attr-defined]
    fake.artifact_list = artifact_list  # type: ignore[attr-defined]
    fake.artifact_show = artifact_show  # type: ignore[attr-defined]
    fake.artifact_graph = artifact_graph  # type: ignore[attr-defined]
    fake.artifact_export = artifact_export  # type: ignore[attr-defined]
    fake.artifact_doctor = artifact_doctor  # type: ignore[attr-defined]
    fake.artifact_rebuild = artifact_rebuild  # type: ignore[attr-defined]
    fake.artifact_upsert_path = artifact_upsert_path  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    index_path = Path("/tmp/artifacts.sqlite")
    node_request = ArtifactNodeUpsertWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=_node(),
    )
    remove_request = ArtifactNodeRemoveWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        id="/tmp/example.md",
    )

    assert artifact_facade.artifact_add(index_path, node_request).nodes_added == 1
    assert (
        artifact_facade.artifact_remove(index_path, remove_request).nodes_removed == 1
    )
    assert artifact_facade.artifact_list(index_path)[0] == _node()
    assert artifact_facade.artifact_show(index_path, "/tmp/example.md").node == _node()
    assert artifact_facade.artifact_graph(index_path).node_count == 1
    assert artifact_facade.artifact_export(index_path, output_format="dot").startswith(
        "digraph"
    )
    assert artifact_facade.artifact_doctor(index_path).ok is True
    assert artifact_facade.artifact_rebuild(index_path).operation == "rebuild"
    assert (
        artifact_facade.artifact_upsert_path(index_path, "/tmp/example.md").operation
        == "upsert_path"
    )

    assert calls == [
        (
            "artifact_add",
            (
                "/tmp/artifacts.sqlite",
                artifact_wire_to_json_dict(node_request),
            ),
        ),
        (
            "artifact_remove",
            (
                "/tmp/artifacts.sqlite",
                artifact_wire_to_json_dict(remove_request),
            ),
        ),
        (
            "artifact_list",
            (
                "/tmp/artifacts.sqlite",
                artifact_query_to_dict(
                    ArtifactQueryWire(file_types=(), kinds=(), link_types=())
                ),
            ),
        ),
        ("artifact_show", ("/tmp/artifacts.sqlite", "/tmp/example.md")),
        (
            "artifact_graph",
            (
                "/tmp/artifacts.sqlite",
                artifact_wire_to_json_dict(ArtifactGraphOptionsWire()),
            ),
        ),
        (
            "artifact_export",
            (
                "/tmp/artifacts.sqlite",
                artifact_wire_to_json_dict(ArtifactGraphOptionsWire()),
                "dot",
            ),
        ),
        (
            "artifact_doctor",
            (
                "/tmp/artifacts.sqlite",
                artifact_wire_to_json_dict(ArtifactDoctorOptionsWire()),
            ),
        ),
        (
            "artifact_rebuild",
            (
                "/tmp/artifacts.sqlite",
                artifact_rebuild_request_to_dict(ArtifactRebuildRequestWire()),
            ),
        ),
        (
            "artifact_upsert_path",
            (
                "/tmp/artifacts.sqlite",
                "/tmp/example.md",
                artifact_path_upsert_request_to_dict(ArtifactPathUpsertRequestWire()),
            ),
        ),
    ]


def test_artifact_facade_real_extension_smoke(tmp_path: Path) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    required = {
        "artifact_add",
        "artifact_remove",
        "artifact_rebuild",
        "artifact_upsert_path",
        "artifact_list",
        "artifact_show",
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
    detail = artifact_facade.artifact_show(index_path, str(child_path))
    assert detail.node == child_node
    assert detail.payloads == [payload]
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
