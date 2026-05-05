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
    ArtifactPayloadWire,
    ArtifactQueryWire,
    artifact_detail_from_dict,
    artifact_doctor_from_dict,
    artifact_doctor_options_to_dict,
    artifact_graph_from_dict,
    artifact_graph_options_to_dict,
    artifact_mutation_result_from_dict,
    artifact_node_from_dict,
    artifact_query_to_dict,
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


# pyvision: public_api_methods.txt
def artifact_add(
    index_path: Path | str,
    request: ArtifactAddRequest,
) -> ArtifactMutationResultWire:
    """Add/upsert an artifact node, link, or payload via ``sase_core_rs``."""
    binding = require_rust_binding("artifact_add")
    payload: dict[str, Any] = binding(_path_str(index_path), _request_to_dict(request))
    return artifact_mutation_result_from_dict(payload)


# pyvision: public_api_methods.txt
def artifact_remove(
    index_path: Path | str,
    request: ArtifactRemoveRequest,
) -> ArtifactMutationResultWire:
    """Remove or tombstone an artifact node or link via ``sase_core_rs``."""
    binding = require_rust_binding("artifact_remove")
    payload: dict[str, Any] = binding(_path_str(index_path), _request_to_dict(request))
    return artifact_mutation_result_from_dict(payload)


# pyvision: public_api_methods.txt
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


# pyvision: public_api_methods.txt
def artifact_show(index_path: Path | str, artifact_id: str) -> ArtifactDetailWire:
    """Return one artifact detail record."""
    binding = require_rust_binding("artifact_show")
    payload: dict[str, Any] = binding(_path_str(index_path), artifact_id)
    return artifact_detail_from_dict(payload)


# pyvision: public_api_methods.txt
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


# pyvision: public_api_methods.txt
def artifact_rebuild(
    index_path: Path | str,
    request: dict[str, Any] | None = None,
) -> ArtifactMutationResultWire:
    """Run the current Rust rebuild entry point.

    Epic 1's binding returns an explicit no-op result until source ingesters
    are implemented in a later epic.
    """
    binding = require_rust_binding("artifact_rebuild")
    if request is None:
        payload: dict[str, Any] = binding(_path_str(index_path))
    else:
        payload = binding(_path_str(index_path), artifact_wire_to_json_dict(request))
    return artifact_mutation_result_from_dict(payload)


# pyvision: public_api_methods.txt
def artifact_upsert_path(
    index_path: Path | str,
    artifact_path: Path | str,
    request: dict[str, Any] | None = None,
) -> ArtifactMutationResultWire:
    """Upsert a path-derived node using the Rust binding's path helper."""
    binding = require_rust_binding("artifact_upsert_path")
    if request is None:
        payload: dict[str, Any] = binding(
            _path_str(index_path), _path_str(artifact_path)
        )
    else:
        payload = binding(
            _path_str(index_path),
            _path_str(artifact_path),
            artifact_wire_to_json_dict(request),
        )
    return artifact_mutation_result_from_dict(payload)


# pyvision: public_api_methods.txt
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
