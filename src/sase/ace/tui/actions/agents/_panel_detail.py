"""Agent detail-panel actions for the ace TUI app."""

from __future__ import annotations

from ._panel_types import TabName


class AgentPanelDetailMixin:
    """Mixin providing detail-panel file, chat, and thinking actions."""

    current_tab: TabName

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
        """Cycle to the next file / next (older) chop run."""
        if self.current_tab == "agents":
            from ...widgets import AgentDetail

            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_detail.cycle_next_file()
        elif self.current_tab == "axe":
            self._axe_step_chop_run(direction=1)  # type: ignore[attr-defined]

    def action_prev_agent_file(self) -> None:
        """Cycle to the previous file / previous (newer) chop run."""
        if self.current_tab == "agents":
            from ...widgets import AgentDetail

            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_detail.cycle_prev_file()
        elif self.current_tab == "axe":
            self._axe_step_chop_run(direction=-1)  # type: ignore[attr-defined]

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

    def action_toggle_attempt_view(self) -> None:
        """Toggle the attempt history view between merged and current-only."""
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return
        if not agent.attempt_history:
            self.notify(  # type: ignore[attr-defined]
                "No prior attempts for this agent", severity="warning"
            )
            return
        # Attempt-pinned view renders the selected record directly; the
        # merged / current-only toggle does not apply.
        if getattr(self, "current_attempt_number", None) is not None:
            return

        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        agent_detail.toggle_attempt_view()
        mode = agent_detail.attempt_view_mode
        self.notify(f"Attempt view: {mode}")  # type: ignore[attr-defined]
        self._refresh_agents_display()  # type: ignore[attr-defined]

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
