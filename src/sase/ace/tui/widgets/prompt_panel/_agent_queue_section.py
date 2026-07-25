"""Pure in-memory rendering for runner-slot queue context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from rich.cells import cell_len
from rich.text import Text

from sase.agent.status_buckets import QUEUED_STATUS_COLOR
from sase.core.runner_slots import DEFAULT_WAIT_PRIORITY
from sase.core.time import local_now

from ...models.agent import Agent, format_compact_duration, wait_display_agent
from ...models.agent_runner_slots import (
    RunnerCapacitySnapshot,
    RunnerQueueEntry,
)
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from ._helpers import append_section_heading

_QUEUE_RULE = "━" * 50
_QUEUE_SECTION_ID = "queue"
_QUEUE_NAME_WIDTH = 18
_PARKED_COLOR = "#AF87FF"


@dataclass(frozen=True, slots=True)
class _RunnerQueueSelection:
    """Selected waiter's immutable position and admission context."""

    queue: tuple[RunnerQueueEntry, ...]
    index: int
    ahead_count: int


@dataclass(frozen=True, slots=True)
class _QueueWindowRow:
    rank: int | None = None
    entry: RunnerQueueEntry | None = None
    hidden_count: int = 0


def runner_queue_selection(
    agent: Agent,
    capacity: RunnerCapacitySnapshot | None,
) -> _RunnerQueueSelection | None:
    """Resolve *agent* against the one preordered queue used for its rank."""
    wait_agent = wait_display_agent(agent)
    if capacity is None or wait_agent.runner_slot_queue_position is None:
        return None
    selected_index = next(
        (
            index
            for index, entry in enumerate(capacity.queue)
            if entry.identity == wait_agent.identity
        ),
        None,
    )
    if selected_index is None:
        return None
    selected_threshold = _threshold(capacity.queue[selected_index])
    ahead_count = sum(
        _threshold(entry) >= selected_threshold
        for entry in capacity.queue[:selected_index]
    )
    return _RunnerQueueSelection(
        queue=capacity.queue,
        index=selected_index,
        ahead_count=ahead_count,
    )


def append_runner_queue_section(
    text: Text,
    agent: Agent,
    selection: _RunnerQueueSelection | None,
) -> None:
    """Append the selected waiter's bounded queue ladder, when available."""
    if selection is None:
        return

    wait_agent = wait_display_agent(agent)
    queue = selection.queue
    text.append("\n")
    text.append(_QUEUE_RULE + "\n", style=f"bold {QUEUED_STATUS_COLOR}")
    heading = Text()
    heading.append("❖ ", style=f"bold {QUEUED_STATUS_COLOR}")
    heading.append(
        "QUEUE",
        style=f"bold {QUEUED_STATUS_COLOR} underline",
    )
    heading.append(f" · {len(queue)} waiting", style="dim")
    if wait_agent.runner_slots_in_use is not None:
        if wait_agent.wait_runners is not None:
            heading.append(
                (
                    f" · {wait_agent.runner_slots_in_use}/"
                    f"{wait_agent.wait_runners + 1} runners"
                ),
                style="dim",
            )
        else:
            heading.append(
                f" · {wait_agent.runner_slots_in_use} runners",
                style="dim",
            )
    append_section_heading(text, heading, section_id=_QUEUE_SECTION_ID)

    threshold_width = max(
        (
            cell_len(f"≤{_threshold(entry)}")
            for entry in queue
            if entry.wait_runners_explicit
        ),
        default=0,
    )
    priority_width = max(
        (
            cell_len(f"p{entry.priority}")
            for entry in queue
            if entry.priority != DEFAULT_WAIT_PRIORITY
        ),
        default=0,
    )
    selected_threshold = _threshold(queue[selection.index])
    now = local_now()
    for row in _queue_window(queue, selection.index):
        if row.entry is None or row.rank is None:
            text.append(f"   … +{row.hidden_count} more\n", style="dim italic")
            continue
        _append_queue_entry(
            text,
            row.entry,
            rank=row.rank,
            queue_size=len(queue),
            selected_index=selection.index,
            selected_threshold=selected_threshold,
            threshold_width=threshold_width,
            priority_width=priority_width,
            now=now,
        )


def _queue_window(
    queue: tuple[RunnerQueueEntry, ...],
    selected_index: int,
) -> tuple[_QueueWindowRow, ...]:
    if len(queue) <= 7:
        return tuple(
            _QueueWindowRow(rank=index + 1, entry=entry)
            for index, entry in enumerate(queue)
        )

    visible = {0}
    visible.update(
        range(
            max(0, selected_index - 2),
            min(len(queue), selected_index + 3),
        )
    )
    rows: list[_QueueWindowRow] = []
    previous_index = -1
    for index in sorted(visible):
        hidden_count = index - previous_index - 1
        if hidden_count:
            rows.append(_QueueWindowRow(hidden_count=hidden_count))
        rows.append(_QueueWindowRow(rank=index + 1, entry=queue[index]))
        previous_index = index
    hidden_count = len(queue) - previous_index - 1
    if hidden_count:
        rows.append(_QueueWindowRow(hidden_count=hidden_count))
    return tuple(rows)


def _append_queue_entry(
    text: Text,
    entry: RunnerQueueEntry,
    *,
    rank: int,
    queue_size: int,
    selected_index: int,
    selected_threshold: int,
    threshold_width: int,
    priority_width: int,
    now: datetime,
) -> None:
    index = rank - 1
    rank_label = f"#{rank}"
    rank_width = cell_len(f"#{queue_size}")
    if index == selected_index:
        text.append(
            f" {rank_label.rjust(rank_width)} ",
            style=f"bold black on {QUEUED_STATUS_COLOR}",
        )
        name_style = f"bold {_AGENT_NAME_ANNOTATION_STYLE}"
    else:
        text.append("   ")
        if index < selected_index:
            if _threshold(entry) >= selected_threshold:
                rank_style = QUEUED_STATUS_COLOR
            else:
                rank_style = _PARKED_COLOR
        else:
            rank_style = "dim"
        text.append(rank_label.rjust(rank_width), style=rank_style)
        text.append(" ")
        name_style = (
            f"dim {_AGENT_NAME_ANNOTATION_STYLE}"
            if index < selected_index and rank_style == _PARKED_COLOR
            else _AGENT_NAME_ANNOTATION_STYLE
        )

    name = Text(entry.presented_name, style=name_style)
    name.truncate(_QUEUE_NAME_WIDTH, overflow="ellipsis", pad=True)
    text.append_text(name)
    if threshold_width:
        text.append(" ")
        threshold_label = f"≤{_threshold(entry)}" if entry.wait_runners_explicit else ""
        text.append(
            threshold_label.ljust(threshold_width),
            style=_PARKED_COLOR if threshold_label else None,
        )
    if priority_width:
        text.append(" ")
        priority_label = (
            f"p{entry.priority}" if entry.priority != DEFAULT_WAIT_PRIORITY else ""
        )
        text.append(
            priority_label.ljust(priority_width),
            style="dim" if priority_label else None,
        )
    text.append(" ")
    text.append(
        _queue_duration(entry.slot_requested_at, now),
        style="dim",
    )
    text.append("\n")


def _threshold(entry: RunnerQueueEntry) -> int:
    return entry.threshold if entry.threshold is not None else 0


def _queue_duration(requested_at: str | None, now: datetime) -> str:
    if not requested_at:
        return "?"
    try:
        requested = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
    except ValueError:
        return "?"
    if requested.tzinfo is None:
        requested = requested.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    elapsed = max(0.0, (now - requested.astimezone(now.tzinfo)).total_seconds())
    return format_compact_duration(elapsed)
