"""Lifecycle, quit, and selection-persistence methods for the ace TUI app."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from ..util.shutdown import request_shutdown

if TYPE_CHECKING:
    from ...changespec import ChangeSpec

# Type alias for tab names (used in type hints)
TabName = Literal["changespecs", "agents", "axe"]


class LifecycleMixin:
    """Mixin providing quit, selection persistence, and agent tracking init."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    _changespecs_last_idx: int
    _last_unread_ids: set[str]

    def on_unmount(self) -> None:
        """Clean up resources when Textual tears the app down."""
        from ..util.pump_tasks import cancel_pump_free_tasks

        cancel_agent_hint_render = getattr(
            self, "_cancel_agent_hint_render_tasks", None
        )
        if callable(cancel_agent_hint_render):
            cancel_agent_hint_render()
        cancel_pump_free_tasks(self)
        self._stop_tui_stall_watchdog()
        stop_watcher = getattr(self, "_stop_artifact_watcher", None)
        if stop_watcher is not None:
            stop_watcher()
        stop_prompt_watcher = getattr(self, "_stop_prompt_source_watcher", None)
        if stop_prompt_watcher is not None:
            stop_prompt_watcher()
        cancel_discovery = getattr(
            self, "_cancel_pending_artifact_file_discovery", None
        )
        if cancel_discovery is not None:
            cancel_discovery()
        cancel_content_search = getattr(
            self, "_cancel_pending_content_search_refresh", None
        )
        if cancel_content_search is not None:
            cancel_content_search()
        from sase.ace.tui.models._loaders._json_cache import (
            shutdown_loader_executor,
        )
        from sase.logs import flush_toasts

        flush_toasts(timeout=1.0)
        stop_task_mirror = getattr(self, "_stop_task_mirror", None)
        if stop_task_mirror is not None:
            stop_task_mirror()
        shutdown_loader_executor()
        restore_artifact_decoration = getattr(
            self, "_restore_artifact_file_tmux_decoration", None
        )
        if restore_artifact_decoration is not None:
            restore_artifact_decoration(notify_warnings=False)
        restore_artifact_signal = getattr(
            self, "_restore_artifact_file_viewer_close_signal_handler", None
        )
        if restore_artifact_signal is not None:
            restore_artifact_signal()

    def _read_unread_notification_ids(self) -> set[str]:
        """Read active-unread (non-silent, non-muted) notification ids from disk.

        Pure disk I/O with no widget access — safe to call from a worker
        thread (e.g. via ``asyncio.to_thread``) during startup so the
        Textual event loop stays free for the startup stopwatch to tick.
        """
        from sase.notifications import read_notification_snapshot

        notifications = read_notification_snapshot().notifications
        return {
            n.id for n in notifications if not n.read and not n.silent and not n.muted
        }

    def _read_notifications_for_startup(self) -> tuple[set[str], int, int, int]:
        """Single-pass disk read returning unread_ids + priority/rest/muted counts.

        Avoids parsing the JSONL twice during startup (once for the unread-id
        seed, once for the indicator counts).
        """
        from sase.notifications import read_notification_snapshot

        snapshot = read_notification_snapshot()
        notifications = snapshot.notifications
        unread_ids: set[str] = set()
        for n in notifications:
            if n.read or n.silent:
                continue
            if not n.muted:
                unread_ids.add(n.id)
        counts = snapshot.counts
        priority_count = counts.priority + counts.errors
        rest_count = counts.rest
        muted_count = counts.muted
        return unread_ids, priority_count, rest_count, muted_count

    def _initialize_agent_tracking(
        self,
        state: tuple[set[str], int, int, int] | None = None,
    ) -> None:
        """Seed unread-id tracker and notification counts from preloaded state.

        ``state`` is ``(unread_ids, priority, rest, muted)``; when ``None``
        we read from disk inline (kept for callers outside the startup
        path). Seeding the unread set prevents bell/toast for notifications
        that were already unread when the TUI started.
        """
        from ..widgets import NotificationIndicator

        if state is None:
            state = self._read_notifications_for_startup()
        unread_ids, priority_count, rest_count, muted_count = state
        self._last_unread_ids = unread_ids

        indicator = self.query_one("#notification-indicator", NotificationIndicator)  # type: ignore[attr-defined]
        indicator.set_counts(priority_count, rest_count, muted_count)

    def _save_current_selection(self) -> None:
        """Save the currently selected ChangeSpec name."""
        from ...last_selection import save_last_selection

        if self.changespecs:
            if self.current_tab == "changespecs":
                idx = min(self.current_idx, len(self.changespecs) - 1)
            else:
                idx = min(self._changespecs_last_idx, len(self.changespecs) - 1)
            changespec = self.changespecs[idx]
            save_last_selection(changespec.name)
            self._save_selection_for_current_query()  # type: ignore[attr-defined]

    def _read_last_selection_name(self) -> str | None:
        """Read the persisted last-selection name from disk.

        Pure disk read. Safe to call from a worker thread. Must NOT grow
        widget calls — if it does, ``on_mount``'s ``asyncio.to_thread``
        wrapping becomes unsafe.
        """
        from ...last_selection import load_last_selection

        return load_last_selection()

    def _restore_last_selection(self, last_name: str | None = None) -> None:
        """Restore the previously selected ChangeSpec if it exists.

        ``last_name`` may be pre-loaded off the main thread; if omitted,
        the name is read from disk inline.
        """
        if last_name is None:
            last_name = self._read_last_selection_name()
        if last_name is None:
            return
        for idx, cs in enumerate(self.changespecs):
            if cs.name == last_name:
                self.current_idx = idx
                return

    def _count_running_tasks(self) -> int:
        """Return the count of running background tasks."""
        return self._task_queue.running_count  # type: ignore[attr-defined]

    def _kill_all_running_tasks(self) -> None:
        """Kill all running background tasks."""
        for task in self._task_queue.get_all():  # type: ignore[attr-defined]
            if task.status == "running":
                self._kill_background_task(task.task_id)  # type: ignore[attr-defined]

    def action_dismiss_toasts(self) -> None:
        """Dismiss all currently-visible toast notifications.

        Uses Textual's private ``_notifications`` / ``_refresh_notifications``
        because the Textual version in use has no public clear API. This
        mirrors what ``App._unnotify()`` does internally per-toast on expiry.
        """
        self._notifications.clear()  # type: ignore[attr-defined]
        self._refresh_notifications()  # type: ignore[attr-defined]

    async def action_quit(self) -> None:
        """Quit the application, saving the current selection."""
        toggle_artifact = getattr(self, "_toggle_tracked_artifact_file_tmux_pane", None)
        if callable(toggle_artifact) and toggle_artifact():
            return
        count = self._count_running_tasks()
        if count > 0:
            from ..modals import QuitConfirmModal

            running = [
                task
                for task in self._task_queue.get_all()  # type: ignore[attr-defined]
                if task.status == "running"
            ]
            if not running:
                await self._begin_controlled_exit()
                return

            def _on_confirm(confirmed: bool | None) -> None:
                if not confirmed:
                    return
                self._kill_all_running_tasks()
                self._request_controlled_exit()

            self.push_screen(  # type: ignore[attr-defined]
                QuitConfirmModal(running),
                callback=_on_confirm,
            )
            return
        await self._begin_controlled_exit()

    async def _flush_then_do_quit(self) -> None:
        """Drain best-effort async persistence, then run synchronous cleanup."""
        try:
            flushes = []
            flush_folds = getattr(self, "_flush_agents_fold_state", None)
            if callable(flush_folds):
                flushes.append(flush_folds())
            flush_admin_center = getattr(self, "_flush_admin_center_tab_state", None)
            if callable(flush_admin_center):
                flushes.append(flush_admin_center())
            if flushes:
                await asyncio.gather(*flushes, return_exceptions=True)
        except Exception:
            # Persistence can never trap the user in the TUI.
            pass
        finally:
            self._do_quit()

    async def _begin_controlled_exit(self) -> None:
        """Start the shared flush-and-exit sequence at most once."""
        request_shutdown()
        if getattr(self, "_controlled_exit_started", False):
            return
        self._controlled_exit_started = True  # type: ignore[attr-defined]
        await self._flush_then_do_quit()

    def _request_controlled_exit(self) -> None:
        """Schedule the shared async exit sequence from a sync callback."""
        request_shutdown()
        if getattr(self, "_controlled_exit_started", False):
            return
        self._controlled_exit_started = True  # type: ignore[attr-defined]
        if not any(
            callable(getattr(self, name, None))
            for name in (
                "_flush_agents_fold_state",
                "_flush_admin_center_tab_state",
            )
        ):
            self._do_quit()
            return
        call_later = getattr(self, "call_later", None)
        if callable(call_later):
            # Controlled exit intentionally keeps pump ordering: no further UI
            # input should run while the final persistence flush precedes exit.
            call_later(self._flush_then_do_quit)
            return
        try:
            asyncio.get_running_loop().create_task(self._flush_then_do_quit())
        except RuntimeError:
            self._do_quit()

    def _do_quit(self) -> None:
        """Run the quit cleanup sequence and exit."""
        request_shutdown()

        def cleanup(step: Callable[[], None]) -> None:
            try:
                step()
            except Exception:
                pass

        def stop_artifact_watcher() -> None:
            # Stop the inotify watcher before exit so its worker thread releases
            # the fd cleanly and Textual's call_from_thread doesn't fire after
            # the event loop is gone.
            stop_watcher = getattr(self, "_stop_artifact_watcher", None)
            if stop_watcher is not None:
                stop_watcher()
            stop_prompt_watcher = getattr(self, "_stop_prompt_source_watcher", None)
            if stop_prompt_watcher is not None:
                stop_prompt_watcher()

        def cancel_artifact_discovery() -> None:
            cancel_discovery = getattr(
                self, "_cancel_pending_artifact_file_discovery", None
            )
            if cancel_discovery is not None:
                cancel_discovery()

        def cancel_content_search_refresh() -> None:
            cancel_content_search = getattr(
                self, "_cancel_pending_content_search_refresh", None
            )
            if cancel_content_search is not None:
                cancel_content_search()

        def cancel_async_refresh_tasks() -> None:
            from ..util.pump_tasks import cancel_pump_free_tasks

            cancel_pump_free_tasks(self)

        def shutdown_loader_executor() -> None:
            from sase.ace.tui.models._loaders._json_cache import (
                shutdown_loader_executor as shutdown,
            )

            shutdown()

        def flush_tui_toasts() -> None:
            from sase.logs import flush_toasts

            flush_toasts(timeout=1.0)

        def stop_durable_task_mirror() -> None:
            stop_mirror = getattr(self, "_stop_task_mirror", None)
            if stop_mirror is not None:
                stop_mirror()

        def unregister_live_session() -> None:
            from ..util.session_registration import unregister_ace_session

            unregister_ace_session()

        def restore_artifact_file_tmux_decoration() -> None:
            restore_artifact_decoration = getattr(
                self, "_restore_artifact_file_tmux_decoration", None
            )
            if restore_artifact_decoration is not None:
                restore_artifact_decoration(notify_warnings=False)

        def restore_artifact_file_viewer_signal_handler() -> None:
            restore_artifact_signal = getattr(
                self, "_restore_artifact_file_viewer_close_signal_handler", None
            )
            if restore_artifact_signal is not None:
                restore_artifact_signal()

        try:
            cleanup(self._save_current_selection)
            cleanup(self._stop_tui_stall_watchdog)
            cleanup(stop_artifact_watcher)
            cleanup(cancel_async_refresh_tasks)
            cleanup(cancel_artifact_discovery)
            cleanup(cancel_content_search_refresh)
            cleanup(flush_tui_toasts)
            cleanup(stop_durable_task_mirror)
            cleanup(unregister_live_session)
            cleanup(shutdown_loader_executor)
            cleanup(restore_artifact_file_tmux_decoration)
            cleanup(restore_artifact_file_viewer_signal_handler)
        finally:
            self.exit()  # type: ignore[attr-defined]

    def _stop_tui_stall_watchdog(self) -> None:
        """Stop the event-loop stall watchdog if it was started."""
        watchdog = getattr(self, "_stall_watchdog", None)
        if watchdog is None:
            return
        self._stall_watchdog = None
        try:
            watchdog.stop()
        except Exception:
            pass
