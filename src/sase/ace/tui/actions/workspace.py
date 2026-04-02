"""Workspace (tmux/checkout) action methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ...changespec import ChangeSpec

# Type alias for tab names (used in type hints)
TabName = Literal["changespecs", "agents", "axe"]


class WorkspaceActionsMixin:
    """Mixin providing tmux and checkout workspace actions."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    query_string: str
    parsed_query: Any

    def action_open_tmux(self) -> None:
        """Open tmux session for the current ChangeSpec's project (workspace #1)."""
        self._open_tmux_for_workspace(1)

    def _open_tmux_for_workspace(self, workspace_num: int) -> None:
        """Open tmux session for the current ChangeSpec's project.

        Args:
            workspace_num: The workspace number to checkout and open tmux for (1-9).
        """
        import subprocess

        from sase.running_field import get_workspace_directory

        from ...changespec import get_base_status

        if not self.changespecs:
            # No matching CLs — try to open tmux for a sole project filter
            from sase.ace.query import get_sole_project_filter

            project_name = get_sole_project_filter(self.parsed_query)
            if project_name is None:
                return
            self._open_tmux_for_project(project_name, workspace_num)
            return

        changespec = self.changespecs[self.current_idx]

        # Validate status
        base_status = get_base_status(changespec.status)
        if base_status in ("Reverted", "Submitted", "Archived"):
            self.notify(  # type: ignore[attr-defined]
                "Tmux not available for Reverted/Submitted/Archived ChangeSpecs",
                severity="warning",
            )
            return

        project_basename = changespec.project_basename

        # Get workspace directory for specified workspace number
        try:
            workspace_dir = get_workspace_directory(
                project_basename, workspace_num=workspace_num
            )
        except RuntimeError as e:
            self.notify(f"Failed to get workspace directory: {e}", severity="error")  # type: ignore[attr-defined]
            return

        # Determine tmux session name: <project> for workspace 1, <project>_<N> otherwise
        if workspace_num == 1:
            tmux_session = project_basename
        else:
            tmux_session = f"{project_basename}_{workspace_num}"

        def run_commands() -> tuple[bool, str]:
            # Checkout via VCS provider
            from sase.vcs_provider import get_vcs_provider

            provider = get_vcs_provider(workspace_dir)
            resolved = provider.resolve_revision(
                changespec.name, project_basename, workspace_dir
            )
            success, error = provider.checkout(resolved, workspace_dir)
            if not success:
                return (False, f"checkout failed: {error}")

            # Switch to existing tmux window or create a new one
            try:
                result = subprocess.run(
                    ["tmux", "list-windows", "-F", "#{window_name}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if (
                    result.returncode == 0
                    and tmux_session in result.stdout.strip().splitlines()
                ):
                    subprocess.run(
                        ["tmux", "select-window", "-t", f":={tmux_session}"],
                        check=False,
                    )
                    return (True, f"Switched to tmux window: {tmux_session}")
                else:
                    subprocess.run(
                        [
                            "tmux",
                            "new-window",
                            "-n",
                            tmux_session,
                            "-c",
                            str(workspace_dir),
                        ],
                        check=False,
                    )
                    return (True, f"Opened tmux window: {tmux_session}")
            except FileNotFoundError:
                return (False, "tmux command not found")

        with self.suspend():  # type: ignore[attr-defined]
            success, message = run_commands()

        if success:
            self.notify(message)  # type: ignore[attr-defined]
        else:
            self.notify(message, severity="error")  # type: ignore[attr-defined]

    def action_checkout(self) -> None:
        """Checkout the current ChangeSpec in the primary workspace (no tmux)."""
        self._checkout_to_workspace(1)

    def _checkout_to_workspace(self, workspace_num: int) -> None:
        """Checkout the current ChangeSpec in the specified workspace (no tmux).

        Args:
            workspace_num: The workspace number to checkout to (1-9).
        """
        from sase.running_field import get_workspace_directory

        from ...changespec import get_base_status

        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        # Validate status
        base_status = get_base_status(changespec.status)
        if base_status in ("Reverted", "Submitted", "Archived"):
            self.notify(  # type: ignore[attr-defined]
                "Checkout not available for Reverted/Submitted/Archived ChangeSpecs",
                severity="warning",
            )
            return

        project_basename = changespec.project_basename

        # Get workspace directory for specified workspace number
        try:
            workspace_dir = get_workspace_directory(
                project_basename, workspace_num=workspace_num
            )
        except RuntimeError as e:
            self.notify(f"Failed to get workspace directory: {e}", severity="error")  # type: ignore[attr-defined]
            return

        def run_checkout() -> tuple[bool, str]:
            # Checkout via VCS provider
            from sase.vcs_provider import get_vcs_provider

            provider = get_vcs_provider(workspace_dir)
            resolved = provider.resolve_revision(
                changespec.name, project_basename, workspace_dir
            )
            success, error = provider.checkout(resolved, workspace_dir)
            if not success:
                return (False, f"checkout failed: {error}")

            return (True, f"Checked out {changespec.name} in {workspace_dir}")

        with self.suspend():  # type: ignore[attr-defined]
            success, message = run_checkout()

        if success:
            self.notify(message)  # type: ignore[attr-defined]
        else:
            self.notify(message, severity="error")  # type: ignore[attr-defined]

    def action_start_checkout_mode(self) -> None:
        """Enter checkout mode - press 1-9 to select workspace."""
        if self.current_tab != "changespecs":
            return
        self._checkout_mode_active = True  # type: ignore[attr-defined]

    def action_start_tmux_mode(self) -> None:
        """Open tmux for selected CL - prompts for workspace number."""
        if self.current_tab != "changespecs":
            return

        from ..modals import WorkspaceInputModal

        def on_workspace_entered(workspace_num: int | None) -> None:
            if workspace_num is None:
                return
            self._open_tmux_for_workspace(workspace_num)

        self.push_screen(WorkspaceInputModal(default_workspace=1), on_workspace_entered)  # type: ignore[attr-defined]

    def _open_tmux_for_project(self, project_basename: str, workspace_num: int) -> None:
        """Open tmux for a project without checking out a branch.

        Used when no CLs match but a sole project filter is present.

        Args:
            project_basename: The project name.
            workspace_num: The workspace number (1-9).
        """
        import subprocess

        from sase.running_field import get_workspace_directory

        try:
            workspace_dir = get_workspace_directory(
                project_basename, workspace_num=workspace_num
            )
        except RuntimeError as e:
            self.notify(f"Failed to get workspace directory: {e}", severity="error")  # type: ignore[attr-defined]
            return

        if workspace_num == 1:
            tmux_session = project_basename
        else:
            tmux_session = f"{project_basename}_{workspace_num}"

        def run_commands() -> tuple[bool, str]:
            try:
                result = subprocess.run(
                    ["tmux", "list-windows", "-F", "#{window_name}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if (
                    result.returncode == 0
                    and tmux_session in result.stdout.strip().splitlines()
                ):
                    subprocess.run(
                        ["tmux", "select-window", "-t", f":={tmux_session}"],
                        check=False,
                    )
                    return (True, f"Switched to tmux window: {tmux_session}")
                else:
                    subprocess.run(
                        [
                            "tmux",
                            "new-window",
                            "-n",
                            tmux_session,
                            "-c",
                            str(workspace_dir),
                        ],
                        check=False,
                    )
                    return (True, f"Opened tmux window: {tmux_session}")
            except FileNotFoundError:
                return (False, "tmux command not found")

        with self.suspend():  # type: ignore[attr-defined]
            success, message = run_commands()

        if success:
            self.notify(message)  # type: ignore[attr-defined]
        else:
            self.notify(message, severity="error")  # type: ignore[attr-defined]

    def _handle_checkout_key(self, key: str) -> bool:
        """Handle key in checkout mode. Returns True if handled."""
        self._checkout_mode_active = False  # type: ignore[attr-defined]

        if key in "123456789":
            workspace_num = int(key)
            self._checkout_to_workspace(workspace_num)
            return True

        # Invalid key - just exit mode
        return True
