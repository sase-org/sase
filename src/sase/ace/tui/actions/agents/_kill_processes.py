"""Process signalling helpers for TUI agent kills."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._kill_persistence import KillKind

if TYPE_CHECKING:
    from ...models import Agent


class AgentKillProcessMixin:
    """Mixin for process-group signalling and kill notifications."""

    def _kill_process_group(
        self,
        pid: int,
        *,
        artifacts_dir: str | None = None,
        reason: str | None = None,
    ) -> bool:
        """Kill a process group by PID.

        Args:
            pid: Process ID to kill.

        Returns:
            True if kill succeeded or process was already dead, False on error.
        """
        from . import _killing as killing_compat

        result = killing_compat.request_user_kill(
            pid,
            artifacts_dir=artifacts_dir,
            source="ace_tui",
            reason=reason,
            wait=False,
            background=True,
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
