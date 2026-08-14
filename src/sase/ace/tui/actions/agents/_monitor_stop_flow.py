"""Stop-monitor action flow: routes the kill key off the agent-kill path.

A monitor member has no LLM process to kill -- ``x`` on a running monitor row
must terminate the supervised command via ``sase.monitor.store.stop_monitor``
instead of the ordinary agent kill/dismiss machinery.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent


class MonitorStopActionFlowMixin:
    """Mixin dispatching the kill key for a selected monitor row."""

    def _handle_monitor_stop_action(self, agent: Agent) -> None:
        """Confirm and stop a running monitor's supervised command."""
        if agent.monitor_state != "running":
            self.notify(  # type: ignore[attr-defined]
                "Monitor has already finished", severity="warning"
            )
            return

        from ...modals import ConfirmStopMonitorModal

        description = (
            agent.monitor_label or agent.monitor_command or agent.agent_name or ""
        )

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_stop_monitor(agent)  # type: ignore[attr-defined]

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmStopMonitorModal(description), on_dismiss
        )

    def _do_stop_monitor(self, agent: Agent) -> None:
        """Submit the blocking monitor stop as a tracked proc."""
        artifacts_dir = agent.get_artifacts_dir()
        monitor_label = agent.monitor_label or agent.monitor_command or "monitor"
        if artifacts_dir is None or not agent.project_file:
            self.notify(  # type: ignore[attr-defined]
                f"Cannot resolve artifacts for {monitor_label}", severity="error"
            )
            return

        project_name = Path(agent.project_file).parent.name

        def proc_callable() -> tuple[bool, str]:
            from sase.monitor.store import get_monitor, stop_monitor

            record = get_monitor(project_name, artifacts_dir)
            if record is None:
                return False, f"Monitor {monitor_label} not found"
            updated = stop_monitor(record)
            if updated.monitor_state == "running":
                return False, f"Timed out waiting for {monitor_label} to stop"
            return True, f"Stopped {monitor_label} ({updated.monitor_state})"

        dedup_key = agent.agent_name or agent.monitor_id or artifacts_dir
        self._submit_proc(  # type: ignore[attr-defined]
            "monitor-stop",
            dedup_key,
            agent.project_file,
            proc_callable,
        )


__all__ = ["MonitorStopActionFlowMixin"]
