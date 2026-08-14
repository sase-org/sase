"""Durable-store synchronization for the Admin Center Tasks pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.proc_queue import ProcInfo

from .procs_pane_render import cached_body_version, is_active
from .procs_store_rows import StoreTasksSnapshot

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object

# Every fourth 0.25s tick, so the spinner keeps its cadence while the store
# is revalidated about once a second.
_STORE_RELOAD_TICKS = 4


class ProcsPaneStoreMixin(_MixinBase):
    """Poll, merge, and operate on durable background-task rows."""

    if TYPE_CHECKING:
        _all_sessions: bool
        _body_cache: object
        _last_statuses: dict[str, tuple[str, str | None, str]]
        _session_id: str | None
        _session_state: object
        _spinner_index: int
        _store_detail_id: str | None
        _store_loaded_once: bool
        _store_load_pending: bool
        _store_mtime: float | None
        _store_rows: list[ProcInfo]
        _tasks: list[ProcInfo]
        _tick_count: int
        _user_scrolled: bool

        def _display_task_live_output(self, task: ProcInfo) -> None: ...

        def _get_selected_task(self) -> ProcInfo | None: ...

        def _highlighted_row(self) -> int | None: ...

        def _is_active_tab(self) -> bool: ...

        def _load_store_rows(
            self,
            *,
            session_id: str | None,
            all_sessions: bool,
            known_mtime: float | None,
            known_detail_task_id: str | None,
            detail_task_id: str | None,
        ) -> StoreTasksSnapshot: ...

        def _merged_tasks(self) -> list[ProcInfo]: ...

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

        def _rekey_task_identity(self, identity: str | None) -> str | None: ...

        def _restore_target(self) -> tuple[str | None, int | None]: ...

        def _selected_task_identity(self) -> str | None: ...

        def _signal_store_task(self, proc_id: str) -> str | None: ...

        def _status_snapshot(self) -> dict[str, tuple[str, str | None, str]]: ...

        def _task_identity(self, task: ProcInfo) -> str: ...

        def _update_title(self) -> None: ...

    def _refresh_running_output(self) -> None:
        """Poll the task queue for status changes and live output."""
        if not self._is_active_tab():
            return

        # The renderer wraps this into its own frame count.
        self._spinner_index += 1
        self._tick_count += 1
        if self._tick_count % _STORE_RELOAD_TICKS == 0:
            self._request_store_reload()
        prior_identity, highlighted = self._restore_target()
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
            or task.log.version != cached_body_version(task, self._body_cache)  # type: ignore[arg-type]
        ):
            self._display_task_live_output(task)

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
                snapshot = self._load_store_rows(
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

        self.run_worker(_load, thread=True, name="procs-store-load", group="procs")

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
        prior_identity, highlighted = self._restore_target()
        if snapshot.unchanged:
            if prior_identity is not None and not any(
                self._task_identity(task) == prior_identity for task in self._tasks
            ):
                self._rebuild_list(
                    highlight_index=highlighted,
                    prior_identity=prior_identity,
                )
            return
        self._store_rows = snapshot.rows
        self._tasks = self._merged_tasks()
        requested_identity = self._rekey_task_identity(
            self._session_state.task.identity  # type: ignore[attr-defined]
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
        return (task.durable_proc_id or task.proc_id), is_active(task)

    def action_toggle_scope(self) -> None:
        """Toggle between this session's tasks and every session's."""
        prior_identity, highlighted = self._restore_target()
        self._all_sessions = not self._all_sessions
        self._session_state.all_sessions = self._all_sessions  # type: ignore[attr-defined]
        self._store_rows = []
        self._store_loaded_once = False
        self._request_store_reload(force=True)
        self._refresh_snapshot(
            highlight_index=highlighted,
            prior_identity=prior_identity,
        )
        scope = "all sessions" if self._all_sessions else "this session"
        self.notify(f"Tasks scope: {scope}")

    def _kill_store_task(self, task: ProcInfo) -> None:
        """Signal a durable task off the event loop, then reload the store."""
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
