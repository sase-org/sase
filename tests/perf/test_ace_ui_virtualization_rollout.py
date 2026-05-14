"""Phase 9F rollout gates for ACE UI virtualization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from sase.ace.tui.util.perf_gates import (
    ACE_M2_SURFACE_GATES,
    EPIC9_DAEMON_NO_CHANGE_FORBIDDEN_SPANS,
    EPIC9_ROLLOUT_PARITY_GATES,
    EPIC9_ROLLOUT_PERF_GATES,
    EPIC9_TUI_TARGETS,
    ace_default_rollout_violations,
    failing_epic9_perf_gates,
    forbidden_daemon_no_change_refresh_spans,
)
from sase.config.core import _load_default_config
from sase.daemon.read_config import (
    ACE_DAEMON_SURFACE_GROUPS,
    DEFAULT_ENABLED_SURFACE_GROUPS,
    daemon_read_surface_enabled,
)


@dataclass(frozen=True)
class _FakeDaemonFixture:
    name: str
    surface: str
    payload: dict[str, Any]


def _daemon_page_fixture() -> _FakeDaemonFixture:
    return _FakeDaemonFixture(
        name="page",
        surface="ace_agent_active",
        payload={
            "schema_version": 1,
            "snapshot": {"snapshot_id": "snap-1"},
            "page": {
                "cursor": None,
                "next_cursor": "cursor-2",
                "limit": 40,
                "estimated_total": 400,
            },
            "entries": [{"handle": "agent:demo:20260514120000"}],
        },
    )


def _cursor_expiry_fixture() -> _FakeDaemonFixture:
    return _FakeDaemonFixture(
        name="cursor_expiry",
        surface="ace_agent_active",
        payload={
            "error": {
                "code": "cursor_expired",
                "cursor": "cursor-2",
                "resync_hint": "page",
            }
        },
    )


def _snapshot_expiry_fixture() -> _FakeDaemonFixture:
    return _FakeDaemonFixture(
        name="snapshot_expiry",
        surface="ace_changespec_list",
        payload={
            "error": {
                "code": "snapshot_expired",
                "snapshot_id": "snap-1",
                "resync_hint": "snapshot",
            }
        },
    )


def _delta_batch_fixture() -> _FakeDaemonFixture:
    return _FakeDaemonFixture(
        name="delta_batch",
        surface="ace_agent_active",
        payload={
            "snapshot_id": "snap-1",
            "sequence": 8,
            "row_patches": [
                {
                    "operation": "upsert",
                    "handle": "agent:demo:20260514120100",
                    "index": 0,
                }
            ],
            "count_patches": [{"key": "running", "value": 12}],
        },
    )


def _projection_error_fixture() -> _FakeDaemonFixture:
    return _FakeDaemonFixture(
        name="projection_error",
        surface="ace_notifications",
        payload={
            "error": {
                "code": "projection_error",
                "fallback_reason": "projection_corrupt",
            }
        },
    )


def _fixture_matrix() -> dict[str, _FakeDaemonFixture]:
    fixtures = [
        _daemon_page_fixture(),
        _cursor_expiry_fixture(),
        _snapshot_expiry_fixture(),
        _delta_batch_fixture(),
        _projection_error_fixture(),
    ]
    return {fixture.name: fixture for fixture in fixtures}


def test_epic9_perf_gate_names_cover_rollout_targets() -> None:
    assert set(EPIC9_TUI_TARGETS) == {
        "ace_shell_first_useful_paint_p95_ms",
        "ace_agents_first_indexed_snapshot_p95_ms",
        "ace_changespecs_first_indexed_snapshot_p95_ms",
        "ace_notifications_first_indexed_snapshot_p95_ms",
        "ace_agents_jk_key_to_paint_p95_ms",
        "ace_changespecs_jk_key_to_paint_p95_ms",
        "ace_no_change_auto_refresh_p95_ms",
        "ace_broad_loader_call_count",
        "ace_changespec_query_edit_large_p95_ms",
        "ace_agent_history_query_edit_large_p95_ms",
        "ace_lazy_detail_stale_cancellation_count",
    }


def test_m2_ace_surface_gates_are_per_surface_and_cover_contracts() -> None:
    assert set(ACE_M2_SURFACE_GATES) == ACE_DAEMON_SURFACE_GROUPS
    assert {
        gate.parity_gate for gate in ACE_M2_SURFACE_GATES.values()
    } == EPIC9_ROLLOUT_PARITY_GATES
    assert {
        gate.perf_gate for gate in ACE_M2_SURFACE_GATES.values()
    } == EPIC9_ROLLOUT_PERF_GATES

    for surface, gate in ACE_M2_SURFACE_GATES.items():
        assert gate.surface == surface
        assert "snapshots" in gate.provider_contracts
        assert set(gate.fallback_tests) >= {
            "daemon_unavailable",
            "projection_degraded",
            "surface_disabled",
        }
        assert "ace.provider_snapshot" in gate.trace_assertions

    assert "deltas" in ACE_M2_SURFACE_GATES["ace_agents"].provider_contracts
    assert "counts" in ACE_M2_SURFACE_GATES["ace_notifications"].provider_contracts
    assert "bounded_detail" in ACE_M2_SURFACE_GATES["ace_artifacts"].provider_contracts


def test_failing_epic9_perf_gates_reports_max_and_min_misses() -> None:
    metrics = {
        "ace_shell_first_useful_paint_p95_ms": 500.0,
        "ace_no_change_auto_refresh_p95_ms": 5.1,
        "ace_lazy_detail_stale_cancellation_count": 0.0,
    }

    assert failing_epic9_perf_gates(metrics) == [
        "ace_no_change_auto_refresh_p95_ms",
        "ace_lazy_detail_stale_cancellation_count",
    ]


def test_forbidden_daemon_no_change_refresh_spans_are_reported() -> None:
    records = [
        {
            "span": "agents.load_from_disk",
            "daemon_backed": True,
            "refresh_kind": "no_change",
        },
        {
            "span": "changespec.filter",
            "daemon_backed": False,
            "refresh_kind": "no_change",
        },
        {
            "span": "widget.agent_list.update_highlight",
            "daemon_backed": True,
            "refresh_kind": "no_change",
        },
    ]

    assert forbidden_daemon_no_change_refresh_spans(records) == [
        "agents.load_from_disk"
    ]
    assert "changespec.filter" in EPIC9_DAEMON_NO_CHANGE_FORBIDDEN_SPANS


def test_ace_daemon_surfaces_remain_default_opt_in() -> None:
    default_config = _load_default_config()
    surfaces = default_config["daemon"]["reads"]["surfaces"]

    assert DEFAULT_ENABLED_SURFACE_GROUPS.isdisjoint(ACE_DAEMON_SURFACE_GROUPS)
    assert {
        surface: surfaces[surface] for surface in ACE_DAEMON_SURFACE_GROUPS
    } == dict.fromkeys(ACE_DAEMON_SURFACE_GROUPS, False)
    with patch("sase.daemon.read_config.load_merged_config", return_value={}):
        assert ace_default_rollout_violations(daemon_read_surface_enabled) == []


def test_rollout_policy_detects_enabled_ace_surface() -> None:
    assert ace_default_rollout_violations(
        lambda surface: surface == "ace_changespecs"
    ) == ["ace_changespecs"]


def test_epic9_daemon_fixtures_cover_pages_expiry_deltas_and_errors() -> None:
    fixtures = _fixture_matrix()

    assert set(fixtures) == {
        "page",
        "cursor_expiry",
        "snapshot_expiry",
        "delta_batch",
        "projection_error",
    }
    assert fixtures["page"].payload["page"]["next_cursor"] == "cursor-2"
    assert fixtures["cursor_expiry"].payload["error"]["code"] == "cursor_expired"
    assert fixtures["snapshot_expiry"].payload["error"]["code"] == "snapshot_expired"
    assert fixtures["delta_batch"].payload["row_patches"][0]["operation"] == "upsert"
    assert fixtures["projection_error"].payload["error"]["fallback_reason"] == (
        "projection_corrupt"
    )
