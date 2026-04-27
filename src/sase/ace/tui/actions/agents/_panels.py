"""Agent detail panel viewing, navigation, and tmux actions for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models.agent_panels import AgentPanelGroup

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentPanelsMixin:
    """Mixin providing agent detail panel viewing, navigation, and tmux actions.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    current_attempt_number: int | None
    _panel_group: AgentPanelGroup
    _current_group_key: tuple[str, ...] | None

    def _change_focused_agent_panel(self, *, forward: bool) -> None:
        """Cycle focus between tag-driven side panels with wrap.

        Snaps ``current_idx`` to the first agent of the new focused
        panel and clears any pending banner-row focus.  No-ops when
        only the untagged main pane exists.
        """
        if self.current_tab != "agents":
            return
        if forward:
            changed = self._panel_group.focus_next()
        else:
            changed = self._panel_group.focus_prev()
        if not changed:
            return

        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        focused_key = self._panel_group.focused_key
        new_idx: int | None = None
        for i, k in enumerate(keys_per_agent):
            if k == focused_key:
                new_idx = i
                break
        if new_idx is not None:
            self.current_idx = new_idx  # type: ignore[attr-defined]
        self.current_attempt_number = None  # type: ignore[attr-defined]
        self._current_group_key = None  # type: ignore[attr-defined]
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def action_focus_next_agent_panel(self) -> None:
        """Move focus to the next tag-driven side panel (with wrap)."""
        self._change_focused_agent_panel(forward=True)

    def action_focus_prev_agent_panel(self) -> None:
        """Move focus to the previous tag-driven side panel (with wrap)."""
        self._change_focused_agent_panel(forward=False)

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

    def action_open_tmux(self) -> None:
        """Open tmux window for primary workspace (agents tab) or default."""
        if self.current_tab == "agents":
            self._open_agent_tmux_window(use_primary=True)
            return
        super().action_open_tmux()  # type: ignore[misc]

    def action_start_tmux_mode(self) -> None:
        """``t`` opens tmux in the focused agent's workspace; tmux mode otherwise."""
        if self.current_tab == "agents":
            self._open_agent_tmux_window(use_primary=False)
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
