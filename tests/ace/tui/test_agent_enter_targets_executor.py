"""Executor coverage for Enter-on-agent targets."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from ._agent_enter_targets_helpers import (
    _EnterApp,
    _gate_row,
    _matching_action_data,
    _notification,
    _remote_agent,
)
from ._agent_unread_helpers import make_agent


def test_executor_runs_patch_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    app = _EnterApp(agents=[agent])
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_navigation.navigate_to_patch_tab",
        lambda app_arg, patch_name, project_file: (
            calls.append((patch_name, project_file)) or True
        ),
    )
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None and resolution.primary.kind == "patch"
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    assert calls == [("demo", agent.project_file)]


def test_executor_dispatches_snapshot_hit_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _gate_row("010101", notification_id="n-sudo")
    notification = _notification(
        "n-sudo", "SudoRequest", action_data=_matching_action_data(agent)
    )
    app = _EnterApp(notifications=[notification], agents=[agent])
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_dispatch.open_notification_action",
        lambda app_arg, note: dispatched.append(note.id) or True,
    )
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    assert dispatched == ["n-sudo"]
    assert app.refreshes == 1


def test_executor_miss_without_notification_id_toasts() -> None:
    agent = _gate_row("010101", gate_id="abcdef123456")
    app = _EnterApp(agents=[agent])
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    assert app.notifies == [("Gate abcdef is no longer pending", "warning")]


def test_executor_question_marker_paths() -> None:
    agent = make_agent(name="q", status="QUESTION", raw_suffix="20260918010101")
    app = _EnterApp(agents=[agent])
    resolution = app._agent_enter_resolution(agent)
    marker = next(t for t in resolution.targets if t.source == "question_marker")
    app._run_agent_enter_target(marker, agent_identity=agent.identity)
    assert app.marker_calls == [agent]
    assert app.notifies == []

    app.marker_result = False
    app._run_agent_enter_target(marker, agent_identity=agent.identity)
    assert app.notifies == [("No pending question found for this agent", "warning")]


def test_executor_hitl_and_remote_branches() -> None:
    hitl_agent = make_agent(
        name="wf", status="WAITING INPUT", raw_suffix="20260918010101"
    )
    remote_agent = _remote_agent(pending=True)
    app = _EnterApp(agents=[hitl_agent, remote_agent])

    hitl_resolution = app._agent_enter_resolution(hitl_agent)
    hitl = next(t for t in hitl_resolution.targets if t.source == "workflow_hitl")
    app._run_agent_enter_target(hitl, agent_identity=hitl_agent.identity)
    assert app.hitls == [hitl_agent]

    remote_resolution = app._agent_enter_resolution(remote_agent)
    [remote_target] = remote_resolution.targets
    app._run_agent_enter_target(remote_target, agent_identity=remote_agent.identity)
    assert app.remotes == [remote_agent]


def test_executor_gone_agent_toasts() -> None:
    agent = make_agent(name="q", status="QUESTION", raw_suffix="20260918010101")
    app = _EnterApp(agents=[])
    resolution = app._agent_enter_resolution(agent)
    marker = next(t for t in resolution.targets if t.source == "question_marker")
    app._run_agent_enter_target(marker, agent_identity=agent.identity)
    assert app.notifies == [("Agent is no longer visible", "warning")]


async def test_executor_off_thread_detail_fallback_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _gate_row("010101", notification_id="n-missing")
    app = _EnterApp(agents=[agent])
    loaded = _notification("n-missing", "SudoRequest")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_provider.read_notification_detail_for_tui",
        lambda notification_id: SimpleNamespace(
            value=SimpleNamespace(notification=loaded)
        ),
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_dispatch.open_notification_action",
        lambda app_arg, note: dispatched.append(note.id) or True,
    )
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    [task] = list(app._agent_enter_async_tasks)
    await task
    await asyncio.sleep(0)
    assert dispatched == ["n-missing"]
    assert app.refreshes == 1


async def test_executor_revalidation_toast_when_target_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _gate_row("010101", notification_id="n-missing")
    app = _EnterApp(agents=[agent])
    loaded = _notification("n-missing", "SudoRequest")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_provider.read_notification_detail_for_tui",
        lambda notification_id: SimpleNamespace(
            value=SimpleNamespace(notification=loaded)
        ),
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_dispatch.open_notification_action",
        lambda app_arg, note: dispatched.append(note.id) or True,
    )
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    # The gate settles while the detail read is in flight.
    agent.gate_state = "answered"
    agent.stop_time = datetime(2026, 9, 18, 13, 0, 0)
    [task] = list(app._agent_enter_async_tasks)
    await task
    await asyncio.sleep(0)
    assert dispatched == []
    assert ("Gate gate-a is no longer pending", "warning") in app.notifies


async def test_executor_load_failure_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _gate_row("010101", gate_id="abcdef123456", notification_id="n-missing")
    app = _EnterApp(agents=[agent])

    def _fail(notification_id: str) -> Any:
        raise FileNotFoundError("gone")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_provider.read_notification_detail_for_tui",
        _fail,
    )
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    [task] = list(app._agent_enter_async_tasks)
    await task
    await asyncio.sleep(0)
    assert app.notifies == [
        ("Couldn't load gate abcdef; try: sase gate show abcdef", "warning")
    ]


def test_ensure_snapshot_short_circuits_when_cached() -> None:
    app = _EnterApp()
    calls: list[str] = []
    app._ensure_agent_enter_snapshot(lambda: calls.append("then"))
    assert calls == ["then"]
    assert app.stored_snapshots == []


async def test_ensure_snapshot_reads_off_pump_once() -> None:
    app = _EnterApp()
    app._notification_snapshot_cache = None
    snapshot = SimpleNamespace(notifications=[])
    app._read_notification_snapshot_from_provider = lambda **kwargs: snapshot  # type: ignore[method-assign]
    calls: list[str] = []
    app._ensure_agent_enter_snapshot(lambda: calls.append("then"))
    [task] = list(app._agent_enter_async_tasks)
    await task
    await asyncio.sleep(0)
    assert calls == ["then"]
    assert app.stored_snapshots == [snapshot]
