"""Rename action methods for the ace TUI app."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sase.ace.changespec.project_spec_path import project_spec_basename
from sase.workflows.commit_utils import run_sase_hg_clean
from sase.vcs_provider import get_vcs_provider
from sase.xprompt.directive_edit import set_prompt_name

from .agents._directive_persistence import (
    AgentDirectivePersistenceResult,
    AgentDirectivePersistenceSpec,
    AgentMetaPatch,
    persist_agent_directive_update,
)
from .task_actions import TrackedTaskCompletion, TrackedTaskResult

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ...changespec import ChangeSpec


class RenameMixin:
    """Mixin providing rename ChangeSpec action."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    _agents: list[Agent]
    current_idx: int
    current_tab: str

    def action_rename_cl(self) -> None:
        """Show rename modal for the current ChangeSpec or name an agent.

        On the ChangeSpecs tab: rename the PR (non-Submitted ChangeSpecs only).
        On the Agents tab: set/change the agent name.
        """
        if self.current_tab == "agents":
            self._set_agent_name()
            return

        from ...changespec import get_base_status
        from ..modals import RenameChangeSpecModal

        if self.current_tab != "changespecs":
            return

        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        # Validate status - rename not available for Submitted or Reverted
        base_status = get_base_status(changespec.status)
        if base_status in ("Submitted", "Reverted"):
            self.notify(  # type: ignore[attr-defined]
                "Rename not available for Submitted/Reverted ChangeSpecs",
                severity="warning",
            )
            return

        def handle_rename_result(new_name: str | None) -> None:
            """Handle the rename modal result."""
            if new_name is None:
                return
            self._execute_rename(changespec, new_name)

        self.push_screen(  # type: ignore[attr-defined]
            RenameChangeSpecModal(
                current_name=changespec.name,
                project_file_path=changespec.file_path,
                status=base_status,
            ),
            handle_rename_result,
        )

    def _execute_rename(self, changespec: ChangeSpec, new_name: str) -> None:
        """Execute the rename operation.

        Args:
            changespec: The ChangeSpec to rename.
            new_name: The new name for the ChangeSpec.
        """
        from sase.running_field import (
            claim_workspace,
            get_first_available_axe_workspace,
            get_workspace_directory_for_num,
            release_workspace,
            update_running_field_cl_name,
        )
        from sase.status_state_machine import update_parent_references_atomic

        from sase.ace.revert import update_changespec_name_atomic

        from ...changespec import get_base_status

        base_status = get_base_status(changespec.status)
        old_name = changespec.name
        project_basename = project_spec_basename(changespec.file_path)
        workspace_num: int | None = None
        cl_name_updated = False

        def run_handler() -> tuple[bool, str]:
            """Execute rename in suspended TUI context.

            Returns:
                Tuple of (success, message)
            """
            nonlocal workspace_num, cl_name_updated

            # For Reverted ChangeSpecs, skip Mercurial operations (no PR exists)
            if base_status == "Reverted":
                # Just update the spec file references
                try:
                    update_changespec_name_atomic(
                        changespec.file_path, old_name, new_name
                    )
                    update_parent_references_atomic(
                        changespec.file_path, old_name, new_name
                    )
                    update_running_field_cl_name(
                        changespec.file_path, old_name, new_name
                    )
                    from sase.ace.timestamps.recording import (
                        add_timestamp_entry_atomic,
                    )

                    add_timestamp_entry_atomic(
                        changespec.file_path,
                        new_name,
                        "RENAME",
                        f"{old_name} -> {new_name}",
                    )
                    return (True, f"Renamed {old_name} to {new_name}")
                except Exception as e:
                    return (False, f"Failed to update spec file: {e}")

            # Get workspace info
            workspace_num = get_first_available_axe_workspace(changespec.file_path)
            workflow_name = f"rename-{old_name}"

            try:
                workspace_dir, _ = get_workspace_directory_for_num(
                    workspace_num, project_basename
                )
            except RuntimeError as e:
                return (False, f"Failed to get workspace directory: {e}")

            # Claim workspace
            pid = os.getpid()
            claim_result = claim_workspace(
                changespec.file_path, workspace_num, workflow_name, pid, old_name
            )
            if not claim_result.success:
                return (
                    False,
                    "Failed to claim workspace: "
                    f"{claim_result.error or 'unknown reason'}",
                )

            try:
                # Clean workspace before switching branches
                clean_success, clean_error = run_sase_hg_clean(
                    workspace_dir, f"{old_name}-rename"
                )
                if not clean_success:
                    print(f"Warning: sase_hg_clean failed: {clean_error}")

                # Checkout the ChangeSpec
                print(f"Checking out {old_name}...")
                provider = get_vcs_provider(workspace_dir)
                resolved = provider.resolve_revision(
                    old_name, project_basename, workspace_dir
                )
                checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
                if not checkout_ok:
                    return (
                        False,
                        f"sase_hg_update failed: {checkout_err}",
                    )

                # Branch handling depends on provider capability
                from sase.core.branch_map import (
                    read_branch_map,
                    remove_branch_alias,
                    write_branch_alias,
                )

                if not provider.can_rename_branch(workspace_dir):
                    # Immutable branch — persist alias instead of
                    # renaming.  The old branch stays on the remote;
                    # resolution will find it via branch_map.
                    branch_map = read_branch_map(project_basename)
                    actual_branch = branch_map.get(old_name)
                    if actual_branch:
                        remove_branch_alias(project_basename, old_name)
                        write_branch_alias(project_basename, new_name, actual_branch)
                    else:
                        old_branch = resolved.removeprefix("origin/")
                        write_branch_alias(project_basename, new_name, old_branch)
                else:
                    # Mutable branch — rename directly
                    print(f"Renaming to {new_name}...")
                    rename_ok, rename_err = provider.rename_branch(
                        new_name, workspace_dir
                    )
                    if not rename_ok:
                        return (
                            False,
                            f"sase_hg_rename failed: {rename_err}",
                        )
                    # Clean up stale alias on successful rename
                    remove_branch_alias(project_basename, new_name)

                # Update spec file references
                print("Updating spec file references...")
                try:
                    update_changespec_name_atomic(
                        changespec.file_path, old_name, new_name
                    )
                    update_parent_references_atomic(
                        changespec.file_path, old_name, new_name
                    )
                    update_running_field_cl_name(
                        changespec.file_path, old_name, new_name
                    )
                    cl_name_updated = True
                except Exception as e:
                    return (False, f"Failed to update spec file: {e}")

                from sase.ace.timestamps.recording import (
                    add_timestamp_entry_atomic,
                )

                add_timestamp_entry_atomic(
                    changespec.file_path,
                    new_name,
                    "RENAME",
                    f"{old_name} -> {new_name}",
                )
                return (True, f"Renamed {old_name} to {new_name}")

            finally:
                # Always release workspace — use new_name if the ChangeSpec name
                # was already updated in the RUNNING field, otherwise old_name.
                if workspace_num is not None:
                    release_cl_name = new_name if cl_name_updated else old_name
                    release_workspace(
                        changespec.file_path,
                        workspace_num,
                        workflow_name,
                        release_cl_name,
                    )

        with self.suspend():  # type: ignore[attr-defined]
            success, message = run_handler()

        if success:
            self.notify(message)  # type: ignore[attr-defined]
        else:
            self.notify(f"Rename failed: {message}", severity="error")  # type: ignore[attr-defined]

        self._reload_and_reposition()  # type: ignore[attr-defined]

    def _set_agent_name(self) -> None:
        """Open AgentNameModal and write the name to agent_meta.json."""
        from ..modals import AgentNameModal

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return
        artifacts_dir = agent.get_artifacts_dir()  # type: ignore[union-attr]
        if artifacts_dir is None:
            self.notify(  # type: ignore[attr-defined]
                "Cannot name this agent (no artifacts directory)",
                severity="warning",
            )
            return

        # Capture stable identity — the agent object may be replaced by
        # periodic _load_agents() while the modal is open.
        agent_identity = agent.identity

        def handle_name_result(new_name: str | None) -> None:
            if new_name is None:
                return
            snapshot_agents = getattr(self, "_snapshot_agents_for_local_display", None)
            previous_agents = (
                snapshot_agents() if callable(snapshot_agents) else list(self._agents)
            )
            from sase.agent.names import NameCollisionError, claim_agent_name
            from sase.agent.launch_validation import (
                AgentNameForeignMachineError,
                AgentNameSyntaxError,
                validate_user_agent_name,
            )
            from sase.core.agent_identity_facade import (
                AgentIdentitySnapshot,
                normalize_owned_agent_name,
            )

            try:
                validate_user_agent_name(new_name)
                claim_agent_name(new_name, artifacts_dir, explicit=True)
            except (
                AgentNameForeignMachineError,
                AgentNameSyntaxError,
                NameCollisionError,
            ) as exc:
                self.notify(str(exc), severity="error")  # type: ignore[attr-defined]
                return

            machine_identity = AgentIdentitySnapshot.current()
            durable_name = normalize_owned_agent_name(new_name, machine_identity)

            spec = AgentDirectivePersistenceSpec(
                artifacts_dir=artifacts_dir,
                prompt_mutator=lambda prompt: set_prompt_name(prompt, new_name),
                meta_patch=AgentMetaPatch(set_values={"name": durable_name}),
            )

            def _task() -> TrackedTaskResult[AgentDirectivePersistenceResult]:
                result = persist_agent_directive_update(spec)
                return TrackedTaskResult(
                    success=True,
                    message=f"Agent name persisted: {new_name}",
                    payload=result,
                )

            def _refresh_from_disk() -> None:
                refresh = getattr(self, "_schedule_agents_async_refresh", None)
                if callable(refresh):
                    refresh(source="agent-name-persist-failed")
                else:
                    self._reload_and_reposition()  # type: ignore[attr-defined]

            def _on_complete(
                completion: TrackedTaskCompletion[AgentDirectivePersistenceResult],
            ) -> None:
                if completion.success:
                    return
                self.notify(  # type: ignore[attr-defined]
                    f"Agent name persist failed: {completion.message}",
                    severity="error",
                )
                _refresh_from_disk()

            task_info = self._submit_tracked_task(  # type: ignore[attr-defined]
                "agent-directive",
                agent.cl_name or agent.display_name or "agent",
                artifacts_dir,
                _task,
                display_name=f"Persist name: {new_name}",
                dedup_key=f"agent-directive-persist:{artifacts_dir}",
                duplicate_message="A directive update is already running for this agent",
                on_complete=_on_complete,
                reload_on_complete=False,
                notify_on_complete=False,
            )
            if task_info is None:
                return

            # Find the current agent by identity (may have been replaced by
            # periodic refresh while the modal was open)
            for candidates in (
                self._agents,
                getattr(self, "_agents_with_children", []),
            ):
                for a in candidates:
                    if a.identity == agent_identity:
                        a.agent_name = durable_name
                        refresh_name = getattr(
                            a,
                            "refresh_presented_agent_name",
                            None,
                        )
                        if callable(refresh_name):
                            refresh_name(machine_identity)

            self.notify(f"Agent named: {new_name}")  # type: ignore[attr-defined]
            refilter = getattr(self, "_refilter_agents", None)
            if callable(refilter):
                try:
                    refilter(previous_agents=previous_agents)
                except TypeError:
                    refilter()
            else:
                self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

        self.push_screen(  # type: ignore[attr-defined]
            AgentNameModal(
                current_name=getattr(agent, "presented_agent_name", None)
                or agent.agent_name
            ),
            handle_name_result,
        )
