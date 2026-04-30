"""Proposal and rebase action methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...hooks.history import get_last_accepted_history_entry_id
from ..widgets import HintInputBar

if TYPE_CHECKING:
    from ...changespec import ChangeSpec


_ROOT_PARENT_SENTINEL = "__root__"


def _rebase_task(
    changespec_name: str,
    changespec_file_path: str,
    project_basename: str,
    new_parent_name: str,
) -> tuple[bool, str]:
    """Execute rebase as a background task.

    Returns:
        Tuple of (success, message).
    """
    import os

    from sase.workflows.commit_utils import run_sase_hg_clean
    from sase.running_field import (
        claim_workspace,
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
        release_workspace,
    )
    from sase.status_state_machine import update_changespec_parent_atomic
    from sase.vcs_provider import get_vcs_provider

    workspace_num = get_first_available_axe_workspace(changespec_file_path)
    workflow_name = f"rebase-{changespec_name}"

    try:
        workspace_dir, _ = get_workspace_directory_for_num(
            workspace_num, project_basename
        )
    except RuntimeError as e:
        return (False, f"Failed to get workspace directory: {e}")

    pid = os.getpid()
    if not claim_workspace(
        changespec_file_path, workspace_num, workflow_name, pid, changespec_name
    ):
        return (False, "Failed to claim workspace")

    try:
        # Clean workspace before switching branches
        clean_success, clean_error = run_sase_hg_clean(
            workspace_dir, f"{changespec_name}-rebase"
        )
        if not clean_success:
            print(f"Warning: sase_hg_clean failed: {clean_error}")

        # Checkout the CL being rebased
        provider = get_vcs_provider(workspace_dir)
        resolved = provider.resolve_revision(
            changespec_name, project_basename, workspace_dir
        )
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            return (False, f"sase_hg_update failed: {checkout_err}")

        # Resolve sentinel to real VCS default for the rebase call
        rebase_parent = new_parent_name
        if new_parent_name == _ROOT_PARENT_SENTINEL:
            rebase_parent = provider.get_default_parent_revision(workspace_dir)

        # Run sase_hg_rebase
        rebase_ok, rebase_err = provider.rebase(
            changespec_name, rebase_parent, workspace_dir
        )
        if not rebase_ok:
            return (False, f"sase_hg_rebase failed: {rebase_err}")

        # Update PARENT field on success
        # If root sentinel was selected, delete the PARENT field (pass None)
        try:
            parent_value = (
                None if new_parent_name == _ROOT_PARENT_SENTINEL else new_parent_name
            )
            update_changespec_parent_atomic(
                changespec_file_path, changespec_name, parent_value
            )
        except Exception as e:
            return (False, f"Failed to update PARENT field: {e}")

        from sase.ace.deltas import refresh_deltas_after_commits_change

        refresh_deltas_after_commits_change(
            changespec_file_path, changespec_name, workspace_dir
        )

        return (True, f"Rebased onto {new_parent_name}")

    finally:
        release_workspace(
            changespec_file_path,
            workspace_num,
            workflow_name,
            changespec_name,
        )


def _accept_task(
    entries: list[tuple[str, str | None]],
    cl_name: str,
    project_file: str,
    mark_ready_to_mail: bool,
    skip_amend: bool,
) -> tuple[bool, str]:
    """Execute accept workflow as a background task.

    Returns:
        Tuple of (success, message).
    """
    from sase.workflows.accept import AcceptWorkflow
    from sase.workflows.accept.conflict_check import format_conflict_message

    workflow = AcceptWorkflow(
        proposals=entries,
        cl_name=cl_name,
        project_file=project_file,
        mark_ready_to_mail=mark_ready_to_mail,
        skip_amend=skip_amend,
    )
    success = workflow.run()

    if success:
        suffix = " (bookkeeping only)" if skip_amend else ""
        if len(entries) == 1:
            return (True, f"Accepted proposal {entries[0][0]}{suffix}")
        else:
            ids = ", ".join(e[0] for e in entries)
            return (True, f"Accepted proposals {ids}{suffix}")
    else:
        conflict_result = workflow.conflict_result
        if conflict_result is not None and not conflict_result.success:
            return (False, format_conflict_message(conflict_result))
        return (False, f"Accept failed for {cl_name}")


class ProposalRebaseMixin:
    """Mixin providing proposal acceptance and rebase actions."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int

    # --- Ready to Mail Actions ---

    def action_mark_ready_to_mail(self) -> None:
        """Prepare the current ChangeSpec for mailing.

        This action:
        1. Kills all running agents
        2. Kills running hooks (except $-prefixed ones)
        3. Rejects all new proposals
        """
        from sase.workflows.commit_utils import reject_all_new_proposals

        from ...changespec import get_base_status
        from ...comments import update_changespec_comments_field
        from ...comments.operations import mark_comment_agents_as_killed
        from ...hooks import (
            kill_running_agent_processes,
            kill_running_hook_processes,
            mark_hook_agents_as_killed,
            mark_hooks_as_killed,
            update_changespec_hooks_field,
        )

        if not self.changespecs or self.current_idx >= len(self.changespecs):
            return

        changespec = self.changespecs[self.current_idx]

        # Validate: must be Ready status
        base_status = get_base_status(changespec.status)
        if base_status != "Ready":
            self.notify("Must be Ready status", severity="warning")  # type: ignore[attr-defined]
            return

        # 1. Kill all running agents (hooks and comments)
        killed_hook_agents, killed_comment_agents = kill_running_agent_processes(
            changespec
        )

        # Update hooks to mark agents as killed and persist
        if killed_hook_agents and changespec.hooks:
            updated_hooks = mark_hook_agents_as_killed(
                changespec.hooks, killed_hook_agents
            )
            update_changespec_hooks_field(
                changespec.file_path, changespec.name, updated_hooks
            )

        # Update comments to mark agents as killed and persist
        if killed_comment_agents and changespec.comments:
            updated_comments = mark_comment_agents_as_killed(
                changespec.comments, killed_comment_agents
            )
            update_changespec_comments_field(
                changespec.file_path, changespec.name, updated_comments
            )

        # 2. Kill running hooks except $-prefixed ones
        killed_hooks = kill_running_hook_processes(changespec, skip_dollar=True)

        # Update hooks to mark as killed and persist
        if killed_hooks and changespec.hooks:
            updated_hooks = mark_hooks_as_killed(
                changespec.hooks, killed_hooks, "Manually marked ready to mail"
            )
            update_changespec_hooks_field(
                changespec.file_path, changespec.name, updated_hooks
            )

        # 3. Reject all new proposals
        reject_all_new_proposals(changespec.file_path, changespec.name)

        self.notify("Marked as ready to mail")  # type: ignore[attr-defined]
        self._reload_and_reposition()  # type: ignore[attr-defined]

    def _mark_ready_to_mail_atomic(
        self,
        changespec: ChangeSpec,
        final_status: str | None = None,
    ) -> bool:
        """Prepare for mailing with atomic proposal rejection and optional status update.

        This is similar to action_mark_ready_to_mail() but:
        - Takes a changespec parameter (doesn't use current selection)
        - Combines proposal rejection and status update atomically
        - Allows specifying final status ("Mailed" or None to keep current)
        - Does NOT call _reload_and_reposition() - caller must do that

        Args:
            changespec: The ChangeSpec to prepare for mailing
            final_status: If "Mailed", set status directly to Mailed.
                          If None, keep current status.

        Returns:
            True if successful, False otherwise.
        """
        from sase.workflows.commit_utils import reject_proposals_and_set_status_atomic

        from ...comments import update_changespec_comments_field
        from ...comments.operations import mark_comment_agents_as_killed
        from ...hooks import (
            kill_running_agent_processes,
            kill_running_hook_processes,
            mark_hook_agents_as_killed,
            mark_hooks_as_killed,
            update_changespec_hooks_field,
        )

        # 1. Kill all running agents (hooks and comments)
        killed_hook_agents, killed_comment_agents = kill_running_agent_processes(
            changespec
        )

        # Update hooks to mark agents as killed and persist
        if killed_hook_agents and changespec.hooks:
            updated_hooks = mark_hook_agents_as_killed(
                changespec.hooks, killed_hook_agents
            )
            update_changespec_hooks_field(
                changespec.file_path, changespec.name, updated_hooks
            )

        # Update comments to mark agents as killed and persist
        if killed_comment_agents and changespec.comments:
            updated_comments = mark_comment_agents_as_killed(
                changespec.comments, killed_comment_agents
            )
            update_changespec_comments_field(
                changespec.file_path, changespec.name, updated_comments
            )

        # 2. Kill running hooks except $-prefixed ones
        killed_hooks = kill_running_hook_processes(changespec, skip_dollar=True)

        # Update hooks to mark as killed and persist
        if killed_hooks and changespec.hooks:
            updated_hooks = mark_hooks_as_killed(
                changespec.hooks, killed_hooks, "Manually marked ready to mail"
            )
            update_changespec_hooks_field(
                changespec.file_path, changespec.name, updated_hooks
            )

        # 3. Atomically reject proposals and optionally set status
        success = reject_proposals_and_set_status_atomic(
            changespec.file_path,
            changespec.name,
            final_status if final_status else "",
        )

        return success

    # --- Accept Proposal Actions ---

    def action_accept_proposal(self) -> None:
        """Accept a proposal for the current ChangeSpec, or answer HITL on agents tab."""
        from ..models import Agent

        # Check if we're on agents tab
        if hasattr(self, "current_tab") and self.current_tab == "agents":  # type: ignore[attr-defined]
            agents: list[Agent] = getattr(self, "_agents", [])
            if agents and 0 <= self.current_idx < len(agents):
                agent = agents[self.current_idx]
                if agent.status == "WAITING INPUT":
                    self._answer_workflow_hitl(agent)  # type: ignore[attr-defined]
                    return
                _APPROVE_ELIGIBLE = {
                    "RUNNING",
                    "PLANNING",
                    "PLAN APPROVED",
                    "WAITING",
                    "QUESTION",
                }
                if agent.status in _APPROVE_ELIGIBLE:
                    self.action_toggle_approve()  # type: ignore[attr-defined]
                    return
            return

        if not self.changespecs or self.current_idx >= len(self.changespecs):
            return

        changespec = self.changespecs[self.current_idx]

        # Check if there are proposed entries
        if not changespec.commits or not any(e.is_proposed for e in changespec.commits):
            self.notify("No proposals to accept", severity="warning")  # type: ignore[attr-defined]
            return

        # Get the last accepted (all-numeric) entry ID to filter proposals
        last_accepted_id = get_last_accepted_history_entry_id(changespec)
        last_accepted_base = int(last_accepted_id) if last_accepted_id else None

        # Build placeholder with just proposal letters for NEW proposals only
        # (proposals whose base number matches the latest all-numeric entry)
        proposal_letters: list[str] = []
        for entry in changespec.commits:
            if entry.is_proposed and entry.number == last_accepted_base:
                # Extract just the letter suffix from display_number (e.g., "2a" -> "a")
                display_num = entry.display_number
                if display_num and len(display_num) > 0:
                    # The letter is the last character
                    proposal_letters.append(display_num[-1])

        placeholder = " ".join(proposal_letters)

        # Store accept mode state
        self._accept_mode_active = True  # type: ignore[attr-defined]
        self._accept_last_base = last_accepted_id  # type: ignore[attr-defined]

        # Mount the accept input bar
        detail_container = self.query_one("#detail-container")  # type: ignore[attr-defined]
        if not detail_container.is_attached:
            return
        accept_bar = HintInputBar(
            mode="accept", placeholder=placeholder, id="hint-input-bar"
        )
        detail_container.mount(accept_bar)

    def _run_accept_workflow(
        self,
        changespec: ChangeSpec,
        entries: list[tuple[str, str | None]],
        mark_ready_to_mail: bool = False,
        skip_amend: bool = False,
    ) -> None:
        """Run the accept workflow as a background task.

        Args:
            changespec: The ChangeSpec to accept proposals for.
            entries: List of (proposal_id, msg) tuples.
            mark_ready_to_mail: If True, also reject remaining proposals in the
                same atomic write. On success, triggers action_mail() via
                on_success callback.
            skip_amend: If True, skip checkout/apply/amend steps and only do
                bookkeeping (renumber commit entries, etc.).
        """
        cl_name = changespec.name
        project_file = changespec.file_path

        # Build display message
        suffix = ""
        if skip_amend:
            suffix = " (bookkeeping only)"
        if len(entries) == 1:
            proposal_id, _ = entries[0]
            if mark_ready_to_mail:
                msg = f"Accepting proposal {proposal_id} and marking ready to mail{suffix}..."
            else:
                msg = f"Accepting proposal {proposal_id}{suffix}..."
        else:
            ids = ", ".join(e[0] for e in entries)
            if mark_ready_to_mail:
                msg = f"Accepting proposals {ids} and marking ready to mail{suffix}..."
            else:
                msg = f"Accepting proposals {ids}{suffix}..."

        def task_callable() -> tuple[bool, str]:
            return _accept_task(
                entries, cl_name, project_file, mark_ready_to_mail, skip_amend
            )

        # If mark_ready_to_mail, trigger mail after accept succeeds
        on_success = None
        if mark_ready_to_mail:

            def on_accept_success() -> None:
                self.action_mail()  # type: ignore[attr-defined]

            on_success = on_accept_success

        submitted = self._submit_background_task(  # type: ignore[attr-defined]
            "accept", cl_name, project_file, task_callable, on_success=on_success
        )

        if submitted:
            self.notify(msg)  # type: ignore[attr-defined]

    # --- Rebase Actions ---

    def action_rebase(self) -> None:
        """Open parent selection modal for rebasing the current ChangeSpec."""
        from ...changespec import get_base_status, get_eligible_parents_in_project
        from ..modals import ParentSelectModal

        if not self.changespecs or self.current_idx >= len(self.changespecs):
            return

        changespec = self.changespecs[self.current_idx]

        # Validate status is eligible (WIP, Draft, Ready, or Mailed)
        base_status = get_base_status(changespec.status)
        if base_status not in ("WIP", "Draft", "Ready", "Mailed"):
            self.notify(  # type: ignore[attr-defined]
                "Rebase is only available for WIP, Draft, Ready, or Mailed ChangeSpecs",
                severity="warning",
            )
            return

        # Get eligible parents from same project file
        eligible_parents = get_eligible_parents_in_project(
            changespec.file_path, changespec.name
        )

        # Always include root as the first option (rebasing to VCS default)
        eligible_parents.insert(0, (_ROOT_PARENT_SENTINEL, "root"))

        if len(eligible_parents) == 1:  # Only p4head, no other parents
            self.notify(  # type: ignore[attr-defined]
                "No eligible ChangeSpecs to use as parent",
                severity="warning",
            )
            return

        def on_dismiss(selected_parent: str | None) -> None:
            if selected_parent:
                self._run_rebase_workflow(changespec, selected_parent)

        self.push_screen(ParentSelectModal(eligible_parents), on_dismiss)  # type: ignore[attr-defined]

    def _run_rebase_workflow(
        self, changespec: ChangeSpec, new_parent_name: str
    ) -> None:
        """Run the rebase workflow as a background task.

        Args:
            changespec: The ChangeSpec being rebased
            new_parent_name: Name of the new parent ChangeSpec
        """
        import os

        project_basename = os.path.basename(changespec.file_path).replace(".gp", "")
        cl_name = changespec.name
        project_file = changespec.file_path

        def task_callable() -> tuple[bool, str]:
            return _rebase_task(
                cl_name, project_file, project_basename, new_parent_name
            )

        submitted = self._submit_background_task(  # type: ignore[attr-defined]
            "rebase", cl_name, project_file, task_callable
        )

        if submitted:
            self.notify(f"Rebase onto {new_parent_name} started for {cl_name}")  # type: ignore[attr-defined]
