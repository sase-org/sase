"""Status change action methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sase.project_display_names import humanize_cl_name

from ..modals import PrOriginModal, StatusModal

if TYPE_CHECKING:
    from ...patch import Patch

# Type alias for tab names (used in type hints)
TabName = Literal["artifacts", "agents", "axe"]


class StatusActionsMixin:
    """Mixin providing status change actions."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    query_string: str
    parsed_query: Any

    def action_change_status(self) -> None:
        """Open status change modal."""
        if self.current_tab != "artifacts":
            return
        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        def on_dismiss(new_status: str | None) -> None:
            if new_status:
                self._apply_status_change(patch, new_status)

        self.push_screen(StatusModal(patch.status), on_dismiss)  # type: ignore[attr-defined]

    def action_mark_pr_origin(self) -> None:
        """Open the PR_ORIGIN marking modal for the selected Patch."""
        if self.current_tab != "artifacts":
            return
        if not self.patches:
            return

        patch = self.patches[self.current_idx]
        if not patch.pr_url:
            return

        def on_dismiss(new_pr_origin: str | None) -> None:
            if new_pr_origin:
                self._apply_pr_origin_change(patch, new_pr_origin)

        self.push_screen(  # type: ignore[attr-defined]
            PrOriginModal(patch.pr_origin), on_dismiss
        )

    def _apply_pr_origin_change(self, patch: Patch, new_pr_origin: str) -> None:
        """Apply a PR_ORIGIN change to a Patch."""
        from sase.status_state_machine import update_patch_pr_origin_atomic

        display_cl_name = humanize_cl_name(patch.name)
        update_patch_pr_origin_atomic(patch.file_path, patch.name, new_pr_origin)
        self.notify(f"PR_ORIGIN set to {new_pr_origin} for {display_cl_name}")  # type: ignore[attr-defined]
        self._reload_and_reposition()  # type: ignore[attr-defined]

    def _apply_status_change(self, patch: Patch, new_status: str) -> None:
        """Apply a status change to a Patch."""
        from sase.core.patch import has_suffix
        from sase.status_state_machine import (
            transition_patch_status,
        )

        from ...status import STATUS_ARCHIVED, STATUS_REVERTED, STATUS_SUBMITTED
        from .patch_durable import submit_patch_operation

        cl_name = patch.name
        display_cl_name = humanize_cl_name(cl_name)
        project_file = patch.file_path

        # Special handling for "Reverted" status → proc
        if new_status == STATUS_REVERTED:
            submitted = submit_patch_operation(
                self,
                verb="revert",
                name=cl_name,
                project_file=project_file,
            )
            if submitted:
                self.notify(f"Reverting {display_cl_name}...")  # type: ignore[attr-defined]
            return

        # Special handling for "Submitted" status (git/gh projects) → proc
        if new_status == STATUS_SUBMITTED:
            from sase.workspace_provider import detect_workflow_type

            vcs_type = detect_workflow_type(project_file)
            if vcs_type in ("git", "gh"):
                submitted = submit_patch_operation(
                    self,
                    verb="submit",
                    name=cl_name,
                    project_file=project_file,
                )
                if submitted:
                    self.notify(f"Submitting {display_cl_name}...")  # type: ignore[attr-defined]
                return

        # Special handling for "Archived" status → proc
        if new_status == STATUS_ARCHIVED:
            submitted = submit_patch_operation(
                self,
                verb="archive",
                name=cl_name,
                project_file=project_file,
            )
            if submitted:
                self.notify(f"Archiving {display_cl_name}...")  # type: ignore[attr-defined]
            return

        # Special handling for transitioning FROM "Reverted" status → proc
        if patch.status == STATUS_REVERTED and new_status in (
            "WIP",
            "Draft",
            "Ready",
        ):
            submitted = submit_patch_operation(
                self,
                verb="restore",
                name=cl_name,
                project_file=project_file,
                extra_argv=(new_status,),
                payload={"status": new_status},
            )
            if submitted:
                self.notify(f"Restoring {display_cl_name}...")  # type: ignore[attr-defined]
            return

        # Kill running processes when transitioning to WIP
        if new_status == "WIP":
            from sase.ace.hooks.processes import kill_and_persist_all_running_processes

            kill_and_persist_all_running_processes(
                patch,
                project_file,
                cl_name,
                "Killed: Patch transitioned to WIP.",
            )

        # Check if this is a Draft→Ready transition with suffix (may trigger sibling reverts)
        may_have_sibling_reverts = (
            patch.status == "Draft" and new_status == "Ready" and has_suffix(cl_name)
        )

        if may_have_sibling_reverts:
            submitted = submit_patch_operation(
                self,
                verb="status",
                name=cl_name,
                project_file=project_file,
                extra_argv=(new_status,),
                payload={"status": new_status},
            )
            if submitted:
                self.notify(f"Transitioning {display_cl_name} to {new_status}...")  # type: ignore[attr-defined]
            return

        # Standard transition (synchronous, fast)
        success, old_status, error_msg, sibling_results = transition_patch_status(
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
