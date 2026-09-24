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

    def _push_service_health(self, footer: Any) -> None:
        """Push the cached service-health roll-up to the footer pill.

        A toast fires only when health flips or the snapshot ``change_token``
        moves while unhealthy -- never on countdown ticks.
        """
        from ..._service_health import derive_service_health

        snapshot = getattr(self, "_service_status", None)
        health = derive_service_health(snapshot)
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
