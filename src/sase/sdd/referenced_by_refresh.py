"""Reconcile Referenced By projections in artifact repositories."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from sase.agents_sync.referenced_by_outbox_models import ReferencedByOutboxItem
from sase.sdd._referenced_by_refresh_models import (
    ReferencedByRefreshIssue,
    ReferencedByRefreshReport,
)
from sase.sdd.artifact_link_store import artifact_links_enabled

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


def refresh_referenced_by(
    store: SddStore,
    *,
    role: str,
    requests: tuple[ReferencedByOutboxItem, ...],
    write: bool = False,
) -> ReferencedByRefreshReport:
    """Refresh managed Referenced By blocks for one sidecar role."""

    repo_root = store.repo_root_for_kind(role).resolve(strict=False)
    if not repo_root.is_dir():
        return _report_with_error(
            repo_root,
            role,
            write,
            "root-missing",
            str(repo_root),
            f"artifact repository root does not exist: {repo_root}",
        )

    use_artifact_links = artifact_links_enabled()
    from sase.sdd._git_contention import store_git_write_lock

    lock = (
        store_git_write_lock(
            repo_root,
            op=(
                "sdd.artifact_links.refresh"
                if use_artifact_links
                else "sdd.referenced_by.refresh"
            ),
            mutates_worktree=True,
        )
        if write
        else nullcontext(True)
    )
    with lock as acquired:
        if not acquired:
            return _report_with_error(
                repo_root,
                role,
                write,
                "lock-busy",
                str(repo_root),
                "artifact repository write lock is busy",
            )
        if write:
            pull_issue = _pull_rebase_if_remote(repo_root)
            if pull_issue is not None:
                return ReferencedByRefreshReport(
                    root=repo_root,
                    role=role,
                    write=write,
                    scanned=0,
                    actions=(),
                    issues=(pull_issue,),
                    changed_files=(),
                    committed=False,
                )
        if use_artifact_links:
            from sase.sdd._artifact_link_refresh import (
                refresh_artifact_links_locked,
            )

            return refresh_artifact_links_locked(
                store,
                role=role,
                requests=requests,
                write=write,
            )

        from sase.sdd._referenced_by_refresh_legacy import refresh_legacy_locked

        return refresh_legacy_locked(
            store,
            role=role,
            requests=requests,
            write=write,
        )


def _pull_rebase_if_remote(repo_root: Path) -> ReferencedByRefreshIssue | None:
    from sase.sdd._git import run_sdd_git
    from sase.sdd._git_contention import run_sdd_git_write

    remote = run_sdd_git(
        ["remote", "get-url", "origin"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        op="sdd.referenced_by.remote",
    )
    if remote.returncode != 0 or not remote.stdout.strip():
        return None
    result = run_sdd_git_write(
        ["pull", "--rebase"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        op="sdd.referenced_by.pull",
    )
    if result.returncode == 0:
        return None
    detail = result.stderr.strip() or result.stdout.strip() or "git pull failed"
    return ReferencedByRefreshIssue(
        "error",
        "pull-failed",
        str(repo_root),
        detail,
    )


def _report_with_error(
    root: Path,
    role: str,
    write: bool,
    code: str,
    path: str,
    message: str,
) -> ReferencedByRefreshReport:
    return ReferencedByRefreshReport(
        root=root,
        role=role,
        write=write,
        scanned=0,
        actions=(),
        issues=(ReferencedByRefreshIssue("error", code, path, message),),
        changed_files=(),
        committed=False,
    )


__all__ = ["refresh_referenced_by"]
