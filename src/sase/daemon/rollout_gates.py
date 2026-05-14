"""Milestone gate aggregation for daemon rollout policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from sase.daemon.rollout_registry import (
    Milestone,
    RolloutSurfaceRecord,
    rollout_surface_records,
)


class GateKind(StrEnum):
    """Rollout gate categories tracked by the milestone aggregator."""

    CAPABILITY = "capability"
    CONTRACT = "contract"
    PARITY = "parity"
    PERF = "perf"
    RECOVERY = "recovery"
    DOCS = "docs"


@dataclass(frozen=True)
class GateCoverage:
    """Available gate coverage collected from tests, contracts, and runbooks."""

    capabilities: frozenset[str] = frozenset()
    contract_snapshots: frozenset[str] = frozenset()
    parity_gates: frozenset[str] = frozenset()
    perf_gates: frozenset[str] = frozenset()
    recovery_checks: frozenset[str] = frozenset()
    docs_links: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MilestoneGateRecord:
    """Cumulative gates required to claim one daemon rollout milestone."""

    milestone: Milestone
    title: str
    surface_ids: tuple[str, ...]
    required_capabilities: frozenset[str]
    required_contract_snapshots: frozenset[str]
    required_parity_gates: frozenset[str]
    required_perf_gates: frozenset[str]
    required_recovery_checks: frozenset[str]
    required_docs_links: frozenset[str]

    @property
    def required_gates(self) -> dict[GateKind, frozenset[str]]:
        return {
            GateKind.CAPABILITY: self.required_capabilities,
            GateKind.CONTRACT: self.required_contract_snapshots,
            GateKind.PARITY: self.required_parity_gates,
            GateKind.PERF: self.required_perf_gates,
            GateKind.RECOVERY: self.required_recovery_checks,
            GateKind.DOCS: self.required_docs_links,
        }


@dataclass(frozen=True)
class MilestoneCoverage:
    """Coverage status for one milestone."""

    milestone: Milestone
    missing_by_kind: dict[GateKind, tuple[str, ...]]

    @property
    def covered(self) -> bool:
        return all(not missing for missing in self.missing_by_kind.values())


@dataclass(frozen=True)
class SurfaceGateStatus:
    """Default-enablement eligibility for one rollout surface."""

    surface_id: str
    eligible: bool
    blocked_reasons: tuple[str, ...]


@dataclass(frozen=True)
class DefaultGateViolation:
    """A configured default that lacks the required rollout gates."""

    surface_id: str
    reason: str


MILESTONE_ORDER: tuple[Milestone, ...] = ("M0", "M1", "M2", "M3", "M4", "M5")
MILESTONE_TITLES: Mapping[Milestone, str] = {
    "M0": "shadow indexing and diff diagnostics",
    "M1": "selected CLI/editor daemon reads",
    "M2": "ACE daemon reads",
    "M3": "selected daemon writes with source export",
    "M4": "daemon-owned scheduler and workflow state",
    "M5": "provider/plugin/workflow host fallback posture",
}
MILESTONE_DOCS: Mapping[Milestone, str] = {
    "M0": "docs/rust_backend.md#rollout",
    "M1": "docs/perf_runbook.md#daemon-read-rollout",
    "M2": "docs/ace.md#daemon-read-rollout",
    "M3": "docs/rust_backend.md#daemon-write-rollout",
    "M4": "docs/local_daemon.md#scheduler-rollout",
    "M5": "docs/plugins.md#provider-host-rollout",
}

_MILESTONE_INDEX = {milestone: index for index, milestone in enumerate(MILESTONE_ORDER)}


def milestone_gate_records(
    records: Iterable[RolloutSurfaceRecord] | None = None,
) -> tuple[MilestoneGateRecord, ...]:
    """Return cumulative M0-M5 gate records for the supplied rollout surfaces."""

    rollout_records = tuple(rollout_surface_records() if records is None else records)
    return tuple(
        _milestone_record(milestone, rollout_records) for milestone in MILESTONE_ORDER
    )


def evaluate_milestone_coverage(
    coverage: GateCoverage,
    records: Iterable[RolloutSurfaceRecord] | None = None,
) -> tuple[MilestoneCoverage, ...]:
    """Return coverage for every milestone."""

    return tuple(
        MilestoneCoverage(
            record.milestone,
            {
                GateKind.CAPABILITY: _missing(
                    record.required_capabilities, coverage.capabilities
                ),
                GateKind.CONTRACT: _missing(
                    record.required_contract_snapshots, coverage.contract_snapshots
                ),
                GateKind.PARITY: _missing(
                    record.required_parity_gates, coverage.parity_gates
                ),
                GateKind.PERF: _missing(
                    record.required_perf_gates, coverage.perf_gates
                ),
                GateKind.RECOVERY: _missing(
                    record.required_recovery_checks, coverage.recovery_checks
                ),
                GateKind.DOCS: _missing(
                    record.required_docs_links, coverage.docs_links
                ),
            },
        )
        for record in milestone_gate_records(records)
    )


def covered_milestones(
    coverage: GateCoverage,
    records: Iterable[RolloutSurfaceRecord] | None = None,
) -> tuple[Milestone, ...]:
    """Return milestones whose cumulative gate records are fully covered."""

    return tuple(
        status.milestone
        for status in evaluate_milestone_coverage(coverage, records)
        if status.covered
    )


def default_enablement_statuses(
    coverage: GateCoverage,
    records: Iterable[RolloutSurfaceRecord] | None = None,
) -> dict[str, SurfaceGateStatus]:
    """Return default-enablement eligibility for each rollout surface."""

    rollout_records = tuple(rollout_surface_records() if records is None else records)
    return {
        record.surface_id: _surface_status(record, coverage)
        for record in rollout_records
    }


def default_gate_violations(
    default_enabled_surface_ids: Iterable[str],
    coverage: GateCoverage,
    records: Iterable[RolloutSurfaceRecord] | None = None,
) -> tuple[DefaultGateViolation, ...]:
    """Return enabled defaults that are blocked by the rollout gate policy."""

    statuses = default_enablement_statuses(coverage, records)
    violations: list[DefaultGateViolation] = []
    for surface_id in sorted(set(default_enabled_surface_ids)):
        status = statuses.get(surface_id)
        if status is None:
            violations.append(
                DefaultGateViolation(surface_id, "surface is not in rollout registry")
            )
        elif not status.eligible:
            violations.append(
                DefaultGateViolation(surface_id, "; ".join(status.blocked_reasons))
            )
    return tuple(violations)


def _milestone_record(
    milestone: Milestone,
    records: tuple[RolloutSurfaceRecord, ...],
) -> MilestoneGateRecord:
    cumulative = tuple(
        record
        for record in records
        if _MILESTONE_INDEX[record.minimum_milestone] <= _MILESTONE_INDEX[milestone]
    )
    return MilestoneGateRecord(
        milestone=milestone,
        title=MILESTONE_TITLES[milestone],
        surface_ids=tuple(record.surface_id for record in cumulative),
        required_capabilities=frozenset(
            capability
            for record in cumulative
            for capability in record.daemon_capabilities
        ),
        required_contract_snapshots=frozenset(
            _contract_snapshot_name(schema_name, version)
            for record in cumulative
            for schema_name, version in record.schema_versions
        ),
        required_parity_gates=frozenset(
            gate for record in cumulative for gate in record.parity_gates
        ),
        required_perf_gates=frozenset(
            gate for record in cumulative for gate in record.perf_gates
        ),
        required_recovery_checks=frozenset(
            _recovery_check_name(command)
            for record in cumulative
            for command in record.recovery_commands
        ),
        required_docs_links=frozenset(
            MILESTONE_DOCS[record.minimum_milestone] for record in cumulative
        ),
    )


def _surface_status(
    record: RolloutSurfaceRecord,
    coverage: GateCoverage,
) -> SurfaceGateStatus:
    blocked: list[str] = []
    if record.default_policy in {"direct_only", "future_authoritative"}:
        blocked.append(f"{record.default_policy} surfaces are not default-enableable")
    if not record.default_enablement_allowed:
        blocked.append("registry policy does not allow default enablement")
    _append_missing(
        blocked, "capabilities", record.daemon_capabilities, coverage.capabilities
    )
    _append_missing(
        blocked,
        "contract snapshots",
        (
            _contract_snapshot_name(schema_name, version)
            for schema_name, version in record.schema_versions
        ),
        coverage.contract_snapshots,
    )
    _append_missing(blocked, "parity gates", record.parity_gates, coverage.parity_gates)
    _append_missing(blocked, "perf gates", record.perf_gates, coverage.perf_gates)
    _append_missing(
        blocked,
        "recovery checks",
        (_recovery_check_name(command) for command in record.recovery_commands),
        coverage.recovery_checks,
    )
    _append_missing(
        blocked,
        "docs links",
        (MILESTONE_DOCS[record.minimum_milestone],),
        coverage.docs_links,
    )
    return SurfaceGateStatus(
        surface_id=record.surface_id,
        eligible=not blocked,
        blocked_reasons=tuple(blocked),
    )


def _append_missing(
    blocked: list[str],
    label: str,
    required: Iterable[str],
    available: frozenset[str],
) -> None:
    missing = _missing(required, available)
    if missing:
        blocked.append(f"missing {label}: {', '.join(missing)}")


def _missing(required: Iterable[str], available: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(set(required) - available))


def _contract_snapshot_name(schema_name: str, version: int) -> str:
    return f"{schema_name}.v{version}"


def _recovery_check_name(command: str) -> str:
    token = "".join(ch if ch.isalnum() else "_" for ch in command.lower())
    return ".".join(part for part in token.split("_") if part)


__all__ = [
    "DefaultGateViolation",
    "GateCoverage",
    "GateKind",
    "MILESTONE_DOCS",
    "MILESTONE_ORDER",
    "MILESTONE_TITLES",
    "MilestoneCoverage",
    "MilestoneGateRecord",
    "SurfaceGateStatus",
    "covered_milestones",
    "default_enablement_statuses",
    "default_gate_violations",
    "evaluate_milestone_coverage",
    "milestone_gate_records",
]
