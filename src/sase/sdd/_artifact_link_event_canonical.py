"""Canonical artifact-link event payloads, types, and row reduction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    validate_artifact_link_row,
)

ARTIFACT_LINK_EVENT_COMMIT_MESSAGE = "chore(artifact-links): persist link events"
ARTIFACT_LINK_EVENT_LOCK_FILENAME = "artifact-link-events.lock"
_EVENT_SCHEMA_VERSION = 1


class ArtifactLinkEventPublishError(RuntimeError):
    """Raised when an immutable event cannot be made locally durable."""


class ArtifactLinkEventCorruptionError(ArtifactLinkEventPublishError):
    """Raised when a content-addressed event path already has different bytes."""


@dataclass(frozen=True, slots=True)
class ArtifactLinkEventObject:
    """Canonical immutable event payload plus its content-addressed location."""

    event: dict[str, Any]
    canonical_json: str
    payload: bytes
    digest: str
    relative_path: Path


def canonical_artifact_link_event_object(
    event: Mapping[str, Any],
) -> ArtifactLinkEventObject:
    """Return canonical bytes, digest, and path for one event via Rust."""

    canonical = dict(
        require_rust_binding("artifact_link_event_canonicalize")(dict(event))
    )
    canonical_json = str(
        require_rust_binding("artifact_link_event_canonical_json")(canonical)
    )
    payload = canonical_json.encode("utf-8")
    digest = str(require_rust_binding("artifact_link_event_digest")(canonical))
    relative = Path(
        str(require_rust_binding("artifact_link_event_path_for_digest")(digest))
    )
    validated = dict(
        require_rust_binding("artifact_link_event_validate_bytes")(
            payload,
            relative.as_posix(),
        )
    )
    return ArtifactLinkEventObject(
        event=dict(validated["event"]),
        canonical_json=str(validated["canonical_json"]),
        payload=payload,
        digest=str(validated["digest"]),
        relative_path=Path(str(validated["path"])),
    )


def stable_artifact_link_operation_id(*parts: object) -> str:
    """Return a deterministic 128-bit operation id for replayable writers."""

    payload = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


def observation_or_put_event_from_row(
    row: Mapping[str, Any],
    *,
    project_key: str,
    operation_id: str,
) -> dict[str, Any]:
    """Build a canonical observation or edge-put event from one legacy row."""

    canonical_row = validate_artifact_link_row(row)
    origin = str(canonical_row.get("origin") or "")
    edge = edge_from_row(canonical_row)
    if origin in {"read", "prompt_ref"}:
        kind = {
            "type": "observation",
            "edge": edge,
            "description": str(canonical_row.get("description") or ""),
            "occurrences": row_uses(canonical_row),
        }
    else:
        kind = {
            "type": "edge-put",
            "edge": edge,
            "description": str(canonical_row.get("description") or ""),
            "observed_operation_ids": [],
        }
    return canonical_event(
        {
            "schema_version": _artifact_link_event_schema_version(),
            "project_key": project_key,
            "operation_id": operation_id,
            "created_by": str(canonical_row.get("created_by") or ""),
            "origin": origin,
            "created_at": str(canonical_row.get("created_at") or ""),
            "kind": kind,
        }
    )


def edge_put_event_from_row(
    row: Mapping[str, Any],
    *,
    project_key: str,
    operation_id: str,
    observed_operation_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Build a canonical explicit edge-put event from one row."""

    canonical_row = validate_artifact_link_row(row)
    return canonical_event(
        {
            "schema_version": _artifact_link_event_schema_version(),
            "project_key": project_key,
            "operation_id": operation_id,
            "created_by": str(canonical_row.get("created_by") or ""),
            "origin": str(canonical_row.get("origin") or ""),
            "created_at": str(canonical_row.get("created_at") or ""),
            "kind": {
                "type": "edge-put",
                "edge": edge_from_row(canonical_row),
                "description": str(canonical_row.get("description") or ""),
                "observed_operation_ids": list(observed_operation_ids),
            },
        }
    )


def edge_remove_event(
    *,
    project_key: str,
    operation_id: str,
    source_ref: str,
    relation: str,
    target_ref: str,
    created_by: str,
    origin: str,
    created_at: str,
    observed_operation_ids: Sequence[str],
) -> dict[str, Any]:
    """Build a canonical explicit edge-remove event."""

    return canonical_event(
        {
            "schema_version": _artifact_link_event_schema_version(),
            "project_key": project_key,
            "operation_id": operation_id,
            "created_by": created_by,
            "origin": origin,
            "created_at": created_at,
            "kind": {
                "type": "edge-remove",
                "edge": {
                    "kind": "directed",
                    "source_ref": source_ref,
                    "relation": relation,
                    "target_ref": target_ref,
                },
                "observed_operation_ids": list(observed_operation_ids),
            },
        }
    )


def canonical_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize one event through the Rust event contract."""

    return dict(require_rust_binding("artifact_link_event_canonicalize")(dict(event)))


def _artifact_link_event_schema_version() -> int:
    """Return the Rust event schema version."""

    return int(require_rust_binding("artifact_link_event_schema_version")())


def edge_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical event edge for one validated row."""

    event = canonical_event(
        {
            "schema_version": _artifact_link_event_schema_version(),
            "project_key": "edge_probe",
            "operation_id": "00000000000000000000000000000000",
            "created_by": "sase",
            "origin": "manual",
            "created_at": "1970-01-01T00:00:00Z",
            "kind": {
                "type": "edge-put",
                "edge": {
                    "kind": "directed",
                    "source_ref": str(row.get("source_ref") or ""),
                    "relation": str(row.get("relation") or ""),
                    "target_ref": str(row.get("target_ref") or ""),
                },
                "description": str(row.get("description") or "edge probe"),
                "observed_operation_ids": [],
            },
        }
    )
    kind = event.get("kind")
    if not isinstance(kind, dict):
        raise RuntimeError("sase_core_rs returned malformed artifact-link event kind")
    edge = kind.get("edge")
    if not isinstance(edge, dict):
        raise RuntimeError("sase_core_rs returned malformed artifact-link event edge")
    return dict(edge)


def rows_from_events(
    events: Iterable[Mapping[str, Any] | None],
) -> tuple[dict[str, Any], ...]:
    """Reduce canonical events into legacy row projections via Rust."""

    reduction = reduce_events(events)
    rows = reduction.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("sase_core_rs returned malformed link-event rows")
    return tuple(
        validate_artifact_link_row(row) for row in rows if isinstance(row, dict)
    )


def reduce_events(events: Iterable[Mapping[str, Any] | None]) -> dict[str, Any]:
    """Reduce canonical events and return Rust reduction metadata."""

    canonical_events = [canonical_event(event) for event in events if event is not None]
    if not canonical_events:
        return {"schema_version": _EVENT_SCHEMA_VERSION, "rows": [], "edges": []}
    reduction = require_rust_binding("artifact_link_events_reduce")(
        canonical_events,
        [],
    )
    if not isinstance(reduction, Mapping):
        raise RuntimeError("sase_core_rs returned malformed link-event reduction")
    return dict(reduction)


def event_remove_row(event: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = event.get("kind")
    if not isinstance(kind, dict) or str(kind.get("type") or "") != "edge-remove":
        return None
    edge = kind.get("edge")
    if not isinstance(edge, dict):
        return None
    source, relation, target = _edge_row_parts(edge)
    if not source or not relation or not target:
        return None
    return validate_artifact_link_row(
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": source,
            "relation": relation,
            "target_ref": target,
            "description": "removed artifact link",
            "origin": str(event.get("origin") or "manual"),
            "created_by": str(event.get("created_by") or "sase"),
            "created_at": str(event.get("created_at") or "1970-01-01T00:00:00Z"),
            "uses": 1,
        }
    )


def _edge_row_parts(edge: Mapping[str, Any]) -> tuple[str, str, str]:
    edge_kind = str(edge.get("kind") or "")
    if edge_kind == "directed":
        return (
            str(edge.get("source_ref") or ""),
            str(edge.get("relation") or ""),
            str(edge.get("target_ref") or ""),
        )
    if edge_kind == "undirected":
        return (
            str(edge.get("left_ref") or ""),
            str(edge.get("relation") or ""),
            str(edge.get("right_ref") or ""),
        )
    return "", "", ""


def probe_row_from_edge(edge: Mapping[str, Any]) -> dict[str, Any]:
    source, relation, target = _edge_row_parts(edge)
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": source,
        "relation": relation,
        "target_ref": target,
        "description": "edge probe",
        "origin": "manual",
        "created_by": "sase",
        "created_at": "1970-01-01T00:00:00Z",
        "uses": 1,
    }


def row_uses(row: Mapping[str, Any]) -> int:
    try:
        uses = int(row.get("uses") or 0)
    except (TypeError, ValueError):
        return 0
    return max(1, uses)
