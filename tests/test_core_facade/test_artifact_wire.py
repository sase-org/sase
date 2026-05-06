"""Tests for artifact graph wire models and request helpers."""

from __future__ import annotations

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
    ARTIFACT_PROVENANCE_DERIVED,
    ARTIFACT_ROOT_ID,
    ARTIFACT_SOURCE_DIRECTORY,
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactPageRequestWire,
    ArtifactPathUpsertRequestWire,
    ArtifactQueryWire,
    ArtifactRebuildRequestWire,
    artifact_detail_from_dict,
    artifact_detail_paged_from_dict,
    artifact_doctor_from_dict,
    artifact_graph_from_dict,
    artifact_mutation_result_from_dict,
    artifact_page_request_from_dict,
    artifact_page_request_to_dict,
    artifact_path_upsert_request_to_dict,
    artifact_query_from_dict,
    artifact_query_to_dict,
    artifact_rebuild_request_to_dict,
    artifact_root_node,
    artifact_wire_to_json_dict,
)
from tests.test_core_facade._helpers import artifact_mutation_result, artifact_node


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
    assert artifact_wire_to_json_dict(artifact_node()) == {
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

    page_request = ArtifactPageRequestWire()
    assert artifact_page_request_to_dict(page_request) == {
        "schema_version": 1,
        "group_key": None,
        "relation": None,
        "link_type": None,
        "offset": 0,
        "limit": 10,
    }
    assert (
        artifact_page_request_from_dict(artifact_page_request_to_dict(page_request))
        == page_request
    )

    paged = artifact_detail_paged_from_dict(
        {
            "schema_version": 1,
            "node": None,
            "payloads": [],
            "path_to_root": [],
            "diagnostics": [],
            "children_page": {
                "summary": {
                    "group_key": "children",
                    "direction": "children",
                    "link_type": None,
                    "total_count": 42,
                    "loaded_count": 10,
                },
                "nodes": [],
                "links": [],
            },
            "outbound_pages": [],
            "inbound_pages": [],
            "type_counts": [{"artifact_type": "file", "total_count": 42}],
        }
    )
    assert paged.children_page is not None
    assert paged.children_page.summary.total_count == 42
    assert paged.type_counts[0].artifact_type == "file"


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
            "ArtifactDetailPagedWire",
            artifact_detail_paged_from_dict,
            {
                "schema_version": 999,
                "node": None,
                "payloads": [],
                "path_to_root": [],
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
            {**artifact_mutation_result(), "schema_version": 999},
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

    page_request = artifact_facade.artifact_page_request(
        relation="outbound",
        link_type="related",
        offset=10,
        limit=5,
    )
    assert artifact_page_request_to_dict(page_request) == {
        "schema_version": 1,
        "group_key": None,
        "relation": "outbound",
        "link_type": "related",
        "offset": 10,
        "limit": 5,
    }


def test_paged_wire_converters_reject_unknown_fields() -> None:
    with pytest.raises(TypeError, match="unknown ArtifactPageRequestWire field"):
        artifact_page_request_from_dict(
            {
                "schema_version": 1,
                "group_key": None,
                "relation": None,
                "link_type": None,
                "offset": 0,
                "limit": 10,
                "unexpected": True,
            }
        )


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
