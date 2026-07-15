"""Tests for the deferred, coalesced bead-confirmation warmup.

Row and header rendering can only show bead UI from a warm confirmation cache,
so ``AgentBeadWarmupMixin`` confirms visible bead candidates off the
startup-critical loader path: a coalesced background worker resolves the
uncached or expired candidates among the visible rows after a load applies,
then patches rows whose confirmed state changed in place by identity.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime
import json
from pathlib import Path
import threading
from typing import Any

import pytest
from textual.app import App
from textual.message import Message

from sase.ace.tui.actions.agents._loading_bead_warmup import AgentBeadWarmupMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_bead import (
    _BEAD_DISPLAY_CACHE,
    _bead_display_cache_key,
    agent_has_confirmed_bead,
    warm_confirmed_bead_displays,
)
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.bead.model import Issue


@pytest.fixture(autouse=True)
def _clear_bead_display_cache() -> Iterator[None]:
    _BEAD_DISPLAY_CACHE.clear()
    yield
    _BEAD_DISPLAY_CACHE.clear()


class _FakeApp(AgentBeadWarmupMixin):
    def __init__(self) -> None:
        self._agents_first_load_done = True
        self._bead_warmup_scan_scheduled = False
        self._bead_warmup_scan_running = False
        self._bead_warmup_scan_pending = False
        self._bead_warmup_scan_source = "unknown"
        self._bead_warmup_async_tasks: set[asyncio.Task[None]] = set()
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
    agent_name: str | None = "sase-x.3",
    cl_name: str = "feat",
    raw_suffix: str = "20260615190000",
    project_file: str = "/tmp/proj/proj.sase",
    workspace_dir: str | None = "/tmp/ws",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status="RUNNING",
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_dir=workspace_dir,
    )


def _confirmed_lookup(candidate_id: str, **_: object) -> Issue:
    return Issue(id=candidate_id, title="", description="")


# --- scheduling / coalescing -------------------------------------------------


def test_schedule_noop_before_first_load() -> None:
    app = _FakeApp()
    app._agents_first_load_done = False

    app._schedule_bead_confirmation_warmup(source="apply")

    assert app._scheduled == []
    assert app._bead_warmup_scan_scheduled is False


@pytest.mark.asyncio
async def test_schedule_spawns_worker_after_first_load() -> None:
    app = _FakeApp()

    app._schedule_bead_confirmation_warmup(source="apply")

    assert app._bead_warmup_scan_scheduled is True
    assert app._bead_warmup_scan_source == "apply"
    assert len(app._bead_warmup_async_tasks) == 1
    task = next(iter(app._bead_warmup_async_tasks))
    assert task.get_name() == "sase-agents-bead-warmup"
    await task


@pytest.mark.asyncio
async def test_schedule_collapses_to_one_detached_worker() -> None:
    app = _FakeApp()

    app._schedule_bead_confirmation_warmup(source="apply")
    app._schedule_bead_confirmation_warmup(source="auto_refresh")

    assert len(app._bead_warmup_async_tasks) == 1
    await next(iter(app._bead_warmup_async_tasks))


def test_schedule_marks_pending_while_running() -> None:
    app = _FakeApp()
    app._bead_warmup_scan_running = True

    app._schedule_bead_confirmation_warmup(source="beads_watcher")

    assert app._bead_warmup_scan_pending is True
    assert app._scheduled == []


# --- candidate scope ---------------------------------------------------------


def test_warmup_candidates_only_uncached_bead_candidates() -> None:
    app = _FakeApp()
    confirmed = _agent(agent_name="sase-a.1", cl_name="confirmed", raw_suffix="1")
    missing = _agent(agent_name="sase-b.2", cl_name="missing", raw_suffix="2")
    cold = _agent(agent_name="sase-c.3", cl_name="cold", raw_suffix="3")
    ordinary = _agent(agent_name="reviewer", cl_name="ordinary", raw_suffix="4")

    confirmed_key = _bead_display_cache_key(confirmed)
    missing_key = _bead_display_cache_key(missing)
    assert confirmed_key is not None and missing_key is not None
    _BEAD_DISPLAY_CACHE.set(confirmed_key, "sase-a.1 - desc")
    _BEAD_DISPLAY_CACHE.set(missing_key, None)
    # ``cold`` and ``ordinary`` are left uncached; only ``cold`` has a candidate.
    app._agents = [confirmed, missing, cold, ordinary]

    assert app._bead_warmup_candidates() == [cold]


def test_warmup_candidates_include_expired_cached_bead_candidates() -> None:
    app = _FakeApp()
    expired_confirmed = _agent(
        agent_name="sase-a.1", cl_name="expired-confirmed", raw_suffix="1"
    )
    expired_missing = _agent(
        agent_name="sase-b.2", cl_name="expired-missing", raw_suffix="2"
    )
    fresh_confirmed = _agent(
        agent_name="sase-c.3", cl_name="fresh-confirmed", raw_suffix="3"
    )
    for agent, value in (
        (expired_confirmed, "sase-a.1 - desc"),
        (expired_missing, None),
    ):
        key = _bead_display_cache_key(agent)
        assert key is not None
        _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, value)
    fresh_key = _bead_display_cache_key(fresh_confirmed)
    assert fresh_key is not None
    _BEAD_DISPLAY_CACHE.set(fresh_key, "sase-c.3 - desc")
    app._agents = [expired_confirmed, expired_missing, fresh_confirmed]

    assert app._bead_warmup_candidates() == [expired_confirmed, expired_missing]


# --- compute (off-thread body) -----------------------------------------------


def test_warm_confirmed_bead_displays_dedupes_lookups_by_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def counting_lookup(candidate_id: str, **_: object) -> Issue:
        calls.append(candidate_id)
        return Issue(id=candidate_id, title="", description="")

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", counting_lookup)

    # a1 and a2 share a candidate + project + workspace, so one cache key; a3 is
    # a distinct candidate. Two unique keys → two bead-store lookups total.
    a1 = _agent(agent_name="sase-x.3", cl_name="a1", raw_suffix="1")
    a2 = _agent(agent_name="sase-x.3", cl_name="a2", raw_suffix="2")
    a3 = _agent(agent_name="sase-y.4", cl_name="a3", raw_suffix="3")

    results = warm_confirmed_bead_displays([a1, a2, a3])

    assert calls == ["sase-x.3", "sase-y.4"]
    assert results == {a1.identity: True, a2.identity: True, a3.identity: True}


def test_warm_confirmed_bead_displays_omits_missing_and_non_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda candidate_id, **_: None,
    )

    missing = _agent(agent_name="sase-x.3", cl_name="missing", raw_suffix="1")
    ordinary = _agent(agent_name="reviewer", cl_name="ordinary", raw_suffix="2")

    results = warm_confirmed_bead_displays([missing, ordinary])

    assert results == {}


def test_warm_confirmed_bead_displays_reports_deleted_confirmed_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(agent_name="sase-x.3", cl_name="deleted", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3 - stale description")
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda candidate_id, **_: None,
    )

    results = warm_confirmed_bead_displays([agent])

    assert results == {agent.identity: False}
    assert agent_has_confirmed_bead(agent) is False


def test_warm_confirmed_bead_displays_omits_unchanged_expired_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(agent_name="sase-x.3", cl_name="same", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3")
    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", _confirmed_lookup)

    results = warm_confirmed_bead_displays([agent])

    assert results == {}
    assert agent_has_confirmed_bead(agent) is True


def test_warm_confirmed_bead_displays_reuses_store_for_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    beads_dir = workspace / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    issues = [
        _issue_payload("batch-x.3", "First"),
        _issue_payload("batch-y.4", "Second"),
    ]
    (beads_dir / "issues.jsonl").write_text(
        "".join(json.dumps(issue) + "\n" for issue in issues),
        encoding="utf-8",
    )

    from sase.bead import project as project_module

    real_bead_project = project_module.BeadProject
    constructions: list[Path] = []

    def counting_bead_project(
        root_dir: str | Path,
        beads_dirname: str = "sdd/beads",
    ) -> Any:
        constructions.append(Path(root_dir) / beads_dirname)
        return real_bead_project(root_dir, beads_dirname=beads_dirname)

    monkeypatch.setattr(project_module, "BeadProject", counting_bead_project)
    first = _agent(
        agent_name="batch-x.3",
        cl_name="first",
        raw_suffix="1",
        project_file="",
        workspace_dir=str(workspace),
    )
    second = _agent(
        agent_name="batch-y.4",
        cl_name="second",
        raw_suffix="2",
        project_file="",
        workspace_dir=str(workspace),
    )

    results = warm_confirmed_bead_displays([first, second])

    assert results == {first.identity: True, second.identity: True}
    assert constructions == [beads_dir]


# --- apply by identity -------------------------------------------------------


def test_apply_patches_only_result_rows() -> None:
    app = _FakeApp()
    confirmed = _agent(agent_name="sase-x.3", cl_name="confirmed", raw_suffix="1")
    other = _agent(agent_name="sase-y.4", cl_name="other", raw_suffix="2")
    app._agents = [confirmed, other]
    app._agents_with_children = [confirmed, other]

    app._apply_bead_warmup_results({confirmed.identity: True})

    assert app._patched == [confirmed]


def test_apply_patches_rows_losing_confirmed_bead() -> None:
    app = _FakeApp()
    removed = _agent(agent_name="sase-x.3", cl_name="removed", raw_suffix="1")
    other = _agent(agent_name="sase-y.4", cl_name="other", raw_suffix="2")
    app._agents = [removed, other]
    app._agents_with_children = [removed, other]

    app._apply_bead_warmup_results({removed.identity: False})

    assert app._patched == [removed]


def test_apply_rematches_current_object_by_identity() -> None:
    """A refresh may rebuild the list; the patch lands on the live object."""
    app = _FakeApp()
    snapshot = _agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    rebuilt = _agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    app._agents = [rebuilt]
    app._agents_with_children = [rebuilt]

    app._apply_bead_warmup_results({snapshot.identity: True})

    assert app._patched == [rebuilt]


def test_apply_noop_without_results() -> None:
    app = _FakeApp()
    app._agents = [_agent()]

    app._apply_bead_warmup_results({})

    assert app._patched == []


# --- full async worker -------------------------------------------------------


@pytest.mark.asyncio
async def test_run_defers_behind_navigation_gate() -> None:
    app = _FakeApp()
    app._agents = [_agent()]
    app._nav_gate.record()  # user is mid j/k burst

    await app._run_bead_confirmation_warmup()

    assert len(app._timer_calls) == 1
    assert app._timer_calls[0][1] == app._spawn_bead_confirmation_warmup_task
    assert app._patched == []
    assert app._bead_warmup_scan_scheduled is False


@pytest.mark.asyncio
async def test_run_confirms_applies_and_clears_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp()
    agent = _agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._bead_warmup_scan_scheduled = True

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", _confirmed_lookup)

    await app._run_bead_confirmation_warmup()

    assert agent_has_confirmed_bead(agent) is True
    assert app._patched == [agent]
    assert app._bead_warmup_scan_scheduled is False
    assert app._bead_warmup_scan_running is False


@pytest.mark.asyncio
async def test_run_missing_candidate_stays_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp()
    agent = _agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
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
async def test_run_rearms_when_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakeApp()
    agent = _agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._bead_warmup_scan_pending = True

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", _confirmed_lookup)

    await app._run_bead_confirmation_warmup()

    assert app._bead_warmup_scan_pending is False
    assert len(app._bead_warmup_async_tasks) == 1
    await next(iter(app._bead_warmup_async_tasks))


@pytest.mark.asyncio
async def test_run_noop_without_candidates() -> None:
    app = _FakeApp()
    app._agents = [_agent(agent_name="reviewer")]
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
        self._nav_gate = NavigationGate(window_s=0.25)
        self.probe_processed = asyncio.Event()

    def _try_patch_agent_row(self, agent: Agent) -> bool:
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
    app = _PumpResponsiveApp(_agent())
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


def _issue_payload(issue_id: str, title: str) -> dict[str, object]:
    timestamp = "2026-07-12T00:00:00Z"
    return {
        "id": issue_id,
        "title": title,
        "status": "open",
        "issue_type": "plan",
        "parent_id": None,
        "owner": "",
        "assignee": "",
        "created_at": timestamp,
        "created_by": "",
        "updated_at": timestamp,
        "closed_at": None,
        "close_reason": None,
        "description": "",
        "notes": "",
        "design": "",
        "is_ready_to_work": False,
        "changespec_name": "",
        "changespec_bug_id": "",
        "dependencies": [],
    }
