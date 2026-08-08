"""Structured trace taxonomy for Agents refresh work."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.actions.agents._refresh_trace import (
    ALL_AGENT_REFRESH_DATA_COSTS,
    ALL_AGENT_REFRESH_DISPLAY_COSTS,
    ALL_AGENT_REFRESH_FALLBACK_REASONS,
    _AgentRefreshTraceRecord,
    classify_agents_data_cost,
)
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.util.nav_gate import NavigationGate


class _TraceLoadingApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_pending_source = "unknown"
        self._agents_refresh_pending_full_history = False
        self._agents_refresh_pending_full_history_reason = None
        self._agents_refresh_pending_callbacks: list[Callable[[], None]] = []
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_source = "unknown"
        self._agents_refresh_scheduled_full_history = False
        self._agents_refresh_scheduled_full_history_reason = None
        self._agents_refresh_active_source = "unknown"
        self._agents_refresh_debounce_armed = False
        self._agents_refresh_debounce_source = "unknown"
        self._scheduled: list[Any] = []
        self._nav_gate = NavigationGate(window_s=0.25)
        self._agents_refresh_trace_records: list[_AgentRefreshTraceRecord] = []

    def call_later(self, callback: Any) -> None:
        self._scheduled.append(callback)

    def _spawn_agents_refresh_task(self) -> None:
        self._scheduled.append(self._run_agents_async_refresh)


class _TraceDisplayApp(AgentDisplayMixin):
    def __init__(self) -> None:
        self._agents: list[Any] = [object(), object()]
        self._agents_refresh_active_source = "launch"
        self._agents_refresh_trace_records: list[_AgentRefreshTraceRecord] = []
        self.calls: list[dict[str, bool]] = []

    def _refresh_agents_display_impl(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        self.calls.append(
            {"list_changed": bool(list_changed), "defer_detail": bool(defer_detail)}
        )


def test_refresh_trace_taxonomy_covers_phase_one_terms() -> None:
    assert ALL_AGENT_REFRESH_DATA_COSTS == {
        "tier2_full_history",
        "tier1_broad_load",
        "artifact_delta_load",
    }
    assert ALL_AGENT_REFRESH_DISPLAY_COSTS == {
        "display_full_rebuild",
        "display_panel_rebuild",
        "row_patch",
        "row_remove",
        "row_insert",
    }
    assert ALL_AGENT_REFRESH_FALLBACK_REASONS >= {
        "missing_launch_result",
        "missing_artifact_dir",
        "delta_read_failure",
        "active_search",
        "unsupported_grouping",
        "width_growth",
        "panel_membership_change",
        "workflow_tree_change",
        "clan_member_order_change",
        "dirty_queue_overflow",
        "unknown_watcher_path",
        "persistence_error",
    }


def test_launch_refresh_schedule_records_broad_load_classification() -> None:
    app = _TraceLoadingApp()

    app._schedule_agents_async_refresh(source="launch")

    assert app._scheduled == [app._run_agents_async_refresh]
    assert app._agents_refresh_trace_records == [
        _AgentRefreshTraceRecord(
            stage="scheduled",
            source="launch",
            data_cost="tier1_broad_load",
            fallback_reason="missing_launch_result",
            full_history=False,
        )
    ]


def test_full_history_refresh_schedule_records_tier2_classification() -> None:
    app = _TraceLoadingApp()

    app._schedule_agents_async_refresh(
        source="revive",
        full_history=True,
        full_history_reason="manual_history_recovery",
    )

    assert app._agents_refresh_trace_records == [
        _AgentRefreshTraceRecord(
            stage="scheduled",
            source="revive",
            data_cost="tier2_full_history",
            fallback_reason="manual_history_recovery",
            full_history=True,
        )
    ]


def test_starting_poll_broad_schedule_does_not_infer_delta_failure() -> None:
    app = _TraceLoadingApp()

    app._schedule_agents_async_refresh(source="starting_poll")

    assert app._agents_refresh_trace_records == [
        _AgentRefreshTraceRecord(
            stage="scheduled",
            source="starting_poll",
            data_cost="tier1_broad_load",
            full_history=False,
        )
    ]


def test_classify_agents_data_cost_uses_load_state_tier() -> None:
    tier1_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )
    tier2_state = AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )

    assert classify_agents_data_cost(load_state=tier1_state) == "tier1_broad_load"
    assert classify_agents_data_cost(load_state=tier2_state) == "tier2_full_history"
    assert classify_agents_data_cost(artifact_delta=True) == "artifact_delta_load"


def test_display_full_rebuild_records_display_cost() -> None:
    app = _TraceDisplayApp()

    app._refresh_agents_display(list_changed=True, defer_detail=True)

    assert app.calls == [{"list_changed": True, "defer_detail": True}]
    assert app._agents_refresh_trace_records == [
        _AgentRefreshTraceRecord(
            stage="display",
            source="launch",
            display_cost="display_full_rebuild",
        )
    ]
