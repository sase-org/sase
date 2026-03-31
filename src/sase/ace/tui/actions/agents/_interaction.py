"""Agent user interaction methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


def _resolve_vcs_tag(
    agent: Agent, name: str, agents: list[Agent] | None = None
) -> str | None:
    """Resolve a VCS workflow tag for the given agent, applying smart ref replacement.

    Falls back to the parent agent's raw_xprompt when the current agent (e.g. a
    coder follow-up) doesn't have its own raw_xprompt.md.

    Returns the tag string (with trailing space) or None if no VCS tag found.
    """
    from sase.xprompt import extract_vcs_workflow_tag, replace_ref_in_vcs_tag

    raw_content = agent.get_raw_xprompt_content()
    if not raw_content and agent.parent_timestamp and agents:
        for parent in agents:
            if parent.raw_suffix == agent.parent_timestamp:
                raw_content = parent.get_raw_xprompt_content()
                break
    if not raw_content:
        return None

    vcs_tag = extract_vcs_workflow_tag(raw_content)
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


class AgentInteractionMixin:
    """Mixin providing agent user interaction methods (kill, diff, edit, layout, pin).

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _pinned_agents: set[tuple[AgentType, str, str | None]]
    refresh_interval: int
    hide_non_run_agents: bool

    def action_kill_agent(self) -> None:
        """Kill or dismiss agent, or toggle/kill axe on AXE tab."""
        if self.current_tab == "changespecs":
            self.action_toggle_hide_submitted()  # type: ignore[attr-defined]
            return
        if self.current_tab == "axe":
            self._toggle_or_kill_axe_view()  # type: ignore[attr-defined]
            return
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        # Handle completed agents with dismiss (no confirmation needed)
        from ._core import DISMISSABLE_STATUSES

        if agent.status in DISMISSABLE_STATUSES:
            # Pinned agents: unpin first instead of dismissing directly
            if agent.identity in self._pinned_agents:
                self._unpin_and_focus(agent)
                return
            self._dismiss_done_agent(agent)  # type: ignore[attr-defined]
            return

        if agent.pid is None:
            # No process to kill - just dismiss the agent
            self._dismiss_done_agent(agent)  # type: ignore[attr-defined]
            return

        # Build description for confirmation dialog
        desc_parts = [f"Type: {agent.agent_type.value}"]
        desc_parts.append(f"CL: {agent.cl_name}")
        if agent.workspace_num is not None:
            desc_parts.append(f"Workspace: #{agent.workspace_num}")
        desc_parts.append(f"PID: {agent.pid}")
        agent_description = "\n".join(desc_parts)

        # Show confirmation modal
        from ...modals import ConfirmKillModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_kill_agent(agent)  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def action_pin_agent(self) -> None:
        """Toggle pinned state on an agent."""
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.raw_suffix is None:
            self.notify("Cannot pin agent: no timestamp", severity="warning")  # type: ignore[attr-defined]
            return

        from ....pinned_agents import save_pinned_agents, toggle_pinned_agent

        now_pinned = toggle_pinned_agent(self._pinned_agents, agent.identity)
        save_pinned_agents(self._pinned_agents)

        label = "Pinned" if now_pinned else "Unpinned"
        self.notify(f"{label} {agent.display_name}")  # type: ignore[attr-defined]

        # Rebuild panel indices so the item moves to the correct panel
        self._build_panel_indices()  # type: ignore[attr-defined]

        # Follow the item to its new panel (only if agent is already dismissable,
        # since running pinned agents stay in the main panel)
        from ._core import DISMISSABLE_STATUSES

        if agent.status in DISMISSABLE_STATUSES:
            if now_pinned and self._pinned_panel_focused != "pinned":  # type: ignore[has-type]
                self._pinned_panel_focused = "pinned"  # type: ignore[has-type]
            elif not now_pinned and self._pinned_panel_focused != "main":  # type: ignore[has-type]
                self._pinned_panel_focused = "main"  # type: ignore[has-type]

        # Auto-fallback if pinned panel is now empty
        if not self._pinned_panel_indices and self._pinned_panel_focused == "pinned":  # type: ignore[attr-defined, has-type]
            self._pinned_panel_focused = "main"  # type: ignore[has-type]

        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _unpin_and_focus(self, agent: Agent) -> None:
        """Unpin an agent and follow it to the main panel."""
        from ....pinned_agents import save_pinned_agents, toggle_pinned_agent

        toggle_pinned_agent(self._pinned_agents, agent.identity)
        save_pinned_agents(self._pinned_agents)

        self._build_panel_indices()  # type: ignore[attr-defined]
        self._pinned_panel_focused = "main"  # type: ignore[has-type]

        # Find the agent's new position in the main panel
        main_indices: list[int] = self._main_panel_indices  # type: ignore[attr-defined]
        for i, idx in enumerate(main_indices):
            if self._agents[idx] is agent:
                self.current_idx = i
                break

        # Auto-fallback if pinned panel is now empty
        if not self._pinned_panel_indices and self._pinned_panel_focused == "pinned":  # type: ignore[attr-defined, has-type]
            self._pinned_panel_focused = "main"  # type: ignore[has-type]

        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        self.notify(f"Unpinned {agent.display_name}")  # type: ignore[attr-defined]

    def action_show_diff(self) -> None:
        """Show diff - behavior depends on current tab."""
        if self.current_tab == "agents":
            self._refresh_agent_file()
        else:
            # Call parent implementation for ChangeSpecs
            super().action_show_diff()  # type: ignore[misc]

    def _refresh_agent_file(self) -> None:
        """Refresh the file for the currently selected agent."""
        from ...widgets import AgentDetail
        from ._core import DISMISSABLE_STATUSES

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return
        if agent.status in DISMISSABLE_STATUSES:
            return

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.refresh_current_file(agent)

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

        if agent.status not in ("WAITING", "RUNNING"):
            self.notify("Agent is not waiting or running", severity="warning")  # type: ignore[attr-defined]
            return

        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not artifacts_dir:
            self.notify("No artifacts directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        from ...modals import WaitModal

        is_running = agent.status == "RUNNING"

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

        if name:
            # Update waiting.json to wait for the specified agent instead
            waiting_path = Path(artifacts_dir) / "waiting.json"
            try:
                data: dict[str, object] = {}
                if waiting_path.exists():
                    with open(waiting_path, encoding="utf-8") as f:
                        data = json.load(f)
                data["waiting_for"] = [name]
                with open(waiting_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except OSError:
                self.notify("Failed to update waiting.json", severity="error")  # type: ignore[attr-defined]
                return
            agent.waiting_for = [name]
            self.notify(f"Now waiting for: {name}")  # type: ignore[attr-defined]
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
        """Kill a RUNNING agent and restart with %w:<name> added to the prompt."""
        if not name:
            self.notify("Agent is already running", severity="warning")  # type: ignore[attr-defined]
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

    def action_edit_spec(self) -> None:
        """Edit spec/chat - behavior depends on current tab."""
        if self.current_tab == "agents":
            self._open_agent_chat()
        else:
            # Call parent implementation for ChangeSpecs
            super().action_edit_spec()  # type: ignore[misc]

    def _open_agent_chat(self) -> None:
        """Open the agent's chat file in $EDITOR."""
        import os
        import subprocess

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        # Only available for completed agents
        if agent.status not in ("DONE",):
            self.notify("Agent not finished yet", severity="warning")  # type: ignore[attr-defined]
            return

        if not agent.response_path:
            self.notify("No chat file found", severity="warning")  # type: ignore[attr-defined]
            return

        editor = os.environ.get("EDITOR") or "nvim"
        file_path = os.path.expanduser(agent.response_path)

        with self.suspend():  # type: ignore[attr-defined]
            subprocess.run([editor, file_path], check=False)

    def action_next_agent_file(self) -> None:
        """Cycle to the next file (agents tab only)."""
        if self.current_tab == "agents":
            from ...widgets import AgentDetail

            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_detail.cycle_next_file()

    def action_prev_agent_file(self) -> None:
        """Cycle to the previous file (agents tab only)."""
        if self.current_tab == "agents":
            from ...widgets import AgentDetail

            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_detail.cycle_prev_file()

    def action_toggle_layout(self) -> None:
        """Toggle the layout between prompt-priority and file-priority."""
        if self.current_tab != "agents":
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]

        if agent_detail.is_info_mode() or (
            not agent_detail.is_file_visible()
            and not agent_detail.is_thinking_visible()
        ):
            self.notify("No panel to toggle layout", severity="warning")  # type: ignore[attr-defined]
            return

        agent_detail.toggle_layout()

    def action_edit_panel(self) -> None:
        """Open the visible panel's content in $EDITOR."""
        import os
        import subprocess
        import tempfile

        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        file_path, content, suffix = agent_detail.get_editor_file_info()

        if file_path is not None:
            editor = os.environ.get("EDITOR") or "nvim"
            expanded = os.path.expanduser(file_path)
            with self.suspend():  # type: ignore[attr-defined]
                subprocess.run([editor, expanded], check=False)
        elif content is not None:
            editor = os.environ.get("EDITOR") or "nvim"
            from sase.core.paths import get_sase_tmpdir

            fd, tmp_path = tempfile.mkstemp(
                suffix=suffix, prefix="sase_ace_panel_", dir=get_sase_tmpdir()
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(content)
                with self.suspend():  # type: ignore[attr-defined]
                    subprocess.run([editor, tmp_path], check=False)
            finally:
                os.unlink(tmp_path)
        else:
            self.notify("No content to edit", severity="warning")  # type: ignore[attr-defined]

    def action_resume_agent(self) -> None:
        """Resume a DONE agent's conversation, or queue resume for a running named agent."""
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        # Running named agents: use resume_by_name with %w to wait for completion
        from ._core import DISMISSABLE_STATUSES

        if agent.status not in DISMISSABLE_STATUSES and agent.agent_name:
            name = agent.agent_name
            prefix = f"#resume:{name} %w:{name} "

            vcs_tag = _resolve_vcs_tag(agent, name, self._agents)
            if vcs_tag:
                prefix = f"{vcs_tag}{prefix}"

            self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                initial_text=prefix,
                display_name=f"resume({name})",
                history_sort_key=agent.cl_name or "resume",
            )
            return

        if agent.status != "DONE":
            self.notify("Agent not finished yet", severity="warning")  # type: ignore[attr-defined]
            return

        if not agent.agent_name:
            self.notify("No agent name found", severity="warning")  # type: ignore[attr-defined]
            return

        name = agent.agent_name
        prefix = f"#resume:{name} "

        vcs_tag = _resolve_vcs_tag(agent, name, self._agents)
        if vcs_tag:
            prefix = f"{vcs_tag}{prefix}"

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=f"resume({name})",
            history_sort_key=agent.cl_name or "resume",
        )

    def action_wait_for_agent(self) -> None:
        """Populate prompt with VCS workflow and %w directive for the selected agent."""
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if not agent.agent_name:
            self.notify("No agent name found", severity="warning")  # type: ignore[attr-defined]
            return

        name = agent.agent_name
        prefix = f"%w:{name} "

        vcs_tag = _resolve_vcs_tag(agent, name, self._agents)
        if vcs_tag:
            prefix = f"{vcs_tag}{prefix}"

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=f"wait({name})",
            history_sort_key=agent.cl_name or "wait",
        )

    def action_reset_file_trim(self) -> None:
        """Reset file trim to default page size."""
        if self.current_tab != "agents":
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        if not agent_detail.is_file_visible():
            return
        agent_detail.reset_file_trim()

    def action_show_all_file_lines(self) -> None:
        """Show all file lines (remove trimming)."""
        if self.current_tab != "agents":
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        if not agent_detail.is_file_visible():
            return
        agent_detail.show_all_file_lines()

    def action_toggle_thinking(self) -> None:
        """Toggle the thinking panel for the selected agent."""
        self._cycle_panel_mode()

    def action_toggle_thinking_reverse(self) -> None:
        """Toggle the thinking panel in reverse direction."""
        self._cycle_panel_mode(reverse=True)

    def _cycle_panel_mode(self, *, reverse: bool = False) -> None:
        """Cycle the panel mode forward or backward."""
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.toggle_thinking(agent, reverse=reverse)

        # Refresh footer to reflect new state
        self._refresh_agents_display()  # type: ignore[attr-defined]

    def action_open_tmux(self) -> None:
        """Open tmux window for primary workspace (agents tab) or default."""
        if self.current_tab == "agents":
            self._open_agent_tmux_window(use_primary=True)
            return
        super().action_open_tmux()  # type: ignore[misc]

    def action_start_tmux_mode(self) -> None:
        """Open tmux window for agent workspace (agents tab) or enter tmux mode."""
        if self.current_tab == "agents":
            self._open_agent_tmux_window()
            return
        super().action_start_tmux_mode()  # type: ignore[misc]

    def _open_agent_tmux_window(self, *, use_primary: bool = False) -> None:
        """Open a new tmux window in the selected agent's workspace directory.

        Args:
            use_primary: If True, use the primary workspace (num=1) and project
                name as the tmux window name instead of the agent's workspace.
        """
        import subprocess
        from pathlib import Path

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        from ...widgets.prompt_panel._file_path_hints import resolve_agent_workspace_dir

        workspace_num = 1 if use_primary else agent.effective_workspace_num
        workspace_dir = resolve_agent_workspace_dir(workspace_num, agent.project_file)
        if not workspace_dir:
            self.notify("No workspace directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        project_name = Path(agent.project_file).parent.name
        if use_primary:
            window_name = project_name
        else:
            window_name = f"{project_name}_{workspace_num}"
        try:
            # Check if a window with this name already exists
            result = subprocess.run(
                ["tmux", "list-windows", "-F", "#{window_name}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if (
                result.returncode == 0
                and window_name in result.stdout.strip().splitlines()
            ):
                subprocess.run(
                    ["tmux", "select-window", "-t", f":={window_name}"],
                    check=False,
                )
                self.notify(f"Switched to tmux window: {window_name}")  # type: ignore[attr-defined]
            else:
                subprocess.run(
                    ["tmux", "new-window", "-n", window_name, "-c", workspace_dir],
                    check=False,
                )
                self.notify(f"Opened tmux window: {window_name}")  # type: ignore[attr-defined]
        except FileNotFoundError:
            self.notify("tmux command not found", severity="error")  # type: ignore[attr-defined]

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
