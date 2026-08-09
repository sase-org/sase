"""Patch navigation helpers for selected agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.core.paths import sase_projects_dir

from ._panel_types import TabName

if TYPE_CHECKING:
    from ...models import Agent


class AgentPatchNavigationMixin:
    """Mixin providing jump-to-Patch behavior for selected agents."""

    current_tab: TabName
    _agents_with_children: list[Agent]

    def _resolve_agent_cl_name(self, agent: Agent) -> str | None:
        """Resolve the effective Patch name for navigation.

        For workflow step children, looks up the parent workflow's cl_name
        (since children have step_name as cl_name, not a real Patch).
        For project agents, checks meta output variables.
        For all others, uses agent.cl_name directly.

        Returns None when the resolved name is "unknown" or empty.
        """
        # Workflow step children: resolve via parent
        if agent.parent_workflow is not None:
            cl_name = self._resolve_workflow_child_cl_name(agent)
            if not cl_name or cl_name == "unknown":
                return None
            return cl_name

        # Project agents: check meta output
        if agent.is_project_agent:
            from ._notification_actions import get_meta_patch_name

            return get_meta_patch_name(agent)

        # All others (including follow-up agents): use cl_name directly
        cl_name = agent.cl_name
        if not cl_name or cl_name == "unknown":
            return None
        return cl_name

    def _resolve_workflow_child_cl_name(self, agent: Agent) -> str | None:
        """Resolve cl_name for a workflow step child by finding its parent."""
        for candidate in self._agents_with_children:
            if candidate.is_workflow_child:
                continue
            if candidate.raw_suffix != agent.parent_timestamp:
                continue
            if candidate.workflow != agent.parent_workflow:
                continue
            return candidate.cl_name

        # Parent not in list - read workflow_state.json directly
        return self._read_workflow_state_cl_name(agent)

    @staticmethod
    def _read_workflow_state_cl_name(agent: Agent) -> str | None:
        """Read cl_name from workflow_state.json for a workflow child."""
        import json
        from pathlib import Path

        if not agent.parent_workflow or not agent.raw_suffix:
            return None

        project_name = Path(agent.project_file).parent.name
        base_workflow = (
            agent.parent_workflow.split("/")[-1]
            if "/" in agent.parent_workflow
            else agent.parent_workflow
        )
        state_file = (
            sase_projects_dir()
            / project_name
            / "artifacts"
            / f"workflow-{base_workflow}"
            / agent.raw_suffix
            / "workflow_state.json"
        )

        try:
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("context", {}).get("cl_name")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def action_jump_to_agent_patch(self) -> None:
        """Jump to the Patches tab selecting the Patch for the current agent."""
        self._jump_to_agent_patch("No Patch for this agent")

    def _jump_to_agent_patch(self, no_patch_message: str) -> None:
        """Jump to the patch attached to the selected agent."""
        if self.current_tab != "agents":
            return
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return

        cs_name = self._resolve_agent_cl_name(agent)
        if not cs_name:
            self.notify(no_patch_message, severity="warning")  # type: ignore[attr-defined]
            return

        from ._notification_actions import navigate_to_patch_tab

        navigate_to_patch_tab(self, cs_name, agent.project_file)

    def action_jump_to_agent_changespec(self) -> None:  # legacy compatibility alias
        """Legacy alias for :meth:`action_jump_to_agent_patch`."""
        self._jump_to_agent_patch("No Patch for this agent")


AgentChangespecNavigationMixin = AgentPatchNavigationMixin  # legacy compatibility alias
