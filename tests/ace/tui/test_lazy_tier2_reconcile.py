"""Tests for the lazy Tier 2 full-history reconcile.

The Tier 2 reconcile dominates startup wall time on established home
dirs (~2.7 s per the 2026-05-16 perf research). It is now deferred:
the loader still reports incomplete history, but the reconcile is
only scheduled once the user has been idle for
``TIER2_RECONCILE_IDLE_THRESHOLD_S`` or explicitly requests a manual
refresh while the flag is pending.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading_refresh import (
    AgentLoadingRefreshMixin,
    STARTUP_TIER2_RECONCILE_DELAY_S,
    TIER2_RECONCILE_IDLE_THRESHOLD_S,
)
from sase.ace.tui.util.nav_gate import NavigationGate


class _FakeRefreshApp(AgentLoadingRefreshMixin):
    """Minimal app exposing just the surface the refresh mixin touches."""

    def __init__(self) -> None:
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_pending_full_history = False
        self._agents_refresh_pending_callbacks: list[Callable[[], None]] = []
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_full_history = False
        self._agents_refresh_debounce_armed = False
        self._agents_history_reconcile_pending = False
        self._agents_history_reconcile_armed_mono = 0.0
        self._agents_startup_tier2_scheduled = False
        self._last_activity_time = 0.0
        self._nav_gate = NavigationGate(window_s=0.25)
        self._scheduled: list[Any] = []
        self._timer_calls: list[tuple[float, Callable[[], Any]]] = []

    def call_later(self, callback: Any) -> None:
        self._scheduled.append(callback)

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))


def test_idle_trigger_skips_when_flag_not_set() -> None:
    app = _FakeRefreshApp()
    fired = app._maybe_trigger_idle_tier2_reconcile(now_mono=10_000.0)
    assert fired is False
    assert app._scheduled == []


def test_idle_trigger_skips_when_recently_active() -> None:
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 100.0
    app._last_activity_time = 100.0
    fired = app._maybe_trigger_idle_tier2_reconcile(
        now_mono=100.0 + TIER2_RECONCILE_IDLE_THRESHOLD_S - 1.0
    )
    assert fired is False
    assert app._scheduled == []
    assert app._agents_history_reconcile_pending is True


def test_idle_trigger_fires_after_threshold() -> None:
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 100.0
    fired = app._maybe_trigger_idle_tier2_reconcile(
        now_mono=100.0 + TIER2_RECONCILE_IDLE_THRESHOLD_S + 0.5
    )
    assert fired is True
    assert app._agents_history_reconcile_pending is False
    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_scheduled_full_history is True
    assert len(app._scheduled) == 1


def test_idle_trigger_skips_when_load_already_in_flight() -> None:
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 100.0
    app._agents_loading = True
    fired = app._maybe_trigger_idle_tier2_reconcile(
        now_mono=100.0 + TIER2_RECONCILE_IDLE_THRESHOLD_S + 5.0
    )
    assert fired is False
    assert app._scheduled == []
    # Pending flag stays armed for the next eligible tick.
    assert app._agents_history_reconcile_pending is True


def test_idle_trigger_uses_latest_of_activity_and_arm_time() -> None:
    """Active input after arming resets the idle clock."""
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 100.0
    # User pressed a key 5 s ago — not idle long enough yet.
    app._last_activity_time = 100.0 + TIER2_RECONCILE_IDLE_THRESHOLD_S - 5.0
    fired = app._maybe_trigger_idle_tier2_reconcile(
        now_mono=app._last_activity_time + TIER2_RECONCILE_IDLE_THRESHOLD_S - 1.0
    )
    assert fired is False
    # …but a further wait past the threshold from the keypress fires it.
    fired = app._maybe_trigger_idle_tier2_reconcile(
        now_mono=app._last_activity_time + TIER2_RECONCILE_IDLE_THRESHOLD_S + 0.5
    )
    assert fired is True


def test_apply_sets_pending_flag_without_scheduling_refresh() -> None:
    """An incomplete-history load must not auto-schedule a Tier 2 reload."""
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
        artifact_source="artifact_index",
        used_artifact_index=True,
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
async def test_idle_trigger_routes_through_async_refresh() -> None:
    """The deferred reconcile actually issues a full_history reload."""
    app = _FakeRefreshApp()
    captured: list[bool] = []

    async def _fake_load_agents_async(*, full_history: bool = False) -> None:
        captured.append(full_history)

    app._load_agents_async = _fake_load_agents_async  # type: ignore[method-assign]

    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 0.001  # any non-zero value
    fired = app._maybe_trigger_idle_tier2_reconcile(
        now_mono=TIER2_RECONCILE_IDLE_THRESHOLD_S + 1.0
    )
    assert fired is True
    await app._run_agents_async_refresh()
    assert captured == [True]


def _make_incomplete_load_state() -> Any:
    from sase.ace.tui.models.agent_loader import AgentLoadState

    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )


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


def test_apply_arms_startup_tier2_timer() -> None:
    """First incomplete-history apply arms the one-shot startup timer."""
    from tests._agents_tab_query_helpers import FakeAgentApp

    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False
    app._agents_startup_tier2_scheduled = False

    _apply_load(app, _make_incomplete_load_state())

    assert app._agents_startup_tier2_scheduled is True
    assert len(app.timer_calls) == 1
    delay, callback = app.timer_calls[0]
    assert delay == STARTUP_TIER2_RECONCILE_DELAY_S
    assert callback == app._fire_startup_tier2_reconcile


def test_apply_does_not_double_arm_startup_tier2_timer() -> None:
    """Subsequent incomplete-history applies must not re-arm the timer."""
    from tests._agents_tab_query_helpers import FakeAgentApp

    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False
    app._agents_startup_tier2_scheduled = False

    _apply_load(app, _make_incomplete_load_state())
    # Second incomplete-history apply — e.g. a periodic Tier 1 auto-refresh
    # that landed before the startup timer fired.
    app._agents_history_reconcile_pending = False  # cleared by some other path
    _apply_load(app, _make_incomplete_load_state())

    assert len(app.timer_calls) == 1


def test_apply_complete_history_skips_startup_arm() -> None:
    """If Tier 1 already returned complete history, no timer is armed."""
    from tests._agents_tab_query_helpers import FakeAgentApp

    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False
    app._agents_startup_tier2_scheduled = False
    app._agents_seen_complete_history = False

    _apply_load(app, _make_complete_load_state())

    assert app._agents_startup_tier2_scheduled is False
    assert app.timer_calls == []
    assert app._agents_history_reconcile_pending is False


def test_startup_trigger_fires_full_history_refresh() -> None:
    """The startup trigger schedules a full-history refresh when pending."""
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = True

    app._fire_startup_tier2_reconcile()

    assert app._agents_history_reconcile_pending is False
    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_scheduled_full_history is True
    assert len(app._scheduled) == 1


def test_startup_trigger_noop_when_flag_clear() -> None:
    """If the pending flag was cleared (e.g. by the idle path), no schedule."""
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = False

    app._fire_startup_tier2_reconcile()

    assert app._agents_refresh_scheduled is False
    assert app._agents_refresh_scheduled_full_history is False
    assert app._scheduled == []


def test_startup_trigger_noop_when_loading() -> None:
    """In-flight refresh defers to the idle/manual fallback paths."""
    app = _FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_loading = True

    app._fire_startup_tier2_reconcile()

    # Pending flag preserved so idle / manual paths can still trigger.
    assert app._agents_history_reconcile_pending is True
    assert app._agents_refresh_scheduled is False
    assert app._scheduled == []
