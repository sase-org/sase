"""Sync action methods for the ace TUI app."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from sase.commit_utils import run_sase_hg_clean
from sase.vcs_provider import get_vcs_provider

if TYPE_CHECKING:
    from ...changespec import ChangeSpec


def _abort_if_needed(provider: object, workspace_dir: str) -> None:
    """Abort any in-progress sync/rebase to avoid leaving dirty state."""
    try:
        if provider.is_sync_in_progress(workspace_dir):  # type: ignore[attr-defined]
            print("Aborting in-progress rebase...")
            provider.abort_sync(workspace_dir)  # type: ignore[attr-defined]
    except (NotImplementedError, Exception):
        pass


class SyncMixin:
    """Mixin providing workspace sync action."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int

    def action_sync(self) -> None:
        """Sync the current ChangeSpec's workspace.

        This action:
        1. Validates STATUS is not "Submitted" or "Reverted"
        2. Gets first available axe workspace (100-199 range)
        3. Claims workspace
        4. Checks out the CL via VCS provider
        5. Syncs the workspace via VCS provider
        6. Releases workspace in finally block
        7. Shows output via self.suspend() context manager
        8. Reports success/failure via self.notify()
        """
        from sase.running_field import (
            claim_workspace,
            get_first_available_axe_workspace,
            get_workspace_directory_for_num,
            release_workspace,
        )

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
        workspace_num: int | None = None

        def run_handler() -> tuple[bool, str]:
            """Execute sync in suspended TUI context.

            Returns:
                Tuple of (success, message)
            """
            nonlocal workspace_num

            # Get workspace info
            workspace_num = get_first_available_axe_workspace(changespec.file_path)
            workflow_name = f"sync-{changespec.name}"

            try:
                workspace_dir, _ = get_workspace_directory_for_num(
                    workspace_num, project_basename
                )
            except RuntimeError as e:
                return (False, f"Failed to get workspace directory: {e}")

            # Claim workspace (use our process ID since this is synchronous)
            pid = os.getpid()
            if not claim_workspace(
                changespec.file_path, workspace_num, workflow_name, pid, changespec.name
            ):
                return (False, "Failed to claim workspace")

            try:
                # Clean workspace before switching branches
                clean_success, clean_error = run_sase_hg_clean(
                    workspace_dir, f"{changespec.name}-sync"
                )
                if not clean_success:
                    print(f"Warning: sase_hg_clean failed: {clean_error}")

                # Checkout the CL
                print(f"Checking out {changespec.name}...")
                provider = get_vcs_provider(workspace_dir)
                resolved = provider.resolve_revision(
                    changespec.name, project_basename, workspace_dir
                )
                checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
                if not checkout_ok:
                    return (False, f"checkout failed: {checkout_err}")

                # Sync workspace via xprompt workflow
                from sase.xprompt import execute_workflow
                from sase.xprompt.workflow_models import WorkflowExecutionError

                # Set env var so sync_setup.py finds the workspace
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

                    if status == "success":
                        return (True, f"Synced {changespec.name}: {message}")
                    elif status == "resolved":
                        from sase.notifications.senders import notify_sync_result

                        notify_sync_result(
                            status, changespec.name, workspace_dir, changespec.file_path
                        )
                        return (True, f"Synced {changespec.name}: {message}")
                    else:
                        from sase.notifications.senders import notify_sync_result

                        notify_sync_result(
                            status, changespec.name, workspace_dir, changespec.file_path
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
                if workspace_num is not None:
                    release_workspace(
                        changespec.file_path,
                        workspace_num,
                        workflow_name,
                        changespec.name,
                    )

        with self.suspend():  # type: ignore[attr-defined]
            success, message = run_handler()

        if success:
            from ...hooks import reset_dollar_hooks

            reset_dollar_hooks(changespec.file_path, changespec.name)
            self.notify(message)  # type: ignore[attr-defined]
        else:
            self.notify(f"Sync failed: {message}", severity="error")  # type: ignore[attr-defined]

        self._reload_and_reposition()  # type: ignore[attr-defined]
