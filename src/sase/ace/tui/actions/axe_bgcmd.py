"""Background command mixin for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sase.commit_utils import run_sase_hg_clean
from sase.running_field import get_workspace_directory

from ..bgcmd import (
    BackgroundCommandInfo,
    clear_slot,
    find_first_available_slot,
    get_slot_info,
    is_slot_running,
    start_background_command,
    stop_background_command,
)

if TYPE_CHECKING:
    from ...changespec import ChangeSpec
    from ..modals.project_select_modal import SelectionItem

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AxeBgCmdMixin:
    """Mixin providing background command management."""

    # Type hints for attributes accessed from AceApp
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    axe_running: bool
    _bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]

    def action_start_bgcmd(self) -> None:
        """Start the background command workflow (! key on all tabs)."""
        # Check for available slot
        slot = find_first_available_slot()
        if slot is None:
            self.notify("Maximum background commands reached", severity="error")  # type: ignore[attr-defined]
            return

        # Show project select modal
        from ..modals import ProjectSelectModal

        def on_project_selected(
            result: SelectionItem | str | None,
        ) -> None:
            if result is None:
                return

            # Extract project name and optional CL name
            if isinstance(result, str):
                project = result
                cl_name = None
            else:
                project = result.project_name
                cl_name = result.cl_name

            # Show workspace input modal
            self._show_workspace_input(slot, project, cl_name)

        self.push_screen(ProjectSelectModal(), on_project_selected)  # type: ignore[attr-defined]

    def _start_bgcmd_from_changespec(self) -> None:
        """Start background command from current ChangeSpec (CLs tab only).

        This is the quick version triggered from leader mode that skips
        ProjectSelectModal, using the current ChangeSpec's project and CL name.
        """
        if self.current_tab != "changespecs":
            return

        if not self.changespecs:
            self.notify("No ChangeSpecs available", severity="warning")  # type: ignore[attr-defined]
            return

        # Check for available slot
        slot = find_first_available_slot()
        if slot is None:
            self.notify("Maximum background commands reached", severity="error")  # type: ignore[attr-defined]
            return

        changespec = self.changespecs[self.current_idx]
        project = changespec.project_basename
        cl_name = changespec.name

        # Go directly to workspace input, skipping ProjectSelectModal
        self._show_workspace_input(slot, project, cl_name)

    def _show_workspace_input(
        self, slot: int, project: str, cl_name: str | None = None
    ) -> None:
        """Show the workspace input modal.

        Args:
            slot: Slot number to use.
            project: Project name.
            cl_name: Optional CL name to checkout before running command.
        """
        from ..modals import WorkspaceInputModal

        def on_workspace_entered(workspace_num: int | None) -> None:
            if workspace_num is None:
                return
            self._show_command_input(slot, project, workspace_num, cl_name)

        self.push_screen(  # type: ignore[attr-defined]
            WorkspaceInputModal(default_workspace=10), on_workspace_entered
        )

    def _show_command_input(
        self, slot: int, project: str, workspace_num: int, cl_name: str | None = None
    ) -> None:
        """Show the command input/history modal.

        Args:
            slot: Slot number to use.
            project: Project name.
            workspace_num: Workspace number.
            cl_name: Optional CL name to checkout before running command.
        """
        from ..modals import CommandHistoryModal

        def on_command_selected(command: str | None) -> None:
            if command is None:
                return
            self._start_bgcmd(slot, command, project, workspace_num, cl_name)

        self.push_screen(  # type: ignore[attr-defined]
            CommandHistoryModal(current_cl=cl_name, current_project=project),
            on_command_selected,
        )

    def _start_bgcmd(
        self,
        slot: int,
        command: str,
        project: str,
        workspace_num: int,
        cl_name: str | None = None,
    ) -> None:
        """Start a background command.

        Args:
            slot: Slot number (1-9).
            command: Shell command to run.
            project: Project name.
            workspace_num: Workspace number.
            cl_name: Optional CL name to checkout before running command.
        """
        try:
            workspace_dir = get_workspace_directory(project, workspace_num)
        except RuntimeError as e:
            self.notify(f"Failed to get workspace: {e}", severity="error")  # type: ignore[attr-defined]
            return

        # If a CL was selected, checkout that CL first
        if cl_name is not None:
            # Clean workspace first (save uncommitted changes)
            clean_success, clean_error = run_sase_hg_clean(
                workspace_dir, f"{cl_name}-bgcmd"
            )
            if not clean_success:
                self.notify(  # type: ignore[attr-defined]
                    f"Warning: sase_hg_clean failed: {clean_error}", severity="warning"
                )

            # Checkout the CL via VCS provider
            from sase.vcs_provider import get_vcs_provider

            provider = get_vcs_provider(workspace_dir)
            resolved = provider.resolve_revision(cl_name, project, workspace_dir)
            checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
            if not checkout_ok:
                self.notify(f"checkout failed: {checkout_err}", severity="error")  # type: ignore[attr-defined]
                return

        pid = start_background_command(
            slot=slot,
            command=command,
            project=project,
            workspace_num=workspace_num,
            workspace_dir=workspace_dir,
        )

        if pid is None:
            self.notify("Failed to start background command", severity="error")  # type: ignore[attr-defined]
            return

        # Save to command history
        from sase.command_history import add_or_update_command

        add_or_update_command(command, project, cl_name)

        # Reload state and switch to the new view
        self._load_bgcmd_state()  # type: ignore[attr-defined]
        self._switch_to_axe_view(slot)  # type: ignore[attr-defined]
        # Truncate command for notification
        cmd_notify = command[:30] + "..." if len(command) > 30 else command
        self.notify(f"Started: {cmd_notify}")  # type: ignore[attr-defined]

    def _confirm_kill_bgcmd(self, slot: int) -> None:
        """Kill or clear a background command.

        For running commands: Show confirmation dialog before killing.
        For done commands: Clear immediately without confirmation.

        Args:
            slot: Slot number to kill/clear.
        """
        info = get_slot_info(slot)
        if info is None:
            return

        # Check if the command is still running
        if not is_slot_running(slot):
            # Done command - clear immediately without confirmation
            cmd_notify = (
                info.command[:30] + "..." if len(info.command) > 30 else info.command
            )
            clear_slot(slot)
            self.notify(f"Cleared: {cmd_notify}")  # type: ignore[attr-defined]
            self._load_bgcmd_state()  # type: ignore[attr-defined]
            # If no more bgcmds, switch to axe view
            if len(self._bgcmd_slots) == 0:
                self._switch_to_axe_view("axe")  # type: ignore[attr-defined]
            else:
                # Refresh display to update the sidebar immediately
                self._refresh_axe_display()  # type: ignore[attr-defined]
            return

        # Running command - show confirmation dialog
        from ..modals import ConfirmKillModal

        description = (
            f"{info.command}\n({info.project}, workspace {info.workspace_num})"
        )

        def on_confirmed(confirmed: bool) -> None:
            if confirmed:
                stop_background_command(slot)
                clear_slot(slot)
                cmd_notify = (
                    info.command[:30] + "..."
                    if len(info.command) > 30
                    else info.command
                )
                self.notify(f"Stopped: {cmd_notify}")  # type: ignore[attr-defined]
                self._load_bgcmd_state()  # type: ignore[attr-defined]
                # If no more bgcmds, switch to axe view
                if len(self._bgcmd_slots) == 0:
                    self._switch_to_axe_view("axe")  # type: ignore[attr-defined]
                else:
                    # Refresh display to update the sidebar immediately
                    self._refresh_axe_display()  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillModal(description), on_confirmed)  # type: ignore[attr-defined]

    def _show_process_selector(self) -> None:
        """Show the process selector modal (for X on non-AXE tabs)."""
        from ..modals import ProcessSelection, ProcessSelectModal

        def on_selected(selection: ProcessSelection | None) -> None:
            if selection is None:
                return

            if selection.process_type == "start_axe":
                self._start_axe()  # type: ignore[attr-defined]
            elif selection.process_type == "axe":
                self._stop_axe()  # type: ignore[attr-defined]
            elif selection.process_type == "dismiss_bgcmd":
                # Done command - just clear it
                slot = selection.slot
                if slot is not None:
                    info = get_slot_info(slot)
                    clear_slot(slot)
                    if info:
                        cmd_notify = (
                            info.command[:30] + "..."
                            if len(info.command) > 30
                            else info.command
                        )
                        self.notify(f"Cleared: {cmd_notify}")  # type: ignore[attr-defined]
                    self._load_bgcmd_state()  # type: ignore[attr-defined]
                    # Refresh display if on AXE tab
                    if self.current_tab == "axe":
                        self._refresh_axe_display()  # type: ignore[attr-defined]
            else:  # bgcmd (running)
                slot = selection.slot
                if slot is not None:
                    info = get_slot_info(slot)
                    stop_background_command(slot)
                    clear_slot(slot)
                    if info:
                        cmd_notify = (
                            info.command[:30] + "..."
                            if len(info.command) > 30
                            else info.command
                        )
                        self.notify(f"Stopped: {cmd_notify}")  # type: ignore[attr-defined]
                    self._load_bgcmd_state()  # type: ignore[attr-defined]
                    # Refresh display if on AXE tab
                    if self.current_tab == "axe":
                        self._refresh_axe_display()  # type: ignore[attr-defined]

        self.push_screen(  # type: ignore[attr-defined]
            ProcessSelectModal(self.axe_running, self._bgcmd_slots),
            on_selected,
        )
