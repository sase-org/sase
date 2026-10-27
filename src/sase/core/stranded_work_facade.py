"""Python facade for the sase-core stranded-work reducer.

Frozen dataclasses mirror the verdict and report wires. Callers gather facts
in Python and pass them through :func:`reduce_stranded_work`; the Rust
binding owns classification, causes, grace, and ancestor propagation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.core.rust import require_rust_binding

if TYPE_CHECKING:
    from sase.bead.model import BeadCompletionFailure

STRANDED_WORK_WIRE_SCHEMA_VERSION = 1

_REDUCE_BINDING: Any = None


@dataclass(frozen=True, slots=True)
class StrandedWorkVerdict:
    """One candidate bead's stranded-work verdict."""

    bead_id: str
    kind: str
    state: str
    reason: str | None = None
    owner: str | None = None
    delegates: tuple[str, ...] = ()
    session: str | None = None
    last_turn: str | None = None
    last_turn_artifact_dir: str | None = None
    completion_failure: BeadCompletionFailure | None = None
    declared_bead_action: str | None = None
    since: float | None = None
    parent_id: str | None = None
    blocked_by: tuple[str, ...] = ()
    blocks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StrandedWorkReport:
    """Reducer output: verdicts sorted by bead id plus stranded/blocked ids."""

    schema_version: int = STRANDED_WORK_WIRE_SCHEMA_VERSION
    verdicts: tuple[StrandedWorkVerdict, ...] = ()
    stranded_ids: tuple[str, ...] = ()
    blocked_ids: tuple[str, ...] = ()


def _reduce_binding() -> Any:
    global _REDUCE_BINDING  # noqa: PLW0603
    binding = _REDUCE_BINDING
    if binding is None:
        binding = require_rust_binding("stranded_work_reduce")
        _REDUCE_BINDING = binding
    return binding


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        item.strip() for item in value if isinstance(item, str) and item.strip()
    )


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _verdict_from_wire(raw: object) -> StrandedWorkVerdict:
    from sase.bead.completion_failure_codec import completion_failure_from_dict

    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs stranded_work_reduce returned a non-mapping verdict"
        )
    bead_id = _optional_str(raw.get("bead_id")) or ""
    kind = _optional_str(raw.get("kind")) or ""
    state = _optional_str(raw.get("state")) or ""
    return StrandedWorkVerdict(
        bead_id=bead_id,
        kind=kind,
        state=state,
        reason=_optional_str(raw.get("reason")),
        owner=_optional_str(raw.get("owner")),
        delegates=_str_tuple(raw.get("delegates")),
        session=_optional_str(raw.get("session")),
        last_turn=_optional_str(raw.get("last_turn")),
        last_turn_artifact_dir=_optional_str(raw.get("last_turn_artifact_dir")),
        completion_failure=completion_failure_from_dict(raw.get("completion_failure")),
        declared_bead_action=_optional_str(raw.get("declared_bead_action")),
        since=_optional_float(raw.get("since")),
        parent_id=_optional_str(raw.get("parent_id")),
        blocked_by=_str_tuple(raw.get("blocked_by")),
        blocks=_str_tuple(raw.get("blocks")),
    )


def reduce_stranded_work(facts: Mapping[str, Any]) -> StrandedWorkReport:
    """Classify bead facts through ``stranded_work_reduce``.

    *facts* is the reducer input mapping (schema_version, now,
    settle_grace_seconds, beads). Missing keys use the wire defaults.
    """
    raw = _reduce_binding()(dict(facts))
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs stranded_work_reduce returned a non-mapping report"
        )
    version = raw.get("schema_version", STRANDED_WORK_WIRE_SCHEMA_VERSION)
    try:
        schema_version = int(version)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "sase_core_rs stranded_work_reduce returned an invalid schema_version"
        ) from exc
    verdicts_raw = raw.get("verdicts")
    if not isinstance(verdicts_raw, Sequence) or isinstance(verdicts_raw, (str, bytes)):
        raise RuntimeError(
            "sase_core_rs stranded_work_reduce returned non-list verdicts"
        )
    return StrandedWorkReport(
        schema_version=schema_version,
        verdicts=tuple(_verdict_from_wire(item) for item in verdicts_raw),
        stranded_ids=_str_tuple(raw.get("stranded_ids")),
        blocked_ids=_str_tuple(raw.get("blocked_ids")),
    )


__all__ = [
    "STRANDED_WORK_WIRE_SCHEMA_VERSION",
    "StrandedWorkReport",
    "StrandedWorkVerdict",
    "reduce_stranded_work",
]
