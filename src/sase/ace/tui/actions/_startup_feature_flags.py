"""Deferred feature-flag state cleanup notices for ACE startup."""

from __future__ import annotations

import logging
from typing import Any

from sase.feature_flags.snapshot import (
    FeatureFlagCleanupNotice,
    has_pending_feature_flag_cleanup,
    run_pending_feature_flag_cleanup,
)

from ..util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)


class StartupFeatureFlagCleanupMixin:
    """Mixin that runs deferred saved feature-flag cleanup after startup."""

    _feature_flag_cleanup_notice_scheduled: bool

    def _schedule_feature_flag_cleanup_notice(self: Any) -> None:
        """Schedule ACE's one deferred feature-flag cleanup notice, if any."""
        if self._feature_flag_cleanup_notice_scheduled:
            return
        try:
            pending = has_pending_feature_flag_cleanup()
        except Exception:
            log.exception("Failed to inspect pending feature-flag cleanup")
            return
        if not pending:
            return

        self._feature_flag_cleanup_notice_scheduled = True
        coro = self._run_feature_flag_cleanup_notice()
        try:
            task = spawn_pump_free_task(
                self,
                coro,
                name="feature-flag-cleanup",
                registry_attr="_feature_flag_cleanup_async_tasks",
            )
        except Exception as exc:
            coro.close()
            self._feature_flag_cleanup_notice_scheduled = False
            self._notify_feature_flag_cleanup_scheduling_failure(str(exc))
            log.exception("Failed to schedule feature-flag cleanup")
            return
        if task is None:
            coro.close()
            self._feature_flag_cleanup_notice_scheduled = False
            self._notify_feature_flag_cleanup_scheduling_failure(
                "no running event loop"
            )

    async def _run_feature_flag_cleanup_notice(self: Any) -> None:
        """Run the deferred cleanup off-thread and deliver its notice."""
        import asyncio

        notice = await asyncio.to_thread(run_pending_feature_flag_cleanup)
        if notice is None:
            return
        self._show_feature_flag_cleanup_notice(notice)

    def _show_feature_flag_cleanup_notice(
        self: Any, notice: FeatureFlagCleanupNotice
    ) -> None:
        """Display a cleanup notice through normal ACE toast history."""
        self.notify(
            notice.message,
            title=notice.title,
            severity=notice.severity,
            timeout=notice.timeout,
        )

    def _notify_feature_flag_cleanup_scheduling_failure(self: Any, reason: str) -> None:
        """Surface a scheduling failure without attempting cleanup inline."""
        from rich.markup import escape

        self.notify(
            "[bold yellow]CLEANUP FAILED[/]\n"
            "State: pending feature-flag cleanup\n"
            f"Reason: {escape(reason)}\n"
            "Will retry on next startup",
            title="Feature flag cleanup failed",
            severity="warning",
            timeout=15.0,
        )
