"""Tests for ``AgentPanelIndex`` — Phase 4 of tui_perf_overhaul_1."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panel_index import (
    AgentPanelIndex,
    PanelSlice,
    build_agent_panel_index,
)

_DISMISSABLE = {"DONE", "FAILED", "PLAN COMMITTED", "PLAN DONE", "EPIC CREATED"}


def _agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/repo/proj.gp",
    tag: str | None = None,
    agent_name: str | None = None,
    status: str = "RUNNING",
    raw_suffix: str | None = "20260425143000",
    parent_timestamp: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=agent_name,
        tag=tag,
        raw_suffix=raw_suffix,
        parent_timestamp=parent_timestamp,
    )


def test_empty_agents_yields_empty_index() -> None:
    index = build_agent_panel_index([], dismissable_statuses=_DISMISSABLE)
    assert index.keys_per_agent == []
    assert index.panels == {}
    assert index.non_child_indices == []
    assert index.completed_count == 0
    assert index.non_child_total == 0
    assert index.non_child_position(0) == 0


def test_groups_agents_into_panels_by_tag() -> None:
    a0 = _agent(raw_suffix="A", tag=None)
    a1 = _agent(raw_suffix="B", tag="alpha")
    a2 = _agent(raw_suffix="C", tag="alpha")
    a3 = _agent(raw_suffix="D", tag="beta")
    index = build_agent_panel_index([a0, a1, a2, a3], dismissable_statuses=_DISMISSABLE)

    assert index.keys_per_agent == [None, "alpha", "alpha", "beta"]
    assert set(index.panels.keys()) == {None, "alpha", "beta"}
    untagged = index.slice_for(None)
    assert untagged.agents == [a0]
    assert untagged.global_indices == [0]
    assert untagged.global_to_local == {0: 0}

    alpha = index.slice_for("alpha")
    assert alpha.agents == [a1, a2]
    assert alpha.global_indices == [1, 2]
    assert alpha.global_to_local == {1: 0, 2: 1}


def test_local_idx_for_returns_minus_one_for_other_panels() -> None:
    a0 = _agent(raw_suffix="A", tag=None)
    a1 = _agent(raw_suffix="B", tag="alpha")
    index = build_agent_panel_index([a0, a1], dismissable_statuses=_DISMISSABLE)
    assert index.local_idx_for("alpha", 0) == -1
    assert index.local_idx_for(None, 1) == -1
    assert index.local_idx_for("missing", 0) == -1


def test_completed_count_counts_dismissable_statuses_only() -> None:
    agents = [
        _agent(raw_suffix="a", status="RUNNING"),
        _agent(raw_suffix="b", status="DONE"),
        _agent(raw_suffix="c", status="FAILED"),
        _agent(raw_suffix="d", status="WAIT"),
    ]
    index = build_agent_panel_index(agents, dismissable_statuses=_DISMISSABLE)
    assert index.completed_count == 2


def test_non_child_indices_excludes_workflow_children() -> None:
    parent = _agent(raw_suffix="parent")
    child = _agent(raw_suffix=None, parent_timestamp="parent")
    extra = _agent(raw_suffix="x")
    agents = [parent, child, extra]
    index = build_agent_panel_index(agents, dismissable_statuses=_DISMISSABLE)
    assert index.non_child_indices == [0, 2]
    assert index.non_child_total == 2
    # Position is 1-based via bisect_right semantics.
    assert index.non_child_position(0) == 1
    assert index.non_child_position(1) == 1  # child shares parent's position
    assert index.non_child_position(2) == 2


def test_slice_for_unknown_key_returns_empty_slice() -> None:
    index = AgentPanelIndex()
    empty = index.slice_for("missing")
    assert isinstance(empty, PanelSlice)
    assert empty.agents == []
    assert empty.global_indices == []
    assert empty.global_to_local == {}
