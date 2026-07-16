"""Tests for deferred artifact-index maintenance scheduling."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _index_maintenance as maintenance_mod
from sase.ace.tui.actions.agents._index_maintenance import (
    _ACTIVE_TIER_MAINTENANCE_MIN_INTERVAL_S,
    AgentIndexMaintenanceMixin,
)
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.core.agent_artifact_index_lifecycle import DismissedProjectionSyncReport

_ID1 = (AgentType.RUNNING, "one", "20260601010101")
_ID2 = (AgentType.RUNNING, "two", "20260602020202")


class _FakeApp(AgentIndexMaintenanceMixin):
    def __init__(self) -> None:
        self._artifact_index_maintenance_running = False
        self._artifact_index_maintenance_pending = False
        self._artifact_index_maintenance_pending_request = None
        self._artifact_index_maintenance_last_mono = 0.0
        self._artifact_index_schema_bypass = False
        self._nav_gate = NavigationGate(window_s=0.25)
        self._scheduled: list[Callable[[], Any]] = []
        self._timer_calls: list[tuple[float, Callable[[], Any]]] = []

    def _spawn_artifact_index_maintenance_task(self) -> None:
        """Record scheduling without starting a task in narrow unit tests."""
        callback = self._run_artifact_index_maintenance
        self._scheduled.append(callback)

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))


def test_scheduler_defers_while_schema_index_is_bypassed() -> None:
    app = _FakeApp()
    app._artifact_index_schema_bypass = True

    app._schedule_artifact_index_maintenance(dismissed={_ID1}, source="startup")

    assert app._scheduled == []
    assert app._artifact_index_maintenance_running is False
    assert app._artifact_index_maintenance_pending is True
    assert app._artifact_index_maintenance_pending_request is not None

    app._artifact_index_schema_bypass = False
    app._resume_artifact_index_maintenance_after_schema_rebuild()
    assert app._scheduled == [app._run_artifact_index_maintenance]
    assert app._artifact_index_maintenance_running is True


@pytest.mark.asyncio
async def test_scheduler_runs_latest_snapshot_and_or_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def fake_to_thread(
        func: object, /, *args: object, **kwargs: object
    ) -> DismissedProjectionSyncReport:
        assert func is maintenance_mod.sync_dismissed_agent_artifact_index_report
        calls.append((args, kwargs))
        return DismissedProjectionSyncReport(synced=True)

    monkeypatch.setattr(maintenance_mod.asyncio, "to_thread", fake_to_thread)

    app._schedule_artifact_index_maintenance(
        dismissed={_ID1},
        added={_ID1},
        force=True,
        source="first",
    )
    app._schedule_artifact_index_maintenance(
        dismissed={_ID2},
        added={_ID2},
        force=False,
        source="second",
    )

    await app._scheduled.pop(0)()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ({_ID2},)
    assert kwargs["added"] == {_ID2}
    assert kwargs["force"] is True
    assert kwargs["run_active_tier_maintenance"] is False
    assert app._artifact_index_maintenance_running is False


@pytest.mark.asyncio
async def test_scheduler_rearms_when_request_arrives_during_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp()
    dismissed_calls: list[set[object]] = []

    async def fake_to_thread(
        func: object, /, *args: object, **kwargs: object
    ) -> DismissedProjectionSyncReport:
        del func, kwargs
        dismissed_calls.append(set(args[0]))  # type: ignore[arg-type]
        if len(dismissed_calls) == 1:
            app._schedule_artifact_index_maintenance(
                dismissed={_ID2},
                source="during_worker",
            )
        return DismissedProjectionSyncReport(synced=True)

    monkeypatch.setattr(maintenance_mod.asyncio, "to_thread", fake_to_thread)

    app._schedule_artifact_index_maintenance(dismissed={_ID1}, source="first")
    await app._scheduled.pop(0)()

    assert dismissed_calls == [{_ID1}]
    assert app._scheduled == [app._run_artifact_index_maintenance]
    assert app._artifact_index_maintenance_running is True

    await app._scheduled.pop(0)()

    assert dismissed_calls == [{_ID1}, {_ID2}]
    assert app._artifact_index_maintenance_running is False
    assert app._artifact_index_maintenance_pending_request is None


@pytest.mark.asyncio
async def test_scheduler_defers_behind_navigation_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp()
    to_thread_calls = 0

    async def fake_to_thread(
        func: object, /, *args: object, **kwargs: object
    ) -> DismissedProjectionSyncReport:
        del func, args, kwargs
        nonlocal to_thread_calls
        to_thread_calls += 1
        return DismissedProjectionSyncReport(synced=True)

    monkeypatch.setattr(maintenance_mod.asyncio, "to_thread", fake_to_thread)
    app._schedule_artifact_index_maintenance(dismissed={_ID1}, source="first")
    app._nav_gate.record()

    await app._scheduled.pop(0)()

    assert to_thread_calls == 0
    assert len(app._timer_calls) == 1
    delay, callback = app._timer_calls[0]
    assert 0.05 < delay <= 0.30
    assert callback == app._spawn_artifact_index_maintenance_task
    assert app._artifact_index_maintenance_running is True
    assert app._artifact_index_maintenance_pending_request is not None


def test_terminalize_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakeApp()
    monkeypatch.setattr(maintenance_mod.time, "monotonic", lambda: 5000.0)

    assert app._should_run_active_tier_terminalize() is False

    app._artifact_index_maintenance_last_mono = 4999.0
    assert app._should_run_active_tier_terminalize() is False

    app._artifact_index_maintenance_last_mono = (
        5000.0 - _ACTIVE_TIER_MAINTENANCE_MIN_INTERVAL_S
    )
    assert app._should_run_active_tier_terminalize() is True


@pytest.mark.asyncio
async def test_terminalize_runs_only_after_throttle_interval_and_stamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp()
    kwargs_seen: list[dict[str, object]] = []
    monkeypatch.setattr(maintenance_mod.time, "monotonic", lambda: 5000.0)

    async def fake_to_thread(
        func: object, /, *args: object, **kwargs: object
    ) -> DismissedProjectionSyncReport:
        del func, args
        kwargs_seen.append(kwargs)
        return DismissedProjectionSyncReport(synced=True)

    monkeypatch.setattr(maintenance_mod.asyncio, "to_thread", fake_to_thread)

    app._schedule_artifact_index_maintenance(dismissed={_ID1}, source="startup_gap")
    await app._scheduled.pop(0)()

    assert kwargs_seen[-1]["run_active_tier_maintenance"] is False
    assert app._artifact_index_maintenance_last_mono == 0.0

    app._artifact_index_maintenance_last_mono = 1000.0
    app._schedule_artifact_index_maintenance(dismissed={_ID1}, source="aged")
    await app._scheduled.pop(0)()

    assert kwargs_seen[-1]["run_active_tier_maintenance"] is True
    assert app._artifact_index_maintenance_last_mono == 5000.0
