"""Tasks pane for the SASE Admin Center."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.hints import build_editor_args

from ..actions.clipboard import copy_to_system_clipboard
from ..task_queue import TaskInfo, TaskQueue


_STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "running": ("●", "bold green"),
    "success": ("✓", "bold cyan"),
    "error": ("✗", "bold red"),
}


def _relative_time(dt: datetime, *, now: datetime | None = None) -> str:
    """Format a datetime as a short relative time string."""
    reference = now if now is not None else datetime.now()
    delta = int((reference - dt).total_seconds())
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


class _TaskList(OptionList):
    """Task list that reserves vim top/bottom keys for the output pane."""

    BINDINGS = [
        ("g", "scroll_output_top", "Top"),
        ("G", "scroll_output_bottom", "Bottom"),
        ("shift+g", "scroll_output_bottom", "Bottom"),
        *OptionList.BINDINGS,
    ]

    async def handle_key(self, event: events.Key) -> bool:
        if self._handle_output_scroll_key(event):
            return True
        return await super().handle_key(event)

    def on_key(self, event: events.Key) -> None:
        self._handle_output_scroll_key(event)

    def _handle_output_scroll_key(self, event: events.Key) -> bool:
        character = getattr(event, "character", None)
        if event.key in ("G", "shift+g") or character == "G":
            event.prevent_default()
            event.stop()
            pane = self._pane()
            if pane is not None:
                pane.action_scroll_to_bottom()
            return True
        if event.key == "g":
            event.prevent_default()
            event.stop()
            pane = self._pane()
            if pane is not None:
                pane.action_scroll_to_top()
            return True
        return False

    def action_scroll_output_top(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane.action_scroll_to_top()

    def action_scroll_output_bottom(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane.action_scroll_to_bottom()

    def _pane(self) -> TasksPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, TasksPane):
                return node
            node = getattr(node, "parent", None)
        return None


class TasksPane(Vertical):
    """Two-panel live background-task monitor inside the Admin Center."""

    can_focus = False

    _option_list_id = "tasks-list"
    BINDINGS = [
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("d", "dismiss_task", "Dismiss"),
        ("D", "dismiss_all_done", "Dismiss All Done"),
        ("K", "kill_task", "Kill"),
        ("e", "edit_output", "Edit"),
        ("y", "copy_output", "Copy"),
        ("ctrl+d", "scroll_output_down", "Scroll Down"),
        ("ctrl+u", "scroll_output_up", "Scroll Up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
        ("shift+g", "scroll_to_bottom", "Bottom"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tasks: list[TaskInfo] = []
        self._last_statuses: dict[str, str] = {}
        self._user_scrolled = False
        self._syncing_options = False
        self._refresh_timer: Any | None = None

    def compose(self) -> ComposeResult:
        yield Label(self._title_text(), id="tasks-pane-title")
        with Horizontal(id="tasks-panels"):
            with Vertical(id="tasks-list-panel"):
                yield Label("Tasks", classes="config-region-header")
                yield _TaskList(id=self._option_list_id)
            with Vertical(id="tasks-output-panel"):
                yield Label(
                    "Output", classes="config-region-header", id="tasks-output-title"
                )
                with VerticalScroll(id="tasks-output-scroll"):
                    yield Static("", id="tasks-output-content", markup=False)
        yield Static(self._hints(), id="tasks-hints", markup=False)

    def on_mount(self) -> None:
        queue = self._task_queue()
        if queue is not None:
            queue.prune_old()
        self._refresh_snapshot(highlight_index=0)
        self._refresh_timer = self.set_interval(1, self._refresh_running_output)

    def on_unmount(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

    def focus_default(self) -> None:
        """Focus the task list and paint the latest snapshot on activation."""
        self._refresh_snapshot(highlight_index=0)
        option_list = self._option_list()
        if option_list is not None:
            option_list.focus()

    def _task_queue(self) -> TaskQueue | None:
        queue = getattr(self.app, "_task_queue", None)
        return queue if isinstance(queue, TaskQueue) else None

    def _kill_callback(self) -> Callable[[str], bool] | None:
        callback = getattr(self.app, "_kill_background_task", None)
        return callback if callable(callback) else None

    def _is_active_tab(self) -> bool:
        try:
            return getattr(self.screen, "_active_tab", None) == self.id
        except Exception:
            return False

    def _refresh_snapshot(self, *, highlight_index: int | None = None) -> None:
        queue = self._task_queue()
        self._tasks = queue.get_all() if queue is not None else []
        if not self._tasks:
            highlight_index = None
        self._rebuild_list(highlight_index=highlight_index)

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
        text.append(task.label, style="bold")
        time_ref = task.finished_at or task.started_at
        text.append(f"  {_relative_time(time_ref)}", style="dim")
        return text

    def _option_list(self) -> OptionList | None:
        try:
            return self.query_one(f"#{self._option_list_id}", OptionList)
        except Exception:
            return None

    def _get_selected_task(self) -> TaskInfo | None:
        """Return the task for the currently highlighted option."""
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(option_list.highlighted)
        except Exception:
            return None
        if option.id is None:
            return None
        try:
            idx = int(option.id)
        except ValueError:
            return None
        if 0 <= idx < len(self._tasks):
            return self._tasks[idx]
        return None

    def _display_output(self, task: TaskInfo | None) -> None:
        """Render task output in the right pane."""
        title = self.query_one("#tasks-output-title", Label)
        content = self.query_one("#tasks-output-content", Static)

        if task is None:
            title.update("Output")
            content.update(Text("No background tasks yet.", style="dim italic"))
            self._reset_output_scroll()
            return

        title.update(f"Output — {task.label}")
        content.update(self._output_text(task))
        if task.status == "running" and not self._user_scrolled:
            self._scroll_output_to_end()
        elif task.status != "running":
            self._reset_output_scroll()

    def _output_text(self, task: TaskInfo) -> Text:
        out = Text()
        if task.status == "running":
            live = task.get_live_output()
            if live:
                return Text.from_ansi(live)
            out.append("Task is running...", style="bold green")
            return out
        if task.status == "error" and task.error:
            out.append("Error: ", style="bold red")
            out.append(task.error, style="red")
            if task.output:
                out.append("\n\n")
                out.append(task.output)
            return out
        if task.output:
            out.append_text(Text.from_ansi(task.output))
            return out
        out.append(f"Completed: {task.message}", style="dim")
        return out

    def _reset_output_scroll(self) -> None:
        """Reset the output scroll pane to the top."""
        try:
            scroll = self.query_one("#tasks-output-scroll", VerticalScroll)
            self._force_scroll_output_to(0, scroll=scroll)
        except Exception:
            pass

    def _scroll_output_to_end(self) -> None:
        """Scroll the output pane to the bottom."""
        try:
            scroll = self.query_one("#tasks-output-scroll", VerticalScroll)
            self._force_scroll_output_to(scroll.max_scroll_y, scroll=scroll)
        except Exception:
            pass

    def _refresh_running_output(self) -> None:
        """Poll the task queue for status changes and live output."""
        if not self._is_active_tab():
            return

        queue = self._task_queue()
        if queue is None:
            self._tasks = []
        else:
            self._tasks = queue.get_all()
        new_statuses = self._status_snapshot()

        if self._last_statuses != new_statuses:
            highlighted = None
            option_list = self._option_list()
            if option_list is not None:
                highlighted = option_list.highlighted
            self._rebuild_list(highlight_index=highlighted)
            return

        self._update_title()
        task = self._get_selected_task()
        if task is not None and task.status == "running":
            self._display_task_live_output(task)

    def _display_task_live_output(self, task: TaskInfo) -> None:
        """Update the output pane with live output and scroll to bottom."""
        content = self.query_one("#tasks-output-content", Static)
        live = task.get_live_output()
        if live:
            content.update(Text.from_ansi(live))
        else:
            content.update(Text("Task is running...", style="bold green"))
        if not self._user_scrolled:
            self._scroll_output_to_end()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update the output pane when a different task is highlighted."""
        if self._syncing_options:
            return
        self._user_scrolled = False
        if event.option and event.option.id is not None:
            try:
                idx = int(event.option.id)
            except ValueError:
                return
            if 0 <= idx < len(self._tasks):
                self._display_output(self._tasks[idx])

    def action_next_option(self) -> None:
        """Move to next task."""
        option_list = self._option_list()
        if option_list is not None:
            option_list.action_cursor_down()

    def action_prev_option(self) -> None:
        """Move to previous task."""
        option_list = self._option_list()
        if option_list is not None:
            option_list.action_cursor_up()

    def action_dismiss_task(self) -> None:
        """Remove the selected completed task from the queue."""
        task = self._get_selected_task()
        queue = self._task_queue()
        if task is None or queue is None or task.status == "running":
            return
        queue.remove(task.task_id)
        self._tasks = queue.get_all()
        highlighted = 0
        option_list = self._option_list()
        if option_list is not None and option_list.highlighted is not None:
            highlighted = option_list.highlighted
        new_idx = min(highlighted, len(self._tasks) - 1) if self._tasks else None
        self._rebuild_list(highlight_index=new_idx)

    def action_dismiss_all_done(self) -> None:
        """Remove all completed tasks from the queue."""
        queue = self._task_queue()
        if queue is None:
            return
        queue.remove_completed()
        self._tasks = queue.get_all()
        self._rebuild_list(highlight_index=0 if self._tasks else None)

    def action_kill_task(self) -> None:
        """Kill the selected running task after confirmation."""
        task = self._get_selected_task()
        kill_callback = self._kill_callback()
        if task is None or task.status != "running" or kill_callback is None:
            return

        from .confirm_action_modal import ConfirmActionModal
        from .confirm_dialog import ConfirmKind

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            if kill_callback(task.task_id):
                queue = self._task_queue()
                self._tasks = queue.get_all() if queue is not None else []
                highlighted = 0
                option_list = self._option_list()
                if option_list is not None and option_list.highlighted is not None:
                    highlighted = option_list.highlighted
                new_idx = (
                    min(highlighted, len(self._tasks) - 1) if self._tasks else None
                )
                self._rebuild_list(highlight_index=new_idx)
                self.notify(f"Killed: {task.label}")

        self.app.push_screen(
            ConfirmActionModal(
                title="Kill Task",
                message=f"Kill running task: {task.label}?",
                kind=ConfirmKind.DANGER,
                confirm_label="Kill",
                cancel_label="Cancel",
            ),
            _on_confirm,
        )

    def action_scroll_output_down(self) -> None:
        """Scroll the output pane down by half a page."""
        scroll = self.query_one("#tasks-output-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        self._force_scroll_output_to(scroll.scroll_y + height // 2, scroll=scroll)
        if scroll.scroll_y >= scroll.max_scroll_y:
            self._user_scrolled = False

    def action_scroll_output_up(self) -> None:
        """Scroll the output pane up by half a page."""
        self._user_scrolled = True
        scroll = self.query_one("#tasks-output-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        self._force_scroll_output_to(scroll.scroll_y - height // 2, scroll=scroll)

    def action_scroll_to_top(self) -> None:
        """Scroll the output pane to the top."""
        self._user_scrolled = True
        self._reset_output_scroll()

    def action_scroll_to_bottom(self) -> None:
        """Scroll the output pane to the bottom."""
        self._user_scrolled = False
        self._scroll_output_to_end()

    def action_edit_output(self) -> None:
        """Open the selected task's output in $EDITOR."""
        task = self._get_selected_task()
        if task is None:
            return

        output = task.get_live_output()
        if not output:
            self.notify("No output available", severity="warning")
            return

        safe_label = task.label.replace("/", "_").replace(" ", "_")
        fd, path = tempfile.mkstemp(
            suffix=".log", prefix=f"task_{task.task_type}_{safe_label}_"
        )
        try:
            os.write(fd, output.encode())
        finally:
            os.close(fd)

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [path])

        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

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

    def _rebuild_list(self, highlight_index: int | None = None) -> None:
        """Rebuild the option list from current tasks."""
        self._user_scrolled = False
        self._last_statuses = self._status_snapshot()
        self._update_title()
        option_list = self._option_list()
        if option_list is None:
            return

        self._syncing_options = True
        try:
            option_list.clear_options()
            for option in self._create_options():
                option_list.add_option(option)
            if self._tasks and highlight_index is not None:
                option_list.highlighted = max(
                    0,
                    min(highlight_index, len(self._tasks) - 1),
                )
            elif not self._tasks:
                option_list.highlighted = None
        finally:
            self._syncing_options = False

        self._display_output(self._get_selected_task())
        if self._is_active_tab():
            option_list.focus()

    def _status_snapshot(self) -> dict[str, str]:
        return {task.task_id: task.status for task in self._tasks}

    def _update_title(self) -> None:
        try:
            self.query_one("#tasks-pane-title", Label).update(self._title_text())
        except Exception:
            pass

    def _title_text(self) -> str:
        running = sum(1 for task in self._tasks if task.status == "running")
        done = len(self._tasks) - running
        return f"Tasks  [{running} running · {done} done]"

    def _hints(self) -> str:
        return (
            "j/k: move   d/D: dismiss   K: kill   e: edit   y: copy   "
            "ctrl+d/u, g/G: scroll   [ / ]: tab   Esc: close"
        )

    def _force_scroll_output_to(
        self, y: float, *, scroll: VerticalScroll | None = None
    ) -> None:
        output_scroll = (
            scroll
            if scroll is not None
            else self.query_one("#tasks-output-scroll", VerticalScroll)
        )
        target = max(0, min(int(y), int(output_scroll.max_scroll_y)))
        output_scroll._scroll_to(y=target, animate=False, force=True)  # noqa: SLF001


__all__ = ["TasksPane", "_relative_time"]
