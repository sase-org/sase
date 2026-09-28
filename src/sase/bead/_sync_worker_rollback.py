"""Post-guard rollback for the managed bead sync worker."""

from __future__ import annotations

from collections.abc import Callable
import subprocess
import time
from pathlib import Path
from typing import Any

from sase.bead._sync_worker_common import (
    deadline_timeout,
    log_sync_event,
    resolve_git_dir,
    rev_parse_head,
)


def restore_pre_integration_head(
    repo_root: Path,
    log_path: Path,
    *,
    git_runner: Callable[..., subprocess.CompletedProcess[str]],
    deadline: float | None,
    pre_head: str | None,
    reason: str,
) -> str:
    """Pin the rejected HEAD and restore *pre_head*; never raises.

    Mirrors ``_abort_and_verify`` in ``sase.sdd._repository_integration``:
    aborts an in-progress rebase when markers are present, otherwise resets
    ``--hard`` under the store write lock. Returns a short summary for the
    failure message; the full detail goes to the sync log.
    """
    from sase.sdd._git_contention import store_git_write_lock_factory
    from sase.sdd._repository_recovery_git import (
        recovery_ref,
        update_and_verify_ref,
    )

    lock_factory = store_git_write_lock_factory(
        op="bead.sync.post_guard_rollback",
        mutates_worktree=True,
        timeout=deadline_timeout(deadline),
    )
    try:
        return _rollback_with_lock(
            repo_root,
            log_path,
            git_runner=git_runner,
            lock_factory=lock_factory,
            pre_head=pre_head,
            reason=reason,
            recovery_ref=recovery_ref,
            update_and_verify_ref=update_and_verify_ref,
        )
    except Exception as exc:  # noqa: BLE001 - rollback is best-effort
        summary = f"rollback failed: {exc}"
        log_sync_event(log_path, "post_guard_rollback", reason=reason, summary=summary)
        return summary


def _rollback_with_lock(
    repo_root: Path,
    log_path: Path,
    *,
    git_runner: Callable[..., subprocess.CompletedProcess[str]],
    lock_factory: Callable[[Path], Any],
    pre_head: str | None,
    reason: str,
    recovery_ref: Callable[..., str],
    update_and_verify_ref: Callable[..., str | None],
) -> str:
    rejected_head = rev_parse_head(repo_root, git_runner, op="bead.sync.rejected_head")
    branch = _current_branch(repo_root, git_runner)
    fields: dict[str, Any] = {
        "reason": reason,
        "pre_head": pre_head,
        "rejected_head": rejected_head,
    }
    with lock_factory(repo_root) as acquired:
        if not acquired:
            summary = "rollback skipped: store write lock unavailable"
            log_sync_event(log_path, "post_guard_rollback", **fields, summary=summary)
            return summary
        if rejected_head is not None:
            recovery_name = recovery_ref(repo_root, branch, rejected_head, time.time())
            try:
                ref_error = update_and_verify_ref(
                    repo_root,
                    recovery_name,
                    rejected_head,
                    git_runner,
                    "bead.sync.post_guard_rollback",
                )
            except Exception as exc:  # noqa: BLE001 - pinning is best-effort
                ref_error = f"could not pin a recovery ref: {exc}"
            fields["recovery_ref"] = recovery_name
            fields["recovery_ref_error"] = ref_error
        else:
            fields["recovery_ref_error"] = "no rejected HEAD to preserve"
        git_dir = resolve_git_dir(repo_root)
        rebase_active = (git_dir / "rebase-merge").exists() or (
            git_dir / "rebase-apply"
        ).exists()
        fields["rebase_active"] = rebase_active
        restore_error: str | None = None
        if rebase_active:
            try:
                aborted = git_runner(
                    repo_root,
                    ["rebase", "--abort"],
                    op="bead.sync.rollback_rebase_abort",
                )
            except Exception as exc:  # noqa: BLE001 - record, then verify
                restore_error = f"git rebase --abort failed: {exc}"
            else:
                if aborted.returncode != 0:
                    restore_error = (
                        "git rebase --abort failed: "
                        f"{(aborted.stderr or aborted.stdout or '').strip()}"
                    )
        current_head = rev_parse_head(
            repo_root, git_runner, op="bead.sync.rollback_verify_head"
        )
        if restore_error is None and pre_head is not None and current_head != pre_head:
            try:
                restored = git_runner(
                    repo_root,
                    ["reset", "--hard", pre_head],
                    op="bead.sync.rollback_reset",
                )
            except Exception as exc:  # noqa: BLE001 - record, then verify
                restore_error = f"git reset --hard failed: {exc}"
            else:
                if restored.returncode != 0:
                    restore_error = (
                        "git reset --hard failed: "
                        f"{(restored.stderr or restored.stdout or '').strip()}"
                    )
                current_head = rev_parse_head(
                    repo_root, git_runner, op="bead.sync.rollback_verify_head"
                )
        markers_remain = (git_dir / "rebase-merge").exists() or (
            git_dir / "rebase-apply"
        ).exists()
        fields["restore_error"] = restore_error
        fields["current_head"] = current_head
        fields["rebase_markers_remain"] = markers_remain
        if (
            restore_error is None
            and not markers_remain
            and (pre_head is None or current_head == pre_head)
        ):
            if pre_head is None:
                summary = "left HEAD untouched (no pre-integration HEAD recorded)"
            else:
                summary = f"restored pre-integration HEAD {pre_head[:12]}"
                if fields.get("recovery_ref") is not None:
                    summary += f"; rejected HEAD preserved at {fields['recovery_ref']}"
            log_sync_event(log_path, "post_guard_rollback", **fields, summary=summary)
            return summary
        problems = []
        if restore_error is not None:
            problems.append(restore_error)
        if markers_remain:
            problems.append("rebase markers remain after abort")
        if pre_head is not None and current_head != pre_head:
            problems.append(
                f"HEAD is {current_head!r}, expected pre-integration {pre_head!r}"
            )
        summary = "rollback verification failed: " + "; ".join(problems)
        log_sync_event(log_path, "post_guard_rollback", **fields, summary=summary)
        return summary


def _current_branch(
    repo_root: Path,
    git_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    """Resolve the current branch without raising; falls back to a label."""
    try:
        result = git_runner(
            repo_root,
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            op="bead.sync.rollback_branch",
        )
    except Exception:  # noqa: BLE001 - the branch only names the recovery ref
        return "bead-sync"
    branch = result.stdout.strip() if result.returncode == 0 else ""
    return branch or "bead-sync"
