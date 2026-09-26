"""Tier 0 and Tier 1 coverage for the Node Finder preview."""

from __future__ import annotations

import builtins
from datetime import datetime, timedelta
import os
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.modals import node_finder_preview_loader as loader
from sase.ace.tui.modals.node_finder_preview import render_node_finder_preview
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.node_finder import (
    NodeFinderRole,
    NodeFinderRow,
    NodeFinderSnapshot,
    node_finder_kind,
    node_finder_name,
)
from tests.ace.tui._member_jump_navigation_helpers import make_agent


def _started(offset: int = 0) -> datetime:
    return datetime(2026, 9, 25, 12, 0, 0) + timedelta(minutes=offset)


def _row(agent: Agent, *, parent_row: int | None = None) -> NodeFinderRow:
    kind_label, kind_accent = node_finder_kind(agent)
    return NodeFinderRow(
        role=NodeFinderRole.NODE,
        identity=agent.identity,
        agent=agent,
        name=node_finder_name(agent),
        kind_label=kind_label,
        kind_accent=kind_accent,
        parent_row=parent_row,
        jumpable=True,
    )


def _snapshot(*rows: NodeFinderRow) -> NodeFinderSnapshot:
    return NodeFinderSnapshot(rows=rows, node_count=len(rows))


def _monitor() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="check",
        project_file="/project/project.sase",
        status="COMPLETED",
        start_time=_started(),
        raw_suffix="ts-monitor",
        agent_name="check--mon-1",
        agent_session_role="monitor",
        monitor_id="mon-1",
        monitor_label="verify",
        monitor_command="just check",
        monitor_state="completed",
        monitor_exit_code=0,
        proc_log_tail="one\ntwo\nthree",
    )


def test_tier0_is_pure_for_every_node_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rendering never opens or stats an artifact, even for output previews."""

    shell = make_agent("session--code", session="session", role="code")
    session = make_agent("session--plan", session="session", role="plan")
    session.followup_agents = [shell]
    clan_member = make_agent("research.0", clan="research")
    (clan,) = project_clan_tree([clan_member])[:1]
    gate = make_agent("gate", role="gate")
    gate.gate_id = "gate-1"
    gate.gate_label = "Accept plan"
    proc = Agent(
        agent_type=AgentType.NAMED_PROC,
        cl_name="proc",
        project_file="/project/project.sase",
        status="RUNNING",
        start_time=_started(),
        raw_suffix="ts-proc",
        proc_label="background proc",
        proc_safe_preview="echo hello",
        proc_log_tail="log line",
    )
    workflow = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow",
        project_file="/project/project.sase",
        status="RUNNING",
        start_time=_started(),
        raw_suffix="ts-workflow",
        workflow="build",
    )
    step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="workflow-step",
        project_file="/project/project.sase",
        status="DONE",
        start_time=_started(),
        raw_suffix="ts-workflow-step",
        parent_workflow="build",
        parent_timestamp="ts-workflow",
        step_name="code",
        step_type="agent",
    )
    agents = [session, shell, clan, _monitor(), gate, proc, workflow, step]
    rows = tuple(
        _row(agent, parent_row=6 if agent is step else None) for agent in agents
    )
    snapshot = _snapshot(*rows)

    # Warm the configuration-backed tribe style before every filesystem hook
    # becomes a hard failure.
    render_node_finder_preview(rows[0], snapshot, "")

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Tier 0 preview performed I/O")

    monkeypatch.setattr(builtins, "open", fail)
    monkeypatch.setattr(os, "stat", fail)
    monkeypatch.setattr(os, "scandir", fail)
    monkeypatch.setattr(Path, "stat", fail)

    for row in rows:
        rendered = render_node_finder_preview(row, snapshot, "query")
        assert rendered.plain


def test_tier0_renders_session_clan_and_monitor_sections() -> None:
    shell = make_agent("session--code", session="session", role="code")
    session = make_agent("session--plan", session="session", role="plan")
    session.followup_agents = [shell]
    clan_member = make_agent("research.0", clan="research")
    (clan,) = project_clan_tree([clan_member])[:1]
    monitor = _monitor()
    rows = (_row(session), _row(shell, parent_row=0), _row(clan), _row(monitor))
    snapshot = _snapshot(*rows)

    assert "SHELLS" in render_node_finder_preview(rows[0], snapshot, "").plain
    clan_text = render_node_finder_preview(rows[2], snapshot, "").plain
    assert "MEMBERS" in clan_text
    assert ".0" in clan_text
    monitor_text = render_node_finder_preview(rows[3], snapshot, "").plain
    assert "PROCESS" in monitor_text
    assert "OUTPUT · tail" in monitor_text
    assert "three" in monitor_text


def test_tier1_source_uses_newest_session_shell() -> None:
    first = make_agent("session--first", session="session", role="code")
    first.start_time = _started(1)
    newest = make_agent("session--newest", session="session", role="code")
    newest.start_time = _started(2)
    session = make_agent("session--plan", session="session", role="plan")
    session.followup_agents = [first, newest, _monitor()]
    row = _row(session)

    assert loader.tier1_source(row, _snapshot(row)) is newest
    assert loader.tier1_source(_row(_monitor()), _snapshot()) is None


def test_loader_bounds_content_hydrates_only_copy_and_uses_reply_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent("preview")
    agent.record_shape = "list"
    agent.index_record_dir = "record"
    hydrated: list[Agent] = []
    monkeypatch.setattr(loader, "get_prompt_content", lambda _agent: "p" * 3_000)
    monkeypatch.setattr(loader, "projected_agent_waiting_for_hydration", lambda _: True)

    def hydrate(candidate: Agent) -> bool:
        hydrated.append(candidate)
        candidate.record_shape = "full"
        return True

    monkeypatch.setattr(loader, "hydrate_projected_agent", hydrate)
    monkeypatch.setattr(
        agent, "get_timestamped_reply_chunks", lambda: [("t", "first"), ("u", "second")]
    )
    monkeypatch.setattr(agent, "get_live_reply_content", lambda: "live should lose")
    monkeypatch.setattr(loader, "_node_finder_preview_token", lambda _: ())

    payload = loader.load_node_finder_preview(agent)

    assert hydrated and hydrated[0] is not agent
    assert agent.record_shape == "list"
    assert len(payload.prompt) <= 2_048
    assert payload.reply == "first\nsecond"
    assert "PROMPT" in loader.render_tier1(payload).plain


def test_preview_cache_hits_and_evicts() -> None:
    first = make_agent("first")
    second = make_agent("second")
    cache = loader.NodeFinderPreviewCache(capacity=1)
    one = loader.NodeFinderPreviewPayload(first.identity, "first", "", "", 0, 0, ())
    two = loader.NodeFinderPreviewPayload(second.identity, "second", "", "", 0, 0, ())

    cache.put(one)
    assert cache.get(first.identity) is one
    cache.put(two)
    assert cache.get(first.identity) is None
    assert cache.get(second.identity) is two
