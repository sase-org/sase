"""Agent interrupt mixin for the ace TUI app."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentInterruptMixin:
    """Mixin providing the action to send a message to a running agent.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]

    def action_send_agent_message(self) -> None:
        """Send an interrupt message to a running agent."""
        if self.current_tab != "agents":
            return

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        agent = self._agents[self.current_idx]

        # Only for running agents (not done/failed, not axe-spawned)
        _INTERRUPTABLE = {"RUNNING", "PLAN APPROVED", "PLANNING", "WAITING", "QUESTION"}
        if agent.status not in _INTERRUPTABLE:
            self.notify("Agent is not running", severity="warning")  # type: ignore[attr-defined]
            return

        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not artifacts_dir:
            self.notify("No artifacts directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        display_name = agent.display_name or agent.agent_name or agent.cl_name

        from ...modals import AgentInterruptModal

        def on_dismiss(message: str | None) -> None:
            if message is None:
                return
            self._write_interrupt_request(artifacts_dir, message, display_name)  # type: ignore[arg-type]

        self.push_screen(  # type: ignore[attr-defined]
            AgentInterruptModal(display_name, agent.cl_name),
            on_dismiss,
        )

    def _write_interrupt_request(
        self, artifacts_dir: str, message: str, display_name: str
    ) -> None:
        """Write the interrupt request file for the agent provider to pick up."""
        request_path = Path(artifacts_dir) / "interrupt_request.json"
        try:
            with open(request_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"message": message, "timestamp": time.time()},
                    f,
                    indent=2,
                )
        except OSError:
            self.notify("Failed to write interrupt request", severity="error")  # type: ignore[attr-defined]
            return

        self.notify(f"Message sent to {display_name}")  # type: ignore[attr-defined]
