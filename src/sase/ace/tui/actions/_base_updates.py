"""Update-panel shortcut actions for sase's TUI app."""

from __future__ import annotations

import time

from sase.ace.update_scope import UpdateScope

from ..modals.update_panel import UpdatePanel, UpdatePanelResult
from ..update_panel_state import build_update_panel_state
from ..update_restart import restart_after_update_when_ready
from ._base_types import BaseActionsHost


class BaseUpdateActionsMixin(BaseActionsHost):
    """Mixin providing scoped update shortcuts and restart."""

    def _submit_scoped_update_request(
        self,
        *,
        scope: UpdateScope,
        auto_approve: bool = False,
    ) -> bool:
        """Submit one scoped update request from the cached provider projection."""
        from ..modals.plugins_browser_comprehensive_update_models import (
            ComprehensiveUpdateRequest,
        )

        submit = getattr(self, "_submit_update_preview_proc", None)
        if not callable(submit):
            return False
        return bool(
            submit(
                ComprehensiveUpdateRequest(
                    provider_names=getattr(
                        self, "_automatic_update_provider_names", None
                    ),
                    scope=scope,
                    auto_approve=auto_approve,
                )
            )
        )

    def action_update_sase_shortcut(self) -> None:
        """Open the Update panel from already-fetched evidence."""
        # Keystroke dispatch is allocation-only: project the in-memory
        # update-status snapshot and push the panel. Preview I/O starts
        # in the update-preview proc after the user chooses a row.
        state = build_update_panel_state(
            getattr(self, "_automatic_update_status", None),
            now=time.time(),
            running_code=getattr(self, "_running_code_state", None),
            last_failure=self._cached_update_failure(),  # type: ignore[arg-type]
        )

        def on_result(result: UpdatePanelResult | None) -> None:
            if not isinstance(result, UpdatePanelResult):
                return
            if result.scope == "restart":
                self._restart_running_code_when_ready()
                return
            if result.scope == "failure":
                opener = getattr(self, "action_open_update_failure", None)
                if callable(opener):
                    opener()
                return
            self._submit_scoped_update_request(
                scope=UpdateScope(result.scope),
                auto_approve=result.auto_approve,
            )

        self.push_screen(UpdatePanel(state), on_result)  # type: ignore[attr-defined]

    def action_update_everything_shortcut(self) -> None:
        """Plan an Everything update and skip confirmation when runnable."""
        self._submit_scoped_update_request(
            scope=UpdateScope.EVERYTHING,
            auto_approve=True,
        )

    def _cached_update_failure(self) -> object | None:
        """Return the recorded update failure, or None when unavailable."""
        view = getattr(self, "_update_attempts_view", None)
        return getattr(view, "failure", None) if view is not None else None

    def _set_pending_update_restart(self, pending: object | None) -> None:
        """Publish one coalesced pending-restart record to the badge."""
        from ..widgets.updates_indicator import UpdatesAvailableIndicator

        self._pending_update_restart = pending
        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#updates-indicator", UpdatesAvailableIndicator
            )
        except Exception:
            return
        try:
            indicator.set_restart_pending(pending)  # type: ignore[arg-type]
        except Exception:
            pass

    def _restart_running_code_when_ready(self) -> None:
        """Restart ACE through the existing tracked-proc-aware helper."""
        notify = getattr(self, "notify", None)
        restart_after_update_when_ready(
            self,
            "Running SASE code changed on disk",
            deferred=False,
            notify=notify if callable(notify) else None,
            restart_purpose="load new code",
        )
