"""Status change action methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sase.project_display_names import humanize_cl_name

from ..modals import StatusModal

if TYPE_CHECKING:
    from ...changespec import ChangeSpec

# Type alias for tab names (used in type hints)
TabName = Literal["changespecs", "agents", "axe"]


def _revert_task(file_path: str, name: str) -> tuple[bool, str]:
    """Execute revert workflow as a background task."""
    from rich.console import Console

    from sase.ace.changespec import parse_project_file
    from sase.ace.revert import revert_changespec

    changespecs = parse_project_file(file_path)
    cs = next((c for c in changespecs if c.name == name), None)
    display_name = humanize_cl_name(name)
    if cs is None:
        return (False, f"ChangeSpec '{display_name}' not found")

    success, error_msg = revert_changespec(cs, Console())
    if success:
        return (True, f"Reverted {display_name}")
    return (False, error_msg or f"Failed to revert {display_name}")


def _submit_task(file_path: str, name: str, project_basename: str) -> tuple[bool, str]:
    """Execute submit workflow as a background task."""
    from rich.console import Console

    from sase.workspace_provider import submit_changespec

    success, error_msg = submit_changespec(file_path, name, project_basename, Console())
    display_name = humanize_cl_name(name)
    if success:
        return (True, f"Submitted {display_name}")
    return (False, error_msg or f"Failed to submit {display_name}")


def _archive_task(file_path: str, name: str) -> tuple[bool, str]:
    """Execute archive workflow as a background task."""
    from rich.console import Console

    from sase.ace.archive import archive_changespec
    from sase.ace.changespec import parse_project_file

    changespecs = parse_project_file(file_path)
    cs = next((c for c in changespecs if c.name == name), None)
    display_name = humanize_cl_name(name)
    if cs is None:
        return (False, f"ChangeSpec '{display_name}' not found")

    success, error_msg = archive_changespec(cs, Console())
    if success:
        return (True, f"Archived {display_name}")
    return (False, error_msg or f"Failed to archive {display_name}")


def _restore_task(file_path: str, name: str, target_status: str) -> tuple[bool, str]:
    """Execute restore workflow as a background task.

    Handles the full restore flow: restores from Reverted to WIP, then
    optionally transitions to Draft or Ready if target_status requires it.
    """
    from rich.console import Console

    from sase.ace.changespec import parse_project_file
    from sase.ace.restore import restore_changespec
    from sase.core.changespec import strip_reverted_suffix
    from sase.status_state_machine import transition_changespec_status

    changespecs = parse_project_file(file_path)
    cs = next((c for c in changespecs if c.name == name), None)
    display_name = humanize_cl_name(name)
    if cs is None:
        return (False, f"ChangeSpec '{display_name}' not found")

    success, error_msg = restore_changespec(cs, Console())
    if not success:
        return (False, error_msg or f"Failed to restore {display_name}")

    if target_status in ("Draft", "Ready"):
        base_name = strip_reverted_suffix(name)
        changespecs = parse_project_file(file_path)
        restored_cs = next(
            (
                c
                for c in changespecs
                if strip_reverted_suffix(c.name) == base_name and c.status == "WIP"
            ),
            None,
        )
        if restored_cs:
            success, _, error_msg, _ = transition_changespec_status(
                file_path, restored_cs.name, target_status, validate=False
            )
            if not success:
                return (
                    False,
                    f"Restored but failed to transition to {target_status}: {error_msg}",
                )
            return (True, f"Restored and set to {target_status}")
        return (True, f"Restored {display_name} to WIP")

    return (True, f"Restored {display_name}")


def _transition_with_siblings_task(
    file_path: str, name: str, new_status: str
) -> tuple[bool, str]:
    """Execute status transition with potential sibling reverts as a background task."""
    from rich.console import Console

    from sase.status_state_machine import transition_changespec_status

    success, old_status, error_msg, sibling_results = transition_changespec_status(
        file_path, name, new_status, validate=False, console=Console()
    )

    if success:
        msg_parts = [f"Status updated: {old_status} -> {new_status}"]
        reverted = [humanize_cl_name(r.name) for r in sibling_results if r.success]
        failed = [humanize_cl_name(r.name) for r in sibling_results if not r.success]
        if reverted:
            msg_parts.append(f"Auto-reverted siblings: {', '.join(reverted)}")
        if failed:
            msg_parts.append(f"Failed to revert: {', '.join(failed)}")
        return (True, "\n".join(msg_parts))

    return (False, error_msg or f"Failed to transition to {new_status}")


class StatusActionsMixin:
    """Mixin providing status change actions."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    query_string: str
    parsed_query: Any

    def action_change_status(self) -> None:
        """Open status change modal."""
        if self.current_tab != "changespecs":
            return
        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        def on_dismiss(new_status: str | None) -> None:
            if new_status:
                self._apply_status_change(changespec, new_status)

        self.push_screen(StatusModal(changespec.status), on_dismiss)  # type: ignore[attr-defined]

    def _apply_status_change(self, changespec: ChangeSpec, new_status: str) -> None:
        """Apply a status change to a ChangeSpec."""
        from sase.core.changespec import has_suffix
        from sase.status_state_machine import (
            transition_changespec_status,
        )

        from ...status import STATUS_ARCHIVED, STATUS_REVERTED, STATUS_SUBMITTED

        cl_name = changespec.name
        display_cl_name = humanize_cl_name(cl_name)
        project_file = changespec.file_path

        # Special handling for "Reverted" status → background task
        if new_status == STATUS_REVERTED:

            def task_callable() -> tuple[bool, str]:
                return _revert_task(project_file, cl_name)

            submitted = self._submit_background_task(  # type: ignore[attr-defined]
                "revert", cl_name, project_file, task_callable
            )
            if submitted:
                self.notify(f"Reverting {display_cl_name}...")  # type: ignore[attr-defined]
            return

        # Special handling for "Submitted" status (git/gh projects) → background task
        if new_status == STATUS_SUBMITTED:
            from sase.workspace_provider import detect_workflow_type

            vcs_type = detect_workflow_type(project_file)
            if vcs_type in ("git", "gh"):
                from sase.ace.changespec.project_spec_path import project_spec_basename

                project_basename = project_spec_basename(project_file)

                def task_callable() -> tuple[bool, str]:
                    return _submit_task(project_file, cl_name, project_basename)

                submitted = self._submit_background_task(  # type: ignore[attr-defined]
                    "submit", cl_name, project_file, task_callable
                )
                if submitted:
                    self.notify(f"Submitting {display_cl_name}...")  # type: ignore[attr-defined]
                return

        # Special handling for "Archived" status → background task
        if new_status == STATUS_ARCHIVED:

            def task_callable() -> tuple[bool, str]:
                return _archive_task(project_file, cl_name)

            submitted = self._submit_background_task(  # type: ignore[attr-defined]
                "archive", cl_name, project_file, task_callable
            )
            if submitted:
                self.notify(f"Archiving {display_cl_name}...")  # type: ignore[attr-defined]
            return

        # Special handling for transitioning FROM "Reverted" status → background task
        if changespec.status == STATUS_REVERTED and new_status in (
            "WIP",
            "Draft",
            "Ready",
        ):

            def task_callable() -> tuple[bool, str]:
                return _restore_task(project_file, cl_name, new_status)

            submitted = self._submit_background_task(  # type: ignore[attr-defined]
                "restore", cl_name, project_file, task_callable
            )
            if submitted:
                self.notify(f"Restoring {display_cl_name}...")  # type: ignore[attr-defined]
            return

        # Kill running processes when transitioning to WIP
        if new_status == "WIP":
            from sase.ace.hooks.processes import kill_and_persist_all_running_processes

            kill_and_persist_all_running_processes(
                changespec,
                project_file,
                cl_name,
                "Killed: ChangeSpec transitioned to WIP.",
            )

        # Check if this is a Draft→Ready transition with suffix (may trigger sibling reverts)
        may_have_sibling_reverts = (
            changespec.status == "Draft"
            and new_status == "Ready"
            and has_suffix(cl_name)
        )

        if may_have_sibling_reverts:
            # Sibling reverts involve git operations → background task

            def task_callable() -> tuple[bool, str]:
                return _transition_with_siblings_task(project_file, cl_name, new_status)

            submitted = self._submit_background_task(  # type: ignore[attr-defined]
                "status", cl_name, project_file, task_callable
            )
            if submitted:
                self.notify(f"Transitioning {display_cl_name} to {new_status}...")  # type: ignore[attr-defined]
            return

        # Standard transition (synchronous, fast)
        success, old_status, error_msg, sibling_results = transition_changespec_status(
            project_file,
            cl_name,
            new_status,
            validate=False,
        )

        if success:
            # Build notification message
            msg_parts = [f"Status updated: {old_status} -> {new_status}"]

            # Add info about reverted siblings
            reverted = [humanize_cl_name(r.name) for r in sibling_results if r.success]
            failed = [
                humanize_cl_name(r.name) for r in sibling_results if not r.success
            ]

            if reverted:
                msg_parts.append(f"Auto-reverted siblings: {', '.join(reverted)}")
            if failed:
                msg_parts.append(f"Failed to revert: {', '.join(failed)}")

            self.notify("\n".join(msg_parts))  # type: ignore[attr-defined]
        else:
            self.notify(f"Error: {error_msg}", severity="error")  # type: ignore[attr-defined]

        self._reload_and_reposition()  # type: ignore[attr-defined]
