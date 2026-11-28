"""Python facade for the sase-core zombie-plan predicate.

Frozen dataclasses mirror the zombie-plan verdict and report wires. Callers
gather one complete project tree snapshot plus per-plan session-member facts
in Python (see :mod:`sase.bead.zombie`) and pass them through
:func:`evaluate_zombie_plans`; the Rust binding owns tree completeness,
close-event identity, and the shared ownership policy.

The two bindings are looked up with
:func:`~sase.core.rust.optional_rust_binding` so one tree keeps working
against older cores: callers report an explicit unavailable verdict instead
of crashing when the installed wheel predates the detection contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.core.rust import optional_rust_binding

ZOMBIE_PLAN_WIRE_SCHEMA_VERSION = 1

# Verdict state for rows the installed core cannot evaluate.
ZOMBIE_STATE_UNKNOWN = "unknown"
ZOMBIE_UNKNOWN_UNSUPPORTED_CORE = "unsupported_core_binding"

_TREE_SNAPSHOT_BINDING = "bead_zombie_plan_tree_snapshot"
_EVALUATE_BINDING = "zombie_plan_evaluate"


@dataclass(frozen=True, slots=True)
class ZombieVerdict:
    """One in-progress plan bead's zombie-plan verdict."""

    plan_id: str
    title: str = ""
    tier: str | None = None
    assignee: str = ""
    state: str = ZOMBIE_STATE_UNKNOWN
    zombie: bool = False
    recovery_eligible: bool = False
    reason: str | None = None
    unknown_reason: str | None = None
    recovery_reason: str | None = None
    owner: str | None = None
    ownership_reason: str | None = None
    tree_complete: bool = False
    descendant_count: int = 0
    all_descendants_closed: bool | None = None
    latest_descendant_closed_at: str | None = None
    latest_descendant_id: str | None = None
    latest_descendant_close_event_id: str | None = None
    close_token: str | None = None


@dataclass(frozen=True, slots=True)
class ZombieEvaluationReport:
    """Reducer output: verdicts sorted by plan id."""

    schema_version: int = ZOMBIE_PLAN_WIRE_SCHEMA_VERSION
    rows: tuple[ZombieVerdict, ...] = ()


def tree_snapshot_binding() -> Any | None:
    """Return the tree-snapshot binding, or ``None`` on older cores."""
    return optional_rust_binding(_TREE_SNAPSHOT_BINDING)


def _evaluate_binding() -> Any | None:
    """Return the zombie-plan evaluate binding, or ``None`` on older cores."""
    return optional_rust_binding(_EVALUATE_BINDING)


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_bool(value: object, default: bool = False) -> bool:
    return bool(value) if isinstance(value, bool) else default


def _optional_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _verdict_from_wire(raw: object) -> ZombieVerdict:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs zombie_plan_evaluate returned a non-mapping verdict"
        )
    plan_id = _optional_str(raw.get("plan_id")) or ""
    all_closed = raw.get("all_descendants_closed")
    return ZombieVerdict(
        plan_id=plan_id,
        title=_optional_str(raw.get("title")) or "",
        tier=_optional_str(raw.get("tier")),
        assignee=_optional_str(raw.get("assignee")) or "",
        state=_optional_str(raw.get("state")) or ZOMBIE_STATE_UNKNOWN,
        zombie=_optional_bool(raw.get("zombie")),
        recovery_eligible=_optional_bool(raw.get("recovery_eligible")),
        reason=_optional_str(raw.get("reason")),
        unknown_reason=_optional_str(raw.get("unknown_reason")),
        recovery_reason=_optional_str(raw.get("recovery_reason")),
        owner=_optional_str(raw.get("owner")),
        ownership_reason=_optional_str(raw.get("ownership_reason")),
        tree_complete=_optional_bool(raw.get("tree_complete")),
        descendant_count=_optional_int(raw.get("descendant_count")),
        all_descendants_closed=bool(all_closed)
        if isinstance(all_closed, bool)
        else None,
        latest_descendant_closed_at=_optional_str(
            raw.get("latest_descendant_closed_at")
        ),
        latest_descendant_id=_optional_str(raw.get("latest_descendant_id")),
        latest_descendant_close_event_id=_optional_str(
            raw.get("latest_descendant_close_event_id")
        ),
        close_token=_optional_str(raw.get("close_token")),
    )


def evaluate_zombie_plans(request: Mapping[str, Any]) -> ZombieEvaluationReport:
    """Evaluate one project's zombie-plan input through the Rust predicate.

    *request* is the evaluation input mapping (schema_version, snapshot,
    owners). Missing keys use the wire defaults. Raises
    :class:`RuntimeError` when the installed core predates the detection
    contract or returns a malformed report.
    """
    binding = _evaluate_binding()
    if binding is None:
        raise RuntimeError(
            "sase_core_rs does not expose zombie_plan_evaluate; the installed "
            "wheel predates the zombie-plan detection contract"
        )
    raw = binding(dict(request))
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs zombie_plan_evaluate returned a non-mapping report"
        )
    version = raw.get("schema_version", ZOMBIE_PLAN_WIRE_SCHEMA_VERSION)
    try:
        schema_version = int(version)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "sase_core_rs zombie_plan_evaluate returned an invalid schema_version"
        ) from exc
    rows_raw = raw.get("rows")
    if not isinstance(rows_raw, Sequence) or isinstance(rows_raw, (str, bytes)):
        raise RuntimeError("sase_core_rs zombie_plan_evaluate returned non-list rows")
    return ZombieEvaluationReport(
        schema_version=schema_version,
        rows=tuple(_verdict_from_wire(item) for item in rows_raw),
    )


__all__ = [
    "ZOMBIE_PLAN_WIRE_SCHEMA_VERSION",
    "ZOMBIE_STATE_UNKNOWN",
    "ZOMBIE_UNKNOWN_UNSUPPORTED_CORE",
    "ZombieEvaluationReport",
    "ZombieVerdict",
    "evaluate_zombie_plans",
    "tree_snapshot_binding",
]
