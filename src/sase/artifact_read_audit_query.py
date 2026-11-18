"""Targeted Rust-backed queries for artifact-read audit JSONL logs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from sase.artifact_read_log import (
    ARTIFACT_READ_AUDIT_QUERY_WIRE_SCHEMA_VERSION,
    ArtifactReadAuditRow,
    ArtifactReadAuditSourceIdentity,
    ArtifactReadEvent,
    artifact_read_event_from_mapping,
)


def query_artifact_read_events(
    log_path: Path | str,
    *,
    members: Sequence[Mapping[str, Any] | Any],
    limit: int = 50,
    deduplicate: bool = False,
) -> tuple[list[ArtifactReadAuditRow], ArtifactReadAuditSourceIdentity]:
    """Return targeted rows and the identity of their source.

    Rust streams and validates the JSONL file, retaining only rows attributed
    to the ordered selectors. The explicit full-history reader remains
    available separately for callers that need every event.
    """

    from sase.core.rust import require_rust_binding

    _require_audit_query_schema()
    resolved = Path(log_path).expanduser()
    payload_members: list[dict[str, Any]] = []
    for member in members:
        if isinstance(member, Mapping):
            artifacts_dir = member.get("artifacts_dir")
            agent_name = member.get("agent_name")
        else:
            artifacts_dir = getattr(member, "artifacts_dir", None)
            agent_name = getattr(member, "agent_name", None)
        payload_members.append(
            {
                "artifacts_dir": str(artifacts_dir)
                if artifacts_dir is not None
                else None,
                "agent_name": str(agent_name) if agent_name is not None else None,
            }
        )
    binding = require_rust_binding("artifact_read_audit_query")
    raw = binding(
        str(resolved),
        {
            "members": payload_members,
            "limit": int(limit),
            "deduplicate": bool(deduplicate),
        },
    )
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-read audit query "
            "result: expected an object"
        )
    payload = cast(Mapping[str, Any], raw)
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-read audit query "
            "result: expected rows to be a list"
        )
    rows = [
        _artifact_read_query_row_from_wire(
            raw_row, row_number=index, member_count=len(payload_members)
        )
        for index, raw_row in enumerate(raw_rows, start=1)
    ]
    return rows, _artifact_read_query_source_from_wire(payload.get("source"))


def _require_audit_query_schema() -> None:
    from sase.core.rust import require_rust_binding

    binding = require_rust_binding("artifact_read_audit_query_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_READ_AUDIT_QUERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-read audit query wire is stale: "
            f"expected {ARTIFACT_READ_AUDIT_QUERY_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _artifact_read_query_row_from_wire(
    raw: object, *, row_number: int, member_count: int
) -> ArtifactReadAuditRow:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-read audit query row "
            f"{row_number}: expected an object"
        )
    row = cast(Mapping[str, Any], raw)
    raw_event = row.get("event")
    if not isinstance(raw_event, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-read audit query row "
            f"{row_number}: event must be an object"
        )
    member_index = row.get("member_index")
    if (
        not isinstance(member_index, int)
        or isinstance(member_index, bool)
        or member_index < 0
        or member_index >= member_count
    ):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-read audit query row "
            f"{row_number}: member_index out of range"
        )
    event = artifact_read_event_from_mapping(cast(Mapping[str, Any], raw_event))
    if event is None:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-read audit query row "
            f"{row_number}: event failed artifact-read validation"
        )
    return ArtifactReadAuditRow(event=event, member_index=member_index)


def _artifact_read_query_source_from_wire(
    raw: object,
) -> ArtifactReadAuditSourceIdentity:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-read audit query "
            "source identity: expected an object"
        )
    source = cast(Mapping[str, Any], raw)
    missing = source.get("missing", False)
    if not isinstance(missing, bool):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-read audit query "
            "source identity: missing must be a boolean"
        )
    return ArtifactReadAuditSourceIdentity(
        missing=missing,
        size=_require_query_identity_int(source, "size"),
        mtime_ns=_require_query_identity_int(source, "mtime_ns"),
        dev=_require_query_identity_int(source, "dev"),
        ino=_require_query_identity_int(source, "ino"),
    )


def _require_query_identity_int(source: Mapping[str, Any], field: str) -> int:
    value = source.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-read audit query "
            f"source identity: {field} must be a non-negative integer"
        )
    return value
