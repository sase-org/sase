"""Same-tick unread marker for completed agents."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._notification_completion_arrival import (
    CompletionArrivalPrep,
    install_completion_arrival_overlays,
    prepare_completion_arrival_overlays,
    reconcile_arrival_status_overlays,
)
from sase.ace.tui.models import agent_loader
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import notification_activity_cursor

from tests._notification_toasts_helpers import (
    _FakeApp,
    _make,
    _patch_snapshot,
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
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(payload), encoding="utf-8")


def _standalone_agent(
    *,
    cl_name: str = "demo",
    raw_suffix: str,
    artifacts_dir: Path,
    status: str = "RUNNING",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 9, 24, 12, 0, 0),
        raw_suffix=raw_suffix,
        artifacts_dir=str(artifacts_dir),
    )


def _completion_notification(
    *, cl_name: str, raw_suffix: str | None, action: str = "JumpToAgent"
) -> Any:
    action_data: dict[str, str] = {"cl_name": cl_name}
    if raw_suffix is not None:
        action_data["raw_suffix"] = raw_suffix
    return _make(
        action=action,
        notes=["done"],
        action_data=action_data,
        sender="user-agent",
    )


def _install_captures(app: _FakeApp) -> list[tuple[tuple[Path, ...], str]]:
    scheduled: list[tuple[tuple[Path, ...], str]] = []
    app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
        lambda dirs, *, source: scheduled.append((tuple(dirs), source))
    )
    app.current_tab = "agents"  # type: ignore[attr-defined]
    app._agents_loading = False  # type: ignore[attr-defined]
    app._agents_arrival_status_overlays = {}  # type: ignore[attr-defined]
    app._unread_completed_agent_ids = set()  # type: ignore[attr-defined]
    app._manual_unread_agent_ids = set()  # type: ignore[attr-defined]
    return scheduled


def _family_dirs(sase_home: Path, root_ts: str, code_ts: str) -> tuple[Path, Path]:
    root_dir = _ace_run_dir(sase_home, root_ts)
    code_dir = _ace_run_dir(sase_home, code_ts)
    _write_json(
        root_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "context": {"cl_name": "demo"},
            "status": "running",
            "appears_as_agent": True,
            "start_time": "2026-09-24T12:00:00",
            "steps": [],
        },
    )
    _write_json(
        root_dir / "agent_meta.json",
        {
            "name": "demo",
            "cl_name": "demo",
            "agent_session": "fam1",
            "agent_session_role": "root",
            "plan_chain_root": True,
            "role_suffix": "--plan",
            "plan": True,
            "plan_approved": True,
            "plan_action": "tale",
            "run_started_at": "2026-09-24T12:00:00Z",
        },
    )
    _write_json(
        code_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "context": {"cl_name": "demo"},
            "status": "running",
            "appears_as_agent": True,
            "start_time": "2026-09-24T12:00:10",
            "steps": [],
        },
    )
    _write_json(
        code_dir / "agent_meta.json",
        {
            "name": "demo",
            "cl_name": "demo",
            "agent_session": "fam1",
            "agent_session_role": "code",
            "role_suffix": "--code",
            "parent_timestamp": root_ts,
            "run_started_at": "2026-09-24T12:00:10Z",
        },
    )
    return root_dir, code_dir


def _family_agents(
    root_dir: Path, code_dir: Path, root_ts: str, code_ts: str
) -> tuple[Agent, Agent]:
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="demo",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 9, 24, 12, 0, 0),
        raw_suffix=root_ts,
        role_suffix="--plan",
        agent_name="demo",
        agent_session="fam1",
        agent_session_role="root",
        plan_chain_root=True,
        plan_action="tale",
        artifacts_dir=str(root_dir),
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 9, 24, 12, 0, 10),
        raw_suffix=code_ts,
        role_suffix="--code",
        agent_name="demo--code",
        agent_session="fam1",
        agent_session_role="code",
        parent_timestamp=root_ts,
        artifacts_dir=str(code_dir),
    )
    return root, coder


class TestCompletionArrivalPoll:
    def test_standalone_done_overlays_same_tick(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        ts = "20260924120000"
        adir = _ace_run_dir(sase_home, ts)
        agent = _standalone_agent(raw_suffix=ts, artifacts_dir=adir)
        app = _FakeApp()
        app._agents = [agent]  # type: ignore[attr-defined]
        app._agents_with_children = [agent]  # type: ignore[attr-defined]
        scheduled = _install_captures(app)
        notification = _completion_notification(cl_name="demo", raw_suffix=ts)
        _write_json(
            adir / "done.json",
            {"outcome": "completed", "cl_name": "demo", "name": "demo"},
        )
        with _patch_snapshot([notification]):
            saw_new = asyncio.run(app._poll_agent_completions_once())
        assert saw_new is True
        assert agent.status == "DONE"
        assert agent.identity in app._unread_completed_agent_ids
        assert len(scheduled) == 1
        dirs, source = scheduled[0]
        assert source == "notification"
        assert set(dirs) == {adir}

    def test_view_error_report_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        ts = "20260924121000"
        adir = _ace_run_dir(sase_home, ts)
        agent = _standalone_agent(raw_suffix=ts, artifacts_dir=adir)
        app = _FakeApp()
        app._agents = [agent]  # type: ignore[attr-defined]
        app._agents_with_children = [agent]  # type: ignore[attr-defined]
        _install_captures(app)
        notification = _completion_notification(
            cl_name="demo", raw_suffix=ts, action="ViewErrorReport"
        )
        _write_json(
            adir / "done.json",
            {"outcome": "failed", "cl_name": "demo", "name": "demo"},
        )
        with _patch_snapshot([notification]):
            asyncio.run(app._poll_agent_completions_once())
        assert agent.status == "FAILED"
        assert agent.identity in app._unread_completed_agent_ids

    def test_family_coder_finish_mirrors_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        root_ts = "20260924120000"
        code_ts = "20260924120010"
        root_dir, code_dir = _family_dirs(sase_home, root_ts, code_ts)
        root, coder = _family_agents(root_dir, code_dir, root_ts, code_ts)
        from sase.ace.tui.models.agent_nodes import agent_node_projection_index

        index = agent_node_projection_index([root, coder])
        projection = index.owner_for_identity(coder.identity)
        assert projection is not None
        assert projection.node.identity == root.identity
        app = _FakeApp()
        app._agents = [root, coder]  # type: ignore[attr-defined]
        app._agents_with_children = [root, coder]  # type: ignore[attr-defined]
        scheduled = _install_captures(app)
        notification = _completion_notification(cl_name="demo", raw_suffix=code_ts)
        _write_json(
            code_dir / "done.json",
            {"outcome": "completed", "cl_name": "demo", "name": "demo"},
        )
        with _patch_snapshot([notification]):
            asyncio.run(app._poll_agent_completions_once())
        # The loader mirrors TALE DONE onto the family root.
        assert root.status == "TALE DONE"
        assert root.identity in app._unread_completed_agent_ids
        assert len(scheduled) == 1
        dirs, _source = scheduled[0]
        assert set(dirs) == {root_dir, code_dir}

    def test_family_with_other_member_in_flight_no_overlay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        root_ts = "20260924120000"
        code_ts = "20260924120010"
        other_ts = "20260924120020"
        root_dir, code_dir = _family_dirs(sase_home, root_ts, code_ts)
        other_dir = _ace_run_dir(sase_home, other_ts)
        _write_json(
            other_dir / "workflow_state.json",
            {
                "workflow_name": "ace-run",
                "context": {"cl_name": "demo"},
                "status": "running",
                "appears_as_agent": True,
                "start_time": "2026-09-24T12:00:20",
                "steps": [],
            },
        )
        _write_json(
            other_dir / "agent_meta.json",
            {
                "name": "demo",
                "cl_name": "demo",
                "agent_session": "fam1",
                "agent_session_role": "code",
                "role_suffix": "--code",
                "parent_timestamp": root_ts,
                "run_started_at": "2026-09-24T12:00:20Z",
            },
        )
        root, coder = _family_agents(root_dir, code_dir, root_ts, code_ts)
        other = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="demo",
            project_file="/tmp/test.sase",
            status="RUNNING",
            start_time=datetime(2026, 9, 24, 12, 0, 20),
            raw_suffix=other_ts,
            role_suffix="--code",
            agent_name="demo--code2",
            agent_session="fam1",
            agent_session_role="code",
            parent_timestamp=root_ts,
            artifacts_dir=str(other_dir),
        )
        app = _FakeApp()
        app._agents = [root, coder, other]  # type: ignore[attr-defined]
        app._agents_with_children = [root, coder, other]  # type: ignore[attr-defined]
        scheduled = _install_captures(app)
        notification = _completion_notification(cl_name="demo", raw_suffix=code_ts)
        _write_json(
            code_dir / "done.json",
            {"outcome": "completed", "cl_name": "demo", "name": "demo"},
        )
        with _patch_snapshot([notification]):
            asyncio.run(app._poll_agent_completions_once())
        # Another member still runs, so the root stays in flight: no overlay.
        assert root.status == "RUNNING"
        assert app._unread_completed_agent_ids == set()
        # The authoritative delta is still scheduled.
        assert len(scheduled) == 1

    def test_inflight_then_done_heals_on_later_poll(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        ts = "20260924120000"
        adir = _ace_run_dir(sase_home, ts)
        agent = _standalone_agent(raw_suffix=ts, artifacts_dir=adir)
        app = _FakeApp()
        app._agents = [agent]  # type: ignore[attr-defined]
        app._agents_with_children = [agent]  # type: ignore[attr-defined]
        scheduled = _install_captures(app)
        notification = _completion_notification(cl_name="demo", raw_suffix=ts)
        with _patch_snapshot([notification]):
            asyncio.run(app._poll_agent_completions_once())
        assert agent.status == "RUNNING"
        assert app._unread_completed_agent_ids == set()
        assert scheduled == []
        _write_json(
            adir / "done.json",
            {"outcome": "completed", "cl_name": "demo", "name": "demo"},
        )
        with _patch_snapshot([notification]):
            # Second poll sees the same notification as new (fresh cursors).
            app._delivered_notification_activity_cursors.clear()
            asyncio.run(app._poll_agent_completions_once())
        assert agent.status == "DONE"
        assert agent.identity in app._unread_completed_agent_ids
        assert len(scheduled) == 1

    def test_cl_name_only_and_terminal_skip_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        ts = "20260924120000"
        adir = _ace_run_dir(sase_home, ts)
        agent = _standalone_agent(raw_suffix=ts, artifacts_dir=adir, status="RUNNING")
        app = _FakeApp()
        app._agents = [agent]  # type: ignore[attr-defined]
        app._agents_with_children = [agent]  # type: ignore[attr-defined]
        _install_captures(app)
        calls: list[list[Path]] = []
        real_loader = agent_loader.load_artifact_delta_agents

        def recording_loader(dirs: Any, **kwargs: Any) -> tuple[list[Any], Any]:
            calls.append(list(dirs))
            return real_loader(dirs, **kwargs)

        monkeypatch.setattr(
            agent_loader, "load_artifact_delta_agents", recording_loader
        )
        cl_only = _completion_notification(cl_name="demo", raw_suffix=None)
        with _patch_snapshot([cl_only]):
            asyncio.run(app._poll_agent_completions_once())
        assert calls == []
        assert agent.status == "RUNNING"

        done_agent = _standalone_agent(raw_suffix=ts, artifacts_dir=adir, status="DONE")
        app2 = _FakeApp()
        app2._agents = [done_agent]  # type: ignore[attr-defined]
        app2._agents_with_children = [done_agent]  # type: ignore[attr-defined]
        app2.current_tab = "agents"  # type: ignore[attr-defined]
        app2._agents_loading = False  # type: ignore[attr-defined]
        app2._agents_arrival_status_overlays = {}  # type: ignore[attr-defined]
        app2._unread_completed_agent_ids = set()  # type: ignore[attr-defined]
        app2._manual_unread_agent_ids = set()  # type: ignore[attr-defined]
        app2._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: None
        )
        notification = _completion_notification(cl_name="demo", raw_suffix=ts)
        _write_json(
            adir / "done.json",
            {"outcome": "completed", "cl_name": "demo", "name": "demo"},
        )
        calls.clear()
        with _patch_snapshot([notification]):
            asyncio.run(app2._poll_agent_completions_once())
        assert calls == []
        assert done_agent.status == "DONE"

    def test_probe_runs_on_worker_thread(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sase_home = tmp_path / ".sase"
        monkeypatch.setenv("SASE_HOME", str(sase_home))
        ts = "20260924120000"
        adir = _ace_run_dir(sase_home, ts)
        agent = _standalone_agent(raw_suffix=ts, artifacts_dir=adir)
        app = _FakeApp()
        app._agents = [agent]  # type: ignore[attr-defined]
        app._agents_with_children = [agent]  # type: ignore[attr-defined]
        _install_captures(app)
        notification = _completion_notification(cl_name="demo", raw_suffix=ts)
        _write_json(
            adir / "done.json",
            {"outcome": "completed", "cl_name": "demo", "name": "demo"},
        )
        loop_ident = threading.get_ident()
        scan_threads: list[int] = []
        real_loader = agent_loader.load_artifact_delta_agents

        def recording_loader(dirs: Any, **kwargs: Any) -> tuple[list[Any], Any]:
            scan_threads.append(threading.get_ident())
            return real_loader(dirs, **kwargs)

        monkeypatch.setattr(
            agent_loader, "load_artifact_delta_agents", recording_loader
        )
        with _patch_snapshot([notification]):
            asyncio.run(app._poll_agent_completions_once())
        assert scan_threads
        assert loop_ident not in scan_threads
        assert agent.status == "DONE"


class TestArrivalPrepUnit:
    def test_muted_arrival_still_overlays(self, tmp_path: Path) -> None:
        sase_home = tmp_path / ".sase"
        sase_home.mkdir(parents=True, exist_ok=True)
        ts = "20260924120000"
        adir = _ace_run_dir(sase_home, ts)
        agent = _standalone_agent(raw_suffix=ts, artifacts_dir=adir)
        app = SimpleNamespace(
            _agents=[agent],
            _agents_with_children=[agent],
        )
        _write_json(
            adir / "done.json",
            {"outcome": "completed", "cl_name": "demo", "name": "demo"},
        )
        import os

        old = os.environ.get("SASE_HOME")
        os.environ["SASE_HOME"] = str(sase_home)
        try:
            notification = _make(
                action="JumpToAgent",
                notes=["done"],
                action_data={"cl_name": "demo", "raw_suffix": ts},
                sender="user-agent",
                muted=True,
            )
            prep = prepare_completion_arrival_overlays(app, [notification])
        finally:
            if old is None:
                del os.environ["SASE_HOME"]
            else:
                os.environ["SASE_HOME"] = old
        assert isinstance(prep, CompletionArrivalPrep)
        assert (agent.identity, "DONE") in prep.overlays

    def test_install_and_reconcile_lifetime(self) -> None:
        ts = "20260924120000"
        agent = _standalone_agent(
            raw_suffix=ts, artifacts_dir=Path("/tmp/adir"), status="RUNNING"
        )
        app = SimpleNamespace(
            _agents=[agent],
            _agents_with_children=[agent],
            _agents_loading=True,
            _agents_arrival_status_overlays={},
        )
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: None
        )
        prep = CompletionArrivalPrep(
            overlays=((agent.identity, "DONE"),),
            artifact_dirs=(Path("/tmp/adir"),),
        )
        changed = install_completion_arrival_overlays(app, prep)
        assert changed == {agent.identity}
        assert agent.status == "DONE"
        assert (
            app._agents_arrival_status_overlays[agent.identity].survives_stale_apply
            is True
        )

        # Stale load applies fresh RUNNING objects: overlay re-applies once.
        fresh = _standalone_agent(
            raw_suffix=ts, artifacts_dir=Path("/tmp/adir"), status="RUNNING"
        )
        app._agents = [fresh]
        app._agents_with_children = [fresh]
        reconcile_arrival_status_overlays(app)
        assert fresh.status == "DONE"
        assert (
            app._agents_arrival_status_overlays[agent.identity].survives_stale_apply
            is False
        )

        # Next load is authoritative: a new RUNNING family drops the overlay.
        newer = _standalone_agent(
            raw_suffix=ts, artifacts_dir=Path("/tmp/adir"), status="RUNNING"
        )
        app._agents = [newer]
        app._agents_with_children = [newer]
        reconcile_arrival_status_overlays(app)
        assert newer.status == "RUNNING"
        assert agent.identity not in app._agents_arrival_status_overlays

    def test_install_without_inflight_drops_on_next_load(self) -> None:
        ts = "20260924120000"
        agent = _standalone_agent(
            raw_suffix=ts, artifacts_dir=Path("/tmp/adir"), status="RUNNING"
        )
        app = SimpleNamespace(
            _agents=[agent],
            _agents_with_children=[agent],
            _agents_loading=False,
            _agents_arrival_status_overlays={},
        )
        app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
            lambda dirs, *, source: None
        )
        prep = CompletionArrivalPrep(
            overlays=((agent.identity, "DONE"),),
            artifact_dirs=(Path("/tmp/adir"),),
        )
        install_completion_arrival_overlays(app, prep)
        assert agent.status == "DONE"
        loaded = _standalone_agent(
            raw_suffix=ts, artifacts_dir=Path("/tmp/adir"), status="RUNNING"
        )
        app._agents = [loaded]
        app._agents_with_children = [loaded]
        reconcile_arrival_status_overlays(app)
        assert loaded.status == "RUNNING"
        assert app._agents_arrival_status_overlays == {}


class TestPatchStatusChanged:
    def test_status_changed_member_patches_without_unread_change(self) -> None:
        from sase.ace.tui.actions.agents._core import AgentsMixinCore
        from tests.ace.tui._agent_unread_helpers import make_agent

        class _App(AgentsMixinCore):
            def __init__(self, agents: list[Agent]) -> None:
                self._agents = agents
                self._agents_with_children = agents
                self.current_idx = 0
                self.current_tab = "agents"
                self._current_group_key = None
                self._unread_completed_agent_ids = set()
                self._manual_unread_agent_ids = set()
                self._pending_bulk_read_agent_ids = None
                self._agent_info_metrics_cache = None
                self._notification_snapshot_cache = None
                self.patch_calls: list[Agent] = []
                self.refresh_calls: list[dict[str, object]] = []

            def _try_patch_agent_row(self, agent: Agent) -> bool:
                self.patch_calls.append(agent)
                return True

            def _refresh_agents_display(self, **kwargs: object) -> None:
                self.refresh_calls.append(kwargs)

        member = make_agent(status="DONE", raw_suffix="m1")
        app = _App([member])
        before: set[Any] = set()
        ok = app._patch_unread_completed_agent_changes(
            before, status_changed={member.identity}
        )
        assert ok is True
        assert app.patch_calls == [member]
        assert app.refresh_calls == []

    def test_membership_change_falls_back_to_rebuild(self) -> None:
        from sase.ace.tui.actions.agents._core import AgentsMixinCore
        from tests.ace.tui._agent_unread_helpers import make_agent

        class _App(AgentsMixinCore):
            def __init__(self, agents: list[Agent]) -> None:
                self._agents = agents
                self._agents_with_children = agents
                self.current_idx = 0
                self.current_tab = "agents"
                self._current_group_key = None
                self._unread_completed_agent_ids = set()
                self._manual_unread_agent_ids = set()
                self._pending_bulk_read_agent_ids = None
                self._agent_info_metrics_cache = None
                self._notification_snapshot_cache = None
                self.patch_calls: list[Agent] = []

            def _try_patch_agent_row(self, agent: Agent) -> bool:
                self.patch_calls.append(agent)
                return False

            def _refresh_agents_display(self, **kwargs: object) -> None:
                self.refresh_calls = [kwargs]  # type: ignore[attr-defined]

        member = make_agent(status="DONE", raw_suffix="m1")
        app = _App([member])
        app.refresh_calls = []  # type: ignore[attr-defined]
        ok = app._patch_unread_completed_agent_changes(
            set(), status_changed={member.identity}
        )
        assert ok is False
        assert app.refresh_calls


def test_completion_probe_uses_readonly_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe passes patch_snapshot=[] and update_index=False."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    ts = "20260924120000"
    adir = _ace_run_dir(sase_home, ts)
    agent = _standalone_agent(raw_suffix=ts, artifacts_dir=adir)
    app = SimpleNamespace(_agents=[agent], _agents_with_children=[agent])
    _write_json(
        adir / "done.json",
        {"outcome": "completed", "cl_name": "demo", "name": "demo"},
    )
    seen: dict[str, Any] = {}
    real_loader = agent_loader.load_artifact_delta_agents

    def recording_loader(dirs: Any, **kwargs: Any) -> tuple[list[Any], Any]:
        seen.update(kwargs)
        return real_loader(dirs, **kwargs)

    monkeypatch.setattr(agent_loader, "load_artifact_delta_agents", recording_loader)
    notification = _completion_notification(cl_name="demo", raw_suffix=ts)
    prepare_completion_arrival_overlays(app, [notification])
    assert seen.get("update_index") is False
    assert seen.get("patch_snapshot") == []


def test_activity_cursor_marks_delivered_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity: the poll still marks the arrival delivered exactly once."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    ts = "20260924120000"
    adir = _ace_run_dir(sase_home, ts)
    agent = _standalone_agent(raw_suffix=ts, artifacts_dir=adir)
    app = _FakeApp()
    app._agents = [agent]  # type: ignore[attr-defined]
    app._agents_with_children = [agent]  # type: ignore[attr-defined]
    _install_captures(app)
    notification = _completion_notification(cl_name="demo", raw_suffix=ts)
    cursor = notification_activity_cursor(notification)
    _write_json(
        adir / "done.json",
        {"outcome": "completed", "cl_name": "demo", "name": "demo"},
    )
    with _patch_snapshot([notification]):
        asyncio.run(app._poll_agent_completions_once())
    assert cursor in app._delivered_notification_activity_cursors
