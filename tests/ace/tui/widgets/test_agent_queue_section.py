"""Tests for the bounded runner-slot queue detail ladder."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_runner_slots import (
    RunnerCapacitySnapshot,
    RunnerQueueEntry,
    refresh_runner_slot_context,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_header_renderable import (
    AgentHeader,
)
from sase.ace.tui.widgets.prompt_panel._agent_queue_section import (
    _queue_window,
    runner_queue_selection,
)


def _agent(
    name: str,
    *,
    position: int | None,
    size: int | None,
    threshold: int | None = 9,
    explicit: bool = False,
    priority: int | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/project/project.sase",
        status="QUEUED",
        start_time=datetime(2026, 7, 25, 12, 0),
        raw_suffix=name,
        agent_name=name,
        pid=100,
        artifacts_dir=f"/tmp/project/artifacts/ace-run/{name}",
        wait_runners=threshold,
        wait_runners_explicit=explicit,
        wait_priority=priority,
        slot_requested_at="2026-07-25T12:00:00Z",
        runner_slots_in_use=10,
        runner_slot_queue_position=position,
        runner_slot_queue_size=size,
    )


def _entry(
    name: str,
    *,
    threshold: int | None = 9,
    explicit: bool = False,
    priority: int = 10,
    requested_at: str = "2026-07-25T12:00:00Z",
) -> RunnerQueueEntry:
    return RunnerQueueEntry(
        identity=(AgentType.RUNNING, name, name),
        presented_name=name,
        threshold=threshold,
        wait_runners_explicit=explicit,
        priority=priority,
        slot_requested_at=requested_at,
        status="QUEUED",
    )


def _header(
    agent: Agent,
    queue: tuple[RunnerQueueEntry, ...],
) -> AgentHeader:
    header, _ = build_header_text(
        agent,
        cheap=True,
        runner_capacity=RunnerCapacitySnapshot(
            effective_limit=10,
            slots_in_use=10,
            queued_count=len(queue),
            queue=queue,
        ),
    )
    return header


def _style_at(text: AgentHeader, needle: str) -> str | None:
    position = text.plain.rindex(needle)
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return None


def test_queue_window_renders_short_queue_whole_and_long_queue_with_gaps() -> None:
    short = tuple(_entry(f"agent-{index}") for index in range(7))
    assert [row.rank for row in _queue_window(short, 3)] == list(range(1, 8))
    assert all(row.hidden_count == 0 for row in _queue_window(short, 3))

    long = tuple(_entry(f"agent-{index}") for index in range(10))
    window = _queue_window(long, 5)
    assert [
        row.rank if row.rank is not None else f"+{row.hidden_count}" for row in window
    ] == [1, "+2", 4, 5, 6, 7, 8, "+2"]


def test_ahead_count_uses_selected_threshold_and_treats_missing_as_zero() -> None:
    queue = (
        _entry("drain", threshold=0),
        _entry("equal-a", threshold=5),
        _entry("equal-b", threshold=5),
        _entry("selected", threshold=5),
    )
    selected = _agent("selected", position=4, size=4, threshold=5)
    selection = runner_queue_selection(
        selected,
        RunnerCapacitySnapshot(queue=queue),
    )
    assert selection is not None
    assert selection.ahead_count == 2

    missing_queue = (*queue[:-1], _entry("missing", threshold=None))
    missing = _agent("missing", position=4, size=4, threshold=None)
    missing_selection = runner_queue_selection(
        missing,
        RunnerCapacitySnapshot(queue=missing_queue),
    )
    assert missing_selection is not None
    assert missing_selection.ahead_count == 3


def test_queue_field_renders_front_label_and_section_requires_real_position() -> None:
    selected = _agent("selected", position=1, size=1)
    header = _header(selected, (_entry("selected"),))
    assert "Queue: #1 of 1 · at the front · " in header.plain
    assert " in queue" in header.plain
    assert "❖ QUEUE · 1 waiting · 10/10 runners" in header.plain

    without_position = _agent("selected", position=None, size=None)
    no_queue = _header(without_position, (_entry("selected"),))
    assert "❖ QUEUE" not in no_queue.plain


def test_explicit_threshold_waiter_gets_the_same_queue_ladder() -> None:
    selected = _agent(
        "barrier",
        position=1,
        size=1,
        threshold=0,
        explicit=True,
    )
    selected.status = "WAITING"
    header = _header(
        selected,
        (_entry("barrier", threshold=0, explicit=True),),
    )

    assert "Wait: [runners] ≤ 0 (drain barrier)" in header.plain
    assert "❖ QUEUE · 1 waiting · 10/1 runners" in header.plain
    assert "≤0" in header.plain


def test_queue_ladder_demotes_deeper_barrier_and_marks_selected_rank() -> None:
    queue = (
        _entry("drain-barrier", threshold=0, explicit=True),
        _entry("eligible-first", threshold=9),
        _entry("selected", threshold=9),
    )
    header = _header(
        _agent("selected", position=3, size=3),
        queue,
    )

    assert "Queue: #3 of 3 · 1 ahead · " in header.plain
    assert _style_at(header, "#1") == "#AF87FF"
    assert _style_at(header, "drain-barrier") == "dim #FFD700"
    assert _style_at(header, "#2") == "#5F87FF"
    assert _style_at(header, "#3") == "bold black on #5F87FF"


def test_queue_qualifiers_render_only_where_they_explain_ordering() -> None:
    default_queue = (
        _entry("first"),
        _entry("selected"),
    )
    default_header = _header(
        _agent("selected", position=2, size=2),
        default_queue,
    )
    assert "p10" not in default_header.plain
    assert "≤" not in default_header.plain

    qualified_queue = (
        _entry("barrier", threshold=0, explicit=True),
        _entry("priority-jump", priority=5),
        _entry("selected"),
    )
    qualified_header = _header(
        _agent("selected", position=3, size=3),
        qualified_queue,
    )
    assert qualified_header.plain.count("≤0") == 1
    assert qualified_header.plain.count("p5") == 1
    assert "p10" not in qualified_header.plain


def test_snapshot_queue_order_is_the_same_order_assigned_to_row_ranks() -> None:
    agents = [
        _agent("late", position=None, size=None, priority=20),
        _agent("urgent", position=None, size=None, priority=1),
        _agent("default", position=None, size=None),
    ]
    agents[0].slot_requested_at = "2026-07-25T12:00:00Z"
    agents[1].slot_requested_at = "2026-07-25T12:02:00Z"
    agents[2].slot_requested_at = "2026-07-25T12:01:00Z"

    capacity = refresh_runner_slot_context(agents, effective_limit=10)

    positions = {agent.identity: agent.runner_slot_queue_position for agent in agents}
    assert [positions[entry.identity] for entry in capacity.queue] == list(
        range(1, len(capacity.queue) + 1)
    )
