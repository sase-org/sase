"""Confirm kill / dismiss-all modals for sase's TUI."""

from __future__ import annotations

from .confirm_dialog import ConfirmDialog, ConfirmKind


class ConfirmDismissAllModal(ConfirmDialog):
    """Modal for confirming bulk dismissal of all completed agents."""

    def __init__(self, agent_description: str, scope_label: str | None = None) -> None:
        """Initialize the confirm dismiss-all modal.

        Args:
            agent_description: Description of the agents to dismiss.
            scope_label: Bulk scope wording (``on <tab>``); None keeps
                today's message byte-identical.
        """
        self.agent_description = agent_description
        message = "Dismiss these completed agents?"
        if scope_label:
            message = f"Dismiss these completed agents {scope_label}?"
        super().__init__(
            "Dismiss Completed Agents",
            message,
            subject=agent_description,
            kind=ConfirmKind.DANGER,
            confirm_label="Dismiss all",
            cancel_label="Keep",
            default="cancel",
        )


class ConfirmKillModal(ConfirmDialog):
    """Modal for confirming agent termination."""

    BINDINGS = [*ConfirmDialog.BINDINGS, ("h", "hijack", "Hijack instead")]

    def __init__(
        self,
        agent_description: str,
        *,
        hijack_available: bool = False,
        workspace_num: int | None = None,
    ) -> None:
        """Initialize the confirm kill modal.

        Args:
            agent_description: Description of the agent to kill.
        """
        self.agent_description = agent_description
        self.hijack_available = hijack_available
        message = "Kill this agent? Running work will stop immediately."
        if hijack_available:
            workspace = (
                f"#{workspace_num}" if workspace_num is not None else "its workspace"
            )
            message += f"\n\nh Hijack instead · stop it but keep workspace {workspace}"
        super().__init__(
            "Kill Agent",
            message,
            subject=agent_description,
            kind=ConfirmKind.DANGER,
            confirm_label="Kill",
            cancel_label="Keep running",
            default="cancel",
        )

    def action_hijack(self) -> None:
        """Choose the keep-work stop path when it was offered."""
        if self.hijack_available:
            self.dismiss("hijack")  # type: ignore[arg-type]


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


class ConfirmKillNamedProcModal(ConfirmDialog):
    """Modal for confirming a stand-alone named proc should be killed."""

    def __init__(self, proc_description: str) -> None:
        """Initialize the confirm kill-named-proc modal."""
        self.proc_description = proc_description
        super().__init__(
            "Kill Named Proc",
            "Kill this named proc? Running command will stop immediately.",
            subject=proc_description,
            kind=ConfirmKind.DANGER,
            confirm_label="Kill proc",
            cancel_label="Keep running",
            default="cancel",
        )


class ConfirmCancelGateModal(ConfirmDialog):
    """Modal for confirming a pending gate turn should be cancelled."""

    def __init__(self, gate_description: str) -> None:
        """Initialize the confirm cancel-gate modal.

        Args:
            gate_description: Description of the gate to cancel.
        """
        self.gate_description = gate_description
        super().__init__(
            "Cancel Gate",
            "Cancel this pending gate? The waiting decision will not run.",
            subject=gate_description,
            kind=ConfirmKind.DANGER,
            confirm_label="Cancel gate",
            cancel_label="Keep waiting",
            default="cancel",
        )


class ConfirmKillAllModal(ConfirmDialog):
    """Modal for confirming kill & dismiss of all agents (double-confirmation)."""

    def __init__(self, agent_description: str, scope_label: str | None = None) -> None:
        """Initialize the confirm kill-all modal.

        Args:
            agent_description: Description of the agents to kill/dismiss.
            scope_label: Bulk scope wording (``on <tab>``); None keeps
                today's messages byte-identical.
        """
        self.agent_description = agent_description
        self._scope_label = scope_label
        self._confirmed_once = False
        message = "Kill running agents and dismiss completed agents?"
        if scope_label:
            message = f"Kill running agents and dismiss completed agents {scope_label}?"
        super().__init__(
            "Kill & Dismiss All",
            message,
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
            scoped = "This will kill running agents and dismiss completed agents"
            if self._scope_label:
                scoped = f"{scoped} {self._scope_label}"
            self._set_message(
                f"{scoped}.\n\nThis action is irreversible. Press y again to confirm."
            )
            self._set_subject(None)
            self._set_confirm_label("Confirm")
        else:
            self.dismiss(True)


__all__ = [
    "ConfirmCancelGateModal",
    "ConfirmDismissAllModal",
    "ConfirmKillAllModal",
    "ConfirmKillModal",
    "ConfirmKillNamedProcModal",
    "ConfirmStopMonitorModal",
]
