"""Queue records and helpers for the artifact-link operation journal."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from typing import Any

from sase.sdd._artifact_link_store_support import validate_artifact_link_row
from sase.sdd.artifact_link_event_publisher import (
    canonical_event as _canonical_event,
    observation_or_put_event_from_row,
    rows_from_events as _event_rows_from_events,
)

ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION = 2
ARTIFACT_LINK_OUTBOX_FILENAME = "artifact-link-outbox.jsonl"
ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME = "artifact-link-outbox-dropped.jsonl"


@dataclass(frozen=True, slots=True)
class ArtifactLinkOutboxEntry:
    """One queued artifact-link operation plus its recording run's identity.

    ``run_id`` binds this entry to the specific run that recorded it (see
    ``sase.sdd.artifact_link_release_evidence``): a different run of the same
    agent, or another agent in the same family, must not be able to release
    it merely by publishing something of its own.

    Schema-v2 entries store the canonical event payload. The one-time
    legacy-index importer owns schema-v1 row conversion; regular readers no
    longer accept row-only queue entries.
    """

    schema_version: int
    id: str
    created_at: float
    project_key: str
    agent_name: str
    run_id: str
    row: dict[str, Any] | None = None
    event: dict[str, Any] | None = None

    @property
    def logical_key(self) -> tuple[str, str, str]:
        if self.row is None:
            raise RuntimeError("artifact-link outbox entry has no legacy row")
        return _row_key(self.row)

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "created_at": self.created_at,
            "project_key": self.project_key,
            "agent_name": self.agent_name,
            "run_id": self.run_id,
        }
        if self.event is not None:
            payload["event"] = dict(self.event)
        else:
            payload["row"] = dict(self.row or {})
        return payload


def entry_from_line(line: str, project_key: str) -> ArtifactLinkOutboxEntry | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return _entry_from_mapping(data, project_key)
    except (TypeError, ValueError, RuntimeError):
        return None


def _entry_from_mapping(
    data: Mapping[str, Any],
    project_key: str,
) -> ArtifactLinkOutboxEntry:
    schema_version = _integer_schema_version(data.get("schema_version"))
    entry_project = required_text(data.get("project_key"), "project_key")
    if entry_project != project_key:
        raise RuntimeError("artifact-link outbox project mismatch")
    created_at = data.get("created_at")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        raise RuntimeError("artifact-link outbox created_at must be a number")
    raw_event = data.get("event")
    if isinstance(raw_event, dict):
        if schema_version != ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION:
            raise RuntimeError("unsupported artifact-link event outbox schema")
        event = _canonical_event(raw_event)
        parsed_operation_id = event_operation_id(event)
        if required_text(data.get("id"), "id") != parsed_operation_id:
            raise RuntimeError("artifact-link outbox id must match operation_id")
        event_project = required_text(event.get("project_key"), "project_key")
        if event_project != project_key:
            raise RuntimeError("artifact-link outbox event project mismatch")
        rows = _event_rows_from_events((event,))
        return ArtifactLinkOutboxEntry(
            schema_version=schema_version,
            id=parsed_operation_id,
            created_at=float(created_at),
            project_key=entry_project,
            agent_name=required_text(data.get("agent_name"), "agent_name"),
            run_id=str(data.get("run_id") or ""),
            row=rows[0] if len(rows) == 1 else None,
            event=event,
        )

    raise RuntimeError("artifact-link outbox row-only entries require import-indexes")


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("source_ref") or ""),
        str(row.get("relation") or ""),
        str(row.get("target_ref") or ""),
    )


def sidecar_refs(entry: ArtifactLinkOutboxEntry) -> tuple[str, ...]:
    if entry.row is not None:
        return (
            str(entry.row.get("source_ref") or ""),
            str(entry.row.get("target_ref") or ""),
        )
    event = entry.event
    if event is None:
        return ()
    kind = event.get("kind")
    if not isinstance(kind, dict):
        return ()
    event_type = str(kind.get("type") or "")
    if event_type in {"observation", "edge-put", "edge-remove"}:
        edge = kind.get("edge")
        if not isinstance(edge, dict):
            return ()
        edge_kind = str(edge.get("kind") or "")
        if edge_kind == "directed":
            return (
                str(edge.get("source_ref") or ""),
                str(edge.get("target_ref") or ""),
            )
        if edge_kind == "undirected":
            return (
                str(edge.get("left_ref") or ""),
                str(edge.get("right_ref") or ""),
            )
    if event_type == "alias":
        return (
            str(kind.get("old_ref") or ""),
            str(kind.get("new_ref") or ""),
        )
    if event_type == "baseline-import":
        refs: list[str] = []
        rows = kind.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                refs.append(str(row.get("source_ref") or ""))
                refs.append(str(row.get("target_ref") or ""))
        return tuple(refs)
    return ()


def event_from_row(
    row: Mapping[str, Any],
    *,
    project_key: str,
    operation_id: str,
) -> dict[str, Any]:
    return observation_or_put_event_from_row(
        row,
        project_key=project_key,
        operation_id=operation_id,
    )


def rows_from_events(
    events: Iterable[Mapping[str, Any] | None],
) -> tuple[dict[str, Any], ...]:
    return _event_rows_from_events(events)


def operation_id(value: object) -> str:
    text = required_text(value, "operation_id")
    if len(text) != 32 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(
            "artifact-link outbox operation_id must be 32 lowercase hex characters"
        )
    return text


def event_operation_id(event: Mapping[str, Any]) -> str:
    return operation_id(event.get("operation_id"))


def _integer_schema_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError("artifact-link outbox schema_version must be an integer")
    return value


def required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"artifact-link outbox {field} must be a non-empty string")
    return value.strip()


__all__ = [
    "ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME",
    "ARTIFACT_LINK_OUTBOX_FILENAME",
    "ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION",
    "ArtifactLinkOutboxEntry",
    "entry_from_line",
    "event_from_row",
    "event_operation_id",
    "operation_id",
    "required_text",
    "rows_from_events",
    "sidecar_refs",
]
