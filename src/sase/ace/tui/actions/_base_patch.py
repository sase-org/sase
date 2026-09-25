"""Patch diff, reword, tag, and mail actions for sase's TUI app."""

from __future__ import annotations

from sase.project_display_names import humanize_cl_name

from ._base_types import BaseActionsHost


class BasePatchActionsMixin(BaseActionsHost):
    """Mixin providing Patch tool actions."""

    def action_show_diff(self) -> None:
        """Show diff for the current Patch."""
        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        from ...handlers import handle_show_diff
        from .._workflow_context import WorkflowContext

        def run_handler() -> None:
            ctx = WorkflowContext()
            handle_show_diff(ctx, patch)  # type: ignore[arg-type]

        with self.suspend():  # type: ignore[attr-defined]
            run_handler()

    def action_reword(self) -> None:
        """Reword (change change description) for the current Patch.

        Two-phase approach:
        1. Interactive: fetch description and open editor in suspend()
        2. Background: claim workspace, checkout Patch branch, apply reword
        """
        from ...patch import get_base_status

        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        # Validate PR is set
        if patch.pr_url is None:
            self.notify("PR is not set", severity="warning")  # type: ignore[attr-defined]
            return

        # Validate status is WIP, Draft, Ready, or Mailed
        base_status = get_base_status(patch.status)
        if base_status not in ("WIP", "Draft", "Ready", "Mailed"):
            self.notify(  # type: ignore[attr-defined]
                "Reword is only available for WIP, Draft, Ready, or Mailed Patches",
                severity="warning",
            )
            return

        from ...handlers import handle_reword_prepare
        from .._workflow_context import WorkflowContext
        from .patch_durable import submit_patch_operation
        from .proc_actions import TrackedProcCompletion

        # Interactive phase: fetch description and open editor in suspend()
        edited_description = None
        with self.suspend():  # type: ignore[attr-defined]
            ctx = WorkflowContext()
            edited_description = handle_reword_prepare(ctx, patch)  # type: ignore[arg-type]

        # If user cancelled or description unchanged, nothing to do
        if edited_description is None:
            return

        # Non-interactive phase: submit reword as a proc
        cl_name = patch.name
        display_cl_name = humanize_cl_name(cl_name)
        project_file = patch.file_path

        def on_complete(completion: TrackedProcCompletion[object]) -> None:
            if completion.collision or not completion.success:
                return
            from ...hooks import reset_dollar_hooks

            reset_dollar_hooks(project_file, cl_name)

        submitted = submit_patch_operation(
            self,
            verb="reword",
            name=cl_name,
            project_file=project_file,
            payload={"description": edited_description},
            on_complete=on_complete,
        )

        if submitted:
            self.notify(f"Rewording {display_cl_name}...")  # type: ignore[attr-defined]

    def action_add_tag(self) -> None:
        """Add a tag to the current Patch's change description in the background.

        This action:
        1. Validates PR is set and STATUS is editable
        2. Shows TagInputModal for tag name/value input
        3. Submits a proc that claims workspace, checks out Patch branch, adds tag
        4. Shows toast notifications for start/completion/failure
        """
        # On agents tab, dispatch to wait-for action
        if self.current_tab == "agents":
            self.action_wait_for_agent()  # type: ignore[attr-defined]
            return

        from ...patch import get_base_status
        from ...saved_tag_names import load_saved_tags, save_tag
        from ..modals import TagInputModal

        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        # Validate PR is set
        if patch.pr_url is None:
            self.notify("PR is not set", severity="warning")  # type: ignore[attr-defined]
            return

        # Validate status is WIP, Draft, Ready, or Mailed
        base_status = get_base_status(patch.status)
        if base_status not in ("WIP", "Draft", "Ready", "Mailed"):
            self.notify(  # type: ignore[attr-defined]
                "Add tag is only available for WIP, Draft, Ready, or Mailed Patches",
                severity="warning",
            )
            return

        saved_tags = load_saved_tags()

        def on_dismiss(result: tuple[str, str] | None) -> None:
            if result is None:
                return

            tag_name, tag_value = result
            save_tag(tag_name, tag_value)

            from .patch_durable import submit_patch_operation
            from .proc_actions import TrackedProcCompletion

            cl_name = patch.name
            display_cl_name = humanize_cl_name(cl_name)
            project_file = patch.file_path

            def on_complete(completion: TrackedProcCompletion[object]) -> None:
                if completion.collision or not completion.success:
                    return
                from ...hooks import reset_dollar_hooks

                reset_dollar_hooks(project_file, cl_name)

            extra = [tag_name]
            if tag_value:
                extra.append(tag_value)
            submitted = submit_patch_operation(
                self,
                verb="tag",
                name=cl_name,
                project_file=project_file,
                extra_argv=tuple(extra),
                payload={"tag": tag_name, "value": tag_value},
                proc_type="add_tag",
                on_complete=on_complete,
            )

            if submitted:
                self.notify(  # type: ignore[attr-defined]
                    f"Adding tag {tag_name}={tag_value} to {display_cl_name}..."
                )

        self.push_screen(TagInputModal(saved_tags), on_dismiss)  # type: ignore[attr-defined]

    def action_mail(self) -> None:
        """Mail the current Patch in the background (post-confirmation).

        This action:
        1. Validates STATUS is "Ready"
        2. Claims workspace and gets workspace directory
        3. Runs interactive prepare_mail in suspend() (y/n prompt)
        4. If confirmed, submits execute_mail + status transition as a proc
        5. Shows toast notifications for start/completion/failure
        """
        import os

        from ...patch import get_base_status

        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        if get_base_status(patch.status) != "Ready":
            self.notify("Patch must be Ready to mail", severity="warning")  # type: ignore[attr-defined]
            return

        from sase.running_field import (
            WorkspaceClaimError,
            claim_next_axe_workspace_dir,
            release_workspace,
        )

        from ...handlers import handle_mail_prepare
        from .._workflow_context import WorkflowContext
        from .patch_durable import submit_patch_operation

        cl_name = patch.name
        project_file = patch.file_path

        try:
            workspace_num, workspace_dir, _ = claim_next_axe_workspace_dir(
                project_file,
                "mail",
                os.getpid(),
                patch.project_basename,
                cl_name=cl_name,
            )
        except WorkspaceClaimError as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to claim workspace: {exc}",
                severity="error",
            )
            return

        # Interactive phase: checkout + prepare_mail (y/n prompt) in suspend()
        prep_result = None
        with self.suspend():  # type: ignore[attr-defined]
            ctx = WorkflowContext()
            prep_result = handle_mail_prepare(ctx, patch, workspace_dir)

        # If user declined or prepare failed, release workspace and return
        if prep_result is None or not prep_result.should_mail:
            release_workspace(project_file, workspace_num, "mail", cl_name)
            return

        submitted = submit_patch_operation(
            self,
            verb="mail",
            name=cl_name,
            project_file=project_file,
            payload={
                "settlement_owns_release": True,
                "workspace_dir": workspace_dir,
                "workspace_num": workspace_num,
            },
            workspace_num=workspace_num,
            workspace_workflow="mail",
        )

        if submitted:
            self.notify(f"Mailing {humanize_cl_name(cl_name)}...")  # type: ignore[attr-defined]
        else:
            # Dedup rejected — release workspace since the durable proc
            # was never reserved.
            release_workspace(project_file, workspace_num, "mail", cl_name)
