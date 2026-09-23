"""Self-heal ladder for axe workspace preparation."""

import contextlib
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.axe.runner_workspace_errors import WorkspacePreparationError
from sase.axe.runner_workspace_sidecar import retain_current_head_recovery_ref

if TYPE_CHECKING:
    from sase.vcs_provider import VCSProvider
    from sase.vcs_provider._types import CheckoutInspection
    from sase.workspace_provider.rescue import RescueRecord

logger = logging.getLogger(__name__)


def rescue_checkout_for_heal(
    workspace_dir: str, workspace_num: int, *, label: str, reason: str
) -> "RescueRecord | None":
    """Bundle worktree state outside the workspace before healing touches it."""
    from sase.workspace_provider.rescue import rescue_git_repo

    return rescue_git_repo(
        workspace_dir,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        label=label,
        reason=reason,
        include_worktree=True,
    )


def rescue_heal_state(
    workspace_dir: str, workspace_num: int, inspection: "CheckoutInspection"
) -> "RescueRecord | None":
    """Rescue mid-operation, unmerged, or orphan-detached state before healing.

    A plain dirty worktree needs no rescue entry: the in-clone stash below
    stays its backup. Returns the record, or ``None`` when there was nothing
    worth preserving.
    """
    parts = list(inspection.operations)
    if inspection.unmerged_paths:
        parts.append(f"{len(inspection.unmerged_paths)} unmerged path(s)")
    if inspection.detached_orphan:
        parts.append("detached HEAD holding orphan commits")
    if not parts:
        return None
    record = rescue_checkout_for_heal(
        workspace_dir,
        workspace_num,
        label="checkout",
        reason=f"self-heal: checkout has {', '.join(parts)}",
    )
    if record is not None:
        print(
            f"Self-heal: rescued {', '.join(parts)} "
            f"to {record.rescue_dir} before aborting operations"
        )
    return record


def heal_checkout_rung(
    provider: "VCSProvider",
    update_target: str,
    checkout_err: str | None,
    *,
    is_default_parent: bool,
    workspace_dir: str,
) -> tuple[bool, str | None]:
    """Retry a failed checkout with ``-f``, then recreate the default branch."""
    print(
        f"Self-heal: checkout of {update_target} failed "
        f"({checkout_err or 'unknown error'}); retrying with -f"
    )
    try:
        forced_ok, forced_err = provider.force_checkout(update_target, workspace_dir)
    except NotImplementedError:
        return False, checkout_err
    if forced_ok:
        print(f"Self-heal: force-checked-out {update_target} in {workspace_dir}")
        return True, None
    if not is_default_parent:
        return False, forced_err
    remote_ref = update_target
    if remote_ref.startswith("origin/"):
        branch = remote_ref[len("origin/") :]
    else:
        branch = remote_ref
    print(
        f"Self-heal: forced checkout failed ({forced_err or 'unknown error'}); "
        f"recreating {branch} at {remote_ref}"
    )
    try:
        recreated_ok, recreated_err = provider.recreate_branch_from_remote(
            branch, remote_ref, workspace_dir
        )
    except NotImplementedError:
        return False, forced_err
    if recreated_ok:
        print(f"Self-heal: recreated {branch} at {remote_ref} in {workspace_dir}")
    return recreated_ok, recreated_err


def heal_sync_rung(
    provider: "VCSProvider", workspace_dir: str, workspace_num: int, *, remote_ref: str
) -> None:
    """Fetch, then rebase onto the default parent's remote tip.

    A fetch failure stays a hard failure with its own step and is never
    eligible for re-creation. A conflicting rebase is aborted, the local-only
    commits are rescued (bundle plus recovery ref), and the branch is hard
    reset to the remote tip.
    """
    try:
        fetch_ok, fetch_err = provider.fetch_origin(workspace_dir)
    except NotImplementedError:
        _bundled_sync_fallback(provider, workspace_dir)
        return
    if not fetch_ok:
        reason = f"git fetch origin failed: {fetch_err or 'unknown error'}"
        print(reason, file=sys.stderr)
        raise WorkspacePreparationError(
            reason,
            step="fetch",
            workspace_dir=workspace_dir,
            reclone_eligible=False,
        )
    try:
        rebase_ok, rebase_err = provider.rebase_onto(remote_ref, workspace_dir)
    except NotImplementedError:
        _bundled_sync_fallback(provider, workspace_dir)
        return
    if rebase_ok:
        return
    print(
        f"Self-heal: rebase onto {remote_ref} failed "
        f"({rebase_err or 'unknown error'}); aborting and rescuing local commits"
    )
    with contextlib.suppress(Exception):
        provider.abort_sync(workspace_dir)
    recovery_ref = _pin_heal_recovery_ref(workspace_dir)
    record = rescue_checkout_for_heal(
        workspace_dir,
        workspace_num,
        label="sync-conflict",
        reason=f"self-heal: rebase onto {remote_ref} conflicted",
    )
    try:
        reset_ok, reset_err = provider.reset_to_remote(remote_ref, workspace_dir)
    except NotImplementedError:
        reset_ok = False
        reset_err = "reset_to_remote is not supported by this VCS provider"
    if not reset_ok:
        reason = (
            f"self-heal reset to {remote_ref} after rebase conflict failed: "
            f"{reset_err or 'unknown error'}"
        )
        print(reason, file=sys.stderr)
        raise WorkspacePreparationError(
            reason,
            step="sync",
            workspace_dir=workspace_dir,
            reclone_eligible=True,
        )
    if remote_ref.startswith("origin/"):
        branch = remote_ref[len("origin/") :]
    else:
        branch = remote_ref
    rescued_parts: list[str] = []
    if record is not None:
        rescued_parts.append(str(record.rescue_dir))
    if recovery_ref is not None:
        rescued_parts.append(recovery_ref)
    if rescued_parts:
        print(
            f"Reset {branch} to {remote_ref} after rebase conflict; "
            f"local commits rescued to {', '.join(rescued_parts)}"
        )
    else:
        print(
            f"Reset {branch} to {remote_ref} after rebase conflict; "
            "WARNING: local commits could not be rescued",
            file=sys.stderr,
        )


def _bundled_sync_fallback(provider: "VCSProvider", workspace_dir: str) -> None:
    """Run today's bundled fetch+rebase when split sync is unsupported."""
    try:
        sync_ok, sync_err = provider.sync_workspace(workspace_dir)
    except NotImplementedError:
        sync_ok, sync_err = True, None
    if not sync_ok:
        reason = f"sync_workspace failed: {sync_err or 'unknown error'}"
        print(reason, file=sys.stderr)
        raise WorkspacePreparationError(
            reason,
            step="sync",
            workspace_dir=workspace_dir,
            reclone_eligible=True,
        )


def _pin_heal_recovery_ref(workspace_dir: str) -> str | None:
    """Pin HEAD to an in-clone recovery ref before a heal reset. Best-effort."""
    try:
        ref, _ = retain_current_head_recovery_ref(Path(workspace_dir))
    except Exception:  # noqa: BLE001 - the rescue bundle stays the backup.
        logger.warning(
            "Self-heal could not pin a recovery ref for %s",
            workspace_dir,
            exc_info=True,
        )
        return None
    return ref


def verify_healed_checkout(
    provider: "VCSProvider", workspace_dir: str, expected_branch: str
) -> None:
    """Verify the clean postcondition: no markers, no conflicts, attached HEAD."""
    try:
        final = provider.inspect_checkout(workspace_dir)
    except NotImplementedError:
        return
    problems: list[str] = []
    if final.operations:
        problems.append(f"in-progress operations remain: {', '.join(final.operations)}")
    if final.unmerged_paths:
        problems.append(f"unmerged paths remain: {', '.join(final.unmerged_paths)}")
    if (final.branch or "") != expected_branch:
        problems.append(
            f"HEAD is on {final.branch or 'a detached HEAD'} "
            f"(expected {expected_branch})"
        )
    if final.dirty:
        problems.append("worktree is still dirty")
    if problems:
        reason = "self-heal postcondition failed: " + "; ".join(problems)
        print(reason, file=sys.stderr)
        raise WorkspacePreparationError(
            reason,
            step="verify",
            workspace_dir=workspace_dir,
            reclone_eligible=True,
        )


__all__ = [
    "heal_checkout_rung",
    "heal_sync_rung",
    "rescue_checkout_for_heal",
    "rescue_heal_state",
    "verify_healed_checkout",
]
