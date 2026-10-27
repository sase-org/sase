"""Shared capacity view model for ``sase agent load`` and the TUI inspector.

This module is deliberately dependency-free (stdlib only, no Textual, no
Rich): it projects a :class:`MachineCapacityReport` plus an optional
``running_nodes`` count into typed, render-ready sections. The CLI renders
them with Rich; the capacity inspector modal renders the same sections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CAPACITY_REPORT_STALE_AFTER_SECONDS = 25.0
CAPACITY_OVERRIDE_WARNING_AFTER_SECONDS = 14 * 24 * 3600

CapacityTone = Literal["ok", "tight", "full", "over", "blocked", "unknown"]
CapacityGaugeKind = Literal["used", "over", "free", "unknown", "gap", "limit", "beyond"]
CapacityIdleTier = Literal["attention", "waiting", "inactive"]
CapacityQueueTone = Literal[
    "ready", "capacity", "held", "deferred", "never_fits", "other"
]


@dataclass(frozen=True)
class CapacityHoldingRow:
    """One charged claim, shown once even when several records share it."""

    name: str
    kind: str
    charged_weight: float
    weight_source: str
    since: str | None
    authored_budget: int | None
    owner_key: str
    artifact_dir: str
    project_key: str = ""
    running_seconds: float | None = None
    rider_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapacityRiderRow:
    """A live record riding a claim charged through another member."""

    name: str
    holder_name: str
    owner_key: str
    artifact_dir: str
    holder_artifact_dir: str = ""
    project_key: str = ""
    running_seconds: float | None = None


@dataclass(frozen=True)
class CapacityIdleGroup:
    """Live records holding nothing, grouped by why they hold nothing."""

    reason_code: str
    reason_label: str
    count: int
    members: tuple[str, ...]
    member_artifact_dirs: tuple[str, ...] = ()
    tier: CapacityIdleTier = "waiting"
    explanation: str = ""


@dataclass(frozen=True)
class CapacityQueuedRow:
    """One capacity waiter with the real blocker admission reports."""

    name: str
    queue_position: int
    requested_weight: float
    admission_limit: float
    blocker: str
    eligible: bool
    slot_requested_at: str | None
    artifact_dir: str = ""
    project_key: str = ""
    waiting_seconds: float | None = None
    tone: CapacityQueueTone = "capacity"
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapacityVerdict:
    """Plain-English restatement of what the report already proves."""

    tone: CapacityTone
    title: str
    detail: str | None


@dataclass(frozen=True)
class CapacityLimitInfo:
    """Effective limit plus the override/config provenance behind it."""

    effective: float
    configured: float | None
    override_source: str | None
    override_created_at: float | None
    override_expires_at: float | None
    override_age_seconds: float | None
    override_long_lived: bool


@dataclass(frozen=True)
class CapacityGaugeCell:
    """One character of the capacity gauge, with kind and optional owner."""

    char: str
    kind: CapacityGaugeKind
    owner: int | None


@dataclass(frozen=True)
class MachineCapacityView:
    """Render-ready projection of one :class:`MachineCapacityReport`."""

    headline: str
    limit_line: str
    snapshot_line: str
    running_line: str | None
    over_limit_note: str | None
    riders: tuple[CapacityRiderRow, ...]
    total_charged: float
    queued: tuple[CapacityQueuedRow, ...]
    diagnostics: tuple[str, ...]
    admission_blocked: bool
    accounting_unavailable: bool
    occupied: float = 0.0
    limit: float = 0.0
    free: float = 0.0
    verdict: CapacityVerdict | None = None
    limit_info: CapacityLimitInfo | None = None
    computed_at: float = 0.0
    scan_age_seconds: float = 0.0
    scan_current: bool = True
    charged: tuple[CapacityHoldingRow, ...] = ()
    zero_weight: tuple[CapacityHoldingRow, ...] = ()
    attention_groups: tuple[CapacityIdleGroup, ...] = ()
    waiting_groups: tuple[CapacityIdleGroup, ...] = ()
    inactive_groups: tuple[CapacityIdleGroup, ...] = ()


def format_capacity_duration(seconds: float | None) -> str:
    """Format a relative age at minute granularity after the first minute."""
    if seconds is None:
        return "—"
    remaining = max(0.0, float(seconds))
    if remaining < 60.0:
        return f"{int(remaining)}s"
    if remaining < 3600.0:
        return f"{int(remaining // 60.0)}m"
    if remaining < 86400.0:
        hours = int(remaining // 3600.0)
        minutes = int((remaining % 3600.0) // 60.0)
        return f"{hours}h{minutes:02d}m"
    days = int(remaining // 86400.0)
    hours = int((remaining % 86400.0) // 3600.0)
    return f"{days}d{hours:02d}h"


def capacity_view(
    report: object,
    *,
    running_nodes: int | None = None,
    now: float | None = None,
) -> MachineCapacityView:
    """Project *report* into typed display sections.

    *report* is a :class:`MachineCapacityReport` (duck-typed so tests can
    pass doubles). *running_nodes* is the TUI's live Running-bucket count;
    the CLI passes ``None`` and the running line is omitted. *now*
    defaults to the report's ``computed_at`` so snapshot ages stay
    deterministic.
    """
    from ._capacity_view_rows import project_capacity_view

    return project_capacity_view(
        report,
        running_nodes=running_nodes,
        now=now,
    )


__all__ = [
    "CAPACITY_OVERRIDE_WARNING_AFTER_SECONDS",
    "CAPACITY_REPORT_STALE_AFTER_SECONDS",
    "CapacityGaugeCell",
    "CapacityHoldingRow",
    "CapacityIdleGroup",
    "CapacityLimitInfo",
    "CapacityQueuedRow",
    "CapacityRiderRow",
    "CapacityTone",
    "CapacityVerdict",
    "MachineCapacityView",
    "capacity_view",
    "format_capacity_duration",
]
