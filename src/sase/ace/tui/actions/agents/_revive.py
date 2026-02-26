"""Agent revival methods for the ace TUI app."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


class AgentRevivalMixin:
    """Mixin providing agent revival (un-dismiss) functionality.

    Overrides action_start_rewind to dispatch to revive flow when on the
    Agents tab, otherwise delegates to the original rewind behavior.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: str
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]

    def action_start_rewind(self) -> None:
        """Dispatch R key: revive on Agents tab, rewind on ChangeSpecs tab."""
        if self.current_tab == "agents":
            self._revive_agent()
        else:
            super().action_start_rewind()  # type: ignore[misc]

    def _revive_agent(self) -> None:
        """Show project selection modal, then dismissed agent selection."""
        from ...modals import ProjectSelectModal, ProjectSelectResult, SelectionItem

        if not self._dismissed_agent_objects:
            self.notify("No dismissed agents to revive")  # type: ignore[attr-defined]
            return

        def _on_project_selected(result: ProjectSelectResult | None) -> None:
            if result is None:
                return
            selection = result.selection
            if not isinstance(selection, SelectionItem):
                return
            self._show_dismissed_agents_for_scope(selection)

        self.app.push_screen(  # type: ignore[attr-defined]
            ProjectSelectModal(include_all=True), _on_project_selected
        )

    def _show_dismissed_agents_for_scope(self, selection: object) -> None:
        """Filter dismissed agents by scope and show the selection modal."""
        from ...modals import SelectionItem
        from ...modals.revive_agent_modal import DismissedAgentSelectModal

        if not isinstance(selection, SelectionItem):
            return

        agents = self._dismissed_agent_objects

        if selection.item_type == "all":
            filtered = list(agents)
        elif selection.item_type == "home":
            filtered = [a for a in agents if a.cl_name == "~"]
        elif selection.item_type == "project":
            filtered = [
                a
                for a in agents
                if Path(a.project_file).parent.name == selection.project_name
            ]
            # Sort project-level agents above ChangeSpec agents
            filtered.sort(key=lambda a: 0 if a.is_project_agent else 1)
        elif selection.item_type == "cl":
            filtered = [a for a in agents if a.cl_name == selection.cl_name]
        else:
            return

        if not filtered:
            self.notify("No dismissed agents in this scope")  # type: ignore[attr-defined]
            return

        def _on_agent_selected(agent: object) -> None:
            if agent is None:
                return
            from ...models import Agent

            if not isinstance(agent, Agent):
                return
            self._do_revive_agent(agent)

        self.app.push_screen(  # type: ignore[attr-defined]
            DismissedAgentSelectModal(filtered), _on_agent_selected
        )

    def _do_revive_agent(self, agent: object) -> None:
        """Revive a dismissed agent by removing it from the dismissed set."""
        from ....dismissed_agents import (
            remove_bundle_by_identity,
            save_dismissed_agents,
        )
        from ...models import Agent

        if not isinstance(agent, Agent):
            return

        self._dismissed_agents.discard(agent.identity)

        # Also revive child steps if this is a parent workflow
        if not agent.is_workflow_child and agent.raw_suffix:
            for dismissed_agent in list(self._dismissed_agent_objects):
                if (
                    dismissed_agent.is_workflow_child
                    and dismissed_agent.parent_timestamp == agent.raw_suffix
                    and dismissed_agent.parent_workflow == agent.workflow
                ):
                    self._dismissed_agents.discard(dismissed_agent.identity)

        save_dismissed_agents(self._dismissed_agents)

        # Restore minimal artifact files so load_all_agents() rediscovers the agent
        self._restore_agent_artifacts(agent)

        # Also restore child step artifacts for workflow parents
        if not agent.is_workflow_child and agent.raw_suffix:
            for dismissed_agent in list(self._dismissed_agent_objects):
                if (
                    dismissed_agent.is_workflow_child
                    and dismissed_agent.parent_timestamp == agent.raw_suffix
                    and dismissed_agent.parent_workflow == agent.workflow
                ):
                    self._restore_agent_artifacts(dismissed_agent)

        # Clean up the bundle now that artifacts are restored
        remove_bundle_by_identity(agent.identity)

        self.notify(f"Revived agent for {agent.cl_name}")  # type: ignore[attr-defined]
        self._load_agents()  # type: ignore[attr-defined]

    def _restore_agent_artifacts(self, agent: Agent) -> None:
        """Restore minimal artifact files so load_all_agents() rediscovers the agent.

        For RUNNING agents: writes done.json to the artifacts directory.
        For WORKFLOW parents: writes workflow_state.json.
        For WORKFLOW children: writes prompt_step_<idx>.json to the parent's dir.
        """
        from ...models.agent import AgentType

        project_path = Path(agent.project_file)
        project_name = project_path.parent.name

        if agent.agent_type == AgentType.RUNNING:
            timestamp = agent._extract_artifacts_timestamp()
            if not timestamp:
                return
            artifacts_dir = Path(
                os.path.expanduser(
                    f"~/.sase/projects/{project_name}/artifacts/ace-run/{timestamp}"
                )
            )
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            done_file = artifacts_dir / "done.json"
            if not done_file.exists():
                done_file.write_text(json.dumps({"status": "DONE"}))

        elif agent.agent_type == AgentType.WORKFLOW:
            if agent.is_workflow_child:
                # Child step: write prompt_step_<idx>.json into parent's dir
                if agent.parent_timestamp is None or agent.step_index is None:
                    return
                # Determine parent artifacts dir
                parent_workflow = agent.parent_workflow or ""
                base_workflow = (
                    parent_workflow.split("/")[-1]
                    if "/" in parent_workflow
                    else parent_workflow
                )
                workflow_dir_name = f"workflow-{base_workflow}"
                # Convert parent_timestamp to artifacts format
                parent_ts = agent.parent_timestamp
                if len(parent_ts) == 13 and parent_ts[6] == "_":
                    parent_ts = f"20{parent_ts[:6]}{parent_ts[7:]}"
                artifacts_dir = Path(
                    os.path.expanduser(
                        f"~/.sase/projects/{project_name}/artifacts/{workflow_dir_name}/{parent_ts}"
                    )
                )
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                step_file = artifacts_dir / f"prompt_step_{agent.step_index}.json"
                if not step_file.exists():
                    step_file.write_text(json.dumps({"status": agent.status or "DONE"}))
            else:
                # Parent workflow: write workflow_state.json
                timestamp = agent._extract_artifacts_timestamp()
                if not timestamp:
                    return
                workflow = agent.workflow or ""
                base_workflow = workflow.split("/")[-1] if "/" in workflow else workflow
                workflow_dir_name = f"workflow-{base_workflow}"
                artifacts_dir = Path(
                    os.path.expanduser(
                        f"~/.sase/projects/{project_name}/artifacts/{workflow_dir_name}/{timestamp}"
                    )
                )
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                state_file = artifacts_dir / "workflow_state.json"
                if not state_file.exists():
                    state_file.write_text(
                        json.dumps({"status": agent.status or "DONE"})
                    )
