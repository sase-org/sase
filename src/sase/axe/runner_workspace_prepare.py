"""Workspace checkout, launch eviction, and unpublished-commit orchestration.

Single-pass preparation lives here. The self-heal ladder, sidecar
protection, and re-creation retry live in focused sibling modules and are
re-exported here to preserve the historical import surface.
"""

import logging
import sys
import time
from typing import TYPE_CHECKING

from sase.axe.runner_workspace_errors import WorkspacePreparationError
from sase.axe.runner_workspace_heal import (
    heal_checkout_rung,
    heal_sync_rung,
    rescue_checkout_for_heal,
    rescue_heal_state,
    verify_healed_checkout,
)
from sase.axe.runner_workspace_protection import (
    agents_sidecar_sync_guard,
    protect_unpushed_sidecar_commits,
    prepare_launch_workspace_repos,
    rescue_sidecars_before_eviction,
)
from sase.axe.runner_workspace_reclone import prepare_workspace_with_reclone
from sase.git_lock_retry import (
    STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS,
    git_index_lock_path,
)
from sase.vcs_provider import get_vcs_provider

if TYPE_CHECKING:
    from sase.vcs_provider import VCSProvider
    from sase.vcs_provider._types import CheckoutInspection
    from sase.workspace_provider.rescue import RescueRecord

logger = logging.getLogger(__name__)


# Minimum age before a leftover ``.git/index.lock`` is treated as abandoned.
# Comfortably longer than any normal index operation, so we never race a lock
# a live git process just created.
_STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS = STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS


def clear_stale_git_index_lock(
    workspace_dir: str,
    *,
    min_age_seconds: float = _STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS,
) -> bool:
    """Remove an abandoned ``.git/index.lock`` from *workspace_dir*.

    Returns True only when a stale lock was removed. A missing lock, a lock
    younger than *min_age_seconds* (which could belong to a live git process),
    or any filesystem error is treated as a safe no-op.
    """
    lock_path = git_index_lock_path(workspace_dir)
    if lock_path is None:
        return False
    try:
        age_seconds = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return False
    except OSError:
        logger.debug("Could not stat git index lock %s", lock_path, exc_info=True)
        return False
    if age_seconds < min_age_seconds:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning(
            "Failed to remove stale git index lock %s", lock_path, exc_info=True
        )
        return False
    message = f"Removed stale git index lock ({age_seconds:.0f}s old): {lock_path}"
    print(message, file=sys.stderr)
    logger.warning(message)
    return True


def prepare_workspace(
    workspace_dir: str,
    cl_name: str,
    update_target: str,
    backup_suffix: str = "ace",
    project_basename: str = "",
    *,
    self_heal: bool = False,
    workspace_num: int = 1,
) -> None:
    """Clean and update workspace before running agent or workflow.

    Args:
        workspace_dir: The workspace directory.
        cl_name: Display name for the Patch/project (used for backup diff name).
        update_target: What to checkout (Patch branch or "p4head").
        backup_suffix: Suffix appended to cl_name for the backup diff name
            (e.g., "ace" produces "{cl_name}-ace").
        project_basename: Project basename for resolving patch names to
            git branch names.
        self_heal: Opt-in self-heal ladder for numbered ephemeral
            workspaces: rescue leftover state outside the workspace, abort
            in-progress git operations, survive stash failures, replace a
            conflicting sync rebase with rescue plus a hard reset, and verify
            a clean postcondition. Launch and retry callers pass
            ``workspace_num > 1``; the primary checkout, home mode, and
            ``sase workspace open`` keep the fail-closed default.
        workspace_num: The workspace number, used for rescue entry naming.

    Raises:
        WorkspacePreparationError: If any step fails. The error's ``reason``
            carries the underlying git/update failure text, and each failure
            is also printed so the run log records the cause.
    """
    with agents_sidecar_sync_guard(workspace_dir) as acquired:
        if not acquired:
            reason = (
                "workspace preparation refused to clean the shared agents sidecar "
                f"clone at {workspace_dir}: agents sync lock is busy"
            )
            print(reason, file=sys.stderr)
            raise WorkspacePreparationError(
                reason, step="agents-sync-guard", workspace_dir=workspace_dir
            )
        _prepare_workspace_locked(
            workspace_dir,
            cl_name,
            update_target,
            backup_suffix,
            project_basename,
            self_heal=self_heal,
            workspace_num=workspace_num,
        )


def _prepare_workspace_locked(
    workspace_dir: str,
    cl_name: str,
    update_target: str,
    backup_suffix: str,
    project_basename: str,
    *,
    self_heal: bool = False,
    workspace_num: int = 1,
) -> None:
    """Run the clean/checkout/sync pass that :func:`prepare_workspace` guards.

    Raises:
        WorkspacePreparationError: If any step fails, carrying the underlying
            failure text in ``reason``.
    """

    from sase.workflows.commit_utils import run_sase_hg_clean

    # An index.lock left behind by a crashed or SIGTERM-killed git process
    # blocks every subsequent operation in this clone ("Another git process
    # seems to be running..."), which would fail the clean/checkout below. This
    # runs against a workspace we have exclusively claimed, so a lock old enough
    # to predate the claim is abandoned; clear it as git itself instructs.
    clear_stale_git_index_lock(workspace_dir)

    if not protect_unpushed_sidecar_commits(workspace_dir, workspace_num=workspace_num):
        raise WorkspacePreparationError(
            "sidecar repos hold unpublished commits that could not be published "
            "before workspace cleanup (see diagnostics above)",
            step="sidecar-protection",
            workspace_dir=workspace_dir,
        )

    # The provider is resolved up front only for self-heal inspection; the
    # default path keeps today's order (clean before provider resolution) so
    # early clean failures keep their existing precedence.
    provider: VCSProvider | None = None
    inspection: CheckoutInspection | None = None
    if self_heal:
        # Self-heal inspection. Providers without the heal operations raise
        # NotImplementedError and preparation keeps today's behavior below.
        provider = get_vcs_provider(workspace_dir)
        try:
            inspection = provider.inspect_checkout(workspace_dir)
        except NotImplementedError:
            inspection = None
    healing = inspection is not None
    rescued: RescueRecord | None = None
    if inspection is not None and provider is not None:
        rescued = rescue_heal_state(workspace_dir, workspace_num, inspection)
        if inspection.operations:
            try:
                abort_ok, abort_err = provider.abort_in_progress_operations(
                    workspace_dir
                )
            except NotImplementedError:
                abort_ok, abort_err = True, None
            if not abort_ok:
                reason = (
                    "could not abort in-progress git operations: "
                    f"{abort_err or 'unknown error'}"
                )
                print(reason, file=sys.stderr)
                raise WorkspacePreparationError(
                    reason,
                    step="heal",
                    workspace_dir=workspace_dir,
                    reclone_eligible=True,
                )
            for label in inspection.operations:
                print(f"Aborted stale {label} in {workspace_dir}")

    # Clean workspace (saves any existing changes to a diff file)
    print("Cleaning workspace...")
    success, error = run_sase_hg_clean(workspace_dir, f"{cl_name}-{backup_suffix}")
    # (Healing implies a resolved provider; the extra conjunct is for typing.)
    if not success and healing and provider is not None:
        print(
            "Self-heal: stash backup failed "
            f"({error or 'unknown error'}); rescuing worktree, then reset and clean"
        )
        if rescued is None or rescued.patch_path is None:
            rescue_checkout_for_heal(
                workspace_dir,
                workspace_num,
                label="checkout",
                reason="self-heal: stash backup failed before clean",
            )
        try:
            clean_ok, clean_err = provider.clean_workspace(workspace_dir)
        except NotImplementedError:
            clean_ok = False
            clean_err = "clean_workspace is not supported by this VCS provider"
        if clean_ok:
            print(f"Self-heal: reset and cleaned {workspace_dir} after stash failure")
            success, error = True, ""
        else:
            error = (
                "reset and clean after stash failure failed: "
                f"{clean_err or 'unknown error'}"
            )
    if not success:
        reason = f"sase_hg_clean failed: {error or 'unknown error'}"
        print(reason, file=sys.stderr)
        raise WorkspacePreparationError(
            reason,
            step="clean",
            workspace_dir=workspace_dir,
            reclone_eligible=healing,
        )

    if provider is None:
        provider = get_vcs_provider(workspace_dir)

    # Update workspace to target
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    is_default_parent = update_target == VCS_DEFAULT_REVISION
    if is_default_parent:
        update_target = provider.get_default_parent_revision(workspace_dir)
    elif project_basename:
        update_target = provider.resolve_revision(
            update_target, project_basename, workspace_dir
        )
    if update_target.startswith("origin/"):
        expected_branch = update_target[len("origin/") :]
    else:
        expected_branch = update_target
    print(f"Updating workspace to {update_target}...")
    checkout_ok, checkout_err = provider.checkout(update_target, workspace_dir)
    if not checkout_ok and healing:
        checkout_ok, checkout_err = heal_checkout_rung(
            provider,
            update_target,
            checkout_err,
            is_default_parent=is_default_parent,
            workspace_dir=workspace_dir,
        )
    if not checkout_ok:
        reason = (
            f"sase_hg_update failed for target {update_target}: "
            f"{checkout_err or 'unknown error'}"
        )
        print(reason, file=sys.stderr)
        raise WorkspacePreparationError(
            reason,
            step="checkout",
            workspace_dir=workspace_dir,
            reclone_eligible=healing,
        )

    if is_default_parent:
        if healing:
            heal_sync_rung(
                provider, workspace_dir, workspace_num, remote_ref=update_target
            )
        else:
            try:
                sync_ok, sync_err = provider.sync_workspace(workspace_dir)
            except NotImplementedError:
                sync_ok, sync_err = True, None
            if not sync_ok:
                reason = f"sync_workspace failed: {sync_err or 'unknown error'}"
                print(reason, file=sys.stderr)
                raise WorkspacePreparationError(
                    reason, step="sync", workspace_dir=workspace_dir
                )

    if healing:
        verify_healed_checkout(provider, workspace_dir, expected_branch)

    print("Workspace ready")


__all__ = [
    "WorkspacePreparationError",
    "_prepare_workspace_locked",
    "clear_stale_git_index_lock",
    "prepare_launch_workspace_repos",
    "prepare_workspace",
    "prepare_workspace_with_reclone",
    "rescue_sidecars_before_eviction",
]
