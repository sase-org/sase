"""Tests for pending-gate arrival notification refreshes."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.agents._notification_utils import (
    is_active_agent_refresh_notification,
)
from sase.ace.tui.models import agent_loader
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import notification_activity_cursor
from sase.notifications.models import Notification

from tests._notification_toasts_helpers import (
    _FakeApp,
    _make,
    _patch_snapshot,
    _snapshot,
)


def _ace_run_dir(sase_home: Path, timestamp: str, *, project: str = "demo") -> Path:
    path = (
        sase_home
        / "projects"
        / project
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    path.mkdir(parents=True)
    return path


def _record_scan_threads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record the thread id of every unloaded-timestamp directory scan."""
    real_scan = agent_loader.artifact_dirs_for_normalized_timestamps
    scan_threads: list[int] = []

    def recording_scan(normalized: set[str]) -> list[Path]:
        scan_threads.append(threading.get_ident())
        return real_scan(normalized)

    monkeypatch.setattr(
        agent_loader, "artifact_dirs_for_normalized_timestamps", recording_scan
    )
    return scan_threads


class TestPendingGateArrivalRefresh:
    """Pending-review gates toast and schedule an exact family-chain delta."""

    def _install_capture(
        self, app: _FakeApp
    ) -> tuple[list[tuple[tuple[Path, ...], str]], list[tuple[str, bool]]]:
        scheduled: list[tuple[tuple[Path, ...], str]] = []
        broad: list[tuple[str, bool]] = []
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: scheduled.append((tuple(dirs), source))
        )
        app.request_agents_refresh = (  # type: ignore[attr-defined]
            lambda source, *, latest_only: broad.append((source, latest_only))
        )
        return scheduled, broad

    def _pending_notification(
        self,
        *,
        action: str,
        planner_ts: str,
        gate_ts: str,
        root_ts: str,
        planner_dir: Path | None = None,
        request_id: str = "gate-1",
    ) -> Notification:
        action_data = {
            "request_id": request_id,
            "agent_cl_name": "0nn",
            "agent_timestamp": planner_ts,
            "agent_root_timestamp": root_ts,
            "raw_suffix": gate_ts,
            "family_root_suffix": root_ts,
        }
        if planner_dir is not None:
            action_data["artifacts_dir"] = str(planner_dir)
        return _make(
            action=action,
            notes=[f"{action} ready for @0nn"],
            action_data=action_data,
        )

    def test_plan_approval_poll_schedules_unloaded_family_chain_delta(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        planner_ts = "20260919072902"
        gate_ts = "20260919074517"
        root_ts = "20260919072902"
        planner_dir = _ace_run_dir(sase_home, planner_ts)
        gate_dir = _ace_run_dir(sase_home, gate_ts)
        app = _FakeApp()
        app.current_tab = "services"  # type: ignore[attr-defined]
        planner = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="0nn",
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2026, 9, 19, 7, 29, 2),
            raw_suffix=planner_ts,
            artifacts_dir=str(planner_dir),
            agent_family="0nn",
            agent_family_role="root",
            plan_chain_root=True,
        )
        app._agents_with_children = [planner]  # type: ignore[attr-defined]
        notification = self._pending_notification(
            action="PlanApproval",
            planner_ts=planner_ts,
            gate_ts=gate_ts,
            root_ts=root_ts,
            planner_dir=planner_dir,
        )
        scheduled, broad = self._install_capture(app)
        scan_threads = _record_scan_threads(monkeypatch)

        with _patch_snapshot([notification]):
            asyncio.run(app._run_scheduled_notification_poll(source="watcher"))

        assert app.notify.call_count == 1
        assert broad == []
        assert len(scheduled) == 1
        dirs, source = scheduled[0]
        assert source == "notification"
        assert set(dirs) == {planner_dir, gate_dir}
        # The unloaded gate dir is found by a disk scan; it must run on the
        # notification-poll worker, never on the event-loop thread.
        assert scan_threads
        assert threading.get_ident() not in scan_threads

    @pytest.mark.parametrize("action", ["EpicApproval", "UserQuestion"])
    def test_epic_and_question_share_predicate_and_targeting(
        self,
        action: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        planner_ts = "20260919100000"
        gate_ts = "20260919100010"
        planner_dir = _ace_run_dir(sase_home, planner_ts)
        gate_dir = _ace_run_dir(sase_home, gate_ts)
        app = _FakeApp()
        app._agents_with_children = []  # type: ignore[attr-defined]
        notification = self._pending_notification(
            action=action,
            planner_ts=planner_ts,
            gate_ts=gate_ts,
            root_ts=planner_ts,
            planner_dir=planner_dir,
        )
        assert is_active_agent_refresh_notification(notification)
        scheduled, broad = self._install_capture(app)

        with _patch_snapshot([notification]):
            asyncio.run(app._run_scheduled_notification_poll(source="watcher"))

        assert app.notify.call_count == 1
        assert broad == []
        assert len(scheduled) == 1
        dirs, source = scheduled[0]
        assert source == "notification"
        assert set(dirs) == {planner_dir, gate_dir}

    def test_legacy_plan_approval_resolves_via_indexed_shell_on_worker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        planner_ts = "20260919072902"
        planner_dir = _ace_run_dir(sase_home, planner_ts)
        gate_dir = tmp_path / "gate-member"
        gate_dir.mkdir()
        lookup_threads: list[int] = []

        def find_gate_shell(_project: object, gate_id: str) -> object | None:
            lookup_threads.append(threading.get_ident())
            if gate_id == "legacy-gate":
                return SimpleNamespace(artifacts_dir=str(gate_dir))
            return None

        monkeypatch.setattr(
            "sase.gate_shell.store.find_gate_shell_by_gate_id", find_gate_shell
        )
        app = _FakeApp()
        app.current_tab = "agents"  # type: ignore[attr-defined]
        notification = _make(
            action="PlanApproval",
            notes=["Tale ready for @0nn"],
            action_data={
                "request_id": "legacy-gate",
                "agent_cl_name": "0nn",
                "agent_timestamp": planner_ts,
                "agent_root_timestamp": planner_ts,
                "artifacts_dir": str(planner_dir),
            },
        )
        scheduled, broad = self._install_capture(app)

        with _patch_snapshot([notification]):
            asyncio.run(app._run_scheduled_notification_poll(source="watcher"))

        assert app.notify.call_count == 1
        assert broad == []
        assert len(scheduled) == 1
        dirs, source = scheduled[0]
        assert source == "notification"
        assert set(dirs) == {planner_dir, gate_dir}
        # The indexed lookup is worker-only: it ran, and not on the loop thread.
        assert lookup_threads
        assert threading.get_ident() not in lookup_threads

    def test_quiet_tick_does_not_reload_agents_for_pending_gate_predicate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Real, resolvable dirs and the Agents tab make a wrongly re-fired
        # refresh observable: it would schedule a delta (dirs resolve) or a
        # broad reload (tab allows it), so the empty captures below are not
        # vacuous.
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        planner_ts = "20260919072902"
        gate_ts = "20260919074517"
        planner_dir = _ace_run_dir(sase_home, planner_ts)
        _ace_run_dir(sase_home, gate_ts)
        app = _FakeApp()
        app.current_tab = "agents"  # type: ignore[attr-defined]
        existing = self._pending_notification(
            action="PlanApproval",
            planner_ts=planner_ts,
            gate_ts=gate_ts,
            root_ts=planner_ts,
            planner_dir=planner_dir,
            request_id="already-seen",
        )
        app._notification_snapshot_cache = _snapshot([existing])
        app._delivered_notification_activity_cursors.add(
            notification_activity_cursor(existing)
        )
        scheduled, broad = self._install_capture(app)
        scan_threads = _record_scan_threads(monkeypatch)

        with _patch_snapshot([existing]):
            asyncio.run(app._run_scheduled_notification_poll(source="watcher"))

        assert app.notify.call_count == 0
        assert scheduled == []
        assert broad == []
        assert scan_threads == []
