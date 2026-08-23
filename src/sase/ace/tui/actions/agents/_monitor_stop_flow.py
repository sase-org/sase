"""Stop-monitor action flow: routes the kill key off the agent-kill path.

A monitor member has no LLM process to kill -- ``x`` on a running monitor row
must terminate the supervised command via ``sase.monitor.store.stop_monitor``
instead of the ordinary agent kill/dismiss machinery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.actions._durable_ops import (
    durable_fingerprint,
    durable_request_payload,
    sase_argv,
)
from sase.ops.names import MONITOR_STOP, PROC_KILL
from sase.procs import ACTIVE_PROC_STATUSES, short_proc_id

if TYPE_CHECKING:
    from ...models import Agent


class MonitorStopActionFlowMixin:
    """Mixin dispatching the kill key for a selected monitor row."""

    def _handle_proc_shell_kill_action(self, agent: Agent) -> None:
        """Confirm and kill a stand-alone proc shell through the proc service."""
        if agent.proc_status not in ACTIVE_PROC_STATUSES:
            self.notify(  # type: ignore[attr-defined]
                "Proc shell has already finished", severity="warning"
            )
            return
        proc_id = agent.proc_id
        if not proc_id:
            self.notify("Cannot resolve proc shell id", severity="error")  # type: ignore[attr-defined]
            return

        from ...modals import ConfirmKillProcShellModal

        description = agent.proc_label or agent.agent_name or short_proc_id(proc_id)

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_kill_proc_shell(agent)  # type: ignore[attr-defined]

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmKillProcShellModal(description), on_dismiss
        )

    def _do_kill_proc_shell(self, agent: Agent) -> None:
        """Submit ``sase proc kill`` as a durable proc operation."""
        proc_id = agent.proc_id
        if not proc_id:
            self.notify("Cannot resolve proc shell id", severity="error")  # type: ignore[attr-defined]
            return
        label = agent.proc_label or agent.agent_name or short_proc_id(proc_id)
        proc_ref = proc_id
        dedup_key = f"proc-kill:{proc_id}"
        self._submit_durable_proc(  # type: ignore[attr-defined]
            sase_argv("proc", "kill", proc_ref, "--json"),
            operation=PROC_KILL,
            request=durable_request_payload(
                proc_id=proc_id,
                proc_label=label,
            ),
            request_fingerprint=durable_fingerprint(PROC_KILL, proc_id),
            concurrency_keys=(dedup_key,),
            label=f"kill proc {label}",
            display_name=f"kill proc {label}",
            proc_type="proc.kill",
            cl_name=agent.cl_name or proc_id,
            project_file=agent.project_file,
            duplicate_message=f"A kill proc operation is already running for {label}",
        )

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
        """Submit the blocking monitor stop as a durable proc."""
        artifacts_dir = agent.get_artifacts_dir()
        monitor_label = agent.monitor_label or agent.monitor_command or "monitor"
        if artifacts_dir is None or not agent.project_file:
            self.notify(  # type: ignore[attr-defined]
                f"Cannot resolve artifacts for {monitor_label}", severity="error"
            )
            return

        dedup_key = agent.agent_name or agent.monitor_id or artifacts_dir
        monitor_ref = agent.monitor_id or agent.agent_name or dedup_key
        self._submit_durable_proc(  # type: ignore[attr-defined]
            sase_argv("monitor", "stop", monitor_ref, "--json"),
            operation=MONITOR_STOP,
            request=durable_request_payload(
                artifacts_dir=artifacts_dir,
                monitor_label=monitor_label,
            ),
            request_fingerprint=durable_fingerprint(MONITOR_STOP, monitor_ref),
            concurrency_keys=(f"monitor-stop:{dedup_key}",),
            label=f"stop monitor {monitor_label}",
            display_name=f"stop monitor {monitor_label}",
            cl_name=dedup_key,
            project_file=agent.project_file,
        )


__all__ = ["MonitorStopActionFlowMixin"]
