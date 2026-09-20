"""Background command mixin for sase's TUI app.

``!`` commands are transient oneshot service procs: a durable launch
operation (``sase axe bgcmd-launch``) does the optional Patch checkout and
submits the command through the same detached path as
``sase service proc run``. Kill, rerun, and dismiss all act on the durable
row, so they work across TUI restarts.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from sase.ace.tui.actions._durable_ops import (
    durable_fingerprint,
    durable_request_payload,
    sase_argv,
)
from sase.core.paths import sase_projects_dir
from sase.ops.names import AXE_BGCMD, PROC_KILL
from sase.running_field import get_workspace_directory

from ..bgcmd import (
    BackgroundCommandInfo,
    bgcmd_identity,
    choose_bgcmd_slot,
    dismiss_background_command,
    stop_legacy_background_command,
)

if TYPE_CHECKING:
    from ...patch import Patch
    from ..modals.project_select_modal import ProjectSelectResult

# Type alias for tab names
TabName = Literal["artifacts", "agents", "axe"]

# How long a launched slot stays reserved while the launch operation runs and
# the next Services refresh picks the new oneshot row up.
_PENDING_SLOT_TTL_SECONDS = 30.0


def _bgcmd_description(info: BackgroundCommandInfo) -> str:
    """Return display-only bgcmd confirmation text."""
    if not info.project and not info.workspace_num:
        return info.command
    return f"{info.command}\n({info.display_project}, workspace {info.workspace_num})"


def _command_notify(command: str) -> str:
    return command[:30] + "..." if len(command) > 30 else command


class AxeBgCmdMixin:
    """Mixin providing background command management."""

    # Type hints for attributes accessed from AceApp
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    axe_running: bool
    _bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]
    _bgcmd_pending_slots: dict[int, float]
    _bgcmd_dismissed: set[str]
    _bgcmd_focus_slot: int | None

    # -- Slot allocation --------------------------------------------------

    def _next_bgcmd_slot(self) -> int | None:
        """Pick the ``#n`` index for a new command from cached state.

        Only running commands hold an index, so finished history never
        blocks a launch. ``None`` means nine commands are running.
        """
        now = time.monotonic()
        pending = {
            slot
            for slot, deadline in self._bgcmd_pending_slots.items()
            if deadline > now
        }
        return choose_bgcmd_slot(dict(self._bgcmd_slots), reserved=pending)

    def _reserve_bgcmd_slot(self, slot: int) -> None:
        self._bgcmd_pending_slots[slot] = time.monotonic() + _PENDING_SLOT_TTL_SECONDS

    def _release_bgcmd_slot(self, slot: int) -> None:
        self._bgcmd_pending_slots.pop(slot, None)

    def _notify_bgcmd_slots_full(self) -> None:
        self.notify(  # type: ignore[attr-defined]
            "Maximum background commands reached (9 running)", severity="error"
        )

    # -- Start ------------------------------------------------------------

    def action_start_bgcmd(self) -> None:
        """Start the background command workflow (! key on all tabs)."""
        if self._next_bgcmd_slot() is None:
            self._notify_bgcmd_slots_full()
            return

        # Show project select modal. Its lifecycle/Patch snapshot is loaded
        # off-thread before the pure modal is mounted.
        from ..modals.project_select_modal import show_project_select_modal

        def on_project_selected(
            result: ProjectSelectResult | None,
        ) -> None:
            if result is None:
                return

            selection = result.selection

            # Extract project name and optional Patch name
            if isinstance(selection, str):
                project = selection
                cl_name = None
            else:
                project = selection.project_name
                cl_name = selection.cl_name

            slot = self._next_bgcmd_slot()
            if slot is None:
                self._notify_bgcmd_slots_full()
                return

            # Show workspace input modal
            self._show_workspace_input(slot, project, cl_name)

        show_project_select_modal(self, on_project_selected)

    def _start_bgcmd_from_patch(self) -> None:
        """Start background command from current Patch (Patches tab only).

        This is the quick version triggered from leader mode that skips
        ProjectSelectModal, using the current Patch's project and Patch name.
        """
        if self.current_tab != "artifacts":
            return

        if not self.patches:
            self.notify("No Patches available", severity="warning")  # type: ignore[attr-defined]
            return

        slot = self._next_bgcmd_slot()
        if slot is None:
            self._notify_bgcmd_slots_full()
            return

        patch = self.patches[self.current_idx]
        project = patch.project_basename
        cl_name = patch.name

        # Go directly to workspace input, skipping ProjectSelectModal
        self._show_workspace_input(slot, project, cl_name)

    def _show_workspace_input(
        self, slot: int, project: str, cl_name: str | None = None
    ) -> None:
        """Show the workspace input modal.

        Args:
            slot: Slot number to use.
            project: Project name.
            cl_name: Optional Patch name to checkout before running command.
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
            cl_name: Optional Patch name to checkout before running command.
        """
        from ..modals import CommandHistoryModal

        def on_command_selected(command: str | None) -> None:
            if command is None:
                return
            # The slot was chosen before two modals ran; re-pick it from the
            # latest state so a command that started meanwhile isn't clobbered.
            target = slot if self._slot_still_free(slot) else self._next_bgcmd_slot()
            if target is None:
                self._notify_bgcmd_slots_full()
                return
            self._start_bgcmd(target, command, project, workspace_num, cl_name)

        self.push_screen(  # type: ignore[attr-defined]
            CommandHistoryModal(current_cl=cl_name, current_project=project),
            on_command_selected,
        )

    def _slot_still_free(self, slot: int) -> bool:
        if self._bgcmd_pending_slots.get(slot, 0.0) > time.monotonic():
            return False
        info = dict(self._bgcmd_slots).get(slot)
        return info is None or not (info.running or info.legacy)

    def _start_bgcmd(
        self,
        slot: int,
        command: str,
        project: str,
        workspace_num: int,
        cl_name: str | None = None,
        *,
        workspace_dir: str | None = None,
        record_history: bool = True,
    ) -> bool:
        """Start a background command as a oneshot service proc.

        Workspace clean + VCS checkout + the detached oneshot submit are
        delegated to a durable CLI operation so the supervisor owns the
        long-running work; the command itself then runs as its own durable
        proc and records its exit code.

        Args:
            slot: ``#n`` display index (1-9).
            command: Shell command to run.
            project: Project name (empty for a project-less oneshot).
            workspace_num: Workspace number.
            cl_name: Optional Patch name to checkout before running command.
            workspace_dir: Working directory; resolved from the project and
                workspace number when omitted.
            record_history: Whether to add the command to the history modal.

        Returns:
            Whether the launch operation was submitted.
        """
        if workspace_dir is None:
            try:
                workspace_dir = get_workspace_directory(project, workspace_num)
            except RuntimeError as e:
                self.notify(f"Failed to get workspace: {e}", severity="error")  # type: ignore[attr-defined]
                return False

        project_file = ""
        if project:
            from sase.ace.patch.project_spec_path import preferred_project_spec_path

            project_file = preferred_project_spec_path(
                str(sase_projects_dir() / project), project
            )

        # Synthetic dedup key for the no-Patch path, scoped per slot so two
        # concurrent !!-launches against different slots don't collide.
        is_synthetic_key = cl_name is None
        dedup_key = cl_name if cl_name is not None else f"bgcmd-slot-{slot}"

        def on_complete(completion: object) -> None:
            if not getattr(completion, "success", False):
                self._release_bgcmd_slot(slot)
                return
            if record_history:
                from sase.history.command import add_or_update_command

                add_or_update_command(command, project, cl_name)
            # The new oneshot row lands in the next Services refresh; focus it
            # there. The slot stays reserved until that refresh sees it.
            self._bgcmd_focus_slot = slot
            self._load_bgcmd_state()  # type: ignore[attr-defined]

        # Reserve the index so a second !/,! keypress during the window before
        # the oneshot exists can't pick the same slot. The launch operation
        # holds ``bgcmd-launch-slot:<n>`` and the oneshot row holds
        # ``bgcmd-slot:<n>`` in the proc store, so other TUIs are fenced too.
        self._reserve_bgcmd_slot(slot)

        submitted = self._submit_durable_proc(  # type: ignore[attr-defined]
            sase_argv("axe", "bgcmd-launch", slot, project, workspace_num, "--json"),
            operation=AXE_BGCMD,
            request=durable_request_payload(
                cl_name=cl_name,
                command=command,
                workspace_dir=workspace_dir,
            ),
            request_fingerprint=durable_fingerprint(
                AXE_BGCMD,
                slot,
                project,
                workspace_num,
                dedup_key,
            ),
            concurrency_keys=(
                f"bgcmd-launch:{dedup_key}",
                f"bgcmd-launch-slot:{slot}",
            ),
            label=f"launch bgcmd slot {slot}",
            display_name=f"launch bgcmd slot {slot}",
            cl_name=dedup_key,
            project_file=project_file,
            cwd=workspace_dir,
            on_complete=on_complete,
        )
        if not submitted:
            # Dedup rejected the submission — release the reservation we just
            # made, otherwise this slot stays reserved until it expires.
            self._release_bgcmd_slot(slot)
            if is_synthetic_key:
                # Soften the generic "A bgcmd-launch task is already running
                # for bgcmd-slot-N" message for the synthetic-key path; the
                # warning from the durable submitter already fired.
                self.notify(  # type: ignore[attr-defined]
                    f"A bgcmd launch is already in flight for slot {slot}",
                    severity="warning",
                )
            return False

        self.notify(f"Starting: {_command_notify(command)}")  # type: ignore[attr-defined]
        return True

    # -- Kill / dismiss ---------------------------------------------------

    def _bgcmd_info(self, slot: int) -> BackgroundCommandInfo | None:
        return dict(self._bgcmd_slots).get(slot)

    def _confirm_kill_bgcmd(self, slot: int) -> None:
        """Kill or dismiss a background command.

        For running commands: Show confirmation dialog before killing.
        For finished commands: Dismiss immediately without confirmation.

        Args:
            slot: Slot number to kill/dismiss.
        """
        info = self._bgcmd_info(slot)
        if info is None:
            return

        if not info.running:
            self._dismiss_bgcmd(slot, info, verb="Cleared")
            return

        from ..modals import ConfirmKillModal

        description = _bgcmd_description(info)

        def on_confirmed(confirmed: bool) -> None:
            if confirmed:
                self._stop_bgcmd(slot, info)

        self.push_screen(ConfirmKillModal(description), on_confirmed)  # type: ignore[attr-defined]

    def _stop_bgcmd(self, slot: int, info: BackgroundCommandInfo) -> None:
        """Stop a running command; the killed run leaves the section.

        A durable oneshot is stopped with a durable ``sase proc kill`` (the
        row keeps its recorded outcome in the proc store); a legacy slot
        directory is signalled directly.
        """
        if info.legacy:
            stop_legacy_background_command(slot)
            self._dismiss_bgcmd(slot, info, verb="Stopped")
            return
        proc_id = info.proc_id
        assert proc_id is not None
        label = _command_notify(info.command)

        def on_complete(completion: object) -> None:
            if not getattr(completion, "success", False):
                return
            self._dismiss_bgcmd(slot, info, verb="Stopped")

        self._submit_durable_proc(  # type: ignore[attr-defined]
            sase_argv("proc", "kill", proc_id, "--json"),
            operation=PROC_KILL,
            request=durable_request_payload(proc_id=proc_id, proc_label=label),
            request_fingerprint=durable_fingerprint(PROC_KILL, proc_id),
            concurrency_keys=(f"proc-kill:{proc_id}",),
            label=f"kill oneshot #{slot} {label}",
            display_name=f"kill oneshot #{slot} {label}",
            proc_type="proc.kill",
            cl_name=proc_id,
            duplicate_message=f"A kill operation is already running for #{slot}",
            notify_on_complete=False,
            on_complete=on_complete,
        )

    def _dismiss_bgcmd(
        self, slot: int, info: BackgroundCommandInfo, *, verb: str
    ) -> None:
        """Drop a command's row now and persist the dismissal off-thread."""
        self._bgcmd_dismissed.add(bgcmd_identity(slot, info))
        self._bgcmd_slots = [(s, i) for s, i in self._bgcmd_slots if s != slot]
        details = getattr(self, "_axe_bgcmd_details", None)
        if details is not None:
            details.pop(slot, None)
        self.notify(f"{verb}: {_command_notify(info.command)}")  # type: ignore[attr-defined]
        self.run_worker(  # type: ignore[attr-defined]
            lambda: dismiss_background_command(slot, info),
            thread=True,
            exclusive=False,
            exit_on_error=False,
            group="bgcmd-dismiss",
        )
        self._update_bgcmd_count()  # type: ignore[attr-defined]
        self._build_axe_items()  # type: ignore[attr-defined]
        # If no more bgcmds, switch to axe view
        if len(self._bgcmd_slots) == 0:
            self._switch_to_axe_view("axe")  # type: ignore[attr-defined]
        else:
            # Refresh display to update the sidebar immediately
            self._refresh_axe_display()  # type: ignore[attr-defined]

    # -- Rerun ------------------------------------------------------------

    def _rerun_bgcmd(self, slot: int) -> None:
        """Re-run a finished background command as a new oneshot.

        Prompts the user whether to dismiss the original entry before
        re-running. If yes, dismisses the original; otherwise leaves it in
        place. The new slot is chosen up-front — if all nine commands are
        running, we notify and do not prompt (avoids a prompt whose Yes path
        can't complete).

        Args:
            slot: Slot number of the finished background command.
        """
        info = self._bgcmd_info(slot)
        if info is None:
            return

        # Defense-in-depth: the footer already hides this binding when running.
        if info.running:
            return

        if self._next_bgcmd_slot() is None:
            self._notify_bgcmd_slots_full()
            return

        from ..modals import ConfirmRerunModal

        description = _bgcmd_description(info)

        def on_confirmed(result: bool | None) -> None:
            if result is None:
                return

            # Re-check slot availability in case state changed while the modal
            # was open.
            target_slot = self._next_bgcmd_slot()
            if target_slot is None:
                self._notify_bgcmd_slots_full()
                return

            started = self._start_bgcmd(
                target_slot,
                info.command,
                info.project,
                info.workspace_num,
                workspace_dir=info.workspace_dir,
                record_history=False,
            )
            if started and result:
                self._dismiss_bgcmd(slot, info, verb="Cleared")

        self.push_screen(ConfirmRerunModal(description), on_confirmed)  # type: ignore[attr-defined]

    # -- Process selector -------------------------------------------------

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
            else:
                slot = selection.slot
                info = None if slot is None else self._bgcmd_info(slot)
                if slot is None or info is None:
                    return
                if selection.process_type == "dismiss_bgcmd":
                    # Finished command - just clear it
                    self._dismiss_bgcmd(slot, info, verb="Cleared")
                else:  # bgcmd (running)
                    self._stop_bgcmd(slot, info)

        self.push_screen(  # type: ignore[attr-defined]
            ProcessSelectModal(self.axe_running, self._bgcmd_slots),
            on_selected,
        )
