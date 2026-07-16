"""Tests for the deferred, coalesced live-workspace pencil-hint refresh.

The expensive per-agent live VCS probe is computed off the startup-critical
loader path by ``AgentLiveHintMixin``: a coalesced background worker scans the
active, non-terminal rows after the first agents load applies, then patches
changed rows in place by identity.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _loading_live_hints as live_hints_mod
from sase.ace.tui.actions.agents._loading_live_hints import (
    AgentLiveHintMixin,
    _compute_live_hints,
    carry_over_live_hints,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.ace.tui.widgets._agent_list_render_cache import agent_file_change_hint
from sase.ace.tui.widgets._agent_list_rendering import agent_render_key


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

    def _spawn_live_hint_refresh_task(self) -> None:
        """Record scheduling without starting a task in narrow sync tests."""
        self._scheduled.append(self._run_live_hint_refresh)

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


def _root_plan(*, raw_suffix: str, diff_path: str | None = None) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="plan-feat",
        project_file="/tmp/test.sase",
        status="PLAN APPROVED",
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix=raw_suffix,
        role_suffix="-plan",
        plan_chain_root=True,
        diff_path=diff_path,
    )


def _coder_child(
    *,
    parent_suffix: str,
    status: str = "PLAN APPROVED",
    diff_path: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="plan-feat-code",
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 6, 15, 19, 30, 0),
        raw_suffix=f"{parent_suffix}-code",
        parent_timestamp=parent_suffix,
        role_suffix="-code",
        diff_path=diff_path,
    )


def _row_render_key(agent: Agent) -> tuple[object, ...]:
    return agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 6, 15, 19, 1, 0),
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

    assert candidates == [running, starting, with_diff]


def test_live_hint_candidates_includes_redirected_plan_with_own_diff_path() -> None:
    """A redirected plan row qualifies even with its own bookkeeping diff_path.

    Its resolved active coder child has no persisted diff, so the deferred scan
    must probe the child's workspace to drive the plan row's badge.
    """
    app = _FakeApp()
    plan = _root_plan(raw_suffix="100", diff_path="/tmp/plan.diff")
    plan.followup_agents.append(_coder_child(parent_suffix="100"))
    app._agents = [plan]

    assert app._live_hint_candidates() == [plan]


def test_live_hint_candidates_uses_active_plan_when_coder_child_is_terminal() -> None:
    app = _FakeApp()
    plan = _root_plan(raw_suffix="200", diff_path="/tmp/plan.diff")
    plan.followup_agents.append(_coder_child(parent_suffix="200", status="DONE"))
    app._agents = [plan]

    # The coder child is terminal, so resolution falls back to the still-active
    # plan row. Its persisted diff is only a fallback under active precedence.
    assert app._live_hint_candidates() == [plan]


def test_live_hint_candidates_includes_redirected_plan_when_child_has_diff() -> None:
    app = _FakeApp()
    plan = _root_plan(raw_suffix="300", diff_path="/tmp/plan.diff")
    plan.followup_agents.append(
        _coder_child(parent_suffix="300", diff_path="/tmp/child.diff")
    )
    app._agents = [plan]

    assert app._live_hint_candidates() == [plan]


def test_live_hint_candidates_includes_ordinary_persisted_diff_row() -> None:
    app = _FakeApp()
    with_diff = _agent(cl_name="withdiff", raw_suffix="9", diff_path="/tmp/x.diff")
    app._agents = [with_diff]

    assert app._live_hint_candidates() == [with_diff]


# --- carry-over across reloads ----------------------------------------------


def test_carry_over_live_hints_copies_visible_and_unfiltered_rows() -> None:
    previous_visible = _agent(cl_name="visible", raw_suffix="1")
    previous_visible.live_file_change_hint = True
    previous_unfiltered = _agent(cl_name="folded", raw_suffix="2")
    previous_unfiltered.live_file_change_hint = False
    fresh_visible = _agent(cl_name="visible", raw_suffix="1")
    fresh_unfiltered = _agent(cl_name="folded", raw_suffix="2")
    old_key = _row_render_key(previous_visible)

    carry_over_live_hints(
        [previous_unfiltered, previous_visible],
        [fresh_unfiltered, fresh_visible],
    )

    assert fresh_visible.live_file_change_hint is True
    assert fresh_unfiltered.live_file_change_hint is False
    assert agent_file_change_hint(fresh_visible) is True
    assert _row_render_key(fresh_visible) == old_key


def test_carry_over_live_hints_skips_non_candidates_and_existing_values() -> None:
    previous_with_diff = _agent(cl_name="with-diff", raw_suffix="1")
    previous_with_diff.live_file_change_hint = True
    fresh_with_diff = _agent(
        cl_name="with-diff",
        raw_suffix="1",
        diff_path="/tmp/final.diff",
    )

    previous_done = _agent(cl_name="done", raw_suffix="2")
    previous_done.live_file_change_hint = True
    fresh_done = _agent(cl_name="done", raw_suffix="2", status="DONE")

    previous_unknown = _agent(cl_name="unknown", raw_suffix="3")
    fresh_unknown = _agent(cl_name="unknown", raw_suffix="3")

    previous_loader_value = _agent(cl_name="loader", raw_suffix="4")
    previous_loader_value.live_file_change_hint = True
    fresh_loader_value = _agent(cl_name="loader", raw_suffix="4")
    fresh_loader_value.live_file_change_hint = False

    carry_over_live_hints(
        [
            previous_with_diff,
            previous_done,
            previous_unknown,
            previous_loader_value,
        ],
        [fresh_with_diff, fresh_done, fresh_unknown, fresh_loader_value],
    )

    assert fresh_with_diff.live_file_change_hint is True
    assert fresh_done.live_file_change_hint is None
    assert fresh_unknown.live_file_change_hint is None
    assert fresh_loader_value.live_file_change_hint is False


def test_carry_over_live_hints_includes_redirected_root_plan() -> None:
    previous_plan = _root_plan(raw_suffix="400", diff_path="/tmp/plan.diff")
    previous_plan.followup_agents.append(_coder_child(parent_suffix="400"))
    previous_plan.live_file_change_hint = True
    fresh_plan = _root_plan(raw_suffix="400", diff_path="/tmp/plan.diff")
    fresh_plan.followup_agents.append(_coder_child(parent_suffix="400"))

    carry_over_live_hints([previous_plan], [fresh_plan])

    assert fresh_plan.live_file_change_hint is True
    assert agent_file_change_hint(fresh_plan) is True


def test_carry_over_live_hints_includes_redirected_plan_when_child_has_diff() -> None:
    previous_plan = _root_plan(raw_suffix="500", diff_path="/tmp/plan.diff")
    previous_plan.followup_agents.append(_coder_child(parent_suffix="500"))
    previous_plan.live_file_change_hint = True
    fresh_plan = _root_plan(raw_suffix="500", diff_path="/tmp/plan.diff")
    fresh_plan.followup_agents.append(
        _coder_child(parent_suffix="500", diff_path="/tmp/child.diff")
    )

    carry_over_live_hints([previous_plan], [fresh_plan])

    assert fresh_plan.live_file_change_hint is True


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


def test_apply_retains_boolean_hint_when_result_has_no_signal() -> None:
    app = _FakeApp()
    agent = _agent(cl_name="feat", raw_suffix="1")
    agent.live_file_change_hint = True
    app._agents = [agent]
    app._agents_with_children = [agent]

    app._apply_live_hint_results({agent.identity: None})

    assert agent.live_file_change_hint is True
    assert app._patched == []


def test_apply_false_result_overwrites_true_hint() -> None:
    app = _FakeApp()
    agent = _agent(cl_name="feat", raw_suffix="1")
    agent.live_file_change_hint = True
    app._agents = [agent]
    app._agents_with_children = [agent]

    app._apply_live_hint_results({agent.identity: False})

    assert agent.live_file_change_hint is False
    assert app._patched == [agent]


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


@pytest.mark.asyncio
async def test_live_hint_worker_does_not_block_loop_pump(monkeypatch: Any) -> None:
    """A stuck worker thread must not keep loop messages from progressing."""
    app = _FakeApp()
    agent = _agent()
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._live_hints_scan_scheduled = True
    entered = threading.Event()
    release = threading.Event()

    def _slow_compute(
        candidates: list[Agent],
    ) -> dict[tuple[AgentType, str, str | None], bool]:
        entered.set()
        release.wait(timeout=1.0)
        return {candidate.identity: True for candidate in candidates}

    monkeypatch.setattr(live_hints_mod, "_compute_live_hints", _slow_compute)
    try:
        AgentLiveHintMixin._spawn_live_hint_refresh_task(app)
        await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=0.5)

        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=0.05)
        assert app._live_hints_scan_running is True
    finally:
        release.set()
        tasks = list(getattr(app, "_pump_free_async_tasks", ()))
        if tasks:
            await asyncio.gather(*tasks)
