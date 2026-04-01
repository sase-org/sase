"""Task queue modal for viewing background task history and output."""

from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.hints import build_editor_args

from ..actions.clipboard import copy_to_system_clipboard
from ..task_queue import TaskQueue, TaskInfo
from .base import OptionListNavigationMixin


# Status icon and style mapping
_STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "running": ("●", "bold green"),
    "success": ("✓", "bold cyan"),
    "error": ("✗", "bold red"),
}


def _relative_time(dt: datetime) -> str:
    """Format a datetime as a short relative time string."""
    delta = int((datetime.now() - dt).total_seconds())
    if delta < 0:
        return "just now"
    if delta < 60:
        return f"{delta}s ago"
    minutes = delta // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


class TaskQueueModal(OptionListNavigationMixin, ModalScreen[None]):
    """Modal for viewing background task history and output."""

    _option_list_id = "task-queue-list"
    BINDINGS = [
        *(
            b
            for b in OptionListNavigationMixin.NAVIGATION_BINDINGS
            if b[0] not in ("ctrl+n", "ctrl+p")
        ),
        ("d", "dismiss_task", "Dismiss"),
        ("D", "dismiss_all_done", "Dismiss All Done"),
        ("e", "edit_output", "Edit"),
        ("y", "copy_output", "Copy"),
        ("ctrl+d", "scroll_output_down", "Scroll down"),
        ("ctrl+u", "scroll_output_up", "Scroll up"),
    ]

    def __init__(self, task_queue: TaskQueue) -> None:
        super().__init__()
        self._task_queue = task_queue
        # Prune old tasks on open
        self._task_queue.prune_old()
        self._tasks: list[TaskInfo] = self._task_queue.get_all()

    def compose(self) -> ComposeResult:
        with Container(id="task-queue-container"):
            yield Label("Task Queue", id="task-queue-title")
            with Horizontal(id="task-queue-panels"):
                with Vertical(id="task-queue-left"):
                    if self._tasks:
                        yield OptionList(
                            *self._create_options(),
                            id="task-queue-list",
                        )
                    else:
                        yield Static(
                            "No tasks",
                            id="task-queue-empty",
                        )
                with Vertical(id="task-queue-right"):
                    yield Label("Output", id="task-queue-output-title")
                    with VerticalScroll(id="task-queue-output-scroll"):
                        yield Static(id="task-queue-output-content")
            yield Label(
                "j/k: navigate  d: dismiss  D: dismiss all done  e: edit  y: copy  Ctrl+D/U: scroll  q: close",
                id="task-queue-hints",
            )

    def _create_options(self) -> list[Option]:
        """Create option list entries from current tasks."""
        return [
            Option(self._create_task_label(task), id=str(i))
            for i, task in enumerate(self._tasks)
        ]

    def _create_task_label(self, task: TaskInfo) -> Text:
        """Create styled text for a single task row."""
        icon, icon_style = _STATUS_DISPLAY.get(task.status, ("?", "dim"))
        text = Text()
        text.append(f"{icon} ", style=icon_style)
        text.append(task.task_type, style="bold")
        text.append(f" {task.cl_name}", style="")
        time_ref = task.finished_at or task.started_at
        text.append(f"  {_relative_time(time_ref)}", style="dim")
        return text

    def _get_selected_task(self) -> TaskInfo | None:
        """Return the task for the currently highlighted option."""
        try:
            option_list = self.query_one("#task-queue-list", OptionList)
            highlighted = option_list.highlighted
            if highlighted is not None:
                option = option_list.get_option_at_index(highlighted)
                if option.id is not None:
                    idx = int(option.id)
                    if 0 <= idx < len(self._tasks):
                        return self._tasks[idx]
        except Exception:
            pass
        return None

    def _display_output(self, task: TaskInfo | None) -> None:
        """Render task output in the right pane."""
        title = self.query_one("#task-queue-output-title", Label)
        content = self.query_one("#task-queue-output-content", Static)

        if task is None:
            title.update("Output")
            content.update("")
            return

        title.update(f"Output — {task.task_type} {task.cl_name}")

        out = Text()
        if task.status == "running":
            live = task.get_live_output()
            if live:
                out = Text.from_ansi(live)
            else:
                out.append("Task is running...", style="bold green")
        elif task.status == "error" and task.error:
            out.append("Error: ", style="bold red")
            out.append(task.error, style="red")
            if task.output:
                out.append("\n\n")
                out.append(task.output)
        elif task.output:
            out.append_text(Text.from_ansi(task.output))
        else:
            out.append(f"Completed: {task.message}", style="dim")

        content.update(out)
        if task.status == "running":
            self._scroll_output_to_end()
        else:
            self._reset_output_scroll()

    def _reset_output_scroll(self) -> None:
        """Reset the output scroll pane to the top."""
        try:
            scroll = self.query_one("#task-queue-output-scroll", VerticalScroll)
            scroll.scroll_home(animate=False)
        except Exception:
            pass

    def _scroll_output_to_end(self) -> None:
        """Scroll the output pane to the bottom."""
        try:
            scroll = self.query_one("#task-queue-output-scroll", VerticalScroll)
            scroll.scroll_end(animate=False)
        except Exception:
            pass

    # -- Event handlers -------------------------------------------------------

    def on_mount(self) -> None:
        """Focus the option list on mount and display initial output."""
        try:
            option_list = self.query_one("#task-queue-list", OptionList)
            option_list.focus()
        except Exception:
            pass

        if self._tasks:
            self._display_output(self._tasks[0])

        self._refresh_timer = self.set_interval(1, self._refresh_running_output)

    def on_unmount(self) -> None:
        """Stop the refresh timer on unmount."""
        if hasattr(self, "_refresh_timer"):
            self._refresh_timer.stop()

    def _refresh_running_output(self) -> None:
        """Poll the task queue for status changes and live output."""
        old_statuses = {t.task_id: t.status for t in self._tasks}
        self._tasks = self._task_queue.get_all()
        new_statuses = {t.task_id: t.status for t in self._tasks}

        # Rebuild the list if any status changed or the task count changed
        if old_statuses != new_statuses:
            highlighted = None
            try:
                option_list = self.query_one("#task-queue-list", OptionList)
                highlighted = option_list.highlighted
            except Exception:
                pass
            self._rebuild_list(highlight_index=highlighted)
            return

        # Otherwise just refresh the output pane for the selected task
        task = self._get_selected_task()
        if task is not None and task.status == "running":
            self._display_task_live_output(task)

    def _display_task_live_output(self, task: TaskInfo) -> None:
        """Update the output pane with live output and scroll to bottom."""
        content = self.query_one("#task-queue-output-content", Static)
        live = task.get_live_output()
        if live:
            content.update(Text.from_ansi(live))
        else:
            content.update(Text("Task is running...", style="bold green"))
        try:
            scroll = self.query_one("#task-queue-output-scroll", VerticalScroll)
            scroll.scroll_end(animate=False)
        except Exception:
            pass

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update the right pane when a different task is highlighted."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._tasks):
                self._display_output(self._tasks[idx])

    # -- Actions --------------------------------------------------------------

    def action_dismiss_task(self) -> None:
        """Remove the selected completed task from the queue."""
        task = self._get_selected_task()
        if task is None or task.status == "running":
            return
        self._task_queue.remove(task.task_id)
        self._tasks = self._task_queue.get_all()
        highlighted = self.query_one("#task-queue-list", OptionList).highlighted
        new_idx = min(highlighted or 0, len(self._tasks) - 1) if self._tasks else None
        self._rebuild_list(highlight_index=new_idx)

    def action_dismiss_all_done(self) -> None:
        """Remove all completed tasks from the queue."""
        self._task_queue.remove_completed()
        self._tasks = self._task_queue.get_all()
        new_idx = 0 if self._tasks else None
        self._rebuild_list(highlight_index=new_idx)

    def action_scroll_output_down(self) -> None:
        """Scroll the output pane down by half a page."""
        scroll = self.query_one("#task-queue-output-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_output_up(self) -> None:
        """Scroll the output pane up by half a page."""
        scroll = self.query_one("#task-queue-output-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def action_edit_output(self) -> None:
        """Open the selected task's output in $EDITOR."""
        task = self._get_selected_task()
        if task is None:
            return

        output = task.get_live_output()
        if not output:
            self.notify("No output available", severity="warning")
            return

        fd, path = tempfile.mkstemp(
            suffix=".log", prefix=f"task_{task.task_type}_{task.cl_name}_"
        )
        try:
            os.write(fd, output.encode())
        finally:
            os.close(fd)

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [path])

        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

        # Refresh output display (task may have progressed while in editor)
        self._display_output(self._get_selected_task())

    def action_copy_output(self) -> None:
        """Copy the selected task's output to the system clipboard."""
        task = self._get_selected_task()
        if task is None:
            return

        output = task.get_live_output()
        if not output:
            self.notify("No output available", severity="warning")
            return

        line_count = output.count("\n") + (1 if not output.endswith("\n") else 0)
        if copy_to_system_clipboard(output):
            self.notify(f"Copied: task output ({line_count} lines)")
        else:
            self.notify("Copy failed — clipboard tool not available", severity="error")

    # -- List rebuild ---------------------------------------------------------

    def _rebuild_list(self, highlight_index: int | None = None) -> None:
        """Rebuild the option list from current tasks."""
        try:
            option_list = self.query_one("#task-queue-list", OptionList)
        except Exception:
            return

        option_list.clear_options()

        if not self._tasks:
            option_list.add_class("hidden")
            try:
                self.query_one("#task-queue-empty", Static)
            except Exception:
                left_panel = self.query_one("#task-queue-left", Vertical)
                left_panel.mount(Static("No tasks", id="task-queue-empty"))
            self._display_output(None)
            return

        # Remove empty placeholder if it exists
        try:
            empty = self.query_one("#task-queue-empty", Static)
            empty.remove()
        except Exception:
            pass
        option_list.remove_class("hidden")

        for option in self._create_options():
            option_list.add_option(option)

        if highlight_index is not None:
            option_list.highlighted = highlight_index

        task = self._get_selected_task()
        self._display_output(task)
