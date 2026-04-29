"""Sync action methods for the ace TUI app."""

from __future__ import annotations

import json
import os
import threading
from typing import TYPE_CHECKING

from sase.workflows.commit_utils import run_sase_hg_clean
from sase.vcs_provider import get_vcs_provider

if TYPE_CHECKING:
    from ...changespec import ChangeSpec

# Lock for SASE_SYNC_CWD env var to prevent race conditions
# between concurrent sync tasks for different CLs.
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
    changespec_name: str,
    changespec_file_path: str,
    project_basename: str,
) -> tuple[bool, str]:
    """Execute sync as a background task.

    This standalone function contains the body of the former run_handler().
    It claims a workspace, syncs via the VCS provider, and releases the
    workspace in a finally block.

    Returns:
        Tuple of (success, message).
    """
    from sase.running_field import (
        claim_workspace,
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
        release_workspace,
    )

    workspace_num = get_first_available_axe_workspace(changespec_file_path)
    workflow_name = f"sync-{changespec_name}"

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
            workspace_dir, f"{changespec_name}-sync"
        )
        if not clean_success:
            print(f"Warning: sase_hg_clean failed: {clean_error}")

        # Checkout the CL
        print(f"Checking out {changespec_name}...")
        provider = get_vcs_provider(workspace_dir)
        resolved = provider.resolve_revision(
            changespec_name, project_basename, workspace_dir
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
                            changespec_name,
                            workspace_dir,
                            changespec_file_path,
                        )

                    from sase.ace.timestamps.recording import (
                        add_timestamp_entry_atomic,
                    )

                    add_timestamp_entry_atomic(
                        changespec_file_path,
                        changespec_name,
                        "SYNC",
                        status,
                    )

                    # DELTAS refresh — parent ref likely shifted after sync.
                    try:
                        from sase.ace.deltas import refresh_deltas_for_changespec

                        refresh_deltas_for_changespec(
                            changespec_file_path,
                            changespec_name,
                            workspace_dir,
                        )
                    except Exception:
                        pass
                    return (True, f"Synced {changespec_name}: {message}")
                else:
                    from sase.notifications.senders import notify_sync_result

                    notify_sync_result(
                        status, changespec_name, workspace_dir, changespec_file_path
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
        # Always release workspace
        release_workspace(
            changespec_file_path,
            workspace_num,
            workflow_name,
            changespec_name,
        )


class SyncMixin:
    """Mixin providing workspace sync action."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int

    def action_sync(self) -> None:
        """Sync the current ChangeSpec's workspace in the background.

        This action:
        1. Validates STATUS is not "Submitted", "Reverted", or "Archived"
        2. Checks per-CL deduplication (handled by _submit_background_task)
        3. Submits a background task that claims/releases workspace
        4. Shows toast notifications for start/completion/failure
        """
        from ...changespec import get_base_status

        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        # Validate status
        base_status = get_base_status(changespec.status)
        if base_status in ("Reverted", "Submitted", "Archived"):
            self.notify(  # type: ignore[attr-defined]
                "Sync not available for Reverted/Submitted/Archived ChangeSpecs",
                severity="warning",
            )
            return

        project_basename = os.path.basename(changespec.file_path).replace(".gp", "")
        cl_name = changespec.name
        project_file = changespec.file_path

        # Build the task callable (closure capturing all needed data)
        def task_callable() -> tuple[bool, str]:
            return _sync_task(cl_name, project_file, project_basename)

        # Build on_success callback
        def on_sync_success() -> None:
            from ...hooks import reset_dollar_hooks

            reset_dollar_hooks(project_file, cl_name)

        # Submit background task (handles dedup automatically)
        submitted = self._submit_background_task(  # type: ignore[attr-defined]
            "sync", cl_name, project_file, task_callable, on_success=on_sync_success
        )

        if submitted:
            self.notify(f"Sync started for {cl_name}")  # type: ignore[attr-defined]
