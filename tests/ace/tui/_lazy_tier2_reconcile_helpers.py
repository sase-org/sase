"""Shared helpers for lazy Tier 2 reconcile tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.ace.tui.actions.agents._loading_compute import PreparedApplyData
from sase.ace.tui.actions.agents._loading_refresh import AgentLoadingRefreshMixin
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.util.nav_gate import NavigationGate


class FakeRefreshApp(AgentLoadingRefreshMixin):
    """Minimal app exposing just the surface the refresh mixin touches."""

    def __init__(self) -> None:
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_pending_source = "unknown"
        self._agents_refresh_pending_full_history = False
        self._agents_refresh_pending_full_history_reason = None
        self._agents_refresh_pending_revalidate_index = False
        self._agents_refresh_pending_prefix_completion = False
        self._agents_refresh_pending_callbacks: list[Callable[[], None]] = []
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_source = "unknown"
        self._agents_refresh_scheduled_full_history = False
        self._agents_refresh_scheduled_full_history_reason = None
        self._agents_refresh_scheduled_revalidate_index = False
        self._agents_refresh_scheduled_prefix_completion = False
        self._agents_refresh_active_prefix_completion = False
        self._agents_refresh_debounce_armed = False
        self._agents_history_reconcile_pending = False
        self._agents_history_reconcile_armed_mono = 0.0
        self._agents_index_revalidate_pending = False
        self._agents_index_revalidate_armed_mono = 0.0
        self._agents_index_revalidate_last_mono = 0.0
        self._agents_prefix_completion_pending = False
        self._agents_prefix_completion_done = False
        self._agents_prefix_completion_armed_mono = 0.0
        self._agents_artifact_delta_scheduled = None
        self._last_input_mono = 0.0
        self._nav_gate = NavigationGate(window_s=0.25)
        self._scheduled: list[Any] = []
        self._timer_calls: list[tuple[float, Callable[[], Any]]] = []

    def call_later(self, callback: Any) -> None:
        self._scheduled.append(callback)

    def _spawn_agents_refresh_task(self) -> None:
        self._scheduled.append(self._run_agents_async_refresh)

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))


class FakeBaseActionsApp:
    """Minimal host for BaseActionsMixin refresh actions."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self._agents_history_reconcile_pending = False
        self.scheduled: list[tuple[bool, str | None]] = []
        self.notifications: list[str] = []

    def _schedule_agents_async_refresh(
        self,
        *,
        source: str = "unknown",
        full_history: bool = False,
        full_history_reason: str | None = None,
    ) -> None:
        del source
        self.scheduled.append((full_history, full_history_reason))

    def notify(self, message: str, **_: Any) -> None:
        self.notifications.append(message)


def apply_load(app: Any, load_state: AgentLoadState) -> None:
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[],
            has_always_visible=False,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=load_state,
        persist_dismissed_changes=False,
    )


def make_complete_load_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )


def bounded_partial_load_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=True,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        requested_limit=126,
        returned_count=126,
        has_more=True,
    )
