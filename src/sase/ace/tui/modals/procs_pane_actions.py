"""Output rendering and user actions for the Admin Center Procs pane."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from sase.ace.hints import build_editor_args

from ..actions.clipboard import schedule_copy_delivery
from ..proc_queue import ProcInfo, ProcQueue
from .procs_pane_render import (
    BodyCache,
    is_active,
    output_body,
    output_footer,
    output_header,
)

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class ProcsPaneActionsMixin(_MixinBase):
    """Render task output and implement task/output actions."""

    if TYPE_CHECKING:
        _body_cache: BodyCache
        _spinner_index: int
        _tasks: list[ProcInfo]
        _user_scrolled: bool

        def _get_selected_task(self) -> ProcInfo | None: ...

        def _highlighted_row(self) -> int | None: ...

        def _kill_callback(self) -> Callable[[str], bool] | None: ...

        def _kill_store_task(self, task: ProcInfo) -> None: ...

        def _merged_tasks(self) -> list[ProcInfo]: ...

        def _rebuild_list(
            self,
            highlight_index: int | None = None,
            *,
            prior_identity: str | None = None,
        ) -> None: ...

        def _run_editor(self, editor_args: list[str]) -> None: ...

        def _selected_task_identity(self) -> str | None: ...

        def _proc_queue(self) -> ProcQueue | None: ...

    def _display_output(self, task: ProcInfo | None) -> None:
        """Render task output in the right pane."""
        title = self.query_one("#procs-output-title", Label)
        content = self.query_one("#procs-output-content", Static)

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

    def _output_text(self, task: ProcInfo) -> Text:
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
            scroll = self.query_one("#procs-output-scroll", VerticalScroll)
            self._force_scroll_output_to(0, scroll=scroll)
        except Exception:
            pass

    def _scroll_output_to_end(self) -> None:
        """Scroll the output pane to the bottom."""
        try:
            scroll = self.query_one("#procs-output-scroll", VerticalScroll)
            self._force_scroll_output_to(scroll.max_scroll_y, scroll=scroll)
        except Exception:
            pass

    def _display_task_live_output(self, task: ProcInfo) -> None:
        """Update the output pane with live output and scroll to bottom."""
        content = self.query_one("#procs-output-content", Static)
        content.update(self._output_text(task))
        if not self._user_scrolled:
            self._scroll_output_to_end()

    def action_dismiss_task(self) -> None:
        """Remove the selected completed task from the queue."""
        task = self._get_selected_task()
        queue = self._proc_queue()
        if task is None or queue is None or is_active(task):
            return
        if task.store_backed:
            self.notify(
                "Durable tasks age out with tasks.history_limit",
                severity="warning",
            )
            return
        queue.remove(task.proc_id)
        highlighted = self._highlighted_row()
        self._tasks = self._merged_tasks()
        self._rebuild_list(highlight_index=highlighted)

    def action_dismiss_all_done(self) -> None:
        """Remove all completed tasks from the queue."""
        queue = self._proc_queue()
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
            if kill_callback is not None and kill_callback(task.proc_id):
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

    def action_scroll_output_down(self) -> None:
        """Scroll the output pane down by half a page."""
        scroll = self.query_one("#procs-output-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        self._force_scroll_output_to(scroll.scroll_y + height // 2, scroll=scroll)
        if scroll.scroll_y >= scroll.max_scroll_y:
            self._user_scrolled = False

    def action_scroll_output_up(self) -> None:
        """Scroll the output pane up by half a page."""
        self._user_scrolled = True
        scroll = self.query_one("#procs-output-scroll", VerticalScroll)
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
            prefix=f"task_{task.proc_type}_{safe_label}_",
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
                self._run_editor(editor_args)
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

    def _force_scroll_output_to(
        self, y: float, *, scroll: VerticalScroll | None = None
    ) -> None:
        output_scroll = (
            scroll
            if scroll is not None
            else self.query_one("#procs-output-scroll", VerticalScroll)
        )
        target = max(0, min(int(y), int(output_scroll.max_scroll_y)))
        output_scroll._scroll_to(y=target, animate=False, force=True)  # noqa: SLF001


__all__ = ["ProcsPaneActionsMixin"]
