"""Quit confirmation modal with running background-task details."""

from __future__ import annotations

from datetime import datetime

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from sase.core.time import local_now

from ..task_queue import TaskInfo

_TASK_CARD_WIDTH = 52
_CHIP_TEXT_WIDTH = 6
_CHIP_CELL_WIDTH = _CHIP_TEXT_WIDTH + 2
_STATUS_GLYPH = "●"

_TYPE_CHIP_STYLES = {
    "sync": "bold white on blue",
    "mail": "bold white on magenta",
    "accept": "bold black on green",
    "launch": "bold black on cyan",
    "kill": "bold white on red",
    "dismiss": "bold black on yellow",
    "revert": "bold white on red",
    "submit": "bold black on green",
    "archive": "bold black on yellow",
    "restore": "bold black on cyan",
    "status": "bold white on blue",
}
_DEFAULT_TYPE_CHIP_STYLE = "bold black on cyan"


def _format_elapsed(started_at: datetime) -> str:
    """Return compact elapsed runtime for a running task."""
    now = datetime.now(started_at.tzinfo) if started_at.tzinfo else local_now()
    seconds = max(0, int((now - started_at).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        remainder = minutes % 60
        return f"{hours}h {remainder}m" if remainder else f"{hours}h"
    days = hours // 24
    remainder = hours % 24
    return f"{days}d {remainder}h" if remainder else f"{days}d"


def _truncate_plain(value: str, max_cells: int) -> str:
    """Collapse and truncate text to a fixed terminal cell width."""
    plain = " ".join(value.split())
    if cell_len(plain) <= max_cells:
        return plain
    if max_cells <= 3:
        return "." * max_cells

    limit = max_cells - 3
    out = ""
    for char in plain:
        if cell_len(out + char) > limit:
            break
        out += char
    return out.rstrip() + "..."


class QuitConfirmModal(ModalScreen[bool]):
    """Confirm quitting when tracked background tasks are still running."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("n", "cancel", "No"),
        Binding("N", "cancel", "No"),
        Binding("y", "confirm", "Yes"),
        Binding("Y", "confirm", "Yes"),
        Binding("j", "scroll_tasks_down", "Scroll down", priority=True),
        Binding("down", "scroll_tasks_down", "Scroll down", priority=True),
        Binding("k", "scroll_tasks_up", "Scroll up", priority=True),
        Binding("up", "scroll_tasks_up", "Scroll up", priority=True),
    ]

    def __init__(self, tasks: list[TaskInfo]) -> None:
        super().__init__()
        self.add_class("confirm-dialog")
        self._tasks = list(tasks)

    def compose(self) -> ComposeResult:
        dialog = Container(
            id="quit-confirm-container",
            classes="confirm-dialog-panel confirm-dialog--danger",
        )
        dialog.border_title = self._build_border_title()
        dialog.border_subtitle = "y quit & kill all · n/esc keep running · j/k scroll"
        with dialog:
            yield Static(self._summary_text(), id="quit-confirm-summary")
            with VerticalScroll(id="quit-confirm-procs"):
                for task in self._tasks:
                    yield Static(
                        self._task_card_text(task),
                        classes="quit-confirm-proc-card",
                    )
            with Horizontal(id="quit-confirm-buttons"):
                yield Button(
                    "Quit & kill all (y)",
                    id="confirm-btn",
                    variant="error",
                )
                yield Button(
                    "Keep running (n)",
                    id="cancel-btn",
                    variant="primary",
                )

    def on_mount(self) -> None:
        """Default focus to the safe action."""
        self.query_one("#cancel-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_scroll_tasks_down(self) -> None:
        self._scroll_tasks(3)

    def action_scroll_tasks_up(self) -> None:
        self._scroll_tasks(-3)

    def _scroll_tasks(self, rows: int) -> None:
        scroll = self.query_one("#quit-confirm-procs", VerticalScroll)
        scroll.scroll_relative(y=rows, animate=False)

    def _build_border_title(self) -> Text:
        title = Text()
        title.append("!", style="bold red")
        title.append("  Quit SASE?", style="bold")
        return title

    def _summary_text(self) -> Text:
        count = len(self._tasks)
        noun = "task" if count == 1 else "tasks"
        verb = "is" if count == 1 else "are"
        target_object = "it" if count == 1 else "them"
        target_subject = "it" if count == 1 else "they"
        finish = "finishes" if count == 1 else "finish"

        text = Text()
        text.append("!  ", style="bold yellow")
        text.append(f"{count} background {noun} {verb} still running.", style="bold")
        text.append(
            "\n   Quitting now will kill "
            f"{target_object} before {target_subject} {finish}.",
            style="dim",
        )
        return text

    def _task_card_text(self, task: TaskInfo) -> Text:
        task_type = task.task_type.strip().lower() or "task"
        chip = _truncate_plain(task_type.upper(), _CHIP_TEXT_WIDTH)
        elapsed = _format_elapsed(task.started_at)

        fixed_cells = 3 + 1 + _CHIP_CELL_WIDTH + 1 + cell_len(elapsed)
        label_width = max(12, _TASK_CARD_WIDTH - fixed_cells - 1)
        label = _truncate_plain(task.label, label_width)
        message = _truncate_plain(
            task.message or "No status message",
            _TASK_CARD_WIDTH - 3,
        )

        line = Text()
        line.append(f"{_STATUS_GLYPH}  ", style="bold yellow")
        line.append(label, style="bold")
        line.append(" " * max(1, label_width - cell_len(label) + 1))
        line.append(
            f" {chip:<{_CHIP_TEXT_WIDTH}} ",
            style=_TYPE_CHIP_STYLES.get(task_type, _DEFAULT_TYPE_CHIP_STYLE),
        )
        line.append(" ")
        line.append(" " * max(1, _TASK_CARD_WIDTH - line.cell_len - cell_len(elapsed)))
        line.append(elapsed, style="dim")

        text = Text()
        text.append_text(line)
        text.append(f"\n   {message}", style="dim")
        return text


__all__ = ["QuitConfirmModal"]
