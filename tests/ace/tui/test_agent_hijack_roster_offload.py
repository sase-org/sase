"""Hijack roster path canonicalization stays off the UI thread (sase-1tz.2.1.11).

``_schedule_hijack_decision`` runs on footer refresh and leader mode. It
builds row-local StopDeps on the UI thread, so that build must copy row
fields only; resolving artifacts dirs belongs to the dedicated hijack worker.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.actions.agents._hijack_decision import HijackDecisionView
from sase.ace.tui.actions.agents._hijack_decision_cache import (
    AgentHijackDecisionCacheMixin,
)
from sase.ace.tui.actions.agents._hijack_roster_snapshot import hijack_row_local_deps
from sase.ace.tui.models.agent import Agent, AgentType
from tests._main_thread_fs_guard import main_thread_fs_guard


def _agent(artifacts_dir: Path, *, name: str, role: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/project.sase",
        status="RUNNING",
        start_time=datetime(2026, 11, 19, 10, 0, 0),
        workspace_num=4,
        pid=421,
        raw_suffix=artifacts_dir.name,
        agent_name=name,
        artifacts_dir=str(artifacts_dir),
        agent_session="sess",
        agent_session_role=role,
    )


class _RosterApp(AgentHijackDecisionCacheMixin):
    current_tab = "agents"
    screen_stack: list[object] = []

    def __init__(self, roster: list[Agent]) -> None:
        self._agents = roster
        self._selected = roster[0]

    def _get_selected_agent(self) -> Agent:
        return self._selected

    def _refresh_agent_footer_bindings_only(self) -> None:
        return None


def _roster(tmp_path: Path) -> list[Agent]:
    dirs = []
    for stamp in ("20261119100000", "20261119100100", "20261119100200"):
        path = tmp_path / "artifacts" / stamp
        path.mkdir(parents=True)
        dirs.append(path)
    return [
        _agent(dirs[0], name="sess", role="root"),
        _agent(dirs[1], name="sess.2", role=None),
        _agent(dirs[2], name="sess.3", role=None),
    ]


async def test_row_local_deps_build_resolves_no_paths_on_the_ui_thread(
    tmp_path: Path,
) -> None:
    roster = _roster(tmp_path)
    app = _RosterApp(roster)

    with main_thread_fs_guard() as violations:
        deps = hijack_row_local_deps(app, roster[1])
    assert violations == []

    # The deferred index still answers correctly once a worker asks.
    member_dir = Path(str(roster[2].artifacts_dir))
    finder = deps.find_session_by_member_artifact_dir
    assert finder is not None
    found = await asyncio.to_thread(finder, member_dir)
    assert found is not None
    session, member = found
    assert session.base_name == "sess"
    assert member.name == "sess.3"
    assert len(session.members) == 3


async def test_scheduled_decision_canonicalizes_paths_on_the_hijack_worker(
    tmp_path: Path,
) -> None:
    roster = _roster(tmp_path)
    app = _RosterApp(roster)
    compute_threads: list[int] = []
    lookups: list[object] = []

    def compute(agent: Agent, deps: Any = None) -> HijackDecisionView:
        compute_threads.append(threading.get_ident())
        assert deps is not None
        finder = deps.find_session_by_member_artifact_dir
        lookups.append(finder(agent.artifacts_dir))
        return HijackDecisionView(
            identity=agent.identity,
            roster_generation=0,
            occupant_name=agent.agent_name,
            occupant_reason="test occupant",
            workspace_num=agent.workspace_num,
            decision={"mode": "immediate", "code": None, "redirect_op": None},
            computed_at=time.monotonic(),
        )

    app._hijack_decision_compute = compute  # type: ignore[attr-defined]
    try:
        with main_thread_fs_guard() as violations:
            app._schedule_hijack_decision(roster[1])
            registry: set[asyncio.Task[Any]] = getattr(
                app, "_hijack_decision_tasks", set()
            )
            tasks = tuple(registry)
            assert tasks, "the decision must run on the pump-free worker task"
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=10.0)
    finally:
        app._shutdown_hijack_decision_executor()

    assert violations == []
    assert compute_threads and threading.get_ident() not in compute_threads
    assert lookups[0] is not None
