"""Always-populated gate and summary detail panes for the notification modal."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.notification_gates.models import GateError, GateInputField, validate_color
from sase.notification_gates.paths import resolve_notification_bundle
from sase.notification_gates.presentation import gate_chip_from_action_data
from sase.notification_gates.summary import (
    GateSummary,
    GateSummaryBranch,
    GateSummaryOption,
    gate_summary_from_notification,
    load_gate_summary,
)
from sase.notifications import Notification, format_relative_until

from .gate_primary_footer import primary_action_badge_for_label
from .notification_modal_constants import ACTION_BADGES
from .notification_modal_palette import (
    PANE_ACCENT,
    PANE_ANSWERED,
    PANE_AWAITING,
    PANE_ERROR,
    PANE_KEY,
    PANE_MUTED,
    PANE_RULE,
    PANE_WARN,
)
from .notification_modal_tags import notification_display_tags, shorten_notification_tag

_TERMINAL_STATUSES = frozenset({"answered", "cancelled", "timed_out"})
_STATUS_ROW_RIGHT_MAX_CELLS = 40
_GateSummaryCacheEntry = tuple[tuple[int, ...], GateSummary]


class NotificationGateMixin:
    """Render a live decision card for every gate-backed notification."""

    def _render_gate_pane(
        self: Any, notification: Notification
    ) -> tuple[str, RenderableType] | None:
        """Return the gate pane title and content, or ``None`` for a non-gate row."""
        cache: dict[str, _GateSummaryCacheEntry] = getattr(
            self, "_gate_summary_cache", {}
        )
        cached = cache.get(notification.id)
        loading = cached is None
        summary = (
            cached[1]
            if cached is not None
            else gate_summary_from_notification(notification)
        )
        if summary is None:
            return None

        self._schedule_gate_summary_refresh(notification.id)

        renderables: list[RenderableType] = [_status_row(summary), _meta_row(summary)]
        chip_row = _chip_row(notification)
        if chip_row is not None:
            renderables.append(chip_row)
        if loading:
            renderables.append(Text("loading decision…", style=f"{PANE_MUTED} italic"))
        renderables.append(Text(""))
        renderables.extend(_context_group(notification))
        renderables.extend(_decision_group(summary))
        attachments = _attachments_group(self, summary)
        if attachments:
            renderables.append(Text(""))
            renderables.extend(attachments)
        errors = _errors_group(summary)
        if errors:
            renderables.append(Text(""))
            renderables.extend(errors)

        return summary.title, Group(*renderables)

    def _schedule_gate_summary_refresh(self: Any, notification_id: str) -> None:
        """Debounce bundle enrichment so a burst of highlight moves loads once."""
        debouncer = getattr(self, "_gate_summary_debouncer", None)
        if debouncer is None:
            return
        debouncer.schedule(lambda: self._spawn_gate_summary_task(notification_id))

    def _spawn_gate_summary_task(self: Any, notification_id: str) -> None:
        """Fire the off-pump enrichment task; the debounce callback stays thin."""
        spawn_pump_free_task(
            self,
            self._load_gate_summary(notification_id),
            name=f"gate-summary:{notification_id}",
            registry_attr="_gate_summary_tasks",
        )

    async def _load_gate_summary(self: Any, notification_id: str) -> None:
        """Enrich the cached gate summary for one notification off the UI thread."""
        notification = next(
            (n for n in self._notifications if n.id == notification_id), None
        )
        if notification is None:
            return
        cached = self._gate_summary_cache.get(notification_id)
        resolved = await asyncio.to_thread(_resolve_gate_summary, notification, cached)
        if resolved is None:
            return
        self._gate_summary_cache[notification_id] = resolved
        current = self._get_highlighted_notification()
        if current is not None and current.id == notification_id:
            self._display_file(current)


class NotificationSummaryMixin:
    """Render a compact summary card for every other notification row."""

    def _render_summary_pane(
        self: Any, notification: Notification
    ) -> tuple[str, RenderableType]:
        """Return the summary pane title and content; this never returns ``None``."""
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(ratio=1)
        grid.add_column(justify="right")
        badge = ACTION_BADGES.get(notification.action, "")
        grid.add_row(
            Text(notification.sender, style="bold"),
            Text(badge, style=f"bold {PANE_ACCENT}") if badge else Text(""),
        )

        renderables: list[RenderableType] = [grid, Text("")]
        renderables.extend(_context_group(notification))
        renderables.append(Text(""))
        if notification.files:
            total = len(notification.files)
            current = getattr(self, "_current_file_index", 0)
            index = min(max(current, 0), total - 1) + 1
            name = os.path.basename(notification.files[index - 1])
            renderables.append(
                Text(f"{index}/{total} · {name}   C-n · C-p", style=PANE_MUTED)
            )
        else:
            renderables.append(Text("no attachments", style=PANE_MUTED))

        return "Notification", Group(*renderables)


def _status_row(summary: GateSummary) -> Table:
    left = Text()
    right = Text(justify="right")
    if summary.status == "pending":
        left.append("● Awaiting your decision", style=f"bold {PANE_AWAITING}")
        right.append("press Enter to review", style=f"bold {PANE_KEY}")
    elif summary.status == "answered":
        left.append("✓ Answered", style=f"bold {PANE_ANSWERED}")
        labels = ", ".join(
            option.label
            for branch in summary.branches
            for option in branch.options
            if option.selected
        )
        chosen_text = f"you chose {labels}" if labels else "response recorded"
        right = Text(chosen_text, justify="right", style=PANE_MUTED, no_wrap=True)
        right.truncate(_STATUS_ROW_RIGHT_MAX_CELLS, overflow="ellipsis")
    elif summary.status == "cancelled":
        left.append("⊘ Cancelled", style=f"bold {PANE_MUTED}")
        right.append("no longer actionable", style=PANE_MUTED)
    elif summary.status == "timed_out":
        left.append("⧗ Timed out", style=f"bold {PANE_WARN}")
        right.append("the deadline passed", style=PANE_MUTED)
    elif summary.status == "overdue":
        left.append("● Awaiting your decision", style=f"bold {PANE_WARN}")
        right.append("past its deadline", style=PANE_MUTED)
    else:
        left.append("▲ Gate details unavailable", style=f"bold {PANE_ERROR}")
        right.append("press d to debug", style=PANE_KEY)

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(ratio=1)
    table.add_column(justify="right")
    table.add_row(left, right)
    return table


def _meta_row(summary: GateSummary) -> Table:
    left = Text(style=PANE_MUTED)
    if summary.unavailable_reason:
        left.append(summary.unavailable_reason)
    elif summary.status == "pending" and summary.deadline_at:
        left.append(f"expires in {format_relative_until(summary.deadline_at)}")
    right = Text(f"{summary.kind} gate · {summary.request_id}", style=PANE_MUTED)

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(ratio=1)
    table.add_column(justify="right")
    table.add_row(left, right)
    return table


def _chip_style(color: str | None) -> str:
    """Foreground-only style; a malformed colour degrades to uncoloured bold."""
    try:
        validated = validate_color(color, "presentation.chip")
    except (AttributeError, GateError, TypeError):
        validated = None
    if validated is None:
        return "bold"
    return f"bold {validated}"


def _chip_row(notification: Notification) -> Table | None:
    """Return the identity chip row, or ``None`` when no chip was declared."""
    chip = gate_chip_from_action_data(notification.action_data)
    if chip is None:
        return None
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(ratio=1)
    table.add_row(Text(f"{chip.glyph} {chip.label}", style=_chip_style(chip.color)))
    return table


def _context_group(notification: Notification) -> list[RenderableType]:
    parts: list[RenderableType] = []
    if notification.notes:
        parts.append(Text("\n".join(notification.notes)))
    else:
        parts.append(Text("No context was provided.", style=f"{PANE_MUTED} italic"))

    tags = notification_display_tags(notification)
    if tags:
        tag_line = Text()
        for index, tag in enumerate(tags):
            if index:
                tag_line.append("  ")
            tag_line.append(
                f"#{shorten_notification_tag(tag)}", style=f"{PANE_MUTED} {PANE_KEY}"
            )
        parts.append(tag_line)
    return parts


def _decision_group(summary: GateSummary) -> list[RenderableType]:
    if not summary.branches:
        return []
    parts: list[RenderableType] = [Rule(style=PANE_RULE)]

    header = Table.grid(expand=True, padding=(0, 1))
    header.add_column(ratio=1)
    header.add_column(justify="right")
    header.add_row(
        Text("Decision", style="bold"), Text(summary.query, style=PANE_MUTED)
    )
    parts.append(header)

    terminal = summary.status in _TERMINAL_STATUSES
    for index, branch in enumerate(summary.branches, start=1):
        parts.append(_branch_block(branch, index, terminal))

    if summary.feedback:
        parts.append(Text("Note", style="bold"))
        parts.append(Text(summary.feedback))
    return parts


def _branch_block(
    branch: GateSummaryBranch, index: int, terminal: bool
) -> RenderableType:
    chosen = any(option.selected for option in branch.options)
    header_left = Text()
    header_left.append("▸ " if branch.is_primary else "  ")
    header_left.append(f"{index} ")
    if branch.icon:
        header_left.append(f"{branch.icon} ")
    header_left.append(
        branch.label, style=PANE_MUTED if (terminal and not chosen) else "bold"
    )

    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(justify="right")
    if branch.is_primary:
        grid.add_row(header_left, primary_action_badge_for_label(branch.label, "enter"))
    else:
        grid.add_row(header_left, Text(""))

    multi = len(branch.options) > 1
    for option in branch.options:
        grid.add_row(*_option_row(option, multi=multi))
        for line in _option_input_lines(option, terminal=terminal):
            grid.add_row(line, Text(""))
    return grid


def _option_row(option: GateSummaryOption, *, multi: bool) -> tuple[Text, Text]:
    left = Text("     ")
    if option.selected:
        left.append("● ", style=f"bold {PANE_ANSWERED}")
    elif multi:
        left.append("☑ " if option.default_selected else "☐ ")
    left.append(option.label)
    if option.argv:
        left.append(f"  · {' '.join(option.argv)}", style=PANE_MUTED)

    right = Text()
    if option.feedback != "disabled":
        note = "✎ note required" if option.feedback == "required" else "✎ note optional"
        right.append(note, style=f"{PANE_MUTED} italic")
    return left, right


def _option_input_lines(option: GateSummaryOption, *, terminal: bool) -> list[Text]:
    """Declared fields before an answer; submitted values after one.

    ``feedback`` is skipped here even when it rides along as an ordinary
    declared field, because the pane already shows it in the "Note" section.
    """
    if terminal:
        if not option.selected or not option.submitted_input:
            return []
        labels = {field.id: field.label for field in option.input_fields}
        return [
            _submitted_input_line(labels.get(field_id, field_id), value)
            for field_id, value in option.submitted_input.items()
            if field_id != "feedback"
        ]
    return [
        _declared_input_line(field)
        for field in option.input_fields
        if field.id != "feedback"
    ]


def _declared_input_line(field: GateInputField) -> Text:
    line = Text("       ", style=f"{PANE_MUTED} italic")
    line.append(field.label)
    line.append(f" ({field.type.value})", style=PANE_MUTED)
    if field.required:
        line.append(" · required", style=PANE_MUTED)
    return line


def _submitted_input_line(label: str, value: object) -> Text:
    line = Text("       ", style=PANE_MUTED)
    line.append(f"{label}: ")
    line.append(_render_submitted_value(value), style="bold")
    return line


def _render_submitted_value(value: object) -> str:
    if isinstance(value, Mapping) and value.get("$redacted") is True:
        return "••• (redacted)"
    if isinstance(value, list):
        return ", ".join(_render_submitted_value(item) for item in value)
    return str(value)


def _attachments_group(self: Any, summary: GateSummary) -> list[RenderableType]:
    if not summary.attachments:
        return []
    total = len(summary.attachments)
    current = getattr(self, "_current_file_index", 0)
    index = min(max(current, 0), total - 1) + 1
    name = summary.attachments[index - 1]

    line = Text()
    line.append(f"{index}/{total} · {name}", style=PANE_MUTED)
    line.append("   C-n · C-p", style=PANE_MUTED)
    return [Text("Attachments", style="bold"), line]


def _errors_group(summary: GateSummary) -> list[RenderableType]:
    if summary.error_count <= 0:
        return []
    return [
        Text(
            f"▲ {summary.error_count} command error(s) — press d to debug",
            style=f"bold {PANE_ERROR}",
        )
    ]


def _resolve_gate_summary(
    notification: Notification, cached: _GateSummaryCacheEntry | None
) -> _GateSummaryCacheEntry | None:
    """Off-pump worker: recompute the bundle fingerprint and reload if it changed.

    Runs in a worker thread via ``asyncio.to_thread`` — never on the UI thread.
    """
    bundle = resolve_notification_bundle(notification)
    if bundle is None:
        fingerprint: tuple[int, ...] = ()
    else:
        fingerprint = (
            _mtime_ns(bundle.request),
            _mtime_ns(bundle.response),
            _mtime_ns(bundle.cancellation),
        )
    if cached is not None and cached[0] == fingerprint:
        return None
    summary = load_gate_summary(notification)
    if summary is None:
        return None
    return fingerprint, summary


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


__all__ = ["NotificationGateMixin", "NotificationSummaryMixin"]
