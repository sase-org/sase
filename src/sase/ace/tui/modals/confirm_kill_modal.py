"""Confirm kill / dismiss-all modals for the ace TUI."""

from __future__ import annotations

from .confirm_dialog import ConfirmDialog, ConfirmKind


class ConfirmDismissAllModal(ConfirmDialog):
    """Modal for confirming bulk dismissal of all completed agents."""

    def __init__(self, agent_description: str) -> None:
        """Initialize the confirm dismiss-all modal.

        Args:
            agent_description: Description of the agents to dismiss.
        """
        self.agent_description = agent_description
        super().__init__(
            "Dismiss Completed Agents",
            "Dismiss these completed agents?",
            subject=agent_description,
            kind=ConfirmKind.DANGER,
            confirm_label="Dismiss all",
            cancel_label="Keep",
            default="cancel",
        )


class ConfirmKillModal(ConfirmDialog):
    """Modal for confirming agent termination."""

    def __init__(self, agent_description: str) -> None:
        """Initialize the confirm kill modal.

        Args:
            agent_description: Description of the agent to kill.
        """
        self.agent_description = agent_description
        super().__init__(
            "Kill Agent",
            "Kill this agent? Running work will stop immediately.",
            subject=agent_description,
            kind=ConfirmKind.DANGER,
            confirm_label="Kill",
            cancel_label="Keep running",
            default="cancel",
        )


class ConfirmStopMonitorModal(ConfirmDialog):
    """Modal for confirming a monitor's supervised command should be stopped."""

    def __init__(self, monitor_description: str) -> None:
        """Initialize the confirm stop-monitor modal.

        Args:
            monitor_description: Description of the monitor to stop.
        """
        self.monitor_description = monitor_description
        super().__init__(
            "Stop Monitor",
            "Stop this monitored command? No follow-up agent will launch.",
            subject=monitor_description,
            kind=ConfirmKind.DANGER,
            confirm_label="Stop",
            cancel_label="Keep running",
            default="cancel",
        )


class ConfirmKillAllModal(ConfirmDialog):
    """Modal for confirming kill & dismiss of all agents (double-confirmation)."""

    def __init__(self, agent_description: str) -> None:
        self.agent_description = agent_description
        self._confirmed_once = False
        super().__init__(
            "Kill & Dismiss All",
            "Kill running agents and dismiss completed agents?",
            subject=agent_description,
            kind=ConfirmKind.DANGER,
            confirm_label="Continue",
            cancel_label="Cancel",
            default="cancel",
        )

    def action_confirm(self) -> None:
        if not self._confirmed_once:
            self._confirmed_once = True
            self._set_kind(ConfirmKind.DANGER)
            self._set_title("FINAL CONFIRMATION")
            self._set_message(
                "This will kill running agents and dismiss completed agents.\n\n"
                "This action is irreversible. Press y again to confirm."
            )
            self._set_subject(None)
            self._set_confirm_label("Confirm")
        else:
            self.dismiss(True)


__all__ = [
    "ConfirmDismissAllModal",
    "ConfirmKillAllModal",
    "ConfirmKillModal",
    "ConfirmStopMonitorModal",
]
