"""Agent tmux workspace actions for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._panel_types import TabName

if TYPE_CHECKING:
    from ...models.agent import Agent
    from ...modals.agent_workspace_tmux_modal import AgentWorkspaceTmuxChoice
    from ...opened_workspaces import OpenedWorkspaceDisplayEvent


class AgentPanelTmuxMixin:
    """Mixin providing tmux workspace actions for selected agents."""

    current_tab: TabName

    # ------------------------------------------------------------------
    # No-I/O opened-workspace cache handoff
    #
    # The debounced detail render publishes the selected agent's cached
    # opened-workspace events here (keyed by agent identity). ``t`` reads only
    # this in-memory cache to decide whether to open the chooser, so the
    # keypress never parses marker JSON or ``stat()``s marker files.
    # ------------------------------------------------------------------

    def publish_selected_agent_opened_workspaces(
        self,
        agent: Agent,
        events: tuple[OpenedWorkspaceDisplayEvent, ...],
    ) -> None:
        """Store the cached opened-workspace events for ``agent``.

        Empty tuples are stored too, so old non-empty data cannot leak across
        refreshes once the selection's expensive summary is rebuilt.
        """
        self._selected_agent_opened_workspaces: tuple[
            tuple[Any, ...], tuple[OpenedWorkspaceDisplayEvent, ...]
        ] = (agent.identity, tuple(events))

    def cached_opened_workspaces_for_agent(
        self, agent: Agent
    ) -> tuple[OpenedWorkspaceDisplayEvent, ...]:
        """Return cached opened-workspace events for ``agent`` (no I/O)."""
        cached = getattr(self, "_selected_agent_opened_workspaces", None)
        if cached is None:
            return ()
        identity, events = cached
        if identity != agent.identity:
            return ()
        return events

    def cached_agent_tmux_choice_count(self, agent: Agent | None) -> int:
        """Return the number of tmux chooser targets for ``agent`` (no I/O).

        Counts ``CURRENT`` plus one deduped option per opened linked repo. A
        return value of ``0`` means no opened-workspace context is cached, so
        ``t`` keeps its direct-open behavior.
        """
        if agent is None:
            return 0
        events = self.cached_opened_workspaces_for_agent(agent)
        if not events:
            return 0
        from ...modals.agent_workspace_tmux_modal import (
            build_agent_workspace_tmux_choices,
        )

        return len(build_agent_workspace_tmux_choices(agent, events))

    # ------------------------------------------------------------------
    # Keymap actions
    # ------------------------------------------------------------------

    def action_open_tmux(self) -> None:
        """Open tmux window for primary workspace (agents tab) or default."""
        if self.current_tab == "agents":
            self._open_agent_tmux_window(use_primary=True)
            return
        super().action_open_tmux()  # type: ignore[misc]

    def action_start_tmux_mode(self) -> None:
        """``t`` opens the workspace chooser or tmux directly; tmux mode otherwise."""
        if self.current_tab == "agents":
            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is None:
                self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
                return
            events = self.cached_opened_workspaces_for_agent(agent)
            if events:
                self._open_agent_workspace_tmux_chooser(agent, events)
                return
            self._open_agent_tmux_window(use_primary=False)
            return
        super().action_start_tmux_mode()  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Chooser
    # ------------------------------------------------------------------

    def _open_agent_workspace_tmux_chooser(
        self,
        agent: Agent,
        events: tuple[OpenedWorkspaceDisplayEvent, ...],
    ) -> None:
        """Push the tmux workspace chooser for the selected agent."""
        from ...modals.agent_workspace_tmux_modal import (
            AgentWorkspaceTmuxModal,
            build_agent_workspace_tmux_choices,
        )

        current_dir, _ = self._resolve_agent_tmux_target(agent, use_primary=False)
        choices = build_agent_workspace_tmux_choices(
            agent, events, current_workspace_dir=current_dir
        )

        def _on_selected(index: int | None) -> None:
            if index is None or not (0 <= index < len(choices)):
                return
            choice = choices[index]
            if choice.kind == "current":
                # Route through the existing path so numbered-workspace,
                # directory-mode, and workflow-step behavior stay unchanged.
                self._open_agent_tmux_window(use_primary=False)
                return
            self._open_linked_workspace_tmux(choice)

        self.push_screen(AgentWorkspaceTmuxModal(choices), _on_selected)  # type: ignore[attr-defined]

    def _open_linked_workspace_tmux(self, choice: AgentWorkspaceTmuxChoice) -> None:
        """Open or switch to a tmux window for a recorded linked workspace."""
        import os

        workspace_dir = choice.workspace_dir or ""
        expanded = os.path.expanduser(workspace_dir)
        if not workspace_dir or not os.path.isdir(expanded):
            self.notify(  # type: ignore[attr-defined]
                f"Linked workspace not found: {choice.label}",
                severity="warning",
            )
            return
        self._open_tmux_window_for_directory(expanded.rstrip("/"), choice.window_name)

    # ------------------------------------------------------------------
    # Current/primary workspace resolution + tmux open
    # ------------------------------------------------------------------

    def _resolve_agent_tmux_target(
        self, agent: Agent, *, use_primary: bool
    ) -> tuple[str | None, str]:
        """Resolve ``(workspace_dir, window_name)`` for the selected agent.

        Args:
            use_primary: If True, use the primary workspace (num=1) and project
                name as the tmux window name instead of the agent's workspace.
        """
        from pathlib import Path

        from ...widgets.prompt_panel._file_path_hints import (
            resolve_agent_workspace_dir,
        )

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

        project_name = (
            agent.project_display_name or Path(agent.project_file).parent.name
        )
        if use_primary:
            window_name = project_name
        else:
            window_name = f"{project_name}_{workspace_num}"
        return workspace_dir, window_name

    def _open_agent_tmux_window(self, *, use_primary: bool = False) -> None:
        """Open a new tmux window in the selected agent's workspace directory.

        Args:
            use_primary: If True, use the primary workspace (num=1) and project
                name as the tmux window name instead of the agent's workspace.
        """
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        workspace_dir, window_name = self._resolve_agent_tmux_target(
            agent, use_primary=use_primary
        )
        if not workspace_dir:
            self.notify("No workspace directory for agent", severity="warning")  # type: ignore[attr-defined]
            return

        self._open_tmux_window_for_directory(workspace_dir, window_name)

    def _open_tmux_window_for_directory(
        self, workspace_dir: str, window_name: str
    ) -> None:
        """Select an existing tmux window named ``window_name`` or create one."""
        import subprocess

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
