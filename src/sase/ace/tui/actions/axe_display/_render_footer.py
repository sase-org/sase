"""Footer and state-indicator mixin for the ace axe display.

Pushes the keybinding footer and the axe starting/stopping/restarting
indicators from the in-memory caches populated by
``AxeDisplayLoadersMixin``.
"""

from __future__ import annotations

from typing import Any

from ._render_panels import AxeDisplayPanelsMixin


class AxeDisplayFooterMixin(AxeDisplayPanelsMixin):
    """Mixin providing the axe keybinding-footer and state setters."""

    def _update_axe_keybinding(self) -> None:
        """Update the keybinding footer with current axe state."""
        from ...widgets import KeybindingFooter

        running_count, done_count = self._get_bgcmd_counts()
        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_running(self.axe_running)
            footer.set_bgcmd_count(running_count, done_count)
            self._push_service_health(footer)
        except Exception:
            pass

    def _expire_service_restart_transition(self, transition: Any) -> None:
        """Clear an expected restart window and re-push the cached health.

        Thin and synchronous: no disk I/O. A stale callback for an
        already-settled or replaced transition does nothing.
        """
        if getattr(self, "_service_restart_transition", None) is not transition:
            return
        self._service_restart_transition = None
        update = getattr(self, "_update_axe_keybinding", None)
        if callable(update):
            update()

    def _push_service_health(self, footer: Any) -> None:
        """Push the cached service-health roll-up to the footer pill.

        A toast fires only when health flips or the snapshot ``change_token``
        moves while unhealthy -- never on countdown ticks.
        """
        import time

        from ..._service_health import derive_service_health
        from ._service_restart_transition import restart_transition_settled

        snapshot = getattr(self, "_service_status", None)
        health = derive_service_health(snapshot)
        transition = getattr(self, "_service_restart_transition", None)
        if transition is not None:
            try:
                settled = restart_transition_settled(transition, snapshot, health)
            except Exception:
                settled = False
            if settled:
                self._service_restart_transition = None
            elif time.monotonic() < transition.deadline:
                try:
                    footer.set_service_health(health, restarting=True)
                except TypeError:
                    footer.set_service_health(health)
                return
            else:
                self._service_restart_transition = None
        footer.set_service_health(health)
        token = None if snapshot is None else snapshot.change_token
        signature = (health.healthy, health.summary, None if health.healthy else token)
        if signature == getattr(self, "_service_health_notified", None):
            return
        previous = getattr(self, "_service_health_notified", None)
        self._service_health_notified = signature
        if not health.healthy and (previous is None or previous[2] != token):
            try:
                self.notify(  # type: ignore[attr-defined]
                    f"Services unhealthy: {health.summary}", severity="warning"
                )
            except Exception:
                pass

    def _set_axe_starting(self, starting: bool) -> None:
        """Set axe starting state and update footer.

        Args:
            starting: Whether axe is currently starting up.
        """
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_starting(starting)
        except Exception:
            pass

    def _set_axe_stopping(self, stopping: bool) -> None:
        """Set axe stopping state and update footer.

        Args:
            stopping: Whether axe is currently stopping.
        """
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_stopping(stopping)
        except Exception:
            pass

    def _set_axe_restarting(self, restarting: bool) -> None:
        """Set axe restarting state and update footer.

        Args:
            restarting: Whether axe is currently restarting.
        """
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_restarting(restarting)
        except Exception:
            pass
