"""Rust-backed targeted query facade for memory-read audit logs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.core.rust import require_rust_binding
from sase.memory._read_log_models import MemoryReadEvent


MEMORY_AUDIT_QUERY_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MemoryAuditSourceIdentity:
    """Identity of the log file a targeted audit query actually read."""

    missing: bool
    size: int
    mtime_ns: int
    dev: int
    ino: int


@dataclass(frozen=True)
class _MemoryAuditRow:
    """One matched memory-read event plus the claiming member ordinal."""

    event: MemoryReadEvent
    member_index: int


def query_memory_audit(
    log_path: Path | str,
    *,
    members: Sequence[Mapping[str, Any] | Any],
    limit: int = 50,
    deduplicate: bool = False,
) -> tuple[list[_MemoryAuditRow], MemoryAuditSourceIdentity]:
    """Return matching memory-read rows for ordered member selectors.

    ``members`` is an ordered list of ``{"artifacts_dir": str|None,
    "agent_name": str|None}`` dicts (or objects with those attributes).
    Matching preserves artifact-directory precedence and first-member
    attribution; ``deduplicate`` selects the context duplicate policy.
    """

    _require_audit_schema()
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
    binding = require_rust_binding("memory_audit_query")
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
            "sase_core_rs returned an incompatible memory audit query result: "
            "expected an object"
        )
    payload = cast(Mapping[str, Any], raw)
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query result: "
            "expected rows to be a list"
        )
    rows = [
        _audit_row_from_wire(
            raw_row, row_number=index, member_count=len(payload_members)
        )
        for index, raw_row in enumerate(raw_rows, start=1)
    ]
    return rows, _source_identity_from_wire(payload.get("source"))


def _require_audit_schema() -> None:
    binding = require_rust_binding("memory_audit_query_wire_schema_version")
    version = int(binding())
    if version != MEMORY_AUDIT_QUERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs memory audit query wire is stale: "
            f"expected {MEMORY_AUDIT_QUERY_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _source_identity_from_wire(raw: object) -> MemoryAuditSourceIdentity:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query source "
            "identity: expected an object"
        )
    source = cast(Mapping[str, Any], raw)
    missing = source.get("missing", False)
    if not isinstance(missing, bool):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query source "
            "identity: missing must be a boolean"
        )
    return MemoryAuditSourceIdentity(
        missing=missing,
        size=_require_identity_int(source, "size"),
        mtime_ns=_require_identity_int(source, "mtime_ns"),
        dev=_require_identity_int(source, "dev"),
        ino=_require_identity_int(source, "ino"),
    )


def _require_identity_int(source: Mapping[str, Any], field: str) -> int:
    value = source.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query source "
            f"identity: {field} must be a non-negative integer"
        )
    return value


def _audit_row_from_wire(
    raw: object, *, row_number: int, member_count: int
) -> _MemoryAuditRow:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: expected an object"
        )
    row = cast(Mapping[str, Any], raw)
    raw_event = row.get("event")
    if not isinstance(raw_event, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
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
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: member_index out of range"
        )
    return _MemoryAuditRow(
        event=_memory_event_from_wire(raw_event, row_number=row_number),
        member_index=member_index,
    )


def _memory_event_from_wire(
    raw: Mapping[str, Any], *, row_number: int
) -> MemoryReadEvent:
    try:
        schema_version = raw["schema_version"]
        event_id = raw["id"]
        timestamp = raw["timestamp"]
        project = raw["project"]
        cwd = raw["cwd"]
        canonical_path = raw["canonical_path"]
        resolved_path = raw["resolved_path"]
        agent_name = raw["agent_name"]
        agent_source = raw["agent_source"]
        reason = raw["reason"]
        byte_count = raw["byte_count"]
        frontmatter_stripped = raw["frontmatter_stripped"]
    except KeyError as exc:
        raise RuntimeError(
            "sase_core_rs returned an incomplete memory audit query row "
            f"{row_number}: missing {exc}"
        ) from exc
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: schema_version must be an integer"
        )
    for field_name, value in (
        ("id", event_id),
        ("timestamp", timestamp),
        ("project", project),
        ("cwd", cwd),
        ("canonical_path", canonical_path),
        ("resolved_path", resolved_path),
        ("agent_name", agent_name),
        ("agent_source", agent_source),
        ("reason", reason),
    ):
        if not isinstance(value, str):
            raise RuntimeError(
                "sase_core_rs returned an incompatible memory audit query row "
                f"{row_number}: {field_name} must be a string"
            )
    if not isinstance(byte_count, int) or isinstance(byte_count, bool):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: byte_count must be an integer"
        )
    if not isinstance(frontmatter_stripped, bool):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: frontmatter_stripped must be a boolean"
        )
    artifacts_dir = raw.get("artifacts_dir")
    if artifacts_dir is not None and not isinstance(artifacts_dir, str):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: artifacts_dir must be a string or null"
        )
    kind = raw.get("kind", "note")
    if kind not in ("note", "web", "strand"):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: kind must be note, web, or strand"
        )
    selectors = _string_tuple(raw.get("selectors"), row_number, "selectors")
    resolved_targets = _string_tuple(
        raw.get("resolved_targets"), row_number, "resolved_targets"
    )
    included_targets = _string_tuple(
        raw.get("included_targets"), row_number, "included_targets"
    )
    depth = raw.get("depth")
    if depth is not None and (not isinstance(depth, int) or isinstance(depth, bool)):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: depth must be an integer or null"
        )
    scope_origin = _pair_tuple(raw.get("scope_origin"), row_number, "scope_origin")
    blob_oid = raw.get("blob_oid")
    if blob_oid is not None and not isinstance(blob_oid, str):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: blob_oid must be a string or null"
        )
    included_blob_oids = _pair_tuple(
        raw.get("included_blob_oids"), row_number, "included_blob_oids"
    )
    return MemoryReadEvent(
        schema_version=int(schema_version),
        id=str(event_id),
        timestamp=str(timestamp),
        project=str(project),
        cwd=str(cwd),
        canonical_path=str(canonical_path),
        resolved_path=str(resolved_path),
        agent_name=str(agent_name),
        agent_source=str(agent_source),
        artifacts_dir=artifacts_dir,
        reason=str(reason),
        byte_count=int(byte_count),
        frontmatter_stripped=bool(frontmatter_stripped),
        kind=str(kind),  # type: ignore[arg-type]
        selectors=selectors,
        resolved_targets=resolved_targets,
        included_targets=included_targets,
        depth=depth,
        scope_origin=scope_origin,
        blob_oid=blob_oid,
        included_blob_oids=included_blob_oids,
    )


def _string_tuple(raw: Any, row_number: int, field: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: {field} must be a list of strings"
        )
    return tuple(raw)


def _pair_tuple(raw: Any, row_number: int, field: str) -> tuple[tuple[str, str], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise RuntimeError(
            "sase_core_rs returned an incompatible memory audit query row "
            f"{row_number}: {field} must be a list of pairs"
        )
    pairs: list[tuple[str, str]] = []
    for item in raw:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(part, str) for part in item)
        ):
            raise RuntimeError(
                "sase_core_rs returned an incompatible memory audit query row "
                f"{row_number}: {field} must be a list of string pairs"
            )
        pairs.append((item[0], item[1]))
    return tuple(pairs)


__all__ = [
    "MEMORY_AUDIT_QUERY_WIRE_SCHEMA_VERSION",
    "MemoryAuditSourceIdentity",
    "query_memory_audit",
]
