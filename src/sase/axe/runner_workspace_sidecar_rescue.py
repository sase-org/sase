"""Sidecar rescue, loss reporting, and recovery-ref helpers."""

import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def rescue_damaged_sidecar_repo(
    repo_root: Path,
    damage: str,
    *,
    evicting: bool,
    workspace_dir: Path,
    workspace_num: int,
) -> bool:
    """Quarantine an uncountable sidecar clone into the durable rescue store."""
    from sase.workspace_provider.rescue import quarantine_directory

    if not evicting:
        print(
            f"Warning: could not verify sidecar publication state for {repo_root}: "
            f"{damage}",
            file=sys.stderr,
        )
        return True
    quarantined = quarantine_directory(
        repo_root,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        label=repo_root.name,
        reason=f"damaged sidecar clone could not be published: {damage}",
    )
    if quarantined is not None:
        print(
            "Warning: quarantined damaged sidecar repo "
            f"{repo_root} at {quarantined.quarantined_path}; {damage}",
            file=sys.stderr,
        )
        return True
    report_sidecar_may_be_lost(
        repo_root=repo_root,
        remaining=None,
        detail=f"{damage}; quarantine failed",
    )
    print(
        "Warning: damaged sidecar repo "
        f"{repo_root} could not be quarantined and may lose local commits; "
        f"{damage}; proceeding with eviction",
        file=sys.stderr,
    )
    return True


def rescue_unpublished_sidecar_repo(
    repo_root: Path,
    *,
    remaining: int | None,
    detail: str,
    evicting: bool,
    workspace_dir: Path,
    workspace_num: int,
) -> bool:
    """Rescue unpublishable commits durably, then always allow eviction."""
    from sase.workspace_provider.rescue import (
        quarantine_directory,
        rescue_git_repo,
    )

    recovery_ref, recovery_error = retain_current_head_recovery_ref(repo_root)
    if recovery_error is not None or recovery_ref is None:
        recovery_note = f"recovery ref failed: {recovery_error or 'unknown error'}"
        if not evicting:
            print(
                "workspace preparation refused to discard "
                f"{remaining} unpushed local sidecar commit(s) in {repo_root}: "
                f"{detail}; {recovery_note}",
                file=sys.stderr,
            )
            return False
    else:
        recovery_note = f"retained at {recovery_ref}"

    if not evicting:
        # Ordinary preparation does not destroy the clone, so it warns and
        # proceeds without writing a rescue entry. The launch-time eviction
        # pass rescues exactly once.
        held = (
            f"{remaining} unpublished local sidecar commit(s)"
            if remaining is not None
            else "unverifiable sidecar state"
        )
        print(
            f"Warning: retained {held} at {recovery_ref} before "
            f"workspace cleanup; {detail}",
            file=sys.stderr,
        )
        return True

    rescued = rescue_git_repo(
        repo_root,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        label=repo_root.name,
        reason=(
            f"sidecar held {remaining} unpublished local commit(s) "
            f"({recovery_note}): {detail}"
            if remaining is not None
            else f"sidecar publication state unknown ({recovery_note}): {detail}"
        ),
        include_worktree=True,
    )
    if rescued is not None:
        print(
            "Warning: rescued "
            f"{remaining} unpushed local sidecar commit(s) at {recovery_ref} to "
            f"{rescued.rescue_dir} before workspace cleanup; {detail}",
            file=sys.stderr,
        )
        return True
    quarantined = quarantine_directory(
        repo_root,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        label=repo_root.name,
        reason=f"sidecar rescue bundle failed; {detail}",
    )
    if quarantined is not None:
        print(
            "Warning: quarantined sidecar repo "
            f"{repo_root} at {quarantined.quarantined_path} before "
            f"workspace cleanup; {detail}",
            file=sys.stderr,
        )
        return True
    report_sidecar_may_be_lost(
        repo_root=repo_root,
        remaining=remaining,
        detail=f"{detail}; rescue and quarantine failed",
    )
    print(
        "Warning: sidecar repo "
        f"{repo_root} holds unpublished commits that could not be rescued "
        f"and may be lost; {detail}; proceeding with eviction",
        file=sys.stderr,
    )
    return True


def report_sidecar_may_be_lost(
    *,
    repo_root: Path,
    remaining: int | None,
    detail: str,
) -> None:
    """Send the one fallback notification when rescue itself failed.

    Rescue already notifies on success, so this runs only when neither a
    bundle nor a quarantine could be written and eviction may lose commits.
    """
    try:
        from sase.notifications import notify_workflow_complete

        notes = [
            f"Sidecar commits in {repo_root.name} could not be rescued "
            "before workspace eviction and may be lost.",
            detail,
        ]
        if remaining is not None:
            notes.insert(1, f"{remaining} commit(s) remained ahead of upstream.")
        notify_workflow_complete(
            "workspace-rescue",
            os.environ.get("SASE_AGENT_CL_NAME", ""),
            False,
            notes,
            extra_files=[str(repo_root)],
            tags=["sidecar"],
        )
    except Exception:
        logger.debug(
            "Failed to report sidecar rescue failure",
            exc_info=True,
        )
        print(
            f"Warning: sidecar rescue notification failed for {repo_root}: {detail}",
            file=sys.stderr,
        )


def retain_current_head_recovery_ref(repo_root: Path) -> tuple[str | None, str | None]:
    """Pin HEAD to a recovery ref before a workspace reset can discard it."""
    from sase.sdd._repository_health import default_git_runner, format_git_error
    from sase.sdd._repository_recovery_git import (
        recovery_ref,
        update_and_verify_ref,
    )

    branch_result = default_git_runner(
        repo_root,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        op="workspace.sidecar_safety.branch",
    )
    if branch_result.returncode != 0 or not branch_result.stdout.strip():
        return (
            None,
            format_git_error(
                "could not resolve the branch for sidecar recovery",
                branch_result,
            ),
        )
    head_result = default_git_runner(
        repo_root,
        ["rev-parse", "--verify", "HEAD"],
        op="workspace.sidecar_safety.head",
    )
    if head_result.returncode != 0 or not head_result.stdout.strip():
        return (
            None,
            format_git_error(
                "could not resolve HEAD for sidecar recovery", head_result
            ),
        )

    branch = branch_result.stdout.strip()
    head = head_result.stdout.strip()
    ref = recovery_ref(repo_root, branch, head, time.time())
    error = update_and_verify_ref(
        repo_root,
        ref,
        head,
        default_git_runner,
        "workspace.sidecar_safety",
    )
    if error is not None:
        return None, error
    return ref, None
