"""Take monitor reconciliation off the synchronous agents disk load."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.actions.agents._loading_disk_support import (
    MONITOR_RECONCILE_REFRESH_SOURCE,
    AgentLoadingDiskSupportMixin,
    _reconcile_dead_monitor_supervisors_for_tui,
)
from sase.ace.tui.actions.agents._loading_helpers import (
    _AgentDiskLoadResult,
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from tests.monitor._fixtures import (
    DEAD_PID,
    make_starter_agent,
    patch_project_records,
    record_from_disk,
)


class _IdleNavigationGate:
    def is_navigating(self) -> bool:
        return False

    def time_until_idle(self) -> float:
        return 0.0


class _ReconcileApp(AgentLoadingDiskSupportMixin):
    def __init__(self) -> None:
        self._monitor_reconcile_running = False
        self._monitor_reconcile_pending = False
        self._monitor_reconcile_pending_source = "unknown"
        self._monitor_reconcile_async_tasks: set[asyncio.Task[None]] = set()
        self._nav_gate = _IdleNavigationGate()
        self.refresh_sources: list[str] = []

    def set_timer(self, _delay: float, _callback: object) -> None:
        raise AssertionError("idle reconcile must not arm a navigation timer")

    def _schedule_agents_async_refresh(
        self, *, source: str = "unknown", **_: object
    ) -> None:
        self.refresh_sources.append(source)


class _ScheduleProbeApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self.current_tab = "patches"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents = []
        self._agents_with_children = []
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._agent_search_query = ""
        self._agent_content_search_index = None
        self._agent_status_overrides = {}
        self._agents_seen_complete_history = False
        self._agent_load_state = None
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agents_disk_signature = None
        self._dismissed_agents_disk_identities: set[Any] = set()
        self._dismissed_agents_disk_signature_initialized = True
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_pending_source = "unknown"
        self._agents_refresh_pending_full_history = False
        self._agents_refresh_pending_full_history_reason = None
        self._agents_refresh_pending_callbacks: list[Any] = []
        self._agents_refresh_scheduled = True
        self._agents_refresh_scheduled_source = "test"
        self._agents_refresh_scheduled_full_history = False
        self._agents_refresh_scheduled_full_history_reason = None
        self._agents_refresh_active_source = "unknown"
        self.reconcile_sources: list[str] = []
        self.applied = True

    def _apply_loaded_agents(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def _apply_loaded_agents_prepared(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def _schedule_monitor_reconcile(self, *, source: str) -> None:
        self.reconcile_sources.append(source)


async def _drain_monitor_reconcile(app: _ReconcileApp) -> None:
    for _ in range(200):
        tasks = tuple(app._monitor_reconcile_async_tasks)
        if not app._monitor_reconcile_running and not tasks:
            return
        if tasks:
            await asyncio.gather(*tasks)
        else:
            await asyncio.sleep(0)
    raise AssertionError("monitor reconcile tasks did not drain")


def _expose_monitor_dirs(
    monkeypatch: pytest.MonkeyPatch, artifacts_dirs: list[str]
) -> None:
    from sase.monitor import store as store_module

    def fake_reconciliation_records(
        project_name: str | None,
    ) -> list[object]:
        return [
            record
            for record in (record_from_disk(path) for path in artifacts_dirs)
            if project_name is None or record.project_name == project_name
        ]

    monkeypatch.setattr(
        store_module, "_reconciliation_project_records", fake_reconciliation_records
    )
    patch_project_records(monkeypatch, artifacts_dirs)


def _empty_load_result() -> _AgentDiskLoadResult:
    return _AgentDiskLoadResult(
        all_agents=[],
        dismissed_from_loader=[],
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
        ),
    )


def test_disk_load_does_not_call_reconcile_synchronously() -> None:
    with (
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=(
                [],
                AgentLoadState(
                    tier="tier2",
                    complete_history=True,
                    artifact_source="source_scan",
                    used_artifact_index=False,
                ),
            ),
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
        patch("sase.monitor.reconcile_dead_supervisors") as reconcile,
    ):
        load_agents_from_disk_with_state(set(), source="startup")

    reconcile.assert_not_called()


def test_sync_load_schedules_background_reconcile() -> None:
    app = _ScheduleProbeApp()
    with (
        patch.object(app, "_merge_external_dismissals"),
        patch("sase.ace.patch.find_all_patches_cached", return_value=[]),
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            return_value=_empty_load_result(),
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        app._load_agents(source="startup")

    assert app.reconcile_sources == ["startup"]


@pytest.mark.asyncio
async def test_async_load_schedules_background_reconcile() -> None:
    app = _ScheduleProbeApp()
    with (
        patch(
            "sase.ace.tui.actions.agents._loading_disk."
            "_compute_external_dismissal_merge",
            return_value=None,
        ),
        patch("sase.ace.patch.find_all_patches_cached", return_value=[]),
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            return_value=_empty_load_result(),
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        await app._load_agents_async(source="startup")

    assert app.reconcile_sources == ["startup"]


def test_followup_refresh_source_does_not_reschedule_reconcile() -> None:
    app = _ReconcileApp()
    app._schedule_monitor_reconcile(source=MONITOR_RECONCILE_REFRESH_SOURCE)
    assert app._monitor_reconcile_running is False
    assert app._monitor_reconcile_async_tasks == set()


@pytest.mark.asyncio
async def test_monitor_reconcile_burst_runs_one_trailing_pass() -> None:
    app = _ReconcileApp()
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def fake_reconcile() -> list[object]:
        calls.append("pass")
        if len(calls) == 1:
            started.set()
            release.wait(timeout=2.0)
        return []

    with patch(
        "sase.ace.tui.actions.agents._loading_disk_support."
        "_reconcile_dead_monitor_supervisors_for_tui",
        side_effect=fake_reconcile,
    ):
        app._schedule_monitor_reconcile(source="one")
        await asyncio.wait_for(asyncio.to_thread(started.wait, 1.0), 1.5)
        app._schedule_monitor_reconcile(source="two")
        app._schedule_monitor_reconcile(source="three")
        release.set()
        await _drain_monitor_reconcile(app)

    assert calls == ["pass", "pass"]
    assert app.refresh_sources == []


@pytest.mark.asyncio
async def test_spawn_failure_releases_monitor_reconcile_guard() -> None:
    app = _ReconcileApp()

    def fake_spawn(_owner: object, coro: object, **_kwargs: object) -> None:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return None

    with patch(
        "sase.ace.tui.actions.agents._loading_disk_support.spawn_pump_free_task",
        side_effect=fake_spawn,
    ):
        app._schedule_monitor_reconcile(source="startup")

    assert app._monitor_reconcile_running is False
    assert app._monitor_reconcile_pending is False


@pytest.mark.asyncio
async def test_background_reconcile_settles_dead_supervisor_and_refreshes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
        monitor_command="sleep 60",
        monitor_stop_status="MONITORED",
        pid=DEAD_PID,
    )
    _expose_monitor_dirs(monkeypatch, [monitor_dir])
    app = _ReconcileApp()

    app._schedule_monitor_reconcile(source="startup")
    await _drain_monitor_reconcile(app)

    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "failed"
    assert meta["monitor_settled"] is True
    assert (Path(monitor_dir) / "done.json").exists()
    assert app.refresh_sources == [MONITOR_RECONCILE_REFRESH_SOURCE]


def test_tui_reconcile_helper_returns_settled_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monitor_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="aaa",
        monitor_state="running",
        monitor_command="sleep 60",
        monitor_stop_status="MONITORED",
        pid=DEAD_PID,
    )
    _expose_monitor_dirs(monkeypatch, [monitor_dir])

    settled = _reconcile_dead_monitor_supervisors_for_tui()

    assert [record.monitor_state for record in settled] == ["failed"]  # type: ignore[attr-defined]
    assert (Path(monitor_dir) / "done.json").exists()
