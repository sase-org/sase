"""Pure collapsed Agents-panel summary projection tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panel_summary import (
    build_agent_panel_summary_snapshot,
)
from sase.ace.tui.widgets.agent_panel_summary import _build_agent_panel_summary_text


_NOW = datetime(2026, 7, 17, 15, 0, 0)


def _agent(
    name: str,
    status: str,
    *,
    suffix: str,
    parent: str | None = None,
    workflow_child: bool = False,
    model: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/sase/sase.sase",
        project_display_name="SASE",
        status=status,
        start_time=datetime(2026, 7, 17, 14, 0, 0),
        stop_time=_NOW if status in {"DONE", "FAILED"} else None,
        raw_suffix=suffix,
        parent_timestamp=parent,
        parent_workflow="workflow" if workflow_child else None,
        model=model,
    )


def test_snapshot_labels_counts_priority_and_nested_rows() -> None:
    done = _agent("done", "DONE", suffix="done")
    running = _agent("running", "RUNNING", suffix="running", model="gpt-5")
    child = _agent(
        "running_child",
        "WAITING",
        suffix="child",
        parent="running",
        workflow_child=True,
    )
    failed = _agent("failed", "FAILED", suffix="failed")
    stopped = _agent("stopped", "QUESTION", suffix="stopped")
    unread = _agent("unread", "DONE", suffix="unread")
    agents = [done, running, child, failed, stopped, unread]

    snapshot = build_agent_panel_summary_snapshot(
        "focus",
        agents,
        unread_ids={unread.identity},
        marked_ids={failed.identity},
        now=_NOW,
    )

    assert snapshot.label == "#focus"
    assert (snapshot.entry_count, snapshot.root_count, snapshot.nested_count) == (
        6,
        5,
        1,
    )
    assert snapshot.counts.stopped == 1
    assert snapshot.counts.running == 1
    assert snapshot.counts.waiting == 0  # nested rows do not inflate title totals
    assert snapshot.counts.failed == 1
    assert snapshot.counts.unread == 1
    assert snapshot.counts.done == 1
    assert [row.display_name for row in snapshot.rows] == [
        "stopped",
        "failed",
        "running",
        "running_child",
        "unread",
        "done",
    ]
    assert snapshot.rows[1].is_marked is True
    assert snapshot.rows[3].depth == 1
    assert snapshot.rows[4].is_unread is True
    assert snapshot.rows[2].model == "gpt-5"
    rendered = _build_agent_panel_summary_text(snapshot).plain
    assert "[✓]" in rendered
    assert "✅" in rendered


def test_untagged_snapshot_and_rendering_are_zero_suppressed_and_complete() -> None:
    rows = [
        _agent(f"agent_{index}", "RUNNING", suffix=str(index)) for index in range(75)
    ]
    snapshot = build_agent_panel_summary_snapshot(None, rows, now=_NOW)

    rendered = _build_agent_panel_summary_text(snapshot).plain

    assert snapshot.label == "(untagged)"
    assert "[R75]" in rendered
    assert "S0" not in rendered
    assert "F0" not in rendered
    assert "75 agents" in rendered
    assert "agent_0" in rendered
    assert "agent_74" in rendered


def test_parallel_family_counts_match_panel_title_projection() -> None:
    root = _agent("parallel", "RUNNING", suffix="root")
    done = _agent("parallel_done", "DONE", suffix="done", parent="root")
    done.agent_family_parallel = True
    failed = _agent("parallel_failed", "FAILED", suffix="failed", parent="root")
    failed.agent_family_parallel = True
    waiting = _agent("parallel_waiting", "WAITING", suffix="waiting", parent="root")
    waiting.agent_family_parallel = True
    root.runtime_children = [done, failed, waiting]

    snapshot = build_agent_panel_summary_snapshot(
        "parallel",
        [root, done, failed, waiting],
        unread_ids={done.identity},
        now=_NOW,
    )

    assert snapshot.counts.unread == 1
    assert snapshot.counts.failed == 1
    assert snapshot.counts.waiting == 1
    assert snapshot.counts.running == 0
    assert snapshot.counts.done == 0
