"""Tests for ``AgentList.try_remove_rows`` (Phase 4 of tui_perf_v2)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets.agent_list import AgentList


def _agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/repo/proj.gp",
    agent_name: str | None = None,
    raw_suffix: str = "20260425143000",
    status: str = "RUNNING",
    agent_type: AgentType = AgentType.RUNNING,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file=project_file,
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=agent_name,
        raw_suffix=raw_suffix,
    )


def _wire(monkeypatch: Any) -> AgentList:
    widget = AgentList()

    def _call_later(callback: Callable[[], None]) -> None:
        callback()

    monkeypatch.setattr(widget, "call_later", _call_later)
    monkeypatch.setattr(widget, "post_message", lambda _msg: None)
    return widget


def test_try_remove_rows_drops_targeted_row(monkeypatch: Any) -> None:
    widget = _wire(monkeypatch)
    agents = [_agent(raw_suffix=f"a{i}") for i in range(3)]
    widget.update_list(agents, current_idx=0)
    initial_options = widget.option_count

    ok = widget.try_remove_rows({agents[1].identity})

    assert ok is True
    assert widget.option_count == initial_options - 1
    # The remaining widget._agents shifts the indices.
    remaining_ids = [a.identity for a in widget._agents]
    assert remaining_ids == [agents[0].identity, agents[2].identity]
    # Row trackers stay coherent under the new local indices.
    for new_local in range(len(widget._agents)):
        assert new_local in widget._row_by_agent_idx


def test_try_remove_rows_returns_true_for_unknown_identity(monkeypatch: Any) -> None:
    widget = _wire(monkeypatch)
    agents = [_agent(raw_suffix=f"a{i}") for i in range(2)]
    widget.update_list(agents, current_idx=0)

    fake = (AgentType.RUNNING, "ghost", "20991231235959")
    options_before = widget.option_count
    ok = widget.try_remove_rows({fake})

    # No matching row -> nothing to remove, but no fallback either.
    assert ok is True
    assert widget.option_count == options_before


def test_try_remove_rows_bails_when_grouping_not_standard(monkeypatch: Any) -> None:
    widget = _wire(monkeypatch)
    agents = [_agent(raw_suffix=f"a{i}") for i in range(3)]
    widget.update_list(agents, current_idx=0, grouping_mode=GroupingMode.BY_STATUS)
    options_before = widget.option_count

    ok = widget.try_remove_rows({agents[0].identity})

    assert ok is False
    assert widget.option_count == options_before


def test_try_remove_rows_bails_for_workflow_parent_with_children(
    monkeypatch: Any,
) -> None:
    widget = _wire(monkeypatch)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="wf_parent",
        project_file="/repo/proj.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        workflow="wf",
        raw_suffix="20260425120000",
    )
    child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="step_one",
        project_file=parent.project_file,
        status="DONE",
        start_time=datetime(2026, 4, 25, 12, 1, 0),
        raw_suffix="20260425120100",
        parent_timestamp=parent.raw_suffix,
        parent_workflow=parent.workflow,
    )
    widget.update_list([parent, child], current_idx=0)
    options_before = widget.option_count

    ok = widget.try_remove_rows({parent.identity})

    assert ok is False
    assert widget.option_count == options_before


def test_try_remove_rows_preserves_other_row_lookups(monkeypatch: Any) -> None:
    widget = _wire(monkeypatch)
    agents = [_agent(raw_suffix=f"a{i}") for i in range(5)]
    widget.update_list(agents, current_idx=0)

    ok = widget.try_remove_rows({agents[2].identity})
    assert ok is True

    expected_ids = [agents[0], agents[1], agents[3], agents[4]]
    for new_local, agent in enumerate(expected_ids):
        row = widget._row_by_agent_idx[new_local]
        # Banner-aware row indexing must produce a non-banner entry for
        # surviving agents.
        assert widget._row_entries[row][0] == new_local
        assert widget._agents[new_local].identity == agent.identity
