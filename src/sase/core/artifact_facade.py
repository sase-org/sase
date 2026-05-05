"""Strict Rust facade for the unified artifact graph.

The facade calls ``sase_core_rs`` directly through
:func:`sase.core.rust.require_rust_binding` and rehydrates the returned
dict/list objects into typed Python wire dataclasses. Formatting, CLI defaults,
and human output are intentionally left to later artifact CLI/TUI work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ARTIFACT_STALE_CLEANUP_NONE,
    ArtifactDoctorOptionsWire,
    ArtifactDoctorWire,
    ArtifactDetailWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactLinkRemoveWire,
    ArtifactLinkUpsertWire,
    ArtifactMutationResultWire,
    ArtifactNodeRemoveWire,
    ArtifactNodeUpsertWire,
    ArtifactNodeWire,
    ArtifactPathUpsertRequestWire,
    ArtifactPayloadWire,
    ArtifactQueryWire,
    ArtifactRebuildRequestWire,
    artifact_detail_from_dict,
    artifact_doctor_from_dict,
    artifact_doctor_options_to_dict,
    artifact_graph_from_dict,
    artifact_graph_options_to_dict,
    artifact_mutation_result_from_dict,
    artifact_node_from_dict,
    artifact_path_upsert_request_to_dict,
    artifact_query_to_dict,
    artifact_rebuild_request_to_dict,
    artifact_wire_to_json_dict,
)
from sase.core.rust import require_rust_binding


ArtifactAddRequest = (
    ArtifactNodeUpsertWire | ArtifactLinkUpsertWire | ArtifactPayloadWire
)
ArtifactRemoveRequest = ArtifactNodeRemoveWire | ArtifactLinkRemoveWire


def _path_str(path: Path | str) -> str:
    return str(path)


def _request_to_dict(
    request: ArtifactAddRequest | ArtifactRemoveRequest,
) -> dict[str, Any]:
    payload = artifact_wire_to_json_dict(request)
    if not isinstance(payload, dict):
        raise TypeError("artifact request must serialize to a dict")
    return payload


def artifact_add(
    index_path: Path | str,
    request: ArtifactAddRequest,
) -> ArtifactMutationResultWire:
    """Add/upsert an artifact node, link, or payload via ``sase_core_rs``."""
    binding = require_rust_binding("artifact_add")
    payload: dict[str, Any] = binding(_path_str(index_path), _request_to_dict(request))
    return artifact_mutation_result_from_dict(payload)


def artifact_remove(
    index_path: Path | str,
    request: ArtifactRemoveRequest,
) -> ArtifactMutationResultWire:
    """Remove or tombstone an artifact node or link via ``sase_core_rs``."""
    binding = require_rust_binding("artifact_remove")
    payload: dict[str, Any] = binding(_path_str(index_path), _request_to_dict(request))
    return artifact_mutation_result_from_dict(payload)


def artifact_list(
    index_path: Path | str,
    query: ArtifactQueryWire | None = None,
) -> list[ArtifactNodeWire]:
    """List artifact nodes with optional query filters."""
    binding = require_rust_binding("artifact_list")
    query_wire = query or ArtifactQueryWire()
    payload: list[dict[str, Any]] = binding(
        _path_str(index_path),
        artifact_query_to_dict(query_wire),
    )
    return [artifact_node_from_dict(node) for node in payload]


def artifact_show(index_path: Path | str, artifact_id: str) -> ArtifactDetailWire:
    """Return one artifact detail record."""
    binding = require_rust_binding("artifact_show")
    payload: dict[str, Any] = binding(_path_str(index_path), artifact_id)
    return artifact_detail_from_dict(payload)


def artifact_graph(
    index_path: Path | str,
    options: ArtifactGraphOptionsWire | None = None,
) -> ArtifactGraphWire:
    """Materialize a bounded artifact graph."""
    binding = require_rust_binding("artifact_graph")
    options_wire = options or ArtifactGraphOptionsWire()
    payload: dict[str, Any] = binding(
        _path_str(index_path),
        artifact_graph_options_to_dict(options_wire),
    )
    return artifact_graph_from_dict(payload)


def artifact_rebuild(
    index_path: Path | str,
    request: ArtifactRebuildRequestWire | None = None,
) -> ArtifactMutationResultWire:
    """Run the typed Rust artifact rebuild entry point."""
    binding = require_rust_binding("artifact_rebuild")
    request_wire = request or ArtifactRebuildRequestWire()
    payload: dict[str, Any] = binding(
        _path_str(index_path),
        artifact_rebuild_request_to_dict(request_wire),
    )
    return artifact_mutation_result_from_dict(payload)


def artifact_upsert_path(
    index_path: Path | str,
    artifact_path: Path | str,
    request: ArtifactPathUpsertRequestWire | None = None,
) -> ArtifactMutationResultWire:
    """Upsert a path-derived node and deterministic directory parents."""
    binding = require_rust_binding("artifact_upsert_path")
    request_wire = request or ArtifactPathUpsertRequestWire()
    payload: dict[str, Any] = binding(
        _path_str(index_path),
        _path_str(artifact_path),
        artifact_path_upsert_request_to_dict(request_wire),
    )
    return artifact_mutation_result_from_dict(payload)


def artifact_doctor(
    index_path: Path | str,
    options: ArtifactDoctorOptionsWire | None = None,
) -> ArtifactDoctorWire:
    """Run artifact graph consistency checks."""
    binding = require_rust_binding("artifact_doctor")
    options_wire = options or ArtifactDoctorOptionsWire()
    payload: dict[str, Any] = binding(
        _path_str(index_path),
        artifact_doctor_options_to_dict(options_wire),
    )
    return artifact_doctor_from_dict(payload)


# pyvision: public_api_methods.txt
def artifact_node_upsert_request(
    node: ArtifactNodeWire,
    *,
    replace_payloads: bool = False,
) -> ArtifactNodeUpsertWire:
    """Build a schema-versioned node upsert request."""
    return ArtifactNodeUpsertWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=node,
        replace_payloads=replace_payloads,
    )


def artifact_rebuild_request(
    *,
    projects_root: Path | str | None = None,
    workspace_root: Path | str | None = None,
    beads_dir: Path | str | None = None,
    include_sources: tuple[str, ...] = (),
    exclude_sources: tuple[str, ...] = (),
    target_path: Path | str | None = None,
    artifact_dir: Path | str | None = None,
    stale_cleanup: str = ARTIFACT_STALE_CLEANUP_NONE,
) -> ArtifactRebuildRequestWire:
    """Build a schema-versioned artifact rebuild request."""
    return ArtifactRebuildRequestWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        projects_root=_optional_path_str(projects_root),
        workspace_root=_optional_path_str(workspace_root),
        beads_dir=_optional_path_str(beads_dir),
        include_sources=tuple(include_sources),
        exclude_sources=tuple(exclude_sources),
        target_path=_optional_path_str(target_path),
        artifact_dir=_optional_path_str(artifact_dir),
        stale_cleanup=stale_cleanup,
    )


def artifact_path_upsert_request(
    *,
    kind: str | None = None,
    display_title: str | None = None,
    subtitle: str | None = None,
    provenance: str | None = None,
    source_kind: str | None = None,
    source_id: str | None = None,
    source_version: str | None = None,
    search_text: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtifactPathUpsertRequestWire:
    """Build a schema-versioned path upsert request."""
    return ArtifactPathUpsertRequestWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        kind=kind,
        display_title=display_title,
        subtitle=subtitle,
        provenance=provenance,
        source_kind=source_kind,
        source_id=source_id,
        source_version=source_version,
        search_text=search_text,
        metadata=metadata,
    )


def _optional_path_str(path: Path | str | None) -> str | None:
    return None if path is None else _path_str(path)
