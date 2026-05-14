"""Rollout gate tests for Epic 5 daemon-backed reads."""

from __future__ import annotations

from tests.perf.daemon_read_rollout import (
    EPIC5_DEFAULT_SURFACE_GROUPS,
    EPIC5_TARGETS_MS,
    failing_perf_gates,
)


def test_phase_5i_perf_gate_names_cover_rollout_targets() -> None:
    assert set(EPIC5_TARGETS_MS) == {
        "warm_cli_read_p95",
        "ace_first_indexed_snapshot_p95",
        "ace_no_change_refresh_p95",
        "large_changespec_search_p95",
        "large_agent_history_status_p95",
    }


def test_phase_5i_default_surfaces_have_policy_gate() -> None:
    assert EPIC5_DEFAULT_SURFACE_GROUPS == {
        "changespecs",
        "notifications",
        "agents",
        "beads",
        "catalogs",
    }
    assert "ace_agents" not in EPIC5_DEFAULT_SURFACE_GROUPS


def test_failing_perf_gates_reports_only_exceeded_targets() -> None:
    metrics = {
        "warm_cli_read_p95": EPIC5_TARGETS_MS["warm_cli_read_p95"],
        "large_changespec_search_p95": (
            EPIC5_TARGETS_MS["large_changespec_search_p95"] + 1.0
        ),
    }

    assert failing_perf_gates(metrics) == ["large_changespec_search_p95"]
