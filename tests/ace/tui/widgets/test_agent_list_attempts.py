"""Tests for attempt-child row rendering in the Agents tab list."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType, AttemptRecord
from sase.ace.tui.widgets.agent_list import (
    _BANNER_ROW,
    AgentList,
    _compute_fold_annotation,
)

_BR = (_BANNER_ROW, None)


def _make_record(n: int, *, used_fallback: bool = False) -> AttemptRecord:
    return AttemptRecord(
        attempt_number=n,
        status="failed",
        start_epoch=1745337600.0 + n * 60,
        end_epoch=1745337660.0 + n * 60,
        model=None,
        used_fallback=used_fallback,
        error_snippet=f"boom {n}",
        error_full=f"boom {n} full",
        live_reply_path="/nonexistent/live_reply.md",
        timestamps_path="/nonexistent/live_reply_timestamps.jsonl",
    )


def _make_agent(
    *,
    attempt_history: list[AttemptRecord] | None = None,
    raw_suffix: str = "20260423140000",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/tmp/p.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 23, 14, 0, 0),
        raw_suffix=raw_suffix,
        attempt_history=attempt_history or [],
    )


def test_update_list_emits_attempt_rows_when_history_present() -> None:
    """An agent with two attempts produces 3 agent/attempt rows preceded by the project banner."""
    widget = AgentList()
    agent = _make_agent(attempt_history=[_make_record(1), _make_record(2)])
    widget.update_list([agent], current_idx=0)
    # Main panel: project banner + agent + 2 attempts.
    assert widget._row_entries == [_BR, (0, None), (0, 1), (0, 2)]


def test_update_list_no_attempts_keeps_single_agent_row() -> None:
    widget = AgentList()
    agent = _make_agent()
    widget.update_list([agent], current_idx=0)
    assert widget._row_entries == [_BR, (0, None)]


def test_resolve_row_returns_attempt_number_for_child_rows() -> None:
    widget = AgentList()
    agent = _make_agent(attempt_history=[_make_record(1)])
    widget.update_list([agent], current_idx=0)
    # Rows: 0=project banner, 1=agent, 2=attempt 1.
    assert widget._resolve_row(0) == (0, None, None)  # banner -> first agent
    assert widget._resolve_row(1) == (0, None, None)
    assert widget._resolve_row(2) == (0, 1, None)


def test_attempt_option_text_shows_number_and_snippet() -> None:
    widget = AgentList()
    record = _make_record(2)
    option = widget._format_attempt_option(
        _make_agent(),
        record,
        is_selected=False,
    )
    plain = option.prompt.plain  # type: ignore[union-attr]
    assert "Attempt 2" in plain
    assert "failed" in plain
    assert "boom 2" in plain


def test_attempt_option_id_is_stable() -> None:
    widget = AgentList()
    record = _make_record(3)
    agent = _make_agent(raw_suffix="20260101120000")
    option = widget._format_attempt_option(agent, record, is_selected=False)
    assert option.id == "attempt:20260101120000:3"


def test_attempt_option_text_includes_duration_tail() -> None:
    """Attempt rows append the elapsed duration on the right (end - start)."""
    widget = AgentList()
    record = _make_record(2)  # 60s duration
    option = widget._format_attempt_option(
        _make_agent(),
        record,
        is_selected=False,
    )
    plain = option.prompt.plain  # type: ignore[union-attr]
    assert plain.rstrip().endswith("1m")


def test_fold_annotation_adds_attempts_count() -> None:
    """Non-workflow agent with attempts shows ``(N attempts)`` annotation."""
    agent = _make_agent(attempt_history=[_make_record(1), _make_record(2)])
    annotation = _compute_fold_annotation(agent, {}, set(), set())
    assert annotation == " (2 attempts)"


def test_fold_annotation_empty_when_no_attempts_and_no_workflow() -> None:
    agent = _make_agent()
    annotation = _compute_fold_annotation(agent, {}, set(), set())
    assert annotation == ""


def test_highlight_selects_attempt_row_when_attempt_number_passed() -> None:
    widget = AgentList()
    agent = _make_agent(attempt_history=[_make_record(1), _make_record(2)])
    widget.update_list(
        [agent],
        current_idx=0,
        current_attempt_number=2,
    )
    # Rows: 0=project banner, 1=agent, 2=attempt 1, 3=attempt 2.
    assert widget.highlighted == 3


def test_highlight_selects_agent_row_when_attempt_number_is_none() -> None:
    widget = AgentList()
    agent = _make_agent(attempt_history=[_make_record(1)])
    widget.update_list(
        [agent],
        current_idx=0,
        current_attempt_number=None,
    )
    # Rows: 0=project banner, 1=agent, 2=attempt 1.
    assert widget.highlighted == 1


def test_update_list_skips_attempt_rows_for_workflow_children() -> None:
    """Workflow children share the parent's raw_suffix and attempt_history.

    Emitting attempt rows under each child both misattributes attempts
    (attempts belong to the workflow, not individual steps) and produces
    duplicate option IDs (``attempt:<raw_suffix>:<n>``) which crashes the
    OptionList with ``DuplicateID``.
    """
    widget = AgentList()
    history = [_make_record(1)]
    raw_suffix = "20260423142806"
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="pat_fix_far_past_1",
        project_file="/tmp/p.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 23, 14, 28, 6),
        raw_suffix=raw_suffix,
        appears_as_agent=True,
        attempt_history=history,
    )
    child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/p.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 23, 14, 28, 6),
        raw_suffix=raw_suffix,
        parent_workflow="pat_fix_far_past_1",
        parent_timestamp=raw_suffix,
        attempt_history=history,
    )

    widget.update_list([parent, child], current_idx=0)

    # Parent and child share grouping (child inherits via parent_timestamp),
    # so a single project banner precedes them both.
    assert widget._row_entries == [_BR, (0, None), (0, 1), (1, None)]
