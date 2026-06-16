"""Tests for the deferred, coalesced live-workspace pencil-hint refresh.

The expensive per-agent live VCS probe is computed off the startup-critical
loader path by ``AgentLiveHintMixin``: a coalesced background worker scans the
active, non-terminal rows that lack a persisted ``diff_path`` after the first
agents load applies, then patches changed rows in place by identity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _loading_live_hints as live_hints_mod
from sase.ace.tui.actions.agents._loading_live_hints import (
    AgentLiveHintMixin,
    _compute_live_hints,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.nav_gate import NavigationGate


class _FakeApp(AgentLiveHintMixin):
    def __init__(self) -> None:
        self._agents_first_load_done = True
        self._live_hints_scan_scheduled = False
        self._live_hints_scan_running = False
        self._live_hints_scan_pending = False
        self._live_hints_scan_source = "unknown"
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._nav_gate = NavigationGate(window_s=0.25)
        self._scheduled: list[Any] = []
        self._timer_calls: list[tuple[float, Any]] = []
        self._patched: list[Agent] = []

    def call_later(self, callback: Any) -> None:
        self._scheduled.append(callback)

    def set_timer(self, delay: float, callback: Any) -> None:
        self._timer_calls.append((delay, callback))

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self._patched.append(agent)
        return True


def _agent(
    *,
    cl_name: str = "feat",
    raw_suffix: str = "20260615190000",
    status: str = "RUNNING",
    diff_path: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix=raw_suffix,
        diff_path=diff_path,
    )


# --- scheduling / coalescing -------------------------------------------------


def test_schedule_noop_before_first_load() -> None:
    app = _FakeApp()
    app._agents_first_load_done = False

    app._schedule_live_hint_refresh(source="apply")

    assert app._scheduled == []
    assert app._live_hints_scan_scheduled is False


def test_schedule_queues_worker_after_first_load() -> None:
    app = _FakeApp()

    app._schedule_live_hint_refresh(source="apply")

    assert app._live_hints_scan_scheduled is True
    assert app._live_hints_scan_source == "apply"
    assert app._scheduled == [app._run_live_hint_refresh]


def test_schedule_collapses_to_one_queued_worker() -> None:
    app = _FakeApp()

    app._schedule_live_hint_refresh(source="apply")
    app._schedule_live_hint_refresh(source="auto_refresh")

    # Second request while one is already queued must not enqueue again.
    assert len(app._scheduled) == 1


def test_schedule_marks_pending_while_running() -> None:
    app = _FakeApp()
    app._live_hints_scan_running = True

    app._schedule_live_hint_refresh(source="artifact_watcher")

    assert app._live_hints_scan_pending is True
    assert app._scheduled == []


# --- candidate scope ---------------------------------------------------------


def test_live_hint_candidates_scope() -> None:
    app = _FakeApp()
    running = _agent(cl_name="running", raw_suffix="1")
    starting = _agent(cl_name="starting", raw_suffix="2", status="STARTING")
    done = _agent(cl_name="done", raw_suffix="3", status="DONE")
    failed = _agent(cl_name="failed", raw_suffix="4", status="FAILED")
    failed_retried = _agent(
        cl_name="failed-retried",
        raw_suffix="5",
        status="FAILED (RETRIED)",
    )
    plan_done = _agent(cl_name="plan-done", raw_suffix="6", status="PLAN DONE")
    stopped = _agent(cl_name="stopped", raw_suffix="7", status="STOPPED")
    with_diff = _agent(cl_name="withdiff", raw_suffix="8", diff_path="/tmp/x.diff")
    app._agents = [
        running,
        starting,
        done,
        failed,
        failed_retried,
        plan_done,
        stopped,
        with_diff,
    ]

    candidates = app._live_hint_candidates()

    assert candidates == [running, starting]


# --- compute (off-thread body) -----------------------------------------------


def test_compute_live_hints_keys_by_identity(monkeypatch: Any) -> None:
    a = _agent(cl_name="a", raw_suffix="1")
    b = _agent(cl_name="b", raw_suffix="2")
    results_by_cl = {"a": True, "b": False}

    monkeypatch.setattr(
        live_hints_mod,
        "classify_live_file_change_hint",
        lambda agent: results_by_cl[agent.cl_name],
    )

    results = _compute_live_hints([a, b])

    assert results == {a.identity: True, b.identity: False}


# --- apply by identity -------------------------------------------------------


def test_apply_patches_only_changed_rows() -> None:
    app = _FakeApp()
    changed = _agent(cl_name="changed", raw_suffix="1")
    same = _agent(cl_name="same", raw_suffix="2")
    same.live_file_change_hint = False
    app._agents = [changed, same]
    app._agents_with_children = [changed, same]

    app._apply_live_hint_results({changed.identity: True, same.identity: False})

    assert changed.live_file_change_hint is True
    assert app._patched == [changed]  # unchanged row not repainted


def test_apply_rematches_current_object_by_identity() -> None:
    """A refresh may rebuild the list; the hint lands on the live object."""
    app = _FakeApp()
    snapshot = _agent(cl_name="feat", raw_suffix="1")
    # Simulate an interleaved refresh that replaced the agent object with a
    # fresh instance sharing the same identity.
    rebuilt = _agent(cl_name="feat", raw_suffix="1")
    app._agents = [rebuilt]
    app._agents_with_children = [rebuilt]

    app._apply_live_hint_results({snapshot.identity: True})

    assert rebuilt.live_file_change_hint is True
    assert snapshot.live_file_change_hint is None
    assert app._patched == [rebuilt]


# --- full async worker -------------------------------------------------------


@pytest.mark.asyncio
async def test_run_defers_behind_navigation_gate() -> None:
    app = _FakeApp()
    app._agents = [_agent()]
    app._nav_gate.record()  # user is mid j/k burst

    await app._run_live_hint_refresh()

    # Deferred via set_timer; no compute/apply happened this pass.
    assert len(app._timer_calls) == 1
    assert app._patched == []
    # Coalescing state stays armed so the retry isn't dropped.
    assert app._live_hints_scan_scheduled is False


@pytest.mark.asyncio
async def test_run_computes_applies_and_clears_running(monkeypatch: Any) -> None:
    app = _FakeApp()
    agent = _agent(cl_name="feat", raw_suffix="1")
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._live_hints_scan_scheduled = True

    monkeypatch.setattr(
        live_hints_mod,
        "classify_live_file_change_hint",
        lambda a: True,
    )

    await app._run_live_hint_refresh()

    assert agent.live_file_change_hint is True
    assert app._patched == [agent]
    assert app._live_hints_scan_scheduled is False
    assert app._live_hints_scan_running is False


@pytest.mark.asyncio
async def test_run_rearms_when_pending(monkeypatch: Any) -> None:
    app = _FakeApp()
    agent = _agent()
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._live_hints_scan_pending = True

    monkeypatch.setattr(
        live_hints_mod,
        "classify_live_file_change_hint",
        lambda a: False,
    )

    await app._run_live_hint_refresh()

    # Trailing request consumed and a fresh worker queued.
    assert app._live_hints_scan_pending is False
    assert app._scheduled == [app._run_live_hint_refresh]


@pytest.mark.asyncio
async def test_run_noop_without_candidates() -> None:
    app = _FakeApp()
    app._agents = [_agent(status="DONE")]
    app._live_hints_scan_scheduled = True

    await app._run_live_hint_refresh()

    assert app._live_hints_scan_running is False
    assert app._patched == []
