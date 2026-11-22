"""Async worker and Textual-pump coverage for bead warmup."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from textual.app import App
from textual.message import Message

from sase.ace.tui.actions.agents._loading_bead_warmup import (
    AgentBeadWarmupMixin,
    _AgentBeadWarmupCandidates,
    _AgentBeadWarmupResults,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_bead import agent_has_confirmed_bead
from sase.ace.tui.util.nav_gate import NavigationGate
from tests.ace.tui._agents_bead_warmup_helpers import (
    FakeApp,
    clear_bead_display_cache,
    confirmed_lookup,
    make_agent,
)

__all__ = [
    "WarmupProbe",
    "test_forced_stranded_warmup_failure_keeps_project_and_retries",
    "test_pending_request_runs_followup_scan_with_positive_timer_delay",
    "test_run_confirms_applies_and_clears_running",
    "test_run_defers_behind_navigation_gate",
    "test_run_missing_candidate_stays_silent",
    "test_run_noop_without_candidates",
    "test_run_suppresses_pending_when_caches_are_fresh",
    "test_warmup_trace_counts_candidates_and_resolution_outcomes",
    "test_warmup_does_not_block_textual_message_pump",
]


@pytest.mark.asyncio
async def test_run_defers_behind_navigation_gate() -> None:
    app = FakeApp()
    app._agents = [make_agent()]
    app._nav_gate.record()  # user is mid j/k burst

    await app._run_bead_confirmation_warmup()

    assert len(app._timer_calls) == 1
    assert callable(app._timer_calls[0][1])
    assert app._patched == []
    assert app._bead_warmup_scan_scheduled is False


@pytest.mark.asyncio
async def test_run_confirms_applies_and_clears_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FakeApp()
    agent = make_agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._bead_warmup_scan_scheduled = True

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", confirmed_lookup)

    await app._run_bead_confirmation_warmup()

    assert agent_has_confirmed_bead(agent) is True
    assert app._patched == [agent]
    assert app._bead_warmup_scan_scheduled is False
    assert app._bead_warmup_scan_running is False


@pytest.mark.asyncio
async def test_warmup_trace_counts_candidates_and_resolution_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.util import trace

    log = tmp_path / "tui_trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    trace._context.clear()

    app = FakeApp()
    agent = make_agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._bead_warmup_scan_scheduled = True
    app._bead_warmup_scheduled_candidates = _AgentBeadWarmupCandidates(
        bead_display_agents=(agent,),
        candidates_examined=1,
        cause_counts=(("cold", 1),),
    )
    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", confirmed_lookup)

    await app._run_bead_confirmation_warmup()

    trace._flush_trace_writes()
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    spans = [
        row for row in rows if row.get("span") == "agents.bead_confirmation_warmup"
    ]
    assert len(spans) == 1
    assert spans[0]["candidates_examined"] == 1
    assert spans[0]["candidate_causes"] == {"cold": 1}
    assert spans[0]["bead_display_candidates"] == 1
    assert spans[0]["bead_display_heavy_resolutions"] == 1
    assert spans[0]["bead_display_changed_outcomes"] == 1
    assert spans[0]["bead_display_unchanged_outcomes"] == 0


@pytest.mark.asyncio
async def test_run_missing_candidate_stays_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FakeApp()
    agent = make_agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    app._agents = [agent]
    app._agents_with_children = [agent]

    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda candidate_id, **_: None,
    )

    await app._run_bead_confirmation_warmup()

    assert agent_has_confirmed_bead(agent) is False
    assert app._patched == []


@pytest.mark.asyncio
async def test_run_suppresses_pending_when_caches_are_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FakeApp()
    agent = make_agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._bead_warmup_scan_pending = True

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", confirmed_lookup)

    await app._run_bead_confirmation_warmup()

    assert app._bead_warmup_scan_pending is False
    assert app._bead_warmup_async_tasks == set()


@pytest.mark.asyncio
async def test_pending_request_runs_followup_scan_with_positive_timer_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FakeApp()
    agent = make_agent()
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._agents_roster_generation = 1
    app._bead_warmup_scan_scheduled = True
    app._bead_warmup_scan_pending = True
    app._bead_warmup_scheduled_candidates = _AgentBeadWarmupCandidates(
        bead_display_agents=(agent,),
        roster_generation=0,
    )

    candidate_refresh = _AgentBeadWarmupCandidates(
        bead_display_agents=(agent,),
        roster_generation=1,
    )
    app._bead_warmup_candidates = lambda **_: candidate_refresh  # type: ignore[method-assign]
    spawned: list[bool] = []
    app._spawn_bead_confirmation_warmup_task = lambda: spawned.append(  # type: ignore[method-assign]
        True
    )
    worker_calls = 0

    def warmup(_candidates: object) -> _AgentBeadWarmupResults:
        nonlocal worker_calls
        worker_calls += 1
        return _AgentBeadWarmupResults({}, set())

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._loading_bead_warmup._warm_agent_bead_caches",
        warmup,
    )

    await app._run_bead_confirmation_warmup()

    assert app._timer_calls
    assert app._timer_calls[-1][0] == 0.05
    assert all(delay > 0.0 for delay, _ in app._timer_calls)
    assert callable(app._timer_calls[-1][1])

    app._timer_calls[-1][1]()
    assert spawned == [True]
    assert app._bead_warmup_scan_scheduled is True
    await app._run_bead_confirmation_warmup()
    assert worker_calls == 2


@pytest.mark.asyncio
async def test_forced_stranded_warmup_failure_keeps_project_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FakeApp()
    app._agents = [make_agent()]
    app._bead_warmup_forced_projects = {"proj"}
    app._bead_warmup_forced_immediate_projects = {"proj"}
    app._bead_warmup_scan_scheduled = True
    app._bead_warmup_scheduled_candidates = _AgentBeadWarmupCandidates(
        force_stranded_projects=("proj",),
        force_stranded_immediate=True,
    )

    def fail_warmup(_candidates: object) -> _AgentBeadWarmupResults:
        raise RuntimeError("test worker failure")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._loading_bead_warmup._warm_agent_bead_caches",
        fail_warmup,
    )

    await app._run_bead_confirmation_warmup()

    assert app._bead_warmup_scan_running is False
    assert app._bead_warmup_forced_projects == {"proj"}
    assert app._timer_calls
    assert app._timer_calls[-1][0] >= 1.0


@pytest.mark.asyncio
async def test_run_noop_without_candidates() -> None:
    app = FakeApp()
    app._agents = [make_agent(agent_name="reviewer")]
    app._bead_warmup_scan_scheduled = True

    await app._run_bead_confirmation_warmup()

    assert app._bead_warmup_scan_running is False
    assert app._patched == []


class WarmupProbe(Message):
    """Message used to prove the Textual pump remains responsive."""


class _PumpResponsiveApp(AgentBeadWarmupMixin, App[None]):
    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self._agents_first_load_done = True
        self._bead_warmup_scan_scheduled = False
        self._bead_warmup_scan_running = False
        self._bead_warmup_scan_pending = False
        self._bead_warmup_scan_source = "unknown"
        self._bead_warmup_async_tasks: set[asyncio.Task[None]] = set()
        self._agents = [agent]
        self._agents_with_children = [agent]
        self.current_idx = 0
        self._nav_gate = NavigationGate(window_s=0.25)
        self.probe_processed = asyncio.Event()

    def _try_patch_agent_row(self, agent: Agent, **_: object) -> bool:
        del agent
        return True

    def on_warmup_probe(self, _: WarmupProbe) -> None:
        self.probe_processed.set()


@pytest.mark.asyncio
async def test_warmup_does_not_block_textual_message_pump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_started = threading.Event()
    release_worker = threading.Event()

    def blocked_warmup(_: object) -> dict[object, bool]:
        worker_started.set()
        release_worker.wait(timeout=2.0)
        return {}

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._loading_bead_warmup.warm_confirmed_bead_displays",
        blocked_warmup,
    )
    app = _PumpResponsiveApp(make_agent())
    try:
        async with app.run_test():
            app._schedule_bead_confirmation_warmup(source="test")
            started = await asyncio.to_thread(worker_started.wait, 1.0)
            assert started is True

            app.post_message(WarmupProbe())
            await asyncio.wait_for(app.probe_processed.wait(), timeout=0.5)
            assert all(not task.done() for task in app._bead_warmup_async_tasks)
    finally:
        release_worker.set()
        if app._bead_warmup_async_tasks:
            await asyncio.gather(*app._bead_warmup_async_tasks)
