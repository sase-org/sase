"""Agent auto-approve action for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentApproveMixin:
    """Mixin providing the agent auto-approve action.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]

    def action_toggle_approve(self) -> None:
        """Toggle auto-approve for the selected agent."""
        import json
        from pathlib import Path

        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        _APPROVE_ELIGIBLE = {
            "RUNNING",
            "PLANNING",
            "PLAN APPROVED",
            "WAITING",
            "QUESTION",
        }
        if agent.status not in _APPROVE_ELIGIBLE:
            self.notify("Agent not in an active status", severity="warning")  # type: ignore[attr-defined]
            return

        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not artifacts_dir:
            self.notify("No artifacts directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        # Read existing agent_meta.json
        meta_path = Path(artifacts_dir) / "agent_meta.json"
        meta: dict[str, object] = {}
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

        # Toggle approve field
        new_approve = not meta.get("approve", False)
        meta["approve"] = new_approve
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except OSError:
            self.notify("Failed to write agent_meta.json", severity="error")  # type: ignore[attr-defined]
            return

        # Update in-memory
        agent.approve = new_approve

        # Refresh display for immediate feedback
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

        label = "enabled" if new_approve else "disabled"
        self.notify(f"Auto-approve {label}")  # type: ignore[attr-defined]
