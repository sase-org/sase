"""Agent ordering and auto-approve actions for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentOrderingMixin:
    """Mixin providing agent ordering and auto-approve actions.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _agent_custom_order: list[tuple[AgentType, str, str | None]]

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

    def action_move_agent_down(self) -> None:
        """Move the selected agent down in the list."""
        self._move_agent(1)

    def action_move_agent_up(self) -> None:
        """Move the selected agent up in the list."""
        self._move_agent(-1)

    def _move_agent(self, direction: int) -> None:
        """Move the selected agent up or down within the focused panel.

        Args:
            direction: +1 to move down, -1 to move up.
        """
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return

        # Only top-level agents can be moved
        if agent.is_workflow_child:
            return

        # Get the focused panel's indices
        panel_indices: list[int] = self._active_panel_indices()  # type: ignore[attr-defined]
        if not panel_indices:
            return

        # Find position of selected agent among top-level entries in the panel
        top_level_positions: list[int] = []
        for panel_pos, global_idx in enumerate(panel_indices):
            a = self._agents[global_idx]
            if not a.is_workflow_child:
                top_level_positions.append(panel_pos)

        # Find current agent's position in top-level list
        current_panel_pos = None
        for tl_idx, panel_pos in enumerate(top_level_positions):
            global_idx = panel_indices[panel_pos]
            if self._agents[global_idx].identity == agent.identity:
                current_panel_pos = tl_idx
                break

        if current_panel_pos is None:
            return

        # Compute swap target
        target_tl_idx = current_panel_pos + direction
        if target_tl_idx < 0 or target_tl_idx >= len(top_level_positions):
            return  # At boundary, can't move further

        # Get the identities of both agents
        current_identity = agent.identity
        target_panel_pos = top_level_positions[target_tl_idx]
        target_global_idx = panel_indices[target_panel_pos]
        target_identity = self._agents[target_global_idx].identity

        # Initialize custom order from current agent list if empty
        if not self._agent_custom_order:
            self._agent_custom_order = [
                a.identity for a in self._agents if not a.is_workflow_child
            ]

        # Find positions in custom order
        current_order_idx: int | None = None
        target_order_idx: int | None = None
        for i, identity in enumerate(self._agent_custom_order):
            if identity == current_identity:
                current_order_idx = i
            if identity == target_identity:
                target_order_idx = i

        # If either identity is missing from the custom order, treat the
        # currently displayed top-level order as the explicit user order before
        # applying this move. This keeps a fresh top entry moving one visible
        # slot instead of being appended after older persisted identities.
        if current_order_idx is None or target_order_idx is None:
            self._agent_custom_order = [
                a.identity for a in self._agents if not a.is_workflow_child
            ]
            # Re-find positions
            for i, identity in enumerate(self._agent_custom_order):
                if identity == current_identity:
                    current_order_idx = i
                if identity == target_identity:
                    target_order_idx = i

        if current_order_idx is None or target_order_idx is None:
            return

        # Swap in custom order
        (
            self._agent_custom_order[current_order_idx],
            self._agent_custom_order[target_order_idx],
        ) = (
            self._agent_custom_order[target_order_idx],
            self._agent_custom_order[current_order_idx],
        )

        # Persist
        from ....agent_order import save_agent_order

        save_agent_order(self._agent_custom_order)

        # Rebuild ordering in-place (apply custom order to current list)
        from ._loading import apply_custom_order

        self._agents = apply_custom_order(self._agents, self._agent_custom_order)

        # Rebuild panel indices
        self._build_panel_indices()  # type: ignore[attr-defined]

        # Update current_idx to follow the moved agent
        for i, a in enumerate(self._agents):
            if a.identity == current_identity:
                self.current_idx = i
                break

        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
