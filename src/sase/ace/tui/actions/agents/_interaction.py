"""Agent user interaction methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentInteractionMixin:
    """Mixin providing agent user interaction methods (kill, diff, edit, layout).

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    refresh_interval: int
    hide_non_run_agents: bool

    def action_kill_agent(self) -> None:
        """Kill or dismiss agent, or toggle/kill axe on AXE tab."""
        if self.current_tab == "axe":
            self._toggle_or_kill_axe_view()  # type: ignore[attr-defined]
            return
        if self.current_tab != "agents":
            return

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        agent = self._agents[self.current_idx]

        # Handle completed agents with dismiss (no confirmation needed)
        from ._core import DISMISSABLE_STATUSES

        if agent.status in DISMISSABLE_STATUSES:
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

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        agent = self._agents[self.current_idx]
        if agent.status in DISMISSABLE_STATUSES:
            return

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.refresh_current_file(agent)

    def action_reword(self) -> None:
        """Reword or unwait - behavior depends on current tab."""
        if self.current_tab == "agents":
            self._unwait_agent()
        else:
            # Call parent implementation for ChangeSpecs
            super().action_reword()  # type: ignore[misc]

    def _unwait_agent(self) -> None:
        """Remove the wait directive from a WAITING agent, letting it run immediately."""
        import json
        from pathlib import Path

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        agent = self._agents[self.current_idx]

        if agent.status != "WAITING":
            self.notify("Agent is not waiting", severity="warning")  # type: ignore[attr-defined]
            return

        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not artifacts_dir:
            self.notify("No artifacts directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        ready_path = Path(artifacts_dir) / "ready.json"
        if ready_path.exists():
            self.notify("Agent already has ready.json", severity="warning")  # type: ignore[attr-defined]
            return

        # Write ready.json so the polling agent runner proceeds immediately
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

        self.notify(f"Unwait: {agent.display_name or agent.cl_name}")  # type: ignore[attr-defined]

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

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        agent = self._agents[self.current_idx]

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

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
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
            from sase.sase_utils import get_sase_tmpdir

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
        """Resume a DONE agent's conversation with a new prompt."""
        if self.current_tab != "agents":
            return

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        agent = self._agents[self.current_idx]

        if agent.status != "DONE":
            self.notify("Agent not finished yet", severity="warning")  # type: ignore[attr-defined]
            return

        if not agent.response_path:
            self.notify("No chat file found", severity="warning")  # type: ignore[attr-defined]
            return

        chat_path = agent.response_path
        prefix = f"#resume:{chat_path} "

        from sase.chat_history import extract_prompt_from_chat_file
        from sase.xprompt import extract_vcs_workflow_tag

        prompt_text = extract_prompt_from_chat_file(chat_path)
        if prompt_text:
            vcs_tag = extract_vcs_workflow_tag(prompt_text)
            if vcs_tag:
                prefix = f"{vcs_tag}{prefix}"

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=f"resume({agent.cl_name or 'agent'})",
            history_sort_key=agent.cl_name or "resume",
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
        if self.current_tab != "agents":
            return

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        agent = self._agents[self.current_idx]

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.toggle_thinking(agent)

        # Refresh footer to reflect new state
        self._refresh_agents_display()  # type: ignore[attr-defined]

    def action_toggle_approve(self) -> None:
        """Toggle auto-approve for the selected agent."""
        import json
        from pathlib import Path

        if self.current_tab != "agents":
            return

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        agent = self._agents[self.current_idx]

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
