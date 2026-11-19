"""Thin facade over the Rust publication standing-alert decider.

The Rust core owns the transition policy (opened, changed, escalated once
after 24 h, cleared, or none) and the capped exponential backoff for
project-scoped failure kinds. Python owns observation building, the durable
standing store in :mod:`sase.agents_sync.publication_standing`, and
notifications.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.core._agent_publication_recovery_shared import (
    PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
    require_bool,
    require_str_field,
)
from sase.core.rust import require_rust_binding

STANDING_TRANSITION_OPENED = "opened"
STANDING_TRANSITION_CHANGED = "changed"
STANDING_TRANSITION_ESCALATED = "escalated"
STANDING_TRANSITION_CLEARED = "cleared"
STANDING_TRANSITION_NONE = "none"

_STANDING_TRANSITIONS = frozenset(
    {
        STANDING_TRANSITION_OPENED,
        STANDING_TRANSITION_CHANGED,
        STANDING_TRANSITION_ESCALATED,
        STANDING_TRANSITION_CLEARED,
        STANDING_TRANSITION_NONE,
    }
)

STANDING_KIND_SELECTION_ERROR = "selection_error"
STANDING_KIND_TARGET_UNAVAILABLE = "target_unavailable"
STANDING_KIND_DRAIN_ERROR = "drain_error"
STANDING_KIND_DRAIN_TIMEOUT = "drain_timeout"
STANDING_KIND_LOCK_BUSY = "lock_busy"
STANDING_KIND_CHARGED_ITEM = "charged_item_error"
STANDING_KIND_ARTIFACT_LINK = "artifact_link_error"
STANDING_KIND_REFERENCED_BY = "referenced_by_error"
STANDING_KIND_HEARTBEAT_WRITE = "heartbeat_write"

STANDING_KINDS = frozenset(
    {
        STANDING_KIND_SELECTION_ERROR,
        STANDING_KIND_TARGET_UNAVAILABLE,
        STANDING_KIND_DRAIN_ERROR,
        STANDING_KIND_DRAIN_TIMEOUT,
        STANDING_KIND_LOCK_BUSY,
        STANDING_KIND_CHARGED_ITEM,
        STANDING_KIND_ARTIFACT_LINK,
        STANDING_KIND_REFERENCED_BY,
        STANDING_KIND_HEARTBEAT_WRITE,
    }
)

STANDING_BACKOFF_INITIAL_SECONDS = 60.0
STANDING_BACKOFF_MAX_SECONDS = 1800.0
STANDING_ESCALATE_AFTER_SECONDS = 86400.0


@dataclass(frozen=True)
class StandingAlert:
    """One `(project, signature)` standing alert as decided by Rust core."""

    project: str
    signature: str
    failure_kind: str
    error_class: str
    detail: str
    attempts: int
    first_seen: float
    last_seen: float
    last_reported: float
    escalated: bool
    next_attempt_at: float
    project_scoped: bool


@dataclass(frozen=True)
class StandingDecision:
    """The transition for one observation, plus the stored alert (if any)."""

    transition: str
    alert: StandingAlert | None
    project_scoped: bool


def _parse_alert(raw: Any) -> StandingAlert:
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs standing alert is not a dict")
    attempts = raw.get("attempts")
    if not isinstance(attempts, int) or isinstance(attempts, bool):
        raise RuntimeError("sase_core_rs standing alert attempts is not int")
    for key in ("first_seen", "last_seen", "last_reported", "next_attempt_at"):
        value = raw.get(key)
        if not isinstance(value, (int, float)):
            raise RuntimeError(
                f"sase_core_rs standing alert field {key!r} is not numeric"
            )
    raw_error_class = raw.get("error_class")
    error_class = raw_error_class if isinstance(raw_error_class, str) else ""
    raw_detail = raw.get("detail")
    detail = raw_detail if isinstance(raw_detail, str) else ""
    alert = StandingAlert(
        project=require_str_field(raw, "project"),
        signature=require_str_field(raw, "signature"),
        failure_kind=require_str_field(raw, "failure_kind"),
        error_class=error_class,
        detail=detail,
        attempts=attempts,
        first_seen=float(raw["first_seen"]),
        last_seen=float(raw["last_seen"]),
        last_reported=float(raw["last_reported"]),
        escalated=require_bool(raw, "escalated"),
        next_attempt_at=float(raw["next_attempt_at"]),
        project_scoped=require_bool(raw, "project_scoped"),
    )
    if alert.failure_kind not in STANDING_KINDS:
        raise RuntimeError(
            "sase_core_rs returned an unknown standing failure kind: "
            f"{alert.failure_kind}"
        )
    return alert


def decide_publication_standing(
    previous: Mapping[str, Any] | None,
    observation: Mapping[str, Any] | None,
    *,
    now: float,
) -> StandingDecision:
    """Decide the standing-alert transition for one observation.

    *previous* is the stored alert dict (or ``None``); *observation* carries
    ``project``, ``signature``, ``failure_kind``, and optional
    ``error_class``/``detail`` (or ``None`` after a clean pass).
    """

    binding = require_rust_binding("decide_publication_standing")
    raw = binding(
        {
            "schema_version": PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
            "previous": dict(previous) if previous is not None else None,
            "observation": dict(observation) if observation is not None else None,
            "now": float(now),
        }
    )
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict standing decision")
    if raw.get("schema_version") != PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs publication standing wire is stale: "
            f"{raw.get('schema_version')}"
        )
    transition = require_str_field(raw, "transition")
    if transition not in _STANDING_TRANSITIONS:
        raise RuntimeError(
            f"sase_core_rs returned an unknown standing transition: {transition}"
        )
    alert_raw = raw.get("alert")
    return StandingDecision(
        transition=transition,
        alert=_parse_alert(alert_raw) if alert_raw is not None else None,
        project_scoped=require_bool(raw, "project_scoped"),
    )


__all__ = [
    "STANDING_BACKOFF_INITIAL_SECONDS",
    "STANDING_BACKOFF_MAX_SECONDS",
    "STANDING_ESCALATE_AFTER_SECONDS",
    "STANDING_KIND_ARTIFACT_LINK",
    "STANDING_KIND_CHARGED_ITEM",
    "STANDING_KIND_DRAIN_ERROR",
    "STANDING_KIND_DRAIN_TIMEOUT",
    "STANDING_KIND_HEARTBEAT_WRITE",
    "STANDING_KIND_LOCK_BUSY",
    "STANDING_KIND_REFERENCED_BY",
    "STANDING_KIND_SELECTION_ERROR",
    "STANDING_KIND_TARGET_UNAVAILABLE",
    "STANDING_KINDS",
    "STANDING_TRANSITION_CHANGED",
    "STANDING_TRANSITION_CLEARED",
    "STANDING_TRANSITION_ESCALATED",
    "STANDING_TRANSITION_NONE",
    "STANDING_TRANSITION_OPENED",
    "StandingAlert",
    "StandingDecision",
    "decide_publication_standing",
]
