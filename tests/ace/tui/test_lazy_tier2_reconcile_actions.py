"""Tests for manual and deferred Tier 2 reconcile refresh actions."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents._loading_refresh import (
    TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S,
)
from tests.ace.tui._lazy_tier2_reconcile_helpers import (
    FakeBaseActionsApp,
    FakeRefreshApp,
)


def test_input_quiet_trigger_skips_when_flag_not_set() -> None:
    app = FakeRefreshApp()
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(now_mono=10_000.0)
    assert fired is False
    assert app._scheduled == []


def test_manual_agents_refresh_stays_tier1_even_when_reconcile_pending() -> None:
    from sase.ace.tui.actions.base import BaseActionsMixin

    app = FakeBaseActionsApp()
    app._agents_history_reconcile_pending = True

    BaseActionsMixin.action_refresh(app)  # type: ignore[arg-type]

    assert app.scheduled == [(False, None)]
    assert app._agents_history_reconcile_pending is True
    assert app.notifications == ["Refreshed"]


def test_explicit_agents_full_history_refresh_uses_tier2() -> None:
    from sase.ace.tui.actions.base import BaseActionsMixin

    app = FakeBaseActionsApp()
    app._agents_history_reconcile_pending = True

    BaseActionsMixin.action_refresh_agents_full_history(app)  # type: ignore[arg-type]

    assert app.scheduled == [(True, "manual_full_history_refresh")]
    assert app._agents_history_reconcile_pending is False
    assert app.notifications == ["Refreshing Agents from full history"]


def test_input_quiet_trigger_skips_when_recent_input() -> None:
    app = FakeRefreshApp()
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
    app = FakeRefreshApp()
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
    app = FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 100.0
    app._agents_loading = True
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(
        now_mono=100.0 + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S + 5.0
    )
    assert fired is False
    assert app._scheduled == []
    assert app._agents_history_reconcile_pending is True


def test_input_quiet_trigger_uses_latest_of_input_and_arm_time() -> None:
    """Input after arming resets the quiet clock."""
    app = FakeRefreshApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 100.0
    app._last_input_mono = 100.0 + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S - 5.0
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(
        now_mono=app._last_input_mono + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S - 1.0
    )
    assert fired is False

    fired = app._maybe_trigger_input_quiet_tier2_reconcile(
        now_mono=app._last_input_mono + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S + 0.5
    )
    assert fired is True


@pytest.mark.asyncio
async def test_input_quiet_trigger_routes_through_async_refresh() -> None:
    """The deferred reconcile actually issues a full_history reload."""
    app = FakeRefreshApp()
    captured: list[bool] = []

    async def _fake_load_agents_async(*, full_history: bool = False) -> None:
        captured.append(full_history)

    app._load_agents_async = _fake_load_agents_async  # type: ignore[method-assign]

    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 0.001
    fired = app._maybe_trigger_input_quiet_tier2_reconcile(
        now_mono=TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S + 1.0
    )
    assert fired is True
    await app._run_agents_async_refresh()
    assert captured == [True]
