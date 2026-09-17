"""Rust-backed byte-batch policy for full agent publication payloads."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding

AGENT_PUBLICATION_BATCH_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AgentPublicationPathRecord:
    path: str
    size_bytes: int


@dataclass(frozen=True)
class _AgentPublicationBatch:
    paths: tuple[str, ...]
    size_bytes: int


@dataclass(frozen=True)
class _AgentPublicationBatchPlan:
    schema_version: int
    budget_bytes: int
    total_size_bytes: int
    batches: tuple[_AgentPublicationBatch, ...]


def plan_agent_publication_batches(
    records: Iterable[AgentPublicationPathRecord],
    *,
    budget_bytes: int,
) -> _AgentPublicationBatchPlan:
    """Return deterministic batches through ``sase_core_rs``."""
    if not isinstance(budget_bytes, int) or isinstance(budget_bytes, bool):
        raise TypeError("budget_bytes must be an int")
    if budget_bytes <= 0:
        raise ValueError("budget_bytes must be positive")
    wire_records: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if not isinstance(record, AgentPublicationPathRecord):
            raise TypeError(f"records[{index}] must be an AgentPublicationPathRecord")
        if not isinstance(record.path, str):
            raise TypeError(f"records[{index}].path must be a str")
        if not isinstance(record.size_bytes, int) or isinstance(
            record.size_bytes, bool
        ):
            raise TypeError(f"records[{index}].size_bytes must be an int")
        if record.size_bytes < 0:
            raise ValueError(f"records[{index}].size_bytes must be non-negative")
        wire_records.append({"path": record.path, "size_bytes": record.size_bytes})
    binding = require_rust_binding("plan_agent_publication_batches")
    raw = binding(wire_records, budget_bytes)
    return _plan_from_dict(raw)


def _plan_from_dict(raw: Any) -> _AgentPublicationBatchPlan:
    if not isinstance(raw, dict):
        raise RuntimeError(
            "sase_core_rs returned a non-dict agent publication batch plan"
        )
    try:
        plan = _AgentPublicationBatchPlan(
            schema_version=_require_int(raw, "schema_version"),
            budget_bytes=_require_int(raw, "budget_bytes"),
            total_size_bytes=_require_int(raw, "total_size_bytes"),
            batches=_batches_from_list(raw["batches"]),
        )
    except KeyError as exc:
        raise RuntimeError(
            "sase_core_rs returned an incomplete agent publication batch "
            f"plan: missing {exc}"
        ) from exc
    if plan.schema_version != AGENT_PUBLICATION_BATCH_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs agent publication batch wire is stale: {plan.schema_version}"
        )
    return plan


def _batches_from_list(raw: object) -> tuple[_AgentPublicationBatch, ...]:
    if not isinstance(raw, list):
        raise RuntimeError(
            "sase_core_rs agent publication batch field 'batches' is not list"
        )
    batches: list[_AgentPublicationBatch] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RuntimeError(
                f"sase_core_rs agent publication batch {index} is not dict"
            )
        try:
            batches.append(
                _AgentPublicationBatch(
                    paths=_paths_from_list(item["paths"], index),
                    size_bytes=_require_int(item, "size_bytes"),
                )
            )
        except KeyError as exc:
            raise RuntimeError(
                "sase_core_rs returned an incomplete agent publication "
                f"batch {index}: missing {exc}"
            ) from exc
    return tuple(batches)


def _paths_from_list(raw: object, batch_index: int) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise RuntimeError(
            "sase_core_rs agent publication batch "
            f"{batch_index} field 'paths' is not list"
        )
    paths: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            raise RuntimeError(
                "sase_core_rs agent publication batch "
                f"{batch_index} path {index} is not str"
            )
        paths.append(item)
    return tuple(paths)


def _require_int(raw: dict[str, Any], key: str) -> int:
    value = raw[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(
            f"sase_core_rs agent publication batch field {key!r} is not int"
        )
    return value


__all__ = [
    "AGENT_PUBLICATION_BATCH_WIRE_SCHEMA_VERSION",
    "AgentPublicationPathRecord",
    "plan_agent_publication_batches",
]
