"""Background command mixin for the ace TUI app."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

from sase.workflows.commit_utils import run_sase_hg_clean
from sase.running_field import get_workspace_directory
from sase.vcs_provider import get_vcs_provider

from ..bgcmd import (
    BackgroundCommandInfo,
    clear_slot,
    clear_slot_pending,
    find_first_available_slot,
    get_slot_info,
    is_slot_running,
    mark_slot_pending,
    start_background_command,
    stop_background_command,
)

if TYPE_CHECKING:
    from ...changespec import ChangeSpec
    from ..modals.project_select_modal import ProjectSelectResult

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


def _bgcmd_launch_task(
    slot: int,
    command: str,
    project: str,
    workspace_num: int,
    workspace_dir: str,
    cl_name: str | None,
) -> tuple[bool, str]:
    """Run sase_hg_clean + checkout + start_background_command off the UI thread.

    The caller must have reserved the slot via ``mark_slot_pending`` before
    submitting this task. The marker is always cleared before returning so the
    slot doesn't leak on failure.
    """
    try:
        if cl_name is not None:
            clean_ok, clean_err = run_sase_hg_clean(workspace_dir, f"{cl_name}-bgcmd")
            if not clean_ok:
                print(f"Warning: sase_hg_clean failed: {clean_err}")

            provider = get_vcs_provider(workspace_dir)
            resolved = provider.resolve_revision(cl_name, project, workspace_dir)
            checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
            if not checkout_ok:
                return (False, f"checkout failed: {checkout_err}")

        pid = start_background_command(
            slot=slot,
            command=command,
            project=project,
            workspace_num=workspace_num,
            workspace_dir=workspace_dir,
        )
        if pid is None:
            return (False, "Failed to start background command")

        cmd_notify = command[:30] + "..." if len(command) > 30 else command
        return (True, f"Started bgcmd in slot {slot}: {cmd_notify}")
    finally:
        clear_slot_pending(slot)


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
            result: ProjectSelectResult | None,
        ) -> None:
            if result is None:
                return

            selection = result.selection

            # Extract project name and optional CL name
            if isinstance(selection, str):
                project = selection
                cl_name = None
            else:
                project = selection.project_name
                cl_name = selection.cl_name

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
            WorkspaceInputModal(default_workspace=1), on_workspace_entered
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

        Workspace clean + VCS checkout + subprocess spawn run on a worker
        thread via ``_submit_background_task`` so the TUI event loop stays
        responsive during potentially slow VCS operations.

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

        project_file = os.path.expanduser(f"~/.sase/projects/{project}/{project}.gp")

        # Synthetic dedup key for the no-CL path, scoped per slot so two
        # concurrent !!-launches against different slots don't collide.
        is_synthetic_key = cl_name is None
        dedup_key = cl_name if cl_name is not None else f"bgcmd-slot-{slot}"

        def task_callable() -> tuple[bool, str]:
            return _bgcmd_launch_task(
                slot, command, project, workspace_num, workspace_dir, cl_name
            )

        def on_success() -> None:
            from sase.history.command import add_or_update_command

            add_or_update_command(command, project, cl_name)
            self._load_bgcmd_state()  # type: ignore[attr-defined]
            self._switch_to_axe_view(slot)  # type: ignore[attr-defined]

        # Reserve the slot on disk so a second !/,! keypress during the
        # window before the subprocess spawns can't pick the same slot.
        mark_slot_pending(slot)

        submitted = self._submit_background_task(  # type: ignore[attr-defined]
            "bgcmd-launch",
            dedup_key,
            project_file,
            task_callable,
            on_success=on_success,
        )
        if not submitted:
            # Dedup rejected the submission — clear the marker we just wrote,
            # otherwise this slot stays reserved until the TUI restarts.
            clear_slot_pending(slot)
            if is_synthetic_key:
                # Soften the generic "A bgcmd-launch task is already running
                # for bgcmd-slot-N" message for the synthetic-key path; the
                # warning from _submit_background_task already fired.
                self.notify(  # type: ignore[attr-defined]
                    f"A bgcmd launch is already in flight for slot {slot}",
                    severity="warning",
                )
            return

        cmd_notify = command[:30] + "..." if len(command) > 30 else command
        self.notify(f"Starting: {cmd_notify}")  # type: ignore[attr-defined]

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

    def _rerun_bgcmd(self, slot: int) -> None:
        """Re-run a done background command in a new slot.

        Prompts the user whether to dismiss the original entry before re-running.
        If yes, clears the original slot; otherwise leaves it in place. The new
        slot is allocated up-front — if no slot is available, we notify and do
        not prompt (avoids a prompt whose Yes path can't complete).

        Args:
            slot: Original slot number of the done background command.
        """
        info = get_slot_info(slot)
        if info is None:
            return

        # Defense-in-depth: the footer already hides this binding when running.
        if is_slot_running(slot):
            return

        new_slot = find_first_available_slot()
        if new_slot is None:
            self.notify("Maximum background commands reached", severity="error")  # type: ignore[attr-defined]
            return

        from ..modals import ConfirmRerunModal

        description = (
            f"{info.command}\n({info.project}, workspace {info.workspace_num})"
        )

        original_info = info

        def on_confirmed(result: bool | None) -> None:
            if result is None:
                return

            # Re-check slot availability in case state changed while the modal
            # was open.
            target_slot = find_first_available_slot()
            if target_slot is None:
                self.notify("Maximum background commands reached", severity="error")  # type: ignore[attr-defined]
                return

            if result:
                clear_slot(slot)

            pid = start_background_command(
                slot=target_slot,
                command=original_info.command,
                project=original_info.project,
                workspace_num=original_info.workspace_num,
                workspace_dir=original_info.workspace_dir,
            )

            if pid is None:
                self.notify("Failed to start background command", severity="error")  # type: ignore[attr-defined]
                return

            self._load_bgcmd_state()  # type: ignore[attr-defined]
            self._switch_to_axe_view(target_slot)  # type: ignore[attr-defined]
            cmd_notify = (
                original_info.command[:30] + "..."
                if len(original_info.command) > 30
                else original_info.command
            )
            self.notify(f"Re-running: {cmd_notify}")  # type: ignore[attr-defined]

        self.push_screen(ConfirmRerunModal(description), on_confirmed)  # type: ignore[attr-defined]

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
