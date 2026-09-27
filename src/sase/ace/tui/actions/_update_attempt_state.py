"""Revisioned update-attempt view state for sase's TUI app."""

from __future__ import annotations

import logging
from typing import Any

from sase.ace.update_attempts import (
    UpdateAttemptsView,
    dismiss_update_failure,
    load_update_attempts,
)

log = logging.getLogger(__name__)


class UpdateAttemptStateMixin:
    """Apply journal views to the updates badge without blocking the UI."""

    _update_attempts_view: UpdateAttemptsView | None
    _update_attempts_refresh_in_flight: bool

    def _apply_update_attempts_view(self, view: UpdateAttemptsView) -> None:
        """Store *view* and push its failure to the badge, dropping stale reads."""
        current = getattr(self, "_update_attempts_view", None)
        if current is not None and view.revision < current.revision:
            return
        self._update_attempts_view = view
        try:
            from ..widgets.updates_indicator import UpdatesAvailableIndicator

            indicator = self.query_one(  # type: ignore[attr-defined]
                "#updates-indicator", UpdatesAvailableIndicator
            )
        except Exception:
            return
        try:
            indicator.set_last_failure(view.failure)
        except Exception:
            log.debug("Failed to push update failure to badge", exc_info=True)

    def _schedule_update_attempts_refresh(self) -> None:
        """Reload the journal view off the UI thread, coalescing overlap."""
        if getattr(self, "_update_attempts_refresh_in_flight", False):
            return
        self._update_attempts_refresh_in_flight = True
        try:
            self.run_worker(  # type: ignore[attr-defined]
                self._load_update_attempts_in_worker,  # type: ignore[arg-type]
                thread=True,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            self._update_attempts_refresh_in_flight = False
            log.debug("Failed to schedule update attempts refresh", exc_info=True)

    def _load_update_attempts_in_worker(self) -> None:
        """Read and reconcile the journal, then hand its view to the UI thread."""
        try:
            view: UpdateAttemptsView | None = load_update_attempts()
        except Exception:
            log.debug("Update attempts refresh failed", exc_info=True)
            view = None
        try:
            self.call_from_thread(  # type: ignore[attr-defined]
                self._finish_update_attempts_refresh,
                view,
            )
        except Exception:
            self._update_attempts_refresh_in_flight = False
            log.debug("Failed to finish update attempts refresh", exc_info=True)

    def _finish_update_attempts_refresh(self, view: UpdateAttemptsView | None) -> None:
        """Apply a worker-loaded view and release the overlap guard."""
        self._update_attempts_refresh_in_flight = False
        if view is not None:
            self._apply_update_attempts_view(view)

    def _dismiss_update_failure(self, attempt_id: str) -> None:
        """Clear the badge optimistically, then persist the dismissal off-thread."""
        current = getattr(self, "_update_attempts_view", None)
        revision = current.revision if current is not None else 0
        self._apply_update_attempts_view(
            UpdateAttemptsView(revision=revision, failure=None)
        )

        def _persist() -> None:
            try:
                view = dismiss_update_failure(attempt_id)
            except Exception:
                log.debug("Update failure dismissal failed", exc_info=True)
                return
            try:
                self.call_from_thread(  # type: ignore[attr-defined]
                    self._apply_update_attempts_view,
                    view,
                )
            except Exception:
                log.debug("Failed to deliver dismissed update view", exc_info=True)

        try:
            self.run_worker(  # type: ignore[attr-defined]
                _persist,
                thread=True,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.debug("Failed to schedule update failure dismissal", exc_info=True)

    def action_open_update_failure(self) -> None:
        """Open the failure report for the recorded update failure, if any."""
        view = getattr(self, "_update_attempts_view", None)
        failure = view.failure if view is not None else None
        if failure is None:
            return

        def on_result(result: Any | None) -> None:
            if result == "dismiss":
                self._dismiss_update_failure(failure.attempt_id)
            elif result == "open_update":
                shortcut = getattr(self, "action_update_sase_shortcut", None)
                if callable(shortcut):
                    shortcut()

        from ..modals.update_failure_modal import UpdateFailureModal

        self.push_screen(UpdateFailureModal(failure), on_result)  # type: ignore[attr-defined]


__all__ = ["UpdateAttemptStateMixin"]
