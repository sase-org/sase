"""Rust-backed publication payload batch planning facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Iterable

from sase.core.rust import require_rust_binding

PUBLICATION_PAYLOAD_BATCH_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PublicationPayloadFile:
    path: str
    byte_length: int


@dataclass(frozen=True)
class _PublicationPayloadBatch:
    paths: tuple[str, ...]
    byte_count: int


@dataclass(frozen=True)
class _PublicationPayloadBatchPlan:
    schema_version: int
    byte_budget: int
    total_byte_count: int
    batches: tuple[_PublicationPayloadBatch, ...]


def plan_publication_payload_batches(
    files: Iterable[PublicationPayloadFile],
    byte_budget: int,
) -> _PublicationPayloadBatchPlan:
    """Partition publication file metadata through ``sase_core_rs``."""
    if type(byte_budget) is not int or byte_budget < 1:
        raise ValueError("byte_budget must be a positive integer")
    records = [{"path": file.path, "byte_length": file.byte_length} for file in files]
    binding = require_rust_binding("plan_publication_payload_batches")
    return _plan_from_dict(binding(records, byte_budget))


def _plan_from_dict(raw: Any) -> _PublicationPayloadBatchPlan:
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict payload batch plan")
    try:
        plan = _PublicationPayloadBatchPlan(
            schema_version=_require_int(raw, "schema_version"),
            byte_budget=_require_int(raw, "byte_budget"),
            total_byte_count=_require_int(raw, "total_byte_count"),
            batches=tuple(_batch_from_dict(batch) for batch in raw["batches"]),
        )
    except KeyError as exc:
        raise RuntimeError(
            f"sase_core_rs returned an incomplete payload batch plan: missing {exc}"
        ) from exc
    if plan.schema_version != PUBLICATION_PAYLOAD_BATCH_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs publication payload batch wire is stale: "
            f"{plan.schema_version}"
        )
    return plan


def _batch_from_dict(raw: Any) -> _PublicationPayloadBatch:
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict payload batch")
    try:
        paths = raw["paths"]
        if not isinstance(paths, list) or not all(
            isinstance(path, str) for path in paths
        ):
            raise RuntimeError(
                "sase_core_rs payload batch field 'paths' is not list[str]"
            )
        return _PublicationPayloadBatch(
            paths=tuple(paths),
            byte_count=_require_int(raw, "byte_count"),
        )
    except KeyError as exc:
        raise RuntimeError(
            f"sase_core_rs returned an incomplete payload batch: missing {exc}"
        ) from exc


def _require_int(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if type(value) is not int:
        raise RuntimeError(f"sase_core_rs payload batch field {key!r} is not int")
    return value


__all__ = [
    "PUBLICATION_PAYLOAD_BATCH_WIRE_SCHEMA_VERSION",
    "PublicationPayloadFile",
    "plan_publication_payload_batches",
]
