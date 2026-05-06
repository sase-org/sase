"""Tests for artifact facade binding dispatch and validation."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sase.core import artifact_facade
from sase.core.artifact_wire import (
    ARTIFACT_ROOT_ID,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDoctorOptionsWire,
    ArtifactGraphOptionsWire,
    ArtifactNodeRemoveWire,
    ArtifactNodeUpsertWire,
    ArtifactPageRequestWire,
    ArtifactPathUpsertRequestWire,
    ArtifactQueryWire,
    ArtifactRebuildRequestWire,
    ArtifactSummaryRequestWire,
    artifact_path_upsert_request_to_dict,
    artifact_query_to_dict,
    artifact_rebuild_request_to_dict,
    artifact_root_node,
    artifact_summary_request_to_dict,
    artifact_wire_to_json_dict,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from tests.test_core_facade._helpers import (
    artifact_mutation_result,
    artifact_node,
    force_no_rust_extension,
)


def test_artifact_facade_missing_extension_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    force_no_rust_extension(monkeypatch)
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
        return artifact_mutation_result()

    def artifact_remove(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_remove", args))
        return {**artifact_mutation_result("remove_node"), "nodes_removed": 1}

    def artifact_list(*args: Any) -> list[dict[str, Any]]:
        calls.append(("artifact_list", args))
        return [artifact_wire_to_json_dict(artifact_node())]

    def artifact_search(*args: Any) -> list[dict[str, Any]]:
        calls.append(("artifact_search", args))
        return [artifact_wire_to_json_dict(artifact_node())]

    def artifact_show(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_show", args))
        return {
            "schema_version": 1,
            "node": artifact_wire_to_json_dict(artifact_node()),
            "payloads": [],
            "outbound_links": [],
            "inbound_links": [],
            "children": [],
            "path_to_root": [artifact_wire_to_json_dict(artifact_root_node())],
            "diagnostics": [],
        }

    def artifact_show_paged(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_show_paged", args))
        return {
            "schema_version": 1,
            "node": artifact_wire_to_json_dict(artifact_node()),
            "payloads": [],
            "path_to_root": [artifact_wire_to_json_dict(artifact_root_node())],
            "diagnostics": [],
            "children_page": {
                "summary": {
                    "group_key": "children",
                    "direction": "children",
                    "link_type": None,
                    "total_count": 0,
                    "loaded_count": 0,
                },
                "nodes": [],
                "links": [],
            },
            "outbound_pages": [],
            "inbound_pages": [],
            "type_counts": [],
        }

    def artifact_summary(*args: Any) -> list[dict[str, Any]]:
        calls.append(("artifact_summary", args))
        return [
            {
                "artifact_id": "/tmp/example.md",
                "state": "ok",
                "total_linked_count": 0,
                "file_type_counts": [],
                "kind_counts": [],
                "error": None,
            }
        ]

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
        return artifact_mutation_result("rebuild")

    def artifact_upsert_path(*args: Any) -> dict[str, Any]:
        calls.append(("artifact_upsert_path", args))
        return artifact_mutation_result("upsert_path")

    fake.artifact_add = artifact_add  # type: ignore[attr-defined]
    fake.artifact_remove = artifact_remove  # type: ignore[attr-defined]
    fake.artifact_list = artifact_list  # type: ignore[attr-defined]
    fake.artifact_search = artifact_search  # type: ignore[attr-defined]
    fake.artifact_show = artifact_show  # type: ignore[attr-defined]
    fake.artifact_show_paged = artifact_show_paged  # type: ignore[attr-defined]
    fake.artifact_summary = artifact_summary  # type: ignore[attr-defined]
    fake.artifact_graph = artifact_graph  # type: ignore[attr-defined]
    fake.artifact_export = artifact_export  # type: ignore[attr-defined]
    fake.artifact_doctor = artifact_doctor  # type: ignore[attr-defined]
    fake.artifact_rebuild = artifact_rebuild  # type: ignore[attr-defined]
    fake.artifact_upsert_path = artifact_upsert_path  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    index_path = Path("/tmp/artifacts.sqlite")
    node_request = ArtifactNodeUpsertWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=artifact_node(),
    )
    remove_request = ArtifactNodeRemoveWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        id="/tmp/example.md",
    )

    assert artifact_facade.artifact_add(index_path, node_request).nodes_added == 1
    assert (
        artifact_facade.artifact_remove(index_path, remove_request).nodes_removed == 1
    )
    assert artifact_facade.artifact_list(index_path)[0] == artifact_node()
    assert artifact_facade.artifact_search(index_path)[0] == artifact_node()
    assert (
        artifact_facade.artifact_show(index_path, "/tmp/example.md").node
        == artifact_node()
    )
    assert (
        artifact_facade.artifact_show_paged(index_path, "/tmp/example.md").node
        == artifact_node()
    )
    assert (
        artifact_facade.artifact_summary(
            index_path,
            ArtifactSummaryRequestWire(artifact_ids=("/tmp/example.md",)),
        )[0].artifact_id
        == "/tmp/example.md"
    )
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
        (
            "artifact_search",
            (
                "/tmp/artifacts.sqlite",
                artifact_query_to_dict(
                    ArtifactQueryWire(file_types=(), kinds=(), link_types=())
                ),
            ),
        ),
        ("artifact_show", ("/tmp/artifacts.sqlite", "/tmp/example.md")),
        (
            "artifact_show_paged",
            (
                "/tmp/artifacts.sqlite",
                "/tmp/example.md",
                artifact_wire_to_json_dict(ArtifactPageRequestWire()),
            ),
        ),
        (
            "artifact_summary",
            (
                "/tmp/artifacts.sqlite",
                artifact_summary_request_to_dict(
                    ArtifactSummaryRequestWire(artifact_ids=("/tmp/example.md",))
                ),
            ),
        ),
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


def test_artifact_summary_facade_does_not_call_show_per_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    calls: list[str] = []

    def artifact_summary(*args: Any) -> list[dict[str, Any]]:
        calls.append("artifact_summary")
        return [
            {
                "artifact_id": "agent-1",
                "state": "ok",
                "total_linked_count": 0,
                "file_type_counts": [],
                "kind_counts": [],
                "error": None,
            },
            {
                "artifact_id": "agent-2",
                "state": "missing",
                "total_linked_count": 0,
                "file_type_counts": [],
                "kind_counts": [],
                "error": None,
            },
        ]

    def artifact_show(*args: Any) -> dict[str, Any]:
        calls.append("artifact_show")
        raise AssertionError("artifact_summary must not call artifact_show")

    fake.artifact_summary = artifact_summary  # type: ignore[attr-defined]
    fake.artifact_show = artifact_show  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    summaries = artifact_facade.artifact_summary(
        "/tmp/artifacts.sqlite",
        ArtifactSummaryRequestWire(artifact_ids=("agent-1", "agent-2")),
    )

    assert [summary.artifact_id for summary in summaries] == ["agent-1", "agent-2"]
    assert calls == ["artifact_summary"]
