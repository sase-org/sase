"""Agent wait and fork actions for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    agent_family_base,
    canonical_plan_chain_suffix,
)
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

from ...models.agent_status import is_resumable_done_status

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Post-plan handoff statuses where forking should pick up the coder
# follow-up's chat rather than the planner's. Symmetric with the
# DISMISSABLE_STATUSES set used by other consumers.
_PLAN_HANDOFF_DONE_STATUSES: frozenset[str] = frozenset({"PLAN DONE", "TALE DONE"})


def _is_coder_followup_suffix(suffix: str | None) -> bool:
    """Return True for the coder follow-up suffix."""
    return canonical_plan_chain_suffix(suffix) == PLAN_CHAIN_CODER_SUFFIX


def _is_agent_family_root(agent: Agent) -> bool:
    return not agent.is_workflow_child and (
        agent.plan_chain_root or agent.agent_family_role == "root"
    )


def _agent_prompt_name(agent: Agent) -> str | None:
    """Return the name wait/fork/copy prompts should use for a row."""
    if _is_agent_family_root(agent):
        if agent.agent_family:
            return agent.agent_family
        if agent.agent_name:
            return (
                agent_family_base(agent.agent_name, include_legacy_dash=True)
                or agent.agent_name
            )
    return agent.agent_name


def _parse_wait_dependency_names(text: str) -> list[str]:
    """Parse modal input into agent-name dependencies."""
    return [part.strip() for part in text.split(",") if part.strip()]


def _resolve_vcs_tag(
    agent: Agent, name: str, agents: list[Agent] | None = None
) -> str | None:
    """Resolve a VCS workflow tag for the given agent, applying smart ref replacement.

    Falls back to the parent agent's raw_xprompt when the current agent (e.g. a
    coder follow-up) doesn't have its own raw_xprompt.md.

    Returns the tag string (with trailing space) or None if no VCS tag found.
    """
    from sase.xprompt import (
        extract_vcs_workflow_tag,
        find_vcs_workflow_tag,
        replace_ref_in_vcs_tag,
    )

    raw_content = agent.get_raw_xprompt_content()
    if not raw_content and agent.parent_timestamp and agents:
        for parent in agents:
            if parent.raw_suffix == agent.parent_timestamp:
                raw_content = parent.get_raw_xprompt_content()
                break
    if not raw_content:
        return None

    vcs_tag = extract_vcs_workflow_tag(raw_content) or find_vcs_workflow_tag(
        raw_content
    )
    if not vcs_tag:
        return None

    # Use actual branch name if agent has one (not just the project name)
    if not agent.is_project_agent:
        return replace_ref_in_vcs_tag(vcs_tag, agent.cl_name)

    # Use @<name> if prompt contains #pr (will resolve to agent's branch)
    from sase.xprompt.workflow_validator_extract import extract_xprompt_calls

    if any(call.name == "pr" for call in extract_xprompt_calls(raw_content)):
        return replace_ref_in_vcs_tag(vcs_tag, f"@{name}")

    return vcs_tag


class AgentWaitResumeMixin:
    """Mixin providing agent wait and resume actions.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    def action_reword(self) -> None:
        """Reword or wait - behavior depends on current tab."""
        if self.current_tab == "agents":
            self._wait_agent()
        else:
            # Call parent implementation for ChangeSpecs
            super().action_reword()  # type: ignore[misc]

    def _wait_agent(self) -> None:
        """Prompt for an agent name to wait for, or run immediately."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.status not in ("STARTING", "WAITING", "RUNNING"):
            self.notify(  # type: ignore[attr-defined]
                "Agent is not starting, waiting, or running",
                severity="warning",
            )
            return

        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not artifacts_dir:
            self.notify("No artifacts directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        from ...modals import WaitModal

        is_running = agent.status in {"STARTING", "RUNNING"}

        def handle_wait_result(result: str | None) -> None:
            if result is None:
                return  # cancelled
            if is_running:
                self._apply_wait_running(agent, result)
            else:
                self._apply_wait(artifacts_dir, agent, result)

        self.push_screen(  # type: ignore[attr-defined]
            WaitModal(current_waiting_for=agent.waiting_for, is_running=is_running),
            handle_wait_result,
        )

    def _apply_wait(self, artifacts_dir: str, agent: Agent, name: str) -> None:
        """Apply the wait result: run now (empty) or wait for a new agent."""
        import json
        from pathlib import Path

        wait_names = _parse_wait_dependency_names(name)
        if wait_names:
            # Update waiting.json to wait for the specified agent instead
            waiting_path = Path(artifacts_dir) / "waiting.json"
            try:
                data: dict[str, object] = {}
                if waiting_path.exists():
                    with open(waiting_path, encoding="utf-8") as f:
                        data = json.load(f)
                for condition_key in ("waiting_for", "wait_duration", "wait_until"):
                    data.pop(condition_key, None)
                data["waiting_for"] = wait_names
                with open(waiting_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                update_agent_artifact_index_for_marker_mutation(artifacts_dir)
            except OSError:
                self.notify("Failed to update waiting.json", severity="error")  # type: ignore[attr-defined]
                return
            agent.waiting_for = wait_names
            agent.wait_duration = None
            agent.wait_until = None
            wait_label = ", ".join(wait_names)
            self.notify(f"Now waiting for: {wait_label}")  # type: ignore[attr-defined]
            self._refresh_agents_display(list_changed=False)  # type: ignore[attr-defined]
        else:
            # Empty name → run now (write ready.json)
            ready_path = Path(artifacts_dir) / "ready.json"
            if ready_path.exists():
                self.notify("Agent already has ready.json", severity="warning")  # type: ignore[attr-defined]
                return
            try:
                with open(ready_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {"resolved_deps": agent.waiting_for, "unwait": True},
                        f,
                        indent=2,
                    )
            except OSError:
                self.notify("Failed to write ready.json", severity="error")  # type: ignore[attr-defined]
                return
            self.notify(f"Wait: {agent.display_name or agent.cl_name}")  # type: ignore[attr-defined]

    def _apply_wait_running(self, agent: Agent, name: str) -> None:
        """Kill an active agent and restart with %w:<name> added to the prompt."""
        if not name:
            status = (agent.status or "active").lower()
            self.notify(f"Agent is already {status}", severity="warning")  # type: ignore[attr-defined]
            return

        # Get the raw prompt before killing
        raw_content = agent.get_raw_xprompt_content()
        if not raw_content:
            self.notify("No prompt found for agent", severity="warning")  # type: ignore[attr-defined]
            return

        from ...modals import ConfirmKillModal

        desc_parts = [f"Kill and restart with %w:{name}"]
        if agent.cl_name:
            desc_parts.append(f"CL: {agent.cl_name}")
        if agent.pid:
            desc_parts.append(f"PID: {agent.pid}")
        agent_description = "\n".join(desc_parts)

        def on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return

            # Kill the agent
            self._do_kill_agent(agent)  # type: ignore[attr-defined]

            # Build new prompt with %w:<name> and auto-submit
            new_prompt = f"%w:{name} {raw_content}"

            self._setup_home_prompt_context(  # type: ignore[attr-defined]
                display_name=agent.display_name or agent.cl_name,
                history_sort_key=agent.cl_name or "wait",
            )
            self._finish_agent_launch(new_prompt)  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillModal(agent_description), on_confirm)  # type: ignore[attr-defined]

    def action_fork_agent(self) -> None:
        """Fork a DONE agent's chat, or queue a fork for a running named agent."""
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        # Running named agents: use #fork with %w to wait for completion.
        from ._core import DISMISSABLE_STATUSES

        prompt_name = _agent_prompt_name(agent)

        if agent.status not in DISMISSABLE_STATUSES and prompt_name:
            name = prompt_name
            prefix = f"#fork:{name} %w:{name} "

            vcs_tag = _resolve_vcs_tag(agent, name, self._agents)
            if vcs_tag:
                prefix = f"{vcs_tag}{prefix}"

            self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                initial_text=prefix,
                display_name=f"fork({name})",
                history_sort_key=agent.cl_name or "fork",
            )
            return

        if agent.status in _PLAN_HANDOFF_DONE_STATUSES and not _is_agent_family_root(
            agent
        ):
            # Find the coder follow-up agent to fork its conversation.
            coder = next(
                (
                    f
                    for f in agent.followup_agents
                    if _is_coder_followup_suffix(f.role_suffix)
                ),
                None,
            )
            if coder and coder.agent_name:
                name = coder.agent_name
                prefix = f"#fork:{name} "
                vcs_tag = _resolve_vcs_tag(agent, name, self._agents)
                if vcs_tag:
                    prefix = f"{vcs_tag}{prefix}"
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=f"fork({name})",
                    history_sort_key=agent.cl_name or "fork",
                )
                return

        if not is_resumable_done_status(agent.status):
            self.notify("Agent not finished yet", severity="warning")  # type: ignore[attr-defined]
            return

        if not prompt_name:
            self.notify("No agent name found", severity="warning")  # type: ignore[attr-defined]
            return

        name = prompt_name
        prefix = f"#fork:{name} "

        vcs_tag = _resolve_vcs_tag(agent, name, self._agents)
        if vcs_tag:
            prefix = f"{vcs_tag}{prefix}"

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=f"fork({name})",
            history_sort_key=agent.cl_name or "fork",
        )

    def action_resume_agent(self) -> None:
        """Compatibility alias for the former Agents-tab continuation action."""
        self.action_fork_agent()

    def action_wait_for_agent(self) -> None:
        """Populate prompt with VCS workflow and %w directive for the selected agent."""
        if self.current_tab != "agents":
            return

        if self._marked_agents:
            self._bulk_wait_for_marked_agents()
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        self._wait_for_single_agent(agent)

    def _wait_for_single_agent(self, agent: Agent) -> None:
        """Open the prompt input bar with `%w:<name> ` for a single agent."""
        name = _agent_prompt_name(agent)
        if not name:
            self.notify("No agent name found", severity="warning")  # type: ignore[attr-defined]
            return

        prefix = f"%w:{name} "

        vcs_tag = _resolve_vcs_tag(agent, name, self._agents)
        if vcs_tag:
            prefix = f"{vcs_tag}{prefix}"

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=f"wait({name})",
            history_sort_key=agent.cl_name or "wait",
        )

    def _bulk_wait_for_marked_agents(self) -> None:
        """Open the prompt input bar with `%w:a,b,c ` for the marked agents."""
        marked: list[Agent] = [
            a for a in self._agents_with_children if a.identity in self._marked_agents
        ]
        named: list[Agent] = [a for a in marked if _agent_prompt_name(a)]
        skipped = len(marked) - len(named)

        if not named:
            self.notify("No marked agents have a name", severity="warning")  # type: ignore[attr-defined]
            return

        if len(named) == 1:
            self._wait_for_single_agent(named[0])
            if skipped:
                self.notify(  # type: ignore[attr-defined]
                    f"Skipped {skipped} marked agent(s) with no name",
                    severity="warning",
                )
            return

        names = [_agent_prompt_name(a) for a in named]
        prefix = f"%w:{','.join(n for n in names if n)} "

        cursor = self._get_selected_agent()  # type: ignore[attr-defined]
        tag_source = cursor if cursor is not None and cursor in named else named[0]
        tag_source_name = _agent_prompt_name(tag_source)
        assert tag_source_name is not None
        vcs_tag = _resolve_vcs_tag(tag_source, tag_source_name, self._agents)
        if vcs_tag:
            prefix = f"{vcs_tag}{prefix}"

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=f"wait({len(names)} agents)",
            history_sort_key=(cursor.cl_name if cursor else "wait") or "wait",
        )

        if skipped:
            self.notify(  # type: ignore[attr-defined]
                f"Skipped {skipped} marked agent(s) with no name",
                severity="warning",
            )
