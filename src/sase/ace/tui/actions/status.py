"""Status change action methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ..modals import StatusModal

if TYPE_CHECKING:
    from ...changespec import ChangeSpec

# Type alias for tab names (used in type hints)
TabName = Literal["changespecs", "agents", "axe"]


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
        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        def on_dismiss(new_status: str | None) -> None:
            if new_status:
                self._apply_status_change(changespec, new_status)

        self.push_screen(StatusModal(changespec.status), on_dismiss)  # type: ignore[attr-defined]

    def _apply_status_change(self, changespec: ChangeSpec, new_status: str) -> None:
        """Apply a status change to a ChangeSpec."""
        from sase.sase_utils import has_suffix, strip_reverted_suffix
        from sase.status_state_machine import (
            remove_ready_to_mail_suffix,
            transition_changespec_status,
        )

        from ...archive import archive_changespec
        from ...revert import revert_changespec
        from ...status import STATUS_ARCHIVED, STATUS_REVERTED, STATUS_SUBMITTED

        # Special handling for "Reverted" status
        if new_status == STATUS_REVERTED:
            # Need to suspend for revert workflow
            def run_revert() -> tuple[bool, str | None]:
                from rich.console import Console

                console = Console()
                return revert_changespec(changespec, console)

            with self.suspend():  # type: ignore[attr-defined]
                success, error_msg = run_revert()

            if not success:
                self.notify(f"Error reverting: {error_msg}", severity="error")  # type: ignore[attr-defined]
            self._reload_and_reposition()  # type: ignore[attr-defined]
            return

        # Special handling for "Submitted" status (git/gh projects)
        if new_status == STATUS_SUBMITTED:
            from sase.workspace_provider import detect_workflow_type, submit_changespec

            vcs_type = detect_workflow_type(changespec.file_path)
            if vcs_type in ("git", "gh"):
                import os

                project_basename = os.path.basename(changespec.file_path).replace(
                    ".gp", ""
                )

                def run_submit() -> tuple[bool, str | None]:
                    from rich.console import Console

                    console = Console()
                    return submit_changespec(
                        changespec.file_path, changespec.name, project_basename, console
                    )

                with self.suspend():  # type: ignore[attr-defined]
                    success, error_msg = run_submit()

                if not success:
                    self.notify(f"Error submitting: {error_msg}", severity="error")  # type: ignore[attr-defined]
                self._reload_and_reposition()  # type: ignore[attr-defined]
                return

        # Special handling for "Archived" status
        if new_status == STATUS_ARCHIVED:
            # Need to suspend for archive workflow
            def run_archive() -> tuple[bool, str | None]:
                from rich.console import Console

                console = Console()
                return archive_changespec(changespec, console)

            with self.suspend():  # type: ignore[attr-defined]
                success, error_msg = run_archive()

            if not success:
                self.notify(f"Error archiving: {error_msg}", severity="error")  # type: ignore[attr-defined]
            self._reload_and_reposition()  # type: ignore[attr-defined]
            return

        # Special handling for transitioning FROM "Reverted" status
        if changespec.status == STATUS_REVERTED and new_status in (
            "WIP",
            "Draft",
            "Ready",
        ):
            from ...restore import restore_changespec

            def run_restore() -> tuple[bool, str | None]:
                from rich.console import Console

                console = Console()
                return restore_changespec(changespec, console)

            with self.suspend():  # type: ignore[attr-defined]
                success, error_msg = run_restore()

            if not success:
                self.notify(f"Error restoring: {error_msg}", severity="error")  # type: ignore[attr-defined]
                self._reload_and_reposition()  # type: ignore[attr-defined]
                return

            # restore_changespec sets status to WIP; if target is Draft or Ready, transition again
            if new_status in ("Draft", "Ready"):
                # Need to find the new name (restore strips suffix, sase commit adds it back)
                from ...changespec import parse_project_file

                base_name = strip_reverted_suffix(changespec.name)
                changespecs = parse_project_file(changespec.file_path)
                restored_cs = next(
                    (
                        cs
                        for cs in changespecs
                        if strip_reverted_suffix(cs.name) == base_name
                        and cs.status == "WIP"
                    ),
                    None,
                )
                if restored_cs:
                    success, _, error_msg, _ = transition_changespec_status(
                        changespec.file_path,
                        restored_cs.name,
                        new_status,
                        validate=False,
                    )
                    if not success:
                        self.notify(  # type: ignore[attr-defined]
                            f"Error transitioning to {new_status}: {error_msg}",
                            severity="error",
                        )
                    else:
                        self.notify(f"Restored and set ChangeSpec to {new_status}")  # type: ignore[attr-defined]
                else:
                    self.notify("Restored ChangeSpec to WIP")  # type: ignore[attr-defined]
            else:
                self.notify("Restored ChangeSpec")  # type: ignore[attr-defined]

            self._reload_and_reposition()  # type: ignore[attr-defined]
            return

        # Remove READY TO MAIL suffix if present before transitioning
        remove_ready_to_mail_suffix(changespec.file_path, changespec.name)

        # Check if this is a Draft→Ready transition with suffix (may trigger sibling reverts)
        may_have_sibling_reverts = (
            changespec.status == "Draft"
            and new_status == "Ready"
            and has_suffix(changespec.name)
        )

        if may_have_sibling_reverts:
            # Need to suspend to show console output during sibling reverts
            from rich.console import Console

            with self.suspend():  # type: ignore[attr-defined]
                console = Console()
                success, old_status, error_msg, sibling_results = (
                    transition_changespec_status(
                        changespec.file_path,
                        changespec.name,
                        new_status,
                        validate=False,
                        console=console,
                    )
                )
        else:
            # No sibling reverts expected, run without console
            success, old_status, error_msg, sibling_results = (
                transition_changespec_status(
                    changespec.file_path,
                    changespec.name,
                    new_status,
                    validate=False,
                )
            )

        if success:
            # Build notification message
            msg_parts = [f"Status updated: {old_status} -> {new_status}"]

            # Add info about reverted siblings
            reverted = [r.name for r in sibling_results if r.success]
            failed = [r.name for r in sibling_results if not r.success]

            if reverted:
                msg_parts.append(f"Auto-reverted siblings: {', '.join(reverted)}")
            if failed:
                msg_parts.append(f"Failed to revert: {', '.join(failed)}")

            self.notify("\n".join(msg_parts))  # type: ignore[attr-defined]
        else:
            self.notify(f"Error: {error_msg}", severity="error")  # type: ignore[attr-defined]

        if success and may_have_sibling_reverts:
            # Name changed from e.g. "foo_bar__1" to "foo_bar" during suffix strip
            new_name = strip_reverted_suffix(changespec.name)
            self._reload_and_reposition(current_name=new_name)  # type: ignore[attr-defined]
        else:
            self._reload_and_reposition()  # type: ignore[attr-defined]
