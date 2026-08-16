"""Task-list selection and rendering for the Admin Center Tasks pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual import events
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from ..proc_observer import ObservedProc, ProcProjection
from ..util.selection import restore_selection_by_identity
from .pane_entry_jump import apply_jump_hint_prefix
from .procs_pane_render import is_active, task_row_label

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from .procs_pane import ProcsPane
else:
    _MixinBase = object

_TASK_OPTION_PREFIX = "task__"


class TaskList(OptionList):
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
        pane = self._pane()
        # ``g`` and ``G`` are ordinary hint characters while the pane paints
        # jump hints, so the pane's jump handler gets them instead of the
        # output scroller.
        if pane is not None and pane.jump_mode_active:
            return False
        character = getattr(event, "character", None)
        if event.key in ("G", "shift+g") or character == "G":
            event.prevent_default()
            event.stop()
            if pane is not None:
                pane.action_scroll_to_bottom()
            return True
        if event.key == "g":
            event.prevent_default()
            event.stop()
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

    def _pane(self) -> ProcsPane | None:
        from .procs_pane import ProcsPane

        node: object | None = self.parent
        while node is not None:
            if isinstance(node, ProcsPane):
                return node
            node = getattr(node, "parent", None)
        return None


class ProcsPaneSelectionMixin(_MixinBase):
    """Manage merged task rows, selection restoration, and list rendering."""

    if TYPE_CHECKING:
        _all_sessions: bool
        _last_statuses: dict[str, tuple[str, str | None, str]]
        _option_list_id: str
        _session_state: object
        _store_loaded_once: bool
        _tasks: list[ObservedProc]
        _user_scrolled: bool

        def _display_output(self, task: ObservedProc | None) -> None: ...

        def _is_active_tab(self) -> bool: ...

        def _request_store_reload(self, *, force: bool = False) -> None: ...

        def _proc_projection(self) -> ProcProjection: ...

        def invalidate_jump_hints(
            self, *, identities_changed: bool, target_count: int
        ) -> None: ...

        def jump_hint_for(self, index: int) -> str | None: ...

    def _merged_tasks(self) -> list[ObservedProc]:
        """Return observer rows in the pane's current scope."""
        return self._proc_projection().scoped_rows(all_sessions=self._all_sessions)

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
            Option(
                self._render_task_label(index, task), id=self._option_id_for_task(task)
            )
            for index, task in enumerate(self._tasks)
        ]

    def _render_task_label(self, index: int, task: ObservedProc) -> Text:
        label = task_row_label(task)
        hint = self.jump_hint_for(index)
        if hint is None:
            return label
        return apply_jump_hint_prefix(label, hint)

    def _option_list(self) -> OptionList | None:
        try:
            return self.query_one(f"#{self._option_list_id}", OptionList)
        except Exception:
            return None

    def _get_selected_task(self) -> ObservedProc | None:
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
                f"{_TASK_OPTION_PREFIX}{candidate.proc_id}",
            }:
                return candidate
        idx = self._task_index_for_option_id(option_id)
        if idx is None:
            return None
        if 0 <= idx < len(self._tasks):
            return self._tasks[idx]
        return None

    @staticmethod
    def _task_identity(task: ObservedProc) -> str:
        return task.durable_proc_id or task.proc_id

    def _option_id_for_task(self, task: ObservedProc) -> str:
        return f"{_TASK_OPTION_PREFIX}{self._task_identity(task)}"

    def _task_index_for_option_id(self, option_id: str) -> int | None:
        if not option_id.startswith(_TASK_OPTION_PREFIX):
            return None
        identity = option_id.removeprefix(_TASK_OPTION_PREFIX)
        for index, task in enumerate(self._tasks):
            # ``proc_id`` remains a safe alias during the one rebuild where a
            # task has just gained its durable id.
            if self._task_identity(task) == identity or task.proc_id == identity:
                return index
        return None

    def _rekey_task_identity(self, identity: str | None) -> str | None:
        if identity is None:
            return None
        for task in self._tasks:
            if task.proc_id == identity and task.durable_proc_id:
                self._session_state.task.rekey(identity, task.durable_proc_id)  # type: ignore[attr-defined]
                return task.durable_proc_id
        return identity

    def _highlighted_row(self) -> int | None:
        option_list = self._option_list()
        return option_list.highlighted if option_list is not None else None

    def _selected_task_identity(self) -> str | None:
        task = self._get_selected_task()
        return self._task_identity(task) if task is not None else None

    def _restore_target(self) -> tuple[str | None, int | None]:
        """Return the entry a rebuild must restore: request beats stand-in."""
        bookmark = self._session_state.task  # type: ignore[attr-defined]
        if bookmark.provisional:
            return bookmark.identity, bookmark.row
        return self._selected_task_identity(), self._highlighted_row()

    def _record_bookmark(
        self, index: int | None, *, authoritative: bool = True
    ) -> None:
        bookmark = self._session_state.task  # type: ignore[attr-defined]
        if index is None or not (0 <= index < len(self._tasks)):
            if authoritative:
                bookmark.record(None, None)
            else:
                bookmark.display(None, None)
            return
        task = self._tasks[index]
        identity = self._task_identity(task)
        if authoritative:
            bookmark.record(identity, index)
        else:
            bookmark.display(identity, index)

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
                f"{_TASK_OPTION_PREFIX}{current.proc_id}",
            }:
                return
            identity = self._task_identity(current)
            if self._selection_guard.should_ignore(  # type: ignore[attr-defined]
                identity,
                current_row,
                current_identity=identity,
                current_row=current_row,
            ):
                return
            if 0 <= current_row < len(self._tasks):
                self._user_scrolled = False
                task = self._tasks[current_row]
                bookmark = self._session_state.task  # type: ignore[attr-defined]
                stand_in_echo = bookmark.provisional and (identity, current_row) == (
                    bookmark.displayed_identity,
                    bookmark.displayed_row,
                )
                self._record_bookmark(current_row, authoritative=not stand_in_echo)
                self._display_output(task)
                if not task.output:
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

        previous_ids = [
            option_list.get_option_at_index(i).id
            for i in range(option_list.option_count)
        ]
        next_ids = [self._option_id_for_task(task) for task in self._tasks]
        self.invalidate_jump_hints(
            identities_changed=previous_ids != next_ids,
            target_count=len(self._tasks),
        )

        self._selection_guard.clear()  # type: ignore[attr-defined]
        bookmark = self._session_state.task  # type: ignore[attr-defined]
        identity = self._rekey_task_identity(prior_identity or bookmark.identity)
        selected_index: int | None = None
        pending_missing_bookmark = (
            not any(self._task_identity(task) == identity for task in self._tasks)
            and not self._store_loaded_once
        )
        option_list.clear_options()
        for option in self._create_options():
            option_list.add_option(option)
        if self._tasks:
            index = restore_selection_by_identity(
                self._tasks,
                prior_identity=identity,
                prior_visual_row=(
                    highlight_index if highlight_index is not None else bookmark.row
                ),
                identity_fn=self._task_identity,
            )
            selected_identity = self._task_identity(self._tasks[index])
            self._selection_guard.prepare(selected_identity, index)  # type: ignore[attr-defined]
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
            self.query_one("#procs-pane-title", Label).update(self._title_text())
        except Exception:
            pass

    def _title_text(self) -> str:
        running = sum(1 for task in self._tasks if is_active(task))
        done = len(self._tasks) - running
        scope = "all sessions" if self._all_sessions else "this session"
        return f"Procs · {scope}  [{running} running · {done} done]"


__all__ = ["ProcsPaneSelectionMixin", "TaskList"]
