"""Typed Python boundary for the native artifact-link inverted index.

All chip deduplication, aliasing, adjacency, and target resolution live in
:mod:`sase_core_rs`; this module only converts between
:class:`~sase.core.artifact_entry_target.ArtifactEntryTarget` /
:class:`~sase.core.agent_identity_facade.AgentIdentitySnapshot` and plain
Rust binding dictionaries, and holds no Python fallback.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.rust import require_rust_binding


def _index_wire_schema_version() -> int:
    """Return the native artifact-link index wire schema version."""

    binding = require_rust_binding("artifact_link_index_wire_schema_version")
    return int(binding())


def build_index(
    rows: Sequence[Mapping[str, Any]],
    *,
    identity: AgentIdentitySnapshot,
    relations: Sequence[Mapping[str, Any]],
) -> Any:
    """Compile an immutable native index from already-loaded aggregate rows.

    *rows* is converted in one bulk pass; the returned handle is opaque.
    The GIL is released for core compilation inside the binding.
    """

    binding = require_rust_binding("artifact_link_index_build")
    return binding(
        {
            "schema_version": _index_wire_schema_version(),
            "rows": [dict(row) for row in rows],
            "identity": _identity_to_wire(identity),
            "relations": [_relation_to_wire(item) for item in relations],
        }
    )


def index_chips(handle: Any, ref: str) -> list[dict[str, Any]]:
    """Return native chip records for one ref without enumerating the graph."""

    binding = require_rust_binding("artifact_link_index_chips")
    payload = binding(handle, ref)
    return [dict(chip) for chip in payload]


def index_target(handle: Any, ref: str) -> dict[str, Any]:
    """Return membership plus the first indexed target for one ref."""

    binding = require_rust_binding("artifact_link_index_target")
    return dict(binding(handle, ref))


def index_project(
    handle: Any,
    *,
    known_targets: Sequence[ArtifactEntryTarget],
    permitted_relations: Sequence[str],
    project_hint: str | None = None,
) -> dict[str, Any]:
    """Project indexed edges touching *known_targets* through the index.

    Candidate selection uses the native inverted index, never a full scan;
    Python decorates the returned edge records with kind/label.
    """

    binding = require_rust_binding("artifact_link_index_project")
    payload = binding(
        handle,
        {
            "schema_version": _index_wire_schema_version(),
            "known_targets": [_target_to_wire(target) for target in known_targets],
            "permitted_relations": [str(name) for name in permitted_relations],
            "project_hint": project_hint,
        },
    )
    return {
        "edges": [dict(edge) for edge in payload.get("edges", ())],
        "candidate_row_count": int(payload.get("candidate_row_count", 0)),
    }


def index_stats(handle: Any) -> dict[str, Any]:
    """Return raw/deduplicated row and ref counts for the built handle."""

    stats = handle.stats()
    return {str(key): int(value) for key, value in dict(stats).items()}


def target_from_wire(payload: Mapping[str, Any] | None) -> ArtifactEntryTarget | None:
    """Convert a native row-identity wire dict to an entry target."""

    if payload is None:
        return None
    return ArtifactEntryTarget(
        str(payload["pane_id"]),
        tuple(str(part) for part in payload["parts"]),
    )


def _target_to_wire(target: ArtifactEntryTarget) -> dict[str, Any]:
    return {"pane_id": target.pane_id, "parts": list(target.parts)}


def _identity_to_wire(identity: AgentIdentitySnapshot) -> dict[str, Any]:
    owner = identity.owner
    return {
        "username": None if owner is None else owner.username,
        "machine_name": None if owner is None else owner.machine_name,
        "sibling_machines": list(identity.sibling_machines),
        "known_owner_roots": list(identity.known_owner_roots),
    }


def _relation_to_wire(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "slug": str(item.get("slug") or ""),
        "inverse": str(item.get("inverse") or ""),
        "directed": bool(item.get("directed", True)),
    }


__all__ = [
    "build_index",
    "index_chips",
    "index_project",
    "index_stats",
    "index_target",
    "target_from_wire",
]
