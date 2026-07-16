"""Data models and shared projections for the plan inventory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_HISTORY_LIMIT = 10
PLAN_STATUSES = ("approved", "proposed", "rejected")
_REJECTED_NOTE = (
    "inferred from archived proposal not represented by proposed/approved state"
)


@dataclass(frozen=True)
class ProposedPlan:
    _plan_key: str
    id_prefix: str
    notification_id: str
    timestamp: str
    age: str
    agent: str
    project: str
    provider_model: str
    plan_path: str
    tier: str
    response_dir: str


@dataclass(frozen=True)
class ApprovedPlan:
    _plan_key: str
    timestamp: str
    age: str
    action: str
    agent: str
    project: str
    provider_model: str
    plan_path: str
    tier: str
    meta_path: str


@dataclass(frozen=True)
class RejectedPlan:
    timestamp: str
    age: str
    plan_path: str
    tier: str
    note: str = _REJECTED_NOTE


@dataclass(frozen=True)
class PlanInventory:
    proposed: tuple[ProposedPlan, ...]
    approved: tuple[ApprovedPlan, ...]
    rejected: tuple[RejectedPlan, ...]
    total_archived_proposals: int
    tier_filter: tuple[str, ...] = ()
    status_filter: tuple[str, ...] = ()
    limit: int = DEFAULT_HISTORY_LIMIT
    approved_scan_truncated: bool = False


@dataclass(frozen=True)
class DisplayPathRoots:
    sase_root: Path
    home: Path


def selected_statuses(inventory: PlanInventory) -> set[str]:
    return set(inventory.status_filter or PLAN_STATUSES)


def tier_counts(inventory: PlanInventory) -> dict[str, int]:
    return {
        tier: (
            sum(row.tier == tier for row in inventory.proposed)
            + sum(row.tier == tier for row in inventory.approved)
            + sum(row.tier == tier for row in inventory.rejected)
        )
        for tier in ("tale", "epic")
    }
