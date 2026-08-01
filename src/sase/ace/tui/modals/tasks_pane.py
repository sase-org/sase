"""Tasks pane for the SASE Admin Center.

The pane renders a merged view: in-memory tasks owned by this TUI stay
authoritative for live output, and rows read from the durable task store
fill in everything else — detached `sase task run` commands, epic launches,
session-attributed commands, and work from other sessions. Every store read happens on a thread worker
(see :mod:`.tasks_store_rows`); nothing in a render or keystroke path stats,
reads, or locks the store.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.hints import build_editor_args

from ..util.selection import ProgrammaticSelectionGuard, restore_selection_by_identity
from .config_center_session import TasksSessionState
from ..actions.clipboard import schedule_copy_delivery
from ..task_queue import TaskInfo, TaskQueue
from .tasks_pane_render import (
    BodyCache,
    cached_body_version,
    is_active,
    output_body,
    output_footer,
    output_header,
    task_row_label,
)
from .tasks_store_rows import (
    StoreTasksSnapshot,
    current_tui_session_id,
    kill_store_task,
    load_store_task_rows,
)

# Every fourth 0.25s tick, so the spinner keeps its cadence while the store
# is revalidated about once a second.
_STORE_RELOAD_TICKS = 4
_TASK_OPTION_PREFIX = "task__"


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
        ("a", "toggle_scope", "All Sessions"),
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

    def __init__(
        self,
        *,
        session_state: TasksSessionState | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._session_state = session_state or TasksSessionState()
        self._tasks: list[TaskInfo] = []
        self._last_statuses: dict[str, tuple[str, str | None, str]] = {}
        self._user_scrolled = False
        self._selection_guard = ProgrammaticSelectionGuard()
        self._refresh_timer: Any | None = None
        self._spinner_index = 0
        self._body_cache: BodyCache = {}
        self._all_sessions = self._session_state.all_sessions
        self._session_id: str | None = None
        self._store_rows: list[TaskInfo] = []
        self._store_mtime: float | None = None
        self._store_detail_id: str | None = None
        self._store_load_pending = False
        self._store_loaded_once = False
        self._tick_count = 0

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
        self._session_id = current_tui_session_id()
        self._refresh_snapshot()
        self._request_store_reload(force=True)
        self._refresh_timer = self.set_interval(0.25, self._refresh_running_output)

    def on_unmount(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

    def focus_default(self) -> None:
        """Focus the task list and paint the latest snapshot on activation."""
        self._refresh_snapshot()
        self._request_store_reload(force=True)
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

    def _merged_tasks(self) -> list[TaskInfo]:
        """Merge in-memory tasks with the store rows they do not shadow."""
        queue = self._task_queue()
        memory = queue.get_all() if queue is not None else []
        mirrored = {task.durable_task_id for task in memory if task.durable_task_id}
        merged = [
            *memory,
            *(row for row in self._store_rows if row.task_id not in mirrored),
        ]
        merged.sort(key=lambda task: task.started_at, reverse=True)
        return merged

    def _refresh_snapshot(
        self,
        *,
        highlight_index: int | None = None,
        prior_identity: str | None = None,
    ) -> None:
        self._tasks = self._merged_tasks()
        if not self._tasks:
            highlight_index = None
        self._rebuild_list(
            highlight_index=highlight_index,
            prior_identity=prior_identity,
        )

    def _create_options(self) -> list[Option]:
        """Create option list entries from current tasks."""
        return [
            Option(task_row_label(task), id=self._option_id_for_task(task))
            for task in self._tasks
        ]

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
        option_id = str(option.id)
        highlighted = option_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self._tasks):
            candidate = self._tasks[highlighted]
            if option_id in {
                self._option_id_for_task(candidate),
                f"{_TASK_OPTION_PREFIX}{candidate.task_id}",
            }:
                return candidate
        idx = self._task_index_for_option_id(option_id)
        if idx is None:
            return None
        if 0 <= idx < len(self._tasks):
            return self._tasks[idx]
        return None

    @staticmethod
    def _task_identity(task: TaskInfo) -> str:
        return task.durable_task_id or task.task_id

    def _option_id_for_task(self, task: TaskInfo) -> str:
        return f"{_TASK_OPTION_PREFIX}{self._task_identity(task)}"

    def _task_index_for_option_id(self, option_id: str) -> int | None:
        if not option_id.startswith(_TASK_OPTION_PREFIX):
            return None
        identity = option_id.removeprefix(_TASK_OPTION_PREFIX)
        for index, task in enumerate(self._tasks):
            # ``task_id`` remains a safe alias during the one rebuild where a
            # task has just gained its durable id.
            if self._task_identity(task) == identity or task.task_id == identity:
                return index
        return None

    def _rekey_task_identity(self, identity: str | None) -> str | None:
        if identity is None:
            return None
        for task in self._tasks:
            if task.task_id == identity and task.durable_task_id:
                self._session_state.task.rekey(identity, task.durable_task_id)
                return task.durable_task_id
        return identity

    def _highlighted_row(self) -> int | None:
        option_list = self._option_list()
        return option_list.highlighted if option_list is not None else None

    def _selected_task_identity(self) -> str | None:
        task = self._get_selected_task()
        return self._task_identity(task) if task is not None else None

    def _record_bookmark(
        self, index: int | None, *, authoritative: bool = True
    ) -> None:
        if index is None or not (0 <= index < len(self._tasks)):
            if authoritative:
                self._session_state.task.record(None, None)
            else:
                self._session_state.task.display(None, None)
            return
        task = self._tasks[index]
        identity = self._task_identity(task)
        if authoritative:
            self._session_state.task.record(identity, index)
        else:
            self._session_state.task.display(identity, index)

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
        if is_active(task) and not self._user_scrolled:
            self._scroll_output_to_end()
        elif not is_active(task):
            self._reset_output_scroll()

    def _output_text(self, task: TaskInfo) -> Text:
        out = Text()
        out.append_text(output_header(task, spinner_index=self._spinner_index))
        body = output_body(task, self._body_cache)
        if body.plain:
            out.append("\n")
            out.append_text(body)
        elif is_active(task):
            out.append("\nWorking...", style="dim italic")

        if not is_active(task):
            footer = output_footer(task)
            if footer.plain:
                out.append("\n")
                out.append_text(footer)
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

        # The renderer wraps this into its own frame count.
        self._spinner_index += 1
        self._tick_count += 1
        if self._tick_count % _STORE_RELOAD_TICKS == 0:
            self._request_store_reload()
        prior_identity = self._selected_task_identity()
        highlighted = self._highlighted_row()
        self._tasks = self._merged_tasks()
        new_statuses = self._status_snapshot()

        if self._last_statuses != new_statuses:
            self._rebuild_list(
                highlight_index=highlighted,
                prior_identity=prior_identity,
            )
            return

        self._update_title()
        task = self._get_selected_task()
        if task is not None and (
            is_active(task)
            or task.log.version != cached_body_version(task, self._body_cache)
        ):
            self._display_task_live_output(task)

    def _display_task_live_output(self, task: TaskInfo) -> None:
        """Update the output pane with live output and scroll to bottom."""
        content = self.query_one("#tasks-output-content", Static)
        content.update(self._output_text(task))
        if not self._user_scrolled:
            self._scroll_output_to_end()

    def _request_store_reload(self, *, force: bool = False) -> None:
        """Reload durable rows on a thread worker, never on the event loop."""
        if self._store_load_pending:
            return
        self._store_load_pending = True
        detail, following = self._detail_store_task()
        # A running detached task appends to its log without touching the
        # store, so following one has to bypass the mtime cache.
        use_cache = not force and not following
        known_mtime = self._store_mtime if use_cache else None
        known_detail = self._store_detail_id if use_cache else None
        session_id = self._session_id
        all_sessions = self._all_sessions

        def _load() -> None:
            snapshot: StoreTasksSnapshot | None
            try:
                snapshot = load_store_task_rows(
                    session_id=session_id,
                    all_sessions=all_sessions,
                    known_mtime=known_mtime,
                    known_detail_task_id=known_detail,
                    detail_task_id=detail,
                )
            except Exception:
                snapshot = None
            try:
                self.app.call_from_thread(self._apply_store_snapshot, snapshot)
            except Exception:
                self._store_load_pending = False

        self.run_worker(_load, thread=True, name="tasks-store-load", group="tasks")

    def _apply_store_snapshot(self, snapshot: StoreTasksSnapshot | None) -> None:
        """Apply an off-thread store read on the UI thread."""
        self._store_load_pending = False
        if snapshot is None:
            return
        if snapshot.all_sessions != self._all_sessions:
            # The scope changed while this read was in flight; its rows are
            # for the wrong scope, so drop them and read again.
            self._request_store_reload(force=True)
            return
        self._store_mtime = snapshot.mtime
        self._store_detail_id = snapshot.detail_task_id
        self._store_loaded_once = True
        if snapshot.unchanged:
            identity = self._session_state.task.identity
            if identity is not None and not any(
                self._task_identity(task) == identity for task in self._tasks
            ):
                self._rebuild_list(
                    highlight_index=self._highlighted_row(),
                    prior_identity=identity,
                )
            return
        prior_identity = self._selected_task_identity()
        highlighted = self._highlighted_row()
        self._store_rows = snapshot.rows
        self._tasks = self._merged_tasks()
        requested_identity = self._rekey_task_identity(
            self._session_state.task.identity
        )
        requested_missing = requested_identity is not None and not any(
            self._task_identity(task) == requested_identity for task in self._tasks
        )
        if self._last_statuses != self._status_snapshot() or requested_missing:
            self._rebuild_list(
                highlight_index=highlighted,
                prior_identity=prior_identity,
            )
            return
        self._update_title()
        task = self._get_selected_task()
        if task is not None and task.store_backed:
            self._display_task_live_output(task)

    def _detail_store_task(self) -> tuple[str | None, bool]:
        """Return the store row the output pane needs, and whether it is live."""
        task = self._get_selected_task()
        if task is None or not task.store_backed:
            return None, False
        return (task.durable_task_id or task.task_id), is_active(task)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update the output pane when a different task is highlighted."""
        if event.option and event.option.id is not None:
            current = self._get_selected_task()
            current_row = self._highlighted_row()
            if current is None or current_row is None:
                return
            event_option_id = str(event.option.id)
            if event_option_id not in {
                self._option_id_for_task(current),
                f"{_TASK_OPTION_PREFIX}{current.task_id}",
            }:
                return
            identity = self._task_identity(current)
            if self._selection_guard.should_ignore(
                identity,
                current_row,
                current_identity=identity,
                current_row=current_row,
            ):
                return
            if 0 <= current_row < len(self._tasks):
                self._user_scrolled = False
                task = self._tasks[current_row]
                self._record_bookmark(current_row)
                self._display_output(task)
                if task.store_backed and not task.output:
                    self._request_store_reload(force=True)

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

    def action_toggle_scope(self) -> None:
        """Toggle between this session's tasks and every session's."""
        prior_identity = self._selected_task_identity()
        highlighted = self._highlighted_row()
        self._all_sessions = not self._all_sessions
        self._session_state.all_sessions = self._all_sessions
        self._store_rows = []
        self._store_loaded_once = False
        self._request_store_reload(force=True)
        self._refresh_snapshot(
            highlight_index=highlighted,
            prior_identity=prior_identity,
        )
        scope = "all sessions" if self._all_sessions else "this session"
        self.notify(f"Tasks scope: {scope}")

    def action_dismiss_task(self) -> None:
        """Remove the selected completed task from the queue."""
        task = self._get_selected_task()
        queue = self._task_queue()
        if task is None or queue is None or is_active(task):
            return
        if task.store_backed:
            self.notify(
                "Durable tasks age out with tasks.history_limit",
                severity="warning",
            )
            return
        queue.remove(task.task_id)
        highlighted = self._highlighted_row()
        self._tasks = self._merged_tasks()
        self._rebuild_list(highlight_index=highlighted)

    def action_dismiss_all_done(self) -> None:
        """Remove all completed tasks from the queue."""
        queue = self._task_queue()
        if queue is None:
            return
        queue.remove_completed()
        prior_identity = self._selected_task_identity()
        highlighted = self._highlighted_row()
        self._tasks = self._merged_tasks()
        self._rebuild_list(highlight_index=highlighted, prior_identity=prior_identity)

    def action_kill_task(self) -> None:
        """Kill the selected running task after confirmation."""
        task = self._get_selected_task()
        if task is None or not is_active(task):
            return
        kill_callback = self._kill_callback()
        if not task.store_backed and kill_callback is None:
            return

        from .confirm_action_modal import ConfirmActionModal
        from .confirm_dialog import ConfirmKind

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            if task.store_backed:
                self._kill_store_task(task)
                return
            if kill_callback is not None and kill_callback(task.task_id):
                highlighted = self._highlighted_row()
                self._tasks = self._merged_tasks()
                self._rebuild_list(highlight_index=highlighted)
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

    def _kill_store_task(self, task: TaskInfo) -> None:
        """Signal a durable task off the event loop, then reload the store."""
        task_id = task.durable_task_id or task.task_id
        label = task.label

        def _kill() -> None:
            error = kill_store_task(task_id)
            try:
                self.app.call_from_thread(self._on_store_kill_finished, label, error)
            except Exception:
                pass

        self.run_worker(_kill, thread=True, name="tasks-store-kill", group="tasks")

    def _on_store_kill_finished(self, label: str, error: str | None) -> None:
        if error is None:
            self.notify(f"Killed: {label}")
        else:
            self.notify(f"Kill failed: {error}", severity="error")
        self._request_store_reload(force=True)

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

        from sase.core.paths import get_sase_managed_tmpdir

        safe_label = task.label.replace("/", "_").replace(" ", "_")
        fd, path = tempfile.mkstemp(
            suffix=".log",
            prefix=f"task_{task.task_type}_{safe_label}_",
            dir=get_sase_managed_tmpdir("editors"),
        )
        try:
            try:
                os.write(fd, output.encode())
            finally:
                os.close(fd)

            editor = os.environ.get("EDITOR") or "nvim"
            editor_args = build_editor_args(editor, [path])

            with self.app.suspend():  # type: ignore[attr-defined]
                subprocess.run(editor_args, check=False)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

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
        schedule_copy_delivery(
            self,
            output,
            copied_label=f"task output ({line_count} lines)",
            task_name="sase-copy-task-output",
        )

    def _rebuild_list(
        self,
        highlight_index: int | None = None,
        *,
        prior_identity: str | None = None,
    ) -> None:
        """Rebuild the option list from current tasks."""
        self._user_scrolled = False
        self._last_statuses = self._status_snapshot()
        self._update_title()
        option_list = self._option_list()
        if option_list is None:
            return

        self._selection_guard.clear()
        identity = self._rekey_task_identity(
            prior_identity or self._session_state.task.identity
        )
        selected_index: int | None = None
        pending_missing_bookmark = (
            identity is not None
            and not any(self._task_identity(task) == identity for task in self._tasks)
            and (self._store_load_pending or not self._store_loaded_once)
        )
        option_list.clear_options()
        for option in self._create_options():
            option_list.add_option(option)
        if self._tasks:
            index = restore_selection_by_identity(
                self._tasks,
                prior_identity=identity,
                prior_visual_row=(
                    highlight_index
                    if highlight_index is not None
                    else self._session_state.task.row
                ),
                identity_fn=self._task_identity,
            )
            selected_identity = self._task_identity(self._tasks[index])
            self._selection_guard.prepare(selected_identity, index)
            option_list.highlighted = index
            selected_index = index
        else:
            option_list.highlighted = None
        self._record_bookmark(
            selected_index,
            authoritative=not pending_missing_bookmark,
        )

        self._display_output(self._get_selected_task())
        if self._is_active_tab():
            option_list.focus()

    def _status_snapshot(self) -> dict[str, tuple[str, str | None, str]]:
        return {
            self._task_identity(task): (task.status, task.phase, task.message)
            for task in self._tasks
        }

    def _update_title(self) -> None:
        try:
            self.query_one("#tasks-pane-title", Label).update(self._title_text())
        except Exception:
            pass

    def _title_text(self) -> str:
        running = sum(1 for task in self._tasks if is_active(task))
        done = len(self._tasks) - running
        scope = "all sessions" if self._all_sessions else "this session"
        return f"Tasks · {scope}  [{running} running · {done} done]"

    def _hints(self) -> str:
        return (
            "j/k: move  a: scope  d/D: dismiss  K: kill  e: edit  y: copy  "
            "ctrl+d/u, g/G: scroll  Tab: tab  Esc: close"
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


__all__ = ["TasksPane"]
