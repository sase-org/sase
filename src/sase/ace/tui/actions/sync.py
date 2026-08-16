"""Sync action methods for the ace TUI app."""

from __future__ import annotations

import json
import os
import threading
from typing import TYPE_CHECKING, Any

from sase.ace.patch.project_spec_path import project_spec_basename
from sase.project_display_names import humanize_cl_name
from sase.vcs_provider import get_vcs_provider
from sase.workflows.commit_utils import run_sase_hg_clean

if TYPE_CHECKING:
    from ...patch import Patch

# Lock for SASE_SYNC_CWD env var to prevent race conditions
# between concurrent sync tasks for different Patches.
_sync_env_lock = threading.Lock()


def _abort_if_needed(provider: object, workspace_dir: str) -> None:
    """Abort any in-progress sync/rebase to avoid leaving dirty state."""
    try:
        if provider.is_sync_in_progress(workspace_dir):  # type: ignore[attr-defined]
            print("Aborting in-progress rebase...")
            provider.abort_sync(workspace_dir)  # type: ignore[attr-defined]
    except (NotImplementedError, Exception):
        pass


def _sync_task(
    patch_name: str,
    patch_file_path: str,
    project_basename: str,
    *,
    workspace_num: int | None = None,
    workspace_dir: str | None = None,
    release: bool = True,
) -> tuple[bool, str]:
    """Execute sync as a proc.

    This standalone function contains the body of the former run_handler().
    It claims a workspace, syncs via the VCS provider, and releases the
    workspace in a finally block unless settlement owns that release.

    Returns:
        Tuple of (success, message).
    """
    from sase.running_field import (
        claim_workspace,
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
        release_workspace,
    )

    display_name = humanize_cl_name(patch_name)

    if workspace_num is None:
        workspace_num = get_first_available_axe_workspace(patch_file_path)
    workspace_num = int(workspace_num)
    workflow_name = f"sync-{patch_name}"

    if not workspace_dir:
        try:
            workspace_dir, _ = get_workspace_directory_for_num(
                workspace_num, project_basename
            )
        except RuntimeError as e:
            return (False, f"Failed to get workspace directory: {e}")

    if release:
        pid = os.getpid()
        claim_result = claim_workspace(
            patch_file_path, workspace_num, workflow_name, pid, patch_name
        )
        if not claim_result.success:
            return (
                False,
                f"Failed to claim workspace: {claim_result.error or 'unknown reason'}",
            )

    try:
        # Clean workspace before switching branches
        clean_success, clean_error = run_sase_hg_clean(
            workspace_dir, f"{patch_name}-sync"
        )
        if not clean_success:
            print(f"Warning: sase_hg_clean failed: {clean_error}")

        # Checkout the Patch
        print(f"Checking out {display_name}...")
        provider = get_vcs_provider(workspace_dir)
        # Keep canonical identity for revision resolution and all persistence.
        resolved = provider.resolve_revision(
            patch_name, project_basename, workspace_dir
        )
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            return (False, f"checkout failed: {checkout_err}")

        # Sync workspace via xprompt workflow
        from sase.xprompt import execute_workflow
        from sase.xprompt.workflow_models import WorkflowExecutionError

        # Hold the lock for the entire set + execute + restore to prevent
        # concurrent tasks from seeing a stale SASE_SYNC_CWD value.
        with _sync_env_lock:
            old_sync_cwd = os.environ.get("SASE_SYNC_CWD")
            os.environ["SASE_SYNC_CWD"] = workspace_dir

            try:
                print("Syncing workspace via workflow...")
                result = execute_workflow("sync", [], {}, silent=False)

                # Parse the report step output
                try:
                    report = json.loads(result.output)
                    status = report.get("status", "error")
                    message = report.get("message", "")
                except (json.JSONDecodeError, AttributeError):
                    status = "error"
                    message = "Failed to parse workflow output"

                if status in ("success", "resolved"):
                    if status == "resolved":
                        from sase.notifications.senders import notify_sync_result

                        notify_sync_result(
                            status,
                            patch_name,
                            workspace_dir,
                            patch_file_path,
                        )

                    from sase.ace.timestamps.recording import (
                        add_timestamp_entry_atomic,
                    )

                    add_timestamp_entry_atomic(
                        patch_file_path,
                        patch_name,
                        "SYNC",
                        status,
                    )

                    from sase.ace.deltas import refresh_deltas_after_commits_change

                    refresh_deltas_after_commits_change(
                        patch_file_path,
                        patch_name,
                        workspace_dir,
                    )
                    return (True, f"Synced {display_name}: {message}")
                else:
                    from sase.notifications.senders import notify_sync_result

                    notify_sync_result(
                        status, patch_name, workspace_dir, patch_file_path
                    )
                    _abort_if_needed(provider, workspace_dir)
                    return (False, f"sync failed: {message}")

            except WorkflowExecutionError as e:
                _abort_if_needed(provider, workspace_dir)
                return (False, f"sync workflow failed: {e}")
            except Exception as e:
                _abort_if_needed(provider, workspace_dir)
                return (False, f"sync failed: {e}")
            finally:
                if old_sync_cwd is not None:
                    os.environ["SASE_SYNC_CWD"] = old_sync_cwd
                else:
                    os.environ.pop("SASE_SYNC_CWD", None)

    finally:
        if release:
            release_workspace(
                patch_file_path,
                workspace_num,
                workflow_name,
                patch_name,
            )


class SyncMixin:
    """Mixin providing workspace sync action."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int

    def action_sync(self) -> None:
        """Sync the current Patch's workspace in the background.

        This action:
        1. Validates STATUS is not "Submitted", "Reverted", or "Archived"
        2. Checks per-Patch deduplication (handled by durable submission)
        3. Submits a proc that claims/releases workspace
        4. Shows toast notifications for start/completion/failure
        """
        from ...patch import get_base_status

        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        # Validate status
        base_status = get_base_status(patch.status)
        if base_status in ("Reverted", "Submitted", "Archived"):
            self.notify(  # type: ignore[attr-defined]
                "Sync not available for Reverted/Submitted/Archived Patches",
                severity="warning",
            )
            return

        project_basename = project_spec_basename(patch.file_path)
        cl_name = patch.name
        project_file = patch.file_path
        from .patch_durable import claim_patch_workspace, submit_patch_operation
        from .proc_actions import TrackedProcCompletion

        workflow_name = f"sync-{cl_name}"
        claimed = claim_patch_workspace(
            project_file, cl_name, workflow_name, project_basename
        )
        if claimed[0] is None:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to claim workspace: {claimed[1]}",
                severity="error",
            )
            return
        workspace_num, workspace_dir = claimed

        def on_complete(completion: TrackedProcCompletion[Any]) -> None:
            if completion.collision or not completion.success:
                return
            from ...hooks import reset_dollar_hooks

            reset_dollar_hooks(project_file, cl_name)

        submitted = submit_patch_operation(
            self,
            verb="sync",
            name=cl_name,
            project_file=project_file,
            payload={
                "settlement_owns_release": True,
                "workspace_dir": workspace_dir,
                "workspace_num": workspace_num,
            },
            workspace_num=workspace_num,
            workspace_workflow=workflow_name,
            on_complete=on_complete,
        )
        if submitted:
            self.notify(f"Sync started for {humanize_cl_name(cl_name)}")  # type: ignore[attr-defined]
        else:
            from sase.ace.tui.durable_ops import release_workspace_claim
            from sase.ace.tui.durable_ops import workspace_claim_policy

            release_workspace_claim(
                workspace_claim_policy(
                    project_file=project_file,
                    workspace_num=workspace_num,
                    workflow=workflow_name,
                    cl_name=cl_name,
                )
            )


sync_task = _sync_task
