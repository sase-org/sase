"""Agent tmux workspace actions for the ace TUI app."""

from __future__ import annotations

from ._panel_types import TabName


class AgentPanelTmuxMixin:
    """Mixin providing tmux workspace actions for selected agents."""

    current_tab: TabName

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
        if not use_primary and workspace_num is not None and workspace_num > 0:
            workspace_dir = resolve_agent_workspace_dir(
                workspace_num,
                agent.project_file,
            )
            if not workspace_dir and agent.workspace_dir:
                workspace_dir = resolve_agent_workspace_dir(
                    None,
                    agent.project_file,
                    agent.workspace_dir,
                )
        else:
            workspace_dir = resolve_agent_workspace_dir(
                workspace_num,
                agent.project_file,
                agent.workspace_dir if not use_primary else None,
            )
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
