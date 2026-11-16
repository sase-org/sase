"""Hijack-decision storm hotfix: one worker, stable cache, no default executor."""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents._hijack_decision import (
    HijackDecisionView,
    cheap_hijack_ingress_available,
    hijack_ingress_available_for_footer,
)
from sase.ace.tui.actions.agents._hijack_decision_cache import (
    AgentHijackDecisionCacheMixin,
)
from sase.ace.tui.actions.agents._roster_generation import bump_roster_generation
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(*, status: str = "RUNNING", name: str = "sase-demo.1") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/project.sase",
        status=status,
        start_time=datetime(2026, 11, 3, 10, 0, 0),
        workspace_num=4,
        pid=421,
        raw_suffix="20261103100000",
        agent_name=name,
        artifacts_dir="/tmp/artifacts/20261103100000",
    )


def _view(agent: Agent, *, mode: str = "immediate") -> HijackDecisionView:
    return HijackDecisionView(
        identity=agent.identity,
        roster_generation=0,
        occupant_name=agent.agent_name,
        occupant_reason="test occupant",
        workspace_num=agent.workspace_num,
        decision={"mode": mode, "code": None, "redirect_op": None},
        computed_at=time.monotonic(),
    )


class _StormApp(AgentHijackDecisionCacheMixin):
    current_tab = "agents"
    screen_stack: list[object] = []

    def __init__(self, agent: Agent) -> None:
        self._selected = agent
        self.footer_refreshes = 0

    def _get_selected_agent(self) -> Agent:
        return self._selected

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refreshes += 1


def _fail_to_thread(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("asyncio.to_thread must not run hijack decisions")


@pytest.mark.asyncio
async def test_fifty_footer_refreshes_leave_one_compute_and_one_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent()
    app = _StormApp(agent)
    in_flight = 0
    max_in_flight = 0
    started = 0

    def slow_compute(_agent: Agent, _deps: Any = None) -> HijackDecisionView:
        nonlocal in_flight, max_in_flight, started
        started += 1
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)  # sase-test-wait: fake slow worker so latest-wins queue forms
        in_flight -= 1
        return _view(_agent)

    app._hijack_decision_compute = slow_compute  # type: ignore[attr-defined]
    monkeypatch.setattr(asyncio, "to_thread", _fail_to_thread)
    loop = asyncio.get_running_loop()
    real_run_in_executor = loop.run_in_executor

    def guarded_run_in_executor(executor: Any, func: Any, *args: Any) -> Any:
        if executor is None:
            raise AssertionError("default executor must not run hijack decisions")
        return real_run_in_executor(executor, func, *args)

    monkeypatch.setattr(loop, "run_in_executor", guarded_run_in_executor)

    for index in range(50):
        agent.pid = 1000 + index
        bump_roster_generation(app)
        app._schedule_hijack_decision(agent)

    assert getattr(app, "_hijack_decision_busy", False) is True
    waiting = getattr(app, "_hijack_decision_waiting_passive", None)
    assert waiting is not None
    inflight = getattr(app, "_hijack_decision_inflight", {})
    assert len(inflight) == 1

    await asyncio.sleep(  # sase-test-wait: drain dedicated worker after 50 refreshes
        0.25
    )

    assert max_in_flight == 1
    assert started <= 2
    assert getattr(app, "_hijack_decision_waiting_passive", None) is None


@pytest.mark.asyncio
async def test_generation_bump_with_unchanged_fingerprint_hits_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent()
    app = _StormApp(agent)
    computes: list[int] = []

    def compute(_agent: Agent, _deps: Any = None) -> HijackDecisionView:
        computes.append(1)
        return _view(_agent)

    app._hijack_decision_compute = compute  # type: ignore[attr-defined]
    monkeypatch.setattr(asyncio, "to_thread", _fail_to_thread)
    app._store_hijack_decision(agent, _view(agent))
    bump_roster_generation(app)
    app._schedule_hijack_decision(agent)
    await asyncio.sleep(0)
    assert computes == []
    cached = app._cached_hijack_decision(agent)
    assert cached is not None
    assert cached.mode == "immediate"


@pytest.mark.asyncio
async def test_late_result_refreshes_footer_after_generation_bump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent()
    app = _StormApp(agent)
    started = threading.Event()
    release = threading.Event()

    def slow_compute(_agent: Agent, _deps: Any = None) -> HijackDecisionView:
        started.set()
        release.wait()
        return _view(_agent)

    app._hijack_decision_compute = slow_compute  # type: ignore[attr-defined]
    monkeypatch.setattr(asyncio, "to_thread", _fail_to_thread)
    app._schedule_hijack_decision(agent)
    for _ in range(50):
        if started.is_set():
            break
        await asyncio.sleep(0.01)  # sase-test-wait: poll until dedicated worker starts
    assert started.is_set()
    bump_roster_generation(app)
    release.set()
    for _ in range(50):
        if app.footer_refreshes:
            break
        await asyncio.sleep(  # sase-test-wait: poll until late result refreshes footer
            0.01
        )
    assert app.footer_refreshes >= 1
    assert app._cached_hijack_decision(agent) is not None


def test_teardown_cancels_the_dedicated_worker() -> None:
    agent = _agent()
    app = _StormApp(agent)
    pool = app._hijack_decision_executor()
    assert isinstance(pool, ThreadPoolExecutor)
    app._shutdown_hijack_decision_executor()
    with pytest.raises(RuntimeError, match="cannot schedule new futures"):
        pool.submit(lambda: None)


def test_footer_helper_does_not_schedule_a_compute() -> None:
    agent = _agent()
    app = _StormApp(agent)

    def boom(_agent: Agent | None = None, then: Any = None) -> None:
        del _agent, then
        raise AssertionError("footer helper must not schedule")

    app._schedule_hijack_decision = boom  # type: ignore[method-assign]
    assert hijack_ingress_available_for_footer(app, agent) is True


def test_passive_schedule_skips_named_proc_rows() -> None:
    agent = _agent()
    agent.agent_type = AgentType.NAMED_PROC
    app = _StormApp(agent)
    scheduled: list[int] = []

    def compute(_agent: Agent, _deps: Any = None) -> HijackDecisionView:
        scheduled.append(1)
        return _view(_agent)

    app._hijack_decision_compute = compute  # type: ignore[attr-defined]
    assert cheap_hijack_ingress_available(agent) is False
    app._schedule_hijack_decision(agent)
    assert scheduled == []
    assert getattr(app, "_hijack_decision_busy", False) is False
