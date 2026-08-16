"""Observer synchronization for the Admin Center Procs pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.proc_observer import ObservedProc

from .procs_pane_render import BodyCache, cached_body_version, is_active

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class ProcsPaneStoreMixin(_MixinBase):
    """Poll the observer projection and operate on durable proc rows."""

    if TYPE_CHECKING:
        _all_sessions: bool
        _body_cache: BodyCache
        _last_statuses: dict[str, tuple[str, str | None, str]]
        _session_state: object
        _spinner_index: int
        _store_detail_id: str | None
        _store_loaded_once: bool
        _tasks: list[ObservedProc]
        _tick_count: int
        _user_scrolled: bool

        def _display_task_live_output(self, task: ObservedProc) -> None: ...

        def _get_selected_task(self) -> ObservedProc | None: ...

        def _highlighted_row(self) -> int | None: ...

        def _is_active_tab(self) -> bool: ...

        def _merged_tasks(self) -> list[ObservedProc]: ...

        def _rebuild_list(
            self,
            highlight_index: int | None = None,
            *,
            prior_identity: str | None = None,
        ) -> None: ...

        def _refresh_snapshot(
            self,
            *,
            highlight_index: int | None = None,
            prior_identity: str | None = None,
        ) -> None: ...

        def _restore_target(self) -> tuple[str | None, int | None]: ...

        def _selected_task_identity(self) -> str | None: ...

        def _signal_store_task(self, proc_id: str) -> str | None: ...

        def _status_snapshot(self) -> dict[str, tuple[str, str | None, str]]: ...

        def _task_identity(self, task: ObservedProc) -> str: ...

        def _update_title(self) -> None: ...

    def _refresh_running_output(self) -> None:
        """Refresh rows and selected output from the observer projection."""
        if not self._is_active_tab():
            return

        self._spinner_index += 1
        self._tick_count += 1
        prior_identity, highlighted = self._restore_target()
        self._set_observer_detail(self._detail_task_id())
        self._tasks = self._merged_tasks()
        self._store_loaded_once = True
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

    def _request_store_reload(self, *, force: bool = False) -> None:
        """Ask the app-level observer to poll and refresh the selected log tail."""
        del force
        self._set_observer_detail(self._detail_task_id())
        observer = getattr(self.app, "_proc_observer", None)
        request_poll = getattr(observer, "request_poll", None)
        if callable(request_poll):
            request_poll()

    def _detail_task_id(self) -> str | None:
        task = self._get_selected_task()
        if task is None:
            return None
        return task.durable_proc_id or task.proc_id

    def _set_observer_detail(self, proc_id: str | None) -> None:
        if proc_id == self._store_detail_id:
            return
        self._store_detail_id = proc_id
        observer = getattr(self.app, "_proc_observer", None)
        set_detail = getattr(observer, "set_detail_proc", None)
        if callable(set_detail):
            set_detail(proc_id)

    def action_toggle_scope(self) -> None:
        """Toggle between this session's tasks and every session's."""
        prior_identity, highlighted = self._restore_target()
        prior_identity = prior_identity or self._selected_task_identity()
        self._all_sessions = not self._all_sessions
        self._session_state.all_sessions = self._all_sessions  # type: ignore[attr-defined]
        self._refresh_snapshot(
            highlight_index=highlighted,
            prior_identity=prior_identity,
        )
        scope = "all sessions" if self._all_sessions else "this session"
        self.notify(f"Procs scope: {scope}")

    def _kill_store_task(self, task: ObservedProc) -> None:
        """Signal a durable task off the event loop, then request an observer poll."""
        proc_id = task.durable_proc_id or task.proc_id
        label = task.label

        def _kill() -> None:
            error = self._signal_store_task(proc_id)
            try:
                self.app.call_from_thread(self._on_store_kill_finished, label, error)
            except Exception:
                pass

        self.run_worker(_kill, thread=True, name="procs-store-kill", group="procs")

    def _on_store_kill_finished(self, label: str, error: str | None) -> None:
        if error is None:
            self.notify(f"Killed: {label}")
        else:
            self.notify(f"Kill failed: {error}", severity="error")
        self._request_store_reload(force=True)


__all__ = ["ProcsPaneStoreMixin"]
