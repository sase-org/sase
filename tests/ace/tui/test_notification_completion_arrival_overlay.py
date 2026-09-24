"""Overlay lifetime for same-tick completion arrivals."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._notification_completion_arrival import (
    CompletionArrivalPrep,
    install_completion_arrival_overlays,
    reconcile_arrival_status_overlays,
)
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(*, raw_suffix: str, status: str, artifacts_dir: str = "/tmp/adir") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 9, 24, 12, 0, 0),
        raw_suffix=raw_suffix,
        artifacts_dir=artifacts_dir,
    )


def _app(agents: list[Agent], *, loading: bool) -> SimpleNamespace:
    app = SimpleNamespace(
        _agents=list(agents),
        _agents_with_children=list(agents),
        _agents_loading=loading,
        _agents_arrival_status_overlays={},
    )
    app._schedule_agent_artifact_delta_refresh = (  # type: ignore[attr-defined]
        lambda dirs, *, source: None
    )
    return app


def test_stale_apply_keeps_terminal_then_authoritative_drops() -> None:
    ts = "20260924120000"
    agent = _agent(raw_suffix=ts, status="RUNNING")
    app = _app([agent], loading=True)
    prep = CompletionArrivalPrep(
        overlays=((agent.identity, "DONE"),),
        artifact_dirs=(Path("/tmp/adir"),),
    )
    changed = install_completion_arrival_overlays(app, prep)
    assert changed == {agent.identity}
    assert agent.status == "DONE"

    stale = _agent(raw_suffix=ts, status="RUNNING")
    app._agents = [stale]
    app._agents_with_children = [stale]
    reconcile_arrival_status_overlays(app)
    assert stale.status == "DONE"
    assert (
        app._agents_arrival_status_overlays[agent.identity].survives_stale_apply
        is False
    )

    authoritative = _agent(raw_suffix=ts, status="RUNNING")
    app._agents = [authoritative]
    app._agents_with_children = [authoritative]
    reconcile_arrival_status_overlays(app)
    assert authoritative.status == "RUNNING"
    assert agent.identity not in app._agents_arrival_status_overlays


def test_no_inflight_next_load_wins() -> None:
    ts = "20260924120000"
    agent = _agent(raw_suffix=ts, status="RUNNING")
    app = _app([agent], loading=False)
    prep = CompletionArrivalPrep(
        overlays=((agent.identity, "DONE"),),
        artifact_dirs=(Path("/tmp/adir"),),
    )
    install_completion_arrival_overlays(app, prep)
    assert agent.status == "DONE"

    loaded = _agent(raw_suffix=ts, status="RUNNING")
    app._agents = [loaded]
    app._agents_with_children = [loaded]
    reconcile_arrival_status_overlays(app)
    assert loaded.status == "RUNNING"
    assert app._agents_arrival_status_overlays == {}


def test_status_overrides_untouched() -> None:
    ts = "20260924120000"
    agent = _agent(raw_suffix=ts, status="RUNNING")
    app = _app([agent], loading=False)
    app._agent_status_overrides = {agent.identity: "RUNNING"}
    prep = CompletionArrivalPrep(
        overlays=((agent.identity, "DONE"),),
        artifact_dirs=(Path("/tmp/adir"),),
    )
    install_completion_arrival_overlays(app, prep)
    assert app._agent_status_overrides == {agent.identity: "RUNNING"}

    loaded = _agent(raw_suffix=ts, status="RUNNING")
    app._agents = [loaded]
    app._agents_with_children = [loaded]
    reconcile_arrival_status_overlays(app)
    assert app._agent_status_overrides == {agent.identity: "RUNNING"}


def test_missing_row_drops_overlay() -> None:
    ts = "20260924120000"
    agent = _agent(raw_suffix=ts, status="RUNNING")
    app = _app([agent], loading=True)
    prep = CompletionArrivalPrep(
        overlays=((agent.identity, "DONE"),),
        artifact_dirs=(Path("/tmp/adir"),),
    )
    install_completion_arrival_overlays(app, prep)
    app._agents = []
    app._agents_with_children = []
    reconcile_arrival_status_overlays(app)
    assert app._agents_arrival_status_overlays == {}


def test_terminal_row_not_clobbered_by_stale_apply() -> None:
    ts = "20260924120000"
    agent = _agent(raw_suffix=ts, status="RUNNING")
    app = _app([agent], loading=True)
    prep = CompletionArrivalPrep(
        overlays=((agent.identity, "DONE"),),
        artifact_dirs=(Path("/tmp/adir"),),
    )
    install_completion_arrival_overlays(app, prep)
    terminal = _agent(raw_suffix=ts, status="FAILED")
    app._agents = [terminal]
    app._agents_with_children = [terminal]
    reconcile_arrival_status_overlays(app)
    assert terminal.status == "FAILED"
    assert (
        app._agents_arrival_status_overlays[agent.identity].survives_stale_apply
        is False
    )
