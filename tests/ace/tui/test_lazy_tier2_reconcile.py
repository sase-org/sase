"""Tests for the lazy Tier 2 full-history reconcile.

The Tier 2 reconcile dominates startup wall time on established home
dirs (~2.7 s per the 2026-05-16 perf research). It is now deferred:
the loader reports visible-inbox completeness separately from full archive
history, normal ``y`` refresh stays Tier 1, and full-history refresh is an
explicit Agents action.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading_refresh import (
    AgentLoadingRefreshMixin,
    TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S,
)
from sase.ace.tui.util.nav_gate import NavigationGate


class _FakeRefreshApp(AgentLoadingRefreshMixin):
    """Minimal app exposing just the surface the refresh mixin touches."""

    def __init__(self) -> None:
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_pending_full_history = False
        self._agents_refresh_pending_full_history_reason = None
        self._agents_refresh_pending_callbacks: list[Callable[[], None]] = []
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_full_history = False
        self._agents_refresh_scheduled_full_history_reason = None
        self._agents_refresh_debounce_armed = False
        self._agents_history_reconcile_pending = False
        self._agents_history_reconcile_armed_mono = 0.0
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


class _FakeBaseActionsApp:
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


def test_input_quiet_trigger_skips_when_flag_not_set() -> None:
    app = _FakeRefreshApp()
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(now_mono=10_000.0)
    assert fired is False
    assert app._scheduled == []


def test_manual_agents_refresh_stays_tier1_even_when_reconcile_pending() -> None:
    from sase.ace.tui.actions.base import BaseActionsMixin

    app = _FakeBaseActionsApp()
    app._agents_history_reconcile_pending = True

    BaseActionsMixin.action_refresh(app)  # type: ignore[arg-type]

    assert app.scheduled == [(False, None)]
    assert app._agents_history_reconcile_pending is True
    assert app.notifications == ["Refreshed"]


def test_explicit_agents_full_history_refresh_uses_tier2() -> None:
    from sase.ace.tui.actions.base import BaseActionsMixin

    app = _FakeBaseActionsApp()
    app._agents_history_reconcile_pending = True

    BaseActionsMixin.action_refresh_agents_full_history(app)  # type: ignore[arg-type]

    assert app.scheduled == [(True, "manual_full_history_refresh")]
    assert app._agents_history_reconcile_pending is False
    assert app.notifications == ["Refreshing Agents from full history"]


def test_input_quiet_trigger_skips_when_recent_input() -> None:
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 100.0
    app._last_input_mono = 100.0
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(
        now_mono=100.0 + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S - 1.0
    )
    assert fired is False
    assert app._scheduled == []
    assert app._agents_history_reconcile_pending is True


def test_input_quiet_trigger_fires_after_threshold() -> None:
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 100.0
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(
        now_mono=100.0 + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S + 0.5
    )
    assert fired is True
    assert app._agents_history_reconcile_pending is False
    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_scheduled_full_history is True
    assert (
        app._agents_refresh_scheduled_full_history_reason
        == "input_quiet_tier2_reconcile"
    )
    assert len(app._scheduled) == 1


def test_input_quiet_trigger_skips_when_load_already_in_flight() -> None:
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 100.0
    app._agents_loading = True
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(
        now_mono=100.0 + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S + 5.0
    )
    assert fired is False
    assert app._scheduled == []
    # Pending flag stays armed for the next eligible tick.
    assert app._agents_history_reconcile_pending is True


def test_input_quiet_trigger_uses_latest_of_input_and_arm_time() -> None:
    """Input after arming resets the quiet clock."""
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 100.0
    # User pressed a key 5 s ago — not quiet long enough yet.
    app._last_input_mono = 100.0 + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S - 5.0
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(
        now_mono=app._last_input_mono + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S - 1.0
    )
    assert fired is False
    # …but a further wait past the threshold from the keypress fires it.
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(
        now_mono=app._last_input_mono + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S + 0.5
    )
    assert fired is True


def test_apply_sets_pending_flag_without_scheduling_refresh() -> None:
    """A repair-state load marks reconcile pending without immediate reload."""
    from sase.ace.tui.actions.agents._loading_compute import PreparedApplyData
    from sase.ace.tui.models.agent_loader import AgentLoadState

    from tests._agents_tab_query_helpers import FakeAgentApp

    app = FakeAgentApp()
    # Make the FakeAgentApp look enough like the real one for the
    # apply path to exercise the pending-flag branch.
    app._agents_history_reconcile_pending = False
    app._agents_history_reconcile_armed_mono = 0.0
    app._agents_refresh_pending = False
    app._agents_refresh_pending_full_history = False
    app._agents_refresh_scheduled = False
    app._agents_refresh_scheduled_full_history = False

    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=False,
        artifact_source="source_scan",
        used_artifact_index=False,
        repair_recommended=True,
        repair_reason="artifact_index_missing_bounded_fallback",
    )

    before = time.monotonic()
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

    assert app._agents_history_reconcile_pending is True
    assert app._agents_history_reconcile_armed_mono >= before
    # The old code auto-scheduled the Tier 2 reload via these flags.
    # The new code must NOT touch them.
    assert app._agents_refresh_pending is False
    assert app._agents_refresh_pending_full_history is False
    assert app._agents_refresh_scheduled is False


def test_apply_complete_visible_inbox_does_not_arm_history_reconcile() -> None:
    """Tier 1 can be archive-incomplete while complete for the visible inbox."""
    from sase.ace.tui.actions.agents._loading_compute import PreparedApplyData
    from sase.ace.tui.models.agent_loader import AgentLoadState

    from tests._agents_tab_query_helpers import FakeAgentApp

    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False
    app._agents_history_reconcile_armed_mono = 0.0

    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=True,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

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

    assert app._agents_history_reconcile_pending is False
    assert app._agents_history_reconcile_armed_mono == 0.0


def test_apply_clears_pending_flag_on_complete_history() -> None:
    from sase.ace.tui.actions.agents._loading_compute import PreparedApplyData
    from sase.ace.tui.models.agent_loader import AgentLoadState

    from tests._agents_tab_query_helpers import FakeAgentApp

    app = FakeAgentApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 42.0
    app._agents_seen_complete_history = False

    load_state = AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )

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

    assert app._agents_history_reconcile_pending is False
    assert app._agents_seen_complete_history is True


@pytest.mark.asyncio
async def test_input_quiet_trigger_routes_through_async_refresh() -> None:
    """The deferred reconcile actually issues a full_history reload."""
    app = _FakeRefreshApp()
    captured: list[bool] = []

    async def _fake_load_agents_async(*, full_history: bool = False) -> None:
        captured.append(full_history)

    app._load_agents_async = _fake_load_agents_async  # type: ignore[method-assign]

    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 0.001  # any non-zero value
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(
        now_mono=TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S + 1.0
    )
    assert fired is True
    await app._run_agents_async_refresh()
    assert captured == [True]


def test_repair_notice_only_when_repair_recommended() -> None:
    """Repair diagnostics surface as an operator-visible notice."""
    from sase.ace.tui.actions.agents._loading_apply import (
        _agent_index_repair_notice,
    )
    from sase.ace.tui.models.agent_loader import AgentLoadState

    healthy = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=True,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )
    repair = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=False,
        artifact_source="source_scan",
        used_artifact_index=False,
        repair_recommended=True,
        repair_reason="artifact_index_missing_bounded_fallback",
    )

    assert _agent_index_repair_notice(healthy) is None
    notice = _agent_index_repair_notice(repair)
    assert notice is not None
    assert "artifact_index_missing_bounded_fallback" in notice
    assert "sase agent index gc" in notice


def _make_complete_load_state() -> Any:
    from sase.ace.tui.models.agent_loader import AgentLoadState

    return AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )


def _apply_load(app: Any, load_state: Any) -> None:
    from sase.ace.tui.actions.agents._loading_compute import PreparedApplyData

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


def test_apply_repair_state_marks_reconcile_pending_without_timer() -> None:
    """Repair diagnostics defer full-history repair to idle/manual paths."""
    from tests._agents_tab_query_helpers import FakeAgentApp
    from sase.ace.tui.models.agent_loader import AgentLoadState

    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False

    _apply_load(
        app,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="source_scan",
            used_artifact_index=False,
            repair_recommended=True,
            repair_reason="artifact_index_missing_bounded_fallback",
        ),
    )

    assert app._agents_history_reconcile_pending is True
    assert app.timer_calls == []


def test_apply_incomplete_index_state_does_not_arm_reconcile() -> None:
    """An index-backed incomplete inbox is reported but not auto-promoted."""
    from tests._agents_tab_query_helpers import FakeAgentApp
    from sase.ace.tui.models.agent_loader import AgentLoadState

    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False

    _apply_load(
        app,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
        ),
    )

    assert app._agents_history_reconcile_pending is False
    assert app.timer_calls == []


def test_apply_complete_history_does_not_arm_reconcile() -> None:
    """If a load returned complete history, no reconcile is armed."""
    from tests._agents_tab_query_helpers import FakeAgentApp

    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False
    app._agents_seen_complete_history = False

    _apply_load(app, _make_complete_load_state())

    assert app.timer_calls == []
    assert app._agents_history_reconcile_pending is False
