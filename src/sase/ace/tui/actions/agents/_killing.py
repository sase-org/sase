"""Agent killing/dismissal methods for the ace TUI app."""

from __future__ import annotations

import os
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec


def delete_agent_artifacts(artifacts_dir: str | None) -> None:
    """Delete artifact files that cause an agent to be loaded.

    Removes workflow_state.json, done.json, and prompt_step_*.json files
    from the artifacts directory so the agent won't be reloaded on restart.

    Args:
        artifacts_dir: Path to the agent's artifacts directory, or None.
    """
    from pathlib import Path

    if not artifacts_dir:
        return

    artifacts_path = Path(artifacts_dir)
    if not artifacts_path.is_dir():
        return

    # Delete files that the loaders scan for
    for pattern in ("workflow_state.json", "done.json", "prompt_step_*.json"):
        for f in artifacts_path.glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass


def _dismiss_notifications_for_agent(agent: Agent) -> None:
    """Dismiss notifications that reference the given agent.

    Handles JumpToAgent (cl_name/raw_suffix), PlanApproval and UserQuestion
    (agent_cl_name/agent_timestamp) notification types.
    """
    from sase.notifications import load_notifications, mark_dismissed

    for n in load_notifications():
        if n.action == "JumpToAgent":
            if n.action_data.get("cl_name") != agent.cl_name:
                continue
            n_raw_suffix = n.action_data.get("raw_suffix")
            if n_raw_suffix is not None and n_raw_suffix != agent.raw_suffix:
                continue
            mark_dismissed(n.id)
        elif n.action in ("PlanApproval", "UserQuestion"):
            if n.action_data.get("agent_cl_name") != agent.cl_name:
                continue
            n_timestamp = n.action_data.get("agent_timestamp")
            if n_timestamp is not None:
                from ...models._timestamps import normalize_to_14_digit

                if normalize_to_14_digit(n_timestamp) != agent.raw_suffix:
                    continue
            mark_dismissed(n.id)


def _find_workflow_workspace_from_running_field(
    project_file: str,
    workflow_name: str,
    cl_name: str | None = None,
) -> int | None:
    """Find workspace_num for a workflow from the RUNNING field.

    Args:
        project_file: Path to the project file.
        workflow_name: The workflow name (without "workflow()" wrapper).
        cl_name: Optional CL name for more specific matching.

    Returns:
        The workspace_num if found, None otherwise.
    """
    from sase.running_field import get_claimed_workspaces

    claims = get_claimed_workspaces(project_file)
    expected_workflow = f"workflow({workflow_name})"

    for claim in claims:
        if claim.workflow == expected_workflow:
            if cl_name is not None and claim.cl_name != cl_name:
                continue
            return claim.workspace_num

    return None


class AgentKillingMixin:
    """Mixin providing agent killing/dismissal methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    # ChangeSpec state
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: str

    # Agent state (needed for _dismiss_done_agent)
    _agents: list[Agent]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _pinned_agents: set[tuple[AgentType, str, str | None]]
    _agents_with_children: list[Agent]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]

    def _save_agent_bundle(self, agent: Agent) -> None:
        """Save a serialized bundle of agent data before artifact deletion.

        Bundles are used to populate the revive modal after TUI restart.
        ChangeSpec-loaded agents are skipped since they persist via .gp file fields.
        """
        from ....dismissed_agents import save_dismissed_bundle

        # Skip ChangeSpec-loaded agents — they persist via .gp file fields
        if agent._from_changespec:
            return

        save_dismissed_bundle(agent)

        # Also bundle workflow child steps when dismissing a parent.
        # Use _agents_with_children (unfiltered by fold state) so children
        # are included even when the workflow is collapsed.
        if not agent.is_workflow_child and agent.raw_suffix:
            for step in self._agents_with_children:
                if (
                    step.is_workflow_child
                    and step.parent_timestamp == agent.raw_suffix
                    and step.parent_workflow == agent.workflow
                ):
                    save_dismissed_bundle(step)

    def _persist_dismissed_agent(
        self, identity: tuple[AgentType, str, str | None]
    ) -> None:
        """Add an agent identity to the dismissed set and save to disk."""
        from ....dismissed_agents import save_dismissed_agents

        self._dismissed_agents.add(identity)
        save_dismissed_agents(self._dismissed_agents)

    def _do_kill_agent(self, agent: Agent) -> None:
        """Perform the actual agent kill after confirmation."""
        from ...models.agent import AgentType

        # Dispatch based on agent type and workflow pattern
        workflow = agent.workflow or ""
        if agent.agent_type == AgentType.WORKFLOW:
            self._kill_workflow_agent(agent)
        elif workflow.startswith("axe(fix-hook)") or workflow in (
            "fix-hook",
            "summarize-hook",
        ):
            self._kill_hook_agent(agent)
        elif workflow.startswith(("axe(mentor)", "mentor(")) or workflow == "mentor":
            self._kill_mentor_agent(agent)
        elif workflow.startswith("axe(crs)") or workflow == "crs":
            self._kill_crs_agent(agent)
        elif agent.agent_type == AgentType.RUNNING:
            self._kill_running_agent(agent)
        else:
            self.notify(  # type: ignore[attr-defined]
                f"Unknown agent type: {agent.agent_type}", severity="error"
            )
            return

        _dismiss_notifications_for_agent(agent)
        self._agent_status_overrides.pop(agent.identity, None)
        self._agent_pre_question_status.pop(agent.identity, None)
        self._refresh_notification_count()  # type: ignore[attr-defined]

        # Ensure the killed agent is tracked as dismissed so it's filtered
        # out immediately even if the loader still finds it (e.g. process
        # hasn't fully exited yet).  Some kill methods already call this
        # internally; the duplicate set-add is harmless.
        self._persist_dismissed_agent(agent.identity)

        # Immediately remove the killed agent (and its workflow children)
        # from the in-memory list and refresh the display.  This guarantees
        # the agent disappears from the UI without depending on the full
        # disk-scan in _load_agents(), which can race with process exit or
        # run during an in-flight screen transition (modal dismiss).
        killed_identity = agent.identity
        self._agents = [a for a in self._agents if a.identity != killed_identity]  # type: ignore[attr-defined]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity != killed_identity
        ]
        if agent.agent_type == AgentType.WORKFLOW and not agent.is_workflow_child:
            self._agents = [  # type: ignore[attr-defined]
                a
                for a in self._agents  # type: ignore[attr-defined]
                if not (
                    a.is_workflow_child
                    and a.parent_timestamp == agent.raw_suffix
                    and a.parent_workflow == agent.workflow
                )
            ]
            self._agents_with_children = [
                a
                for a in self._agents_with_children
                if not (
                    a.is_workflow_child
                    and a.parent_timestamp == agent.raw_suffix
                    and a.parent_workflow == agent.workflow
                )
            ]

        self._build_panel_indices()  # type: ignore[attr-defined]

        on_agents_tab = self.current_tab == "agents"  # type: ignore[attr-defined]
        if on_agents_tab:
            if self._agents:  # type: ignore[attr-defined]
                self.current_idx = min(  # type: ignore[attr-defined]
                    self.current_idx,
                    len(self._agents) - 1,  # type: ignore[attr-defined]
                )
            else:
                self.current_idx = 0  # type: ignore[attr-defined]
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

        # Schedule a full disk-scan refresh for the next event-loop
        # iteration so it runs after the screen transition is complete.
        self.call_later(self._load_agents)  # type: ignore[attr-defined]

    def _kill_process_group(self, pid: int) -> bool:
        """Kill a process group by PID.

        Args:
            pid: Process ID to kill.

        Returns:
            True if kill succeeded or process was already dead, False on error.
        """
        try:
            os.killpg(pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            # Process already dead - still consider success
            return True
        except PermissionError:
            self.notify(  # type: ignore[attr-defined]
                f"Permission denied killing PID {pid}", severity="error"
            )
            return False

    def _kill_running_agent(self, agent: Agent) -> None:
        """Kill a RUNNING type agent (workspace-based)."""
        from sase.running_field import release_workspace

        if agent.pid is None:
            return

        if not self._kill_process_group(agent.pid):
            return

        self.notify(f"Killed agent (PID {agent.pid})")  # type: ignore[attr-defined]

        # Release the workspace claim
        if agent.workspace_num is not None:
            release_workspace(
                agent.project_file,
                agent.workspace_num,
                agent.workflow,
                agent.cl_name,
            )

    def _kill_hook_agent(self, agent: Agent) -> None:
        """Kill a hook agent (fix-hook or summarize-hook)."""
        from ....changespec import parse_project_file
        from ....hooks import update_changespec_hooks_field
        from ....hooks.processes import mark_hook_agents_as_killed

        if agent.pid is None:
            return

        if not self._kill_process_group(agent.pid):
            return

        self.notify(f"Killed hook agent (PID {agent.pid})")  # type: ignore[attr-defined]

        # Update hook status to killed_agent
        changespecs = parse_project_file(agent.project_file)
        for cs in changespecs:
            if cs.name == agent.cl_name and cs.hooks:
                killed_hook_agents = []
                for hook in cs.hooks:
                    if hook.status_lines:
                        for sl in hook.status_lines:
                            if (
                                sl.suffix_type == "running_agent"
                                and sl.suffix == agent.raw_suffix
                            ):
                                killed_hook_agents.append((hook, sl, agent.pid))

                if killed_hook_agents:
                    updated_hooks = mark_hook_agents_as_killed(
                        cs.hooks, killed_hook_agents
                    )
                    update_changespec_hooks_field(
                        agent.project_file, agent.cl_name, updated_hooks
                    )
                break

    def _kill_mentor_agent(self, agent: Agent) -> None:
        """Kill a mentor agent."""
        from ....changespec import parse_project_file
        from ....hooks.processes import mark_mentor_agents_as_killed
        from ....mentors import update_changespec_mentors_field

        if agent.pid is None:
            return

        if not self._kill_process_group(agent.pid):
            return

        self.notify(f"Killed mentor agent (PID {agent.pid})")  # type: ignore[attr-defined]

        # Update mentor status to killed_agent
        changespecs = parse_project_file(agent.project_file)
        for cs in changespecs:
            if cs.name == agent.cl_name and cs.mentors:
                killed_mentor_agents = []
                for entry in cs.mentors:
                    if entry.status_lines:
                        for sl in entry.status_lines:
                            if (
                                sl.suffix_type == "running_agent"
                                and sl.suffix == agent.raw_suffix
                            ):
                                killed_mentor_agents.append((entry, sl, agent.pid))

                if killed_mentor_agents:
                    updated_mentors = mark_mentor_agents_as_killed(
                        cs.mentors, killed_mentor_agents
                    )
                    update_changespec_mentors_field(
                        agent.project_file, agent.cl_name, updated_mentors
                    )
                break

    def _kill_crs_agent(self, agent: Agent) -> None:
        """Kill a CRS (comments) agent."""
        from ....changespec import parse_project_file
        from ....comments import update_changespec_comments_field
        from ....comments.operations import mark_comment_agents_as_killed

        if agent.pid is None:
            return

        if not self._kill_process_group(agent.pid):
            return

        self.notify(f"Killed CRS agent (PID {agent.pid})")  # type: ignore[attr-defined]

        # Update comment status to killed_agent
        changespecs = parse_project_file(agent.project_file)
        for cs in changespecs:
            if cs.name == agent.cl_name and cs.comments:
                killed_comment_agents = []
                for comment in cs.comments:
                    if (
                        comment.suffix_type == "running_agent"
                        and comment.suffix == agent.raw_suffix
                    ):
                        killed_comment_agents.append((comment, agent.pid))

                if killed_comment_agents:
                    updated_comments = mark_comment_agents_as_killed(
                        cs.comments, killed_comment_agents
                    )
                    update_changespec_comments_field(
                        agent.project_file, agent.cl_name, updated_comments
                    )
                break

    def _kill_workflow_agent(self, agent: Agent) -> None:
        """Kill a workflow agent.

        Args:
            agent: The workflow agent to kill.
        """
        from sase.running_field import release_workspace

        # Kill the workflow process if it has a PID
        if agent.pid is not None:
            if not self._kill_process_group(agent.pid):
                return
            self.notify(f"Killed workflow (PID {agent.pid})")  # type: ignore[attr-defined]

        # Determine workflow name (steps use parent_workflow)
        workflow_name = agent.workflow
        if agent.is_workflow_child and agent.parent_workflow:
            workflow_name = agent.parent_workflow

        # Release the workspace claim (workflow claims use "workflow(name)" format)
        if workflow_name is not None:
            # Try agent's workspace_num first, then look it up from RUNNING field
            workspace_num = agent.workspace_num
            if workspace_num is None:
                # For steps, don't use the decorated cl_name for lookup
                # Also treat "unknown" as None since it's a placeholder
                lookup_cl_name = None
                if not agent.is_workflow_child and agent.cl_name != "unknown":
                    lookup_cl_name = agent.cl_name
                workspace_num = _find_workflow_workspace_from_running_field(
                    agent.project_file,
                    workflow_name,
                    lookup_cl_name,
                )

            if workspace_num is not None:
                release_workspace(
                    agent.project_file,
                    workspace_num,
                    f"workflow({workflow_name})",
                )

        # Save bundle before deleting artifacts (for revive support)
        self._save_agent_bundle(agent)

        # Delete artifact files so the agent won't be reloaded on restart
        delete_agent_artifacts(agent.artifacts_dir or agent.get_artifacts_dir())

        # Track dismissal as safety net (ensures agent is filtered even if
        # workspace release failed or RUNNING field persists)
        self._persist_dismissed_agent(agent.identity)

        # Also dismiss child steps (use unfiltered list so children are
        # found even when the workflow fold is collapsed).
        if not agent.is_workflow_child:
            for step in self._agents_with_children:
                if (
                    step.is_workflow_child
                    and step.parent_timestamp == agent.raw_suffix
                    and step.parent_workflow == agent.workflow
                ):
                    self._dismissed_agents.add(step.identity)
            # Persist after batching all child dismissals
            from ....dismissed_agents import save_dismissed_agents

            save_dismissed_agents(self._dismissed_agents)

    def _kill_and_dismiss_all_agents(self) -> None:
        """Kill all running agents and dismiss all done agents (double-confirm)."""
        from ._core import DISMISSABLE_STATUSES

        killable = [
            a
            for a in self._agents
            if a.pid is not None
            and a.status not in DISMISSABLE_STATUSES
            and a.identity not in self._pinned_agents
        ]
        dismissable = [
            a
            for a in self._agents
            if a.status in DISMISSABLE_STATUSES
            and a.raw_suffix is not None
            and a.identity not in self._pinned_agents
        ]

        if not killable and not dismissable:
            self.notify("No agents to kill or dismiss", severity="warning")  # type: ignore[attr-defined]
            return

        # Build description showing both groups
        desc_parts: list[str] = []
        if killable:
            k_count = len(killable)
            k_s = "s" if k_count != 1 else ""
            desc_parts.append(f"Kill: {k_count} running agent{k_s}")
            for agent in killable:
                name = agent.display_name
                suffix = f" @{agent.agent_name}" if agent.agent_name else ""
                desc_parts.append(f"  {name}{suffix}")
        if dismissable:
            d_count = len(dismissable)
            d_s = "s" if d_count != 1 else ""
            desc_parts.append(f"Dismiss: {d_count} completed agent{d_s}")
            for agent in dismissable:
                name = agent.display_name
                suffix = f" @{agent.agent_name}" if agent.agent_name else ""
                desc_parts.append(f"  {name}{suffix}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmKillAllModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                # Kill running agents first
                for agent in killable:
                    self._do_kill_agent(agent)
                # Then dismiss completed agents
                if dismissable:
                    self._do_dismiss_all(dismissable)

        self.push_screen(ConfirmKillAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def _dismiss_all_done_agents(self) -> None:
        """Dismiss all done/failed agents after user confirmation."""
        from ._core import DISMISSABLE_STATUSES

        dismissable = [
            a
            for a in self._agents
            if a.status in DISMISSABLE_STATUSES
            and a.raw_suffix is not None
            and a.identity not in self._pinned_agents
        ]

        if not dismissable:
            self.notify("No agents to dismiss", severity="warning")  # type: ignore[attr-defined]
            return

        # Build description similar to ConfirmKillModal format
        count = len(dismissable)
        s = "s" if count != 1 else ""
        desc_parts = [f"Count: {count} agent{s}"]
        for agent in dismissable:
            name = agent.display_name
            suffix = f" @{agent.agent_name}" if agent.agent_name else ""
            desc_parts.append(f"  {name}{suffix}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmDismissAllModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_dismiss_all(dismissable)

        self.push_screen(ConfirmDismissAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def _do_dismiss_all(self, agents: list[Agent]) -> None:
        """Perform batch dismissal of done/failed agents."""
        from ...models.agent import AgentType
        from ....dismissed_agents import save_dismissed_agents

        for agent in agents:
            _dismiss_notifications_for_agent(agent)
            self._agent_status_overrides.pop(agent.identity, None)
            self._agent_pre_question_status.pop(agent.identity, None)

            # Save bundle before deleting artifacts (for revive support)
            self._save_agent_bundle(agent)

            # Handle workspace release for workflow agents
            if agent.agent_type == AgentType.WORKFLOW:
                from sase.running_field import release_workspace

                workflow_name = agent.workflow
                if agent.is_workflow_child and agent.parent_workflow:
                    workflow_name = agent.parent_workflow
                if workflow_name is not None:
                    workspace_num = agent.workspace_num
                    if workspace_num is None:
                        lookup_cl_name = None
                        if not agent.is_workflow_child and agent.cl_name != "unknown":
                            lookup_cl_name = agent.cl_name
                        workspace_num = _find_workflow_workspace_from_running_field(
                            agent.project_file,
                            workflow_name,
                            lookup_cl_name,
                        )
                    if workspace_num is not None:
                        release_workspace(
                            agent.project_file,
                            workspace_num,
                            f"workflow({workflow_name})",
                        )

            # Delete artifact files
            delete_agent_artifacts(agent.artifacts_dir or agent.get_artifacts_dir())

            # Track dismissal
            self._dismissed_agents.add(agent.identity)

            # Also dismiss children for workflow parents
            if agent.agent_type == AgentType.WORKFLOW and not agent.is_workflow_child:
                for step in self._agents_with_children:
                    if (
                        step.is_workflow_child
                        and step.parent_timestamp == agent.raw_suffix
                        and step.parent_workflow == agent.workflow
                    ):
                        self._dismissed_agents.add(step.identity)

        # Batch persist and reload
        save_dismissed_agents(self._dismissed_agents)
        self._refresh_notification_count()  # type: ignore[attr-defined]

        count = len(agents)
        s = "s" if count != 1 else ""
        self.notify(f"Dismissed {count} agent{s}")  # type: ignore[attr-defined]
        self._load_agents()  # type: ignore[attr-defined]

    def _dismiss_done_agent(self, agent: Agent) -> None:
        """Dismiss a DONE or completed workflow agent.

        Deletes artifact files so the agent won't be reloaded on restart,
        and tracks the agent in the dismissed set as a safety net for the
        current session.

        Args:
            agent: The DONE or completed agent to dismiss.
        """
        from ...models.agent import AgentType

        if agent.raw_suffix is None:
            self.notify("Cannot dismiss agent: no timestamp", severity="error")  # type: ignore[attr-defined]
            return

        _dismiss_notifications_for_agent(agent)
        self._agent_status_overrides.pop(agent.identity, None)
        self._agent_pre_question_status.pop(agent.identity, None)
        self._refresh_notification_count()  # type: ignore[attr-defined]

        # Handle workflow agents - preserve artifacts, track dismissal only
        if agent.agent_type == AgentType.WORKFLOW:
            # Release the workspace claim first (workflow claims use
            # "workflow(name)" format in RUNNING field)
            from sase.running_field import release_workspace

            # Determine workflow name (steps use parent_workflow)
            workflow_name = agent.workflow
            if agent.is_workflow_child and agent.parent_workflow:
                workflow_name = agent.parent_workflow

            if workflow_name is not None:
                # Try agent's workspace_num first, then look it up from RUNNING field
                workspace_num = agent.workspace_num
                if workspace_num is None:
                    # For steps, don't use the decorated cl_name for lookup
                    # Also treat "unknown" as None since it's a placeholder
                    lookup_cl_name = None
                    if not agent.is_workflow_child and agent.cl_name != "unknown":
                        lookup_cl_name = agent.cl_name
                    workspace_num = _find_workflow_workspace_from_running_field(
                        agent.project_file,
                        workflow_name,
                        lookup_cl_name,
                    )

                if workspace_num is not None:
                    release_workspace(
                        agent.project_file,
                        workspace_num,
                        f"workflow({workflow_name})",
                    )

            self.notify(f"Dismissed workflow {agent.workflow}")  # type: ignore[attr-defined]

            # Save bundle before deleting artifacts (for revive support)
            self._save_agent_bundle(agent)

            # Delete artifact files so the agent won't be reloaded on restart
            # (dismissed_agents.json has a size limit and can evict old entries)
            delete_agent_artifacts(agent.artifacts_dir or agent.get_artifacts_dir())

            # Track dismissal as safety net for current session
            self._persist_dismissed_agent(agent.identity)

            # If this is a parent workflow (not a child step), also dismiss all
            # its steps.  Use unfiltered list so children are found even when
            # the workflow fold is collapsed.
            if not agent.is_workflow_child:
                for step in self._agents_with_children:
                    if (
                        step.is_workflow_child
                        and step.parent_timestamp == agent.raw_suffix
                        and step.parent_workflow == agent.workflow
                    ):
                        self._dismissed_agents.add(step.identity)
                # Persist after batching all child dismissals
                from ....dismissed_agents import save_dismissed_agents

                save_dismissed_agents(self._dismissed_agents)

            self._load_agents()  # type: ignore[attr-defined]
            return

        # Handle ChangeSpec-loaded agents (hooks, mentors, CRS)
        # These don't have a done.json file - they're stored as status lines
        # in the project file. We track dismissal in _dismissed_agents.
        if agent._from_changespec:
            self._persist_dismissed_agent(agent.identity)

            self.notify(  # type: ignore[attr-defined]
                f"Dismissed agent for {agent.cl_name}"
            )
            self._load_agents()  # type: ignore[attr-defined]
            return

        # Save bundle before deleting artifacts (for revive support)
        self._save_agent_bundle(agent)

        # Delete artifact files so the agent won't be reloaded on restart
        delete_agent_artifacts(agent.get_artifacts_dir())

        # Track dismissal as safety net for current session
        self._persist_dismissed_agent(agent.identity)
        self.notify(f"Dismissed agent for {agent.cl_name}")  # type: ignore[attr-defined]

        # Refresh agents list
        self._load_agents()  # type: ignore[attr-defined]
