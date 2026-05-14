"""Milestone gate aggregation tests for daemon rollout policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.ace.tui.util.perf_gates import (
    EPIC9_ROLLOUT_PARITY_GATES,
    EPIC9_ROLLOUT_PERF_GATES,
)
from sase.daemon.rollout_gates import (
    GateCoverage,
    GateKind,
    covered_milestones,
    default_gate_violations,
    evaluate_milestone_coverage,
    milestone_gate_records,
)
from tests.perf.daemon_read_rollout import (
    EPIC5_ROLLOUT_PARITY_GATES,
    EPIC5_ROLLOUT_PERF_GATES,
)
from tests.perf.daemon_scheduler_rollout import (
    EPIC7_ROLLOUT_PARITY_GATES,
    EPIC7_ROLLOUT_PERF_GATES,
)


def test_milestone_records_are_m0_to_m5_and_cumulative() -> None:
    records = milestone_gate_records()

    assert tuple(record.milestone for record in records) == (
        "M0",
        "M1",
        "M2",
        "M3",
        "M4",
        "M5",
    )
    assert set(records[0].surface_ids) <= set(records[-1].surface_ids)
    assert "milestone.m0_shadow_indexing" in records[0].surface_ids
    assert "milestone.m1_read_through" in records[1].surface_ids
    assert "read.changespecs" in records[1].surface_ids
    assert "read.ace_agents" in records[2].surface_ids
    assert "scheduler.launch" in records[4].surface_ids
    assert "provider_host.llm_metadata" in records[5].surface_ids


def test_milestone_coverage_can_report_partial_readiness() -> None:
    m0 = milestone_gate_records()[0]
    coverage = GateCoverage(
        capabilities=m0.required_capabilities,
        contract_snapshots=m0.required_contract_snapshots,
        parity_gates=m0.required_parity_gates,
        perf_gates=m0.required_perf_gates,
        recovery_checks=m0.required_recovery_checks,
        docs_links=m0.required_docs_links,
    )

    assert covered_milestones(coverage) == ("M0",)
    m1 = evaluate_milestone_coverage(coverage)[1]
    assert not m1.covered
    assert "daemon_read.parity.global" in m1.missing_by_kind[GateKind.PARITY]


def test_milestone_aggregator_connects_existing_rollout_gate_registries() -> None:
    records_by_milestone = {
        record.milestone: record for record in milestone_gate_records()
    }

    assert (
        EPIC5_ROLLOUT_PARITY_GATES <= records_by_milestone["M1"].required_parity_gates
    )
    assert EPIC5_ROLLOUT_PERF_GATES <= records_by_milestone["M1"].required_perf_gates
    assert (
        EPIC9_ROLLOUT_PARITY_GATES <= records_by_milestone["M2"].required_parity_gates
    )
    assert EPIC9_ROLLOUT_PERF_GATES <= records_by_milestone["M2"].required_perf_gates
    assert {
        "daemon_write.idempotency.notifications.append",
        "daemon_write.stale_source_conflict.changespec.status",
        "daemon_write.source_export_repair.beads",
        "daemon_read.parity.notifications",
    } <= records_by_milestone["M3"].required_parity_gates
    assert (
        EPIC7_ROLLOUT_PARITY_GATES <= records_by_milestone["M4"].required_parity_gates
    )
    assert EPIC7_ROLLOUT_PERF_GATES <= records_by_milestone["M4"].required_perf_gates


def test_m0_requires_shadow_rebuild_verify_and_diff_recovery() -> None:
    m0 = milestone_gate_records()[0]

    assert "indexing.rebuild" in m0.required_capabilities
    assert "indexing.verify" in m0.required_capabilities
    assert "indexing.diff" in m0.required_capabilities
    assert "daemon_shadow.parity.rebuild_verify_diff" in m0.required_parity_gates
    assert "sase.daemon.rebuild.surface.all" in m0.required_recovery_checks
    assert "sase.daemon.verify.surface.all" in m0.required_recovery_checks
    assert "sase.daemon.diff.surface.all" in m0.required_recovery_checks


def test_default_config_has_no_gate_policy_violations_with_registered_gates() -> None:
    assert (
        default_gate_violations(
            _default_enabled_surface_ids(),
            _registered_gate_coverage(),
        )
        == ()
    )


def test_missing_perf_gate_blocks_default_enablement() -> None:
    coverage = _registered_gate_coverage()
    coverage = GateCoverage(
        capabilities=coverage.capabilities,
        contract_snapshots=coverage.contract_snapshots,
        parity_gates=coverage.parity_gates,
        perf_gates=coverage.perf_gates - {"daemon_read.perf.changespecs"},
        recovery_checks=coverage.recovery_checks,
        docs_links=coverage.docs_links,
    )

    violations = default_gate_violations(["read.changespecs"], coverage)

    assert len(violations) == 1
    assert violations[0].surface_id == "read.changespecs"
    assert "missing perf gates: daemon_read.perf.changespecs" in violations[0].reason


def test_policy_allows_gated_ace_default_enablement() -> None:
    violations = default_gate_violations(
        ["read.ace_agents"],
        _registered_gate_coverage(),
    )

    assert violations == ()


_PROVIDER_HOST_DEFAULT_OPERATIONS = {
    "llm.metadata",
    "xprompt.catalog",
    "vcs.query",
    "workspace.metadata",
    "workspace.resolve_ref",
    "llm.invoke",
    "workflow.step",
    "vcs.mutation",
}
_PROVIDER_HOST_ROLLOUT_PARITY_GATES = frozenset(
    f"provider_host.parity.{operation}"
    for operation in _PROVIDER_HOST_DEFAULT_OPERATIONS
)
_PROVIDER_HOST_ROLLOUT_PERF_GATES = frozenset(
    f"provider_host.perf.{operation}" for operation in _PROVIDER_HOST_DEFAULT_OPERATIONS
)


def _registered_gate_coverage() -> GateCoverage:
    complete = milestone_gate_records()[-1]
    return GateCoverage(
        capabilities=complete.required_capabilities,
        contract_snapshots=complete.required_contract_snapshots,
        parity_gates=(
            EPIC5_ROLLOUT_PARITY_GATES
            | EPIC7_ROLLOUT_PARITY_GATES
            | EPIC9_ROLLOUT_PARITY_GATES
            | _PROVIDER_HOST_ROLLOUT_PARITY_GATES
            | {"daemon_read.diagnostics.fallback_metadata"}
        ),
        perf_gates=(
            EPIC5_ROLLOUT_PERF_GATES
            | EPIC7_ROLLOUT_PERF_GATES
            | EPIC9_ROLLOUT_PERF_GATES
            | _PROVIDER_HOST_ROLLOUT_PERF_GATES
        ),
        recovery_checks=complete.required_recovery_checks,
        docs_links=complete.required_docs_links,
    )


def _default_enabled_surface_ids() -> set[str]:
    config = _default_config()
    daemon = config["daemon"]
    enabled: set[str] = set()
    if daemon["reads"]["enabled"] and not daemon["reads"]["force_direct"]:
        enabled.add("read.global")
    for surface, surface_enabled in daemon["reads"]["surfaces"].items():
        if surface_enabled:
            enabled.add(f"read.{surface}")
    for operation_key, mode in daemon["provider_host"]["modes"].items():
        if mode in {"host-preferred", "host-required"}:
            enabled.add(f"provider_host.{operation_key}")
    for mode_key, mode in daemon["scheduler"].items():
        if mode != "direct":
            enabled.add(f"scheduler.{mode_key.removesuffix('_mode')}")
    if daemon["reads"]["fallback_diagnostics"]:
        enabled.add("read.fallback_diagnostics")
    return enabled


def _default_config() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    with open(root / "src" / "sase" / "default_config.yml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    return data
