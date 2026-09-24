"""Process signalling helpers for TUI agent kills."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from ._kill_persistence import KillKind

if TYPE_CHECKING:
    from ...models import Agent


class AgentKillProcessMixin:
    """Mixin for immediate agent signalling and kill notifications.

    The TUI only sends the immediate SIGTERM. Escalation to SIGKILL, the sweep
    of processes that left the runner's group, and verification of death run in
    the durable persist-cleanup proc, which survives the TUI.
    """

    def _kill_process_group(
        self,
        pid: int,
        *,
        artifacts_dir: str | None = None,
        reason: str | None = None,
    ) -> bool:
        """Send the immediate SIGTERM to an agent and record the kill intent.

        Args:
            pid: Process ID to signal.

        Returns:
            True if the signal was sent or the process was already dead, False
            on error.
        """
        from . import _killing as killing_compat

        result = killing_compat.request_user_kill(
            pid,
            artifacts_dir=artifacts_dir,
            source="ace_tui",
            reason=reason,
            wait=False,
            background=False,
            killpg=killing_compat.os.killpg,
        )
        if result.success:
            return True
        if result.status == "permission_denied":
            self.notify(  # type: ignore[attr-defined]
                f"Permission denied killing PID {pid}", severity="error"
            )
            return False
        if result.status == "already_stopped":
            return True
        self.notify(  # type: ignore[attr-defined]
            f"Failed killing PID {pid}: {result.error or result.status}",
            severity="error",
        )
        return False

    def _kill_agent_process_group(self, agent: Agent) -> bool:
        if agent.pid is None:
            return True
        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        return self._kill_process_group(
            agent.pid,
            artifacts_dir=artifacts_dir,
            reason=agent.display_name,
        )

    def _escalate_kills_without_cleanup_proc(self, agents: Iterable[Agent]) -> None:
        """Escalate on daemon threads when no durable proc took over.

        Used only when the persist-cleanup proc was rejected, so a kill never
        ends with nothing to escalate a SIGTERM that the agent ignored. The
        threads die with the TUI; the durable proc is the real owner.
        """
        from . import _killing as killing_compat

        for agent in agents:
            if agent.pid is None:
                continue
            killing_compat.escalate_user_kill_in_background(
                agent.pid,
                artifacts_dir=agent.artifacts_dir or agent.get_artifacts_dir(),
            )

    def _notify_killed_agent(self, agent: Agent, kind: KillKind) -> None:
        """Emit kill notification message for an already-signaled process."""
        if agent.pid is None:
            return
        if kind == "workflow":
            self.notify(f"Killed workflow (PID {agent.pid})")  # type: ignore[attr-defined]
            return
        if kind == "hook":
            self.notify(f"Killed hook agent (PID {agent.pid})")  # type: ignore[attr-defined]
            return
        if kind == "mentor":
            self.notify(f"Killed mentor agent (PID {agent.pid})")  # type: ignore[attr-defined]
            return
        if kind == "crs":
            self.notify(f"Killed CRS agent (PID {agent.pid})")  # type: ignore[attr-defined]
            return
        self.notify(f"Killed agent (PID {agent.pid})")  # type: ignore[attr-defined]
