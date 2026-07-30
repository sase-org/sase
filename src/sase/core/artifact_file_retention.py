"""Rust-backed artifact-file retention planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from sase.config.core import DEFAULT_ARTIFACT_RETENTION_KEEP_PER_LABEL
from sase.core.artifact_file_economics import (
    ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION,
)
from sase.core.artifact_file_types import default_artifact_files_index_path
from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class RetentionPolicy:
    """Deterministic inputs for the core retention planner."""

    now: str
    keep_per_label: int = DEFAULT_ARTIFACT_RETENTION_KEEP_PER_LABEL
    before: str | None = None
    kinds: tuple[str, ...] | None = None
    project: str | None = None
    min_size_bytes: int | None = None
    protected_ids: frozenset[str] = frozenset()
    limit: int | None = None


@dataclass(frozen=True)
class _RetentionItem:
    """One artifact selected by a retention plan."""

    id: str
    label: str
    kind: str
    project: str | None
    agent_name: str | None
    path: str | None
    size_bytes: int | None
    created_at: str | None
    reason: str


@dataclass(frozen=True)
class _ProtectedRetentionItem:
    """One artifact excluded from retention and why."""

    id: str
    reason: str


@dataclass(frozen=True)
class _RetentionCounts:
    """Planner counts split by storage representation."""

    candidates: int
    selected: int
    protected: int
    byte_backed_selected: int
    byte_free_selected: int


@dataclass(frozen=True)
class RetentionPlan:
    """Validated, read-only retention plan returned by ``sase_core_rs``."""

    schema_version: int
    selected: tuple[_RetentionItem, ...]
    protected: tuple[_ProtectedRetentionItem, ...]
    counts: _RetentionCounts
    reclaimable_bytes: int
    truncated: int
    summary_lines: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-safe plan projection."""

        return asdict(self)


def plan_artifact_file_retention(
    policy: RetentionPolicy,
    *,
    index_path: Path | str | None = None,
) -> RetentionPlan:
    """Plan artifact retention without changing the index or stored files."""

    _require_lifecycle_schema()
    resolved_index = (
        Path(default_artifact_files_index_path() if index_path is None else index_path)
        .expanduser()
        .resolve(strict=False)
    )
    wire = _policy_to_wire(policy)
    binding = require_rust_binding("artifact_file_retention_plan")
    return _plan_from_wire(binding(str(resolved_index), wire))


def _require_lifecycle_schema() -> None:
    binding = require_rust_binding("artifact_file_lifecycle_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-file lifecycle wire is stale: "
            f"expected {ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _policy_to_wire(policy: RetentionPolicy) -> dict[str, object]:
    if not isinstance(policy.now, str) or not policy.now:
        raise ValueError("now must be a non-empty RFC3339 string")
    keep_per_label = _nonnegative(policy.keep_per_label, "keep_per_label")
    min_size = (
        None
        if policy.min_size_bytes is None
        else _nonnegative(policy.min_size_bytes, "min_size_bytes")
    )
    limit = None if policy.limit is None else _nonnegative(policy.limit, "limit")
    return {
        "schema_version": ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION,
        "now": policy.now,
        "keep_per_label": keep_per_label,
        "before": policy.before,
        "kinds": None if policy.kinds is None else list(policy.kinds),
        "project": policy.project,
        "min_size_bytes": min_size,
        "protected_ids": sorted(policy.protected_ids),
        "limit": limit,
    }


def _plan_from_wire(raw: object) -> RetentionPlan:
    data = _mapping(raw, "result")
    schema_version = _integer(data, "schema_version")
    if schema_version != ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file retention plan: "
            f"schema_version must be {ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION}"
        )
    return RetentionPlan(
        schema_version=schema_version,
        selected=_selected_items(data),
        protected=_protected_items(data),
        counts=_counts(data),
        reclaimable_bytes=_integer(data, "reclaimable_bytes"),
        truncated=_integer(data, "truncated"),
        summary_lines=_string_tuple(data, "summary_lines"),
    )


def _selected_items(data: Mapping[str, Any]) -> tuple[_RetentionItem, ...]:
    field = "selected"
    raw_items = data.get(field)
    if not isinstance(raw_items, list):
        raise _wire_error(f"{field} must be a list")
    items: list[_RetentionItem] = []
    for index, raw_item in enumerate(raw_items, start=1):
        item = _mapping(raw_item, f"{field}[{index}]")
        prefix = f"{field}[{index}]"
        items.append(
            _RetentionItem(
                id=_string(item, "id", prefix),
                label=_string(item, "label", prefix),
                kind=_string(item, "kind", prefix),
                project=_optional_string(item, "project", prefix),
                agent_name=_optional_string(item, "agent_name", prefix),
                path=_optional_string(item, "path", prefix),
                size_bytes=_optional_integer(item, "size_bytes", prefix),
                created_at=_optional_string(item, "created_at", prefix),
                reason=_string(item, "reason", prefix),
            )
        )
    return tuple(items)


def _protected_items(
    data: Mapping[str, Any],
) -> tuple[_ProtectedRetentionItem, ...]:
    field = "protected"
    raw_items = data.get(field)
    if not isinstance(raw_items, list):
        raise _wire_error(f"{field} must be a list")
    items: list[_ProtectedRetentionItem] = []
    for index, raw_item in enumerate(raw_items, start=1):
        item = _mapping(raw_item, f"{field}[{index}]")
        prefix = f"{field}[{index}]"
        items.append(
            _ProtectedRetentionItem(
                id=_string(item, "id", prefix),
                reason=_string(item, "reason", prefix),
            )
        )
    return tuple(items)


def _counts(data: Mapping[str, Any]) -> _RetentionCounts:
    counts = _mapping(data.get("counts"), "counts")
    return _RetentionCounts(
        candidates=_integer(counts, "candidates", prefix="counts"),
        selected=_integer(counts, "selected", prefix="counts"),
        protected=_integer(counts, "protected", prefix="counts"),
        byte_backed_selected=_integer(counts, "byte_backed_selected", prefix="counts"),
        byte_free_selected=_integer(counts, "byte_free_selected", prefix="counts"),
    )


def _mapping(raw: object, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise _wire_error(f"{field} must be an object")
    return cast(Mapping[str, Any], raw)


def _integer(
    data: Mapping[str, Any],
    field: str,
    *,
    prefix: str | None = None,
) -> int:
    value = data.get(field)
    name = f"{prefix}.{field}" if prefix else field
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _wire_error(f"{name} must be a non-negative integer")
    return value


def _optional_integer(
    data: Mapping[str, Any],
    field: str,
    prefix: str,
) -> int | None:
    value = data.get(field)
    if value is None:
        return None
    return _integer(data, field, prefix=prefix)


def _string(data: Mapping[str, Any], field: str, prefix: str) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise _wire_error(f"{prefix}.{field} must be a string")
    return value


def _optional_string(
    data: Mapping[str, Any],
    field: str,
    prefix: str,
) -> str | None:
    value = data.get(field)
    if value is not None and not isinstance(value, str):
        raise _wire_error(f"{prefix}.{field} must be a string or null")
    return value


def _string_tuple(data: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = data.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _wire_error(f"{field} must be a list of strings")
    return tuple(value)


def _wire_error(detail: str) -> RuntimeError:
    return RuntimeError(
        f"sase_core_rs returned an incompatible artifact-file retention plan: {detail}"
    )


def _nonnegative(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


__all__ = [
    "RetentionPlan",
    "RetentionPolicy",
    "plan_artifact_file_retention",
]
