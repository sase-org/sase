"""Bead-store protection for axe workspace preparation."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from sase._linked_repo_paths import SIDECAR_REPO_CLONES_SUBDIR
from sase.axe.runner_workspace_sidecar import (
    report_sidecar_may_be_lost,
    prior_publication_failure,
    record_publication_failure,
    retain_current_head_recovery_ref,
)
from sase.sdd._bead_state import has_bead_state

if TYPE_CHECKING:
    from sase.workspace_provider.rescue import RescueRecord


def protect_workspace_bead_stores(
    workspace_root: Path,
    *,
    evicting: bool,
    workspace_num: int = 1,
) -> tuple[bool, set[Path]]:
    """Publish or rescue workspace bead stores before cleanup.

    Returns whether every store is safe to reset, plus every Git root this
    pass handled — whatever the outcome — so generic sidecar protection never
    re-publishes a bead store with plain git.
    """
    from sase.bead.sync import bead_store_git_root

    protected = True
    handled_roots: set[Path] = set()
    for beads_dir in _workspace_bead_store_dirs(workspace_root):
        store_root = _bead_store_repo_root(
            beads_dir, workspace_root, bead_store_git_root
        )
        if store_root is None:
            continue
        handled_roots.add(store_root)
        if not _protect_bead_store(
            beads_dir,
            store_root,
            evicting=evicting,
            workspace_dir=workspace_root,
            workspace_num=workspace_num,
        ):
            protected = False
    return protected, handled_roots


def _protect_bead_store(
    beads_dir: Path,
    repo_root: Path,
    *,
    evicting: bool,
    workspace_dir: Path,
    workspace_num: int,
) -> bool:
    """Publish or rescue one bead store's local-only canonical commits."""
    from sase.bead.sync import (
        MUTATION_PUBLICATION_WORKER_LOCK_WAIT_SECONDS,
        push_bead_work_launch,
        unpushed_bead_commit_count,
        unpushed_bead_commit_count_result,
    )
    from sase.workspace_provider.rescue import (
        quarantine_directory,
        rescue_git_repo,
    )

    local_bead_commits, count_error = unpushed_bead_commit_count_result(
        repo_root, beads_dir
    )
    if count_error is not None and not evicting:
        print(
            "Warning: could not verify bead publication state for "
            f"{repo_root}: {count_error}",
            file=sys.stderr,
        )
        return True
    if count_error is not None:
        # Unknown publication state: rescue before evict instead of assuming
        # the store is safe to destroy.
        return _rescue_unpublished_bead_store(
            repo_root,
            remaining=None,
            detail=f"could not verify bead publication state: {count_error}",
            evicting=evicting,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            rescue_git_repo=rescue_git_repo,
            quarantine_directory=quarantine_directory,
        )
    if local_bead_commits <= 0:
        return True

    print(
        "Found "
        f"{local_bead_commits} unpushed local bead commit(s) in {repo_root}; "
        "publishing before workspace cleanup..."
    )
    head_sha = _bead_store_head_sha(repo_root)
    prior_detail = prior_publication_failure(repo_root, head_sha)
    outcome_error: str | None
    outcome_log_path: Path | None
    if prior_detail is not None:
        outcome_error = f"{prior_detail} (publication already failed at this HEAD)"
        outcome_pushed = False
        outcome_log_path = None
    else:
        # A concurrently running bead sync counts as a publication failure
        # only after a bounded wait, then this falls back to rescue.
        outcome = push_bead_work_launch(
            beads_dir,
            worker_lock_wait=MUTATION_PUBLICATION_WORKER_LOCK_WAIT_SECONDS,
        )
        outcome_error = outcome.error
        outcome_pushed = outcome.pushed
        outcome_log_path = outcome.log_path
    remaining = unpushed_bead_commit_count(repo_root, beads_dir)
    if remaining <= 0 and outcome_pushed and prior_detail is None:
        return True
    if remaining <= 0:
        remaining = local_bead_commits

    detail = outcome_error
    if detail is None:
        detail = (
            "managed bead sync reported success but local bead commits remain"
            if outcome_pushed
            else "managed bead sync did not publish"
        )
    if outcome_log_path is not None:
        detail = f"{detail} (managed sync log: {outcome_log_path})"
    if prior_detail is None:
        record_publication_failure(repo_root, head_sha, detail)
    return _rescue_unpublished_bead_store(
        repo_root,
        remaining=remaining,
        detail=detail,
        evicting=evicting,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        rescue_git_repo=rescue_git_repo,
        quarantine_directory=quarantine_directory,
    )


def _rescue_unpublished_bead_store(
    repo_root: Path,
    *,
    remaining: int | None,
    detail: str,
    evicting: bool,
    workspace_dir: Path,
    workspace_num: int,
    rescue_git_repo: Callable[..., RescueRecord | None],
    quarantine_directory: Callable[..., RescueRecord | None],
) -> bool:
    """Rescue unpublishable bead commits durably, then always allow eviction."""
    recovery_ref, recovery_error = retain_current_head_recovery_ref(repo_root)
    committed = f"{remaining} unpublished local bead commit(s)" if remaining else None
    if recovery_error is not None or recovery_ref is None:
        print(
            "workspace preparation could not pin a recovery ref for "
            f"{committed or 'unverifiable bead state'} in {repo_root}: "
            f"{detail}; recovery ref failed: {recovery_error or 'unknown error'}",
            file=sys.stderr,
        )
        return False

    if not evicting:
        # Ordinary preparation does not destroy the clone, so it warns and
        # proceeds without writing a rescue entry. The launch-time eviction
        # pass rescues exactly once.
        print(
            "Warning: retained "
            f"{committed or 'unverifiable bead state'} at {recovery_ref} before "
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
            f"bead store held {committed} (retained at {recovery_ref}): {detail}"
            if committed is not None
            else f"bead store publication state unknown "
            f"(retained at {recovery_ref}): {detail}"
        ),
        include_worktree=True,
    )
    if rescued is not None:
        print(
            "Warning: rescued "
            f"{committed or 'unverifiable bead state'} at {recovery_ref} to "
            f"{rescued.rescue_dir} before workspace cleanup; {detail}",
            file=sys.stderr,
        )
        return True
    quarantined = quarantine_directory(
        repo_root,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        label=repo_root.name,
        reason=f"bead store rescue bundle failed; {detail}",
    )
    if quarantined is not None:
        print(
            "Warning: quarantined bead store "
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
        "Warning: bead store "
        f"{repo_root} holds unpublished commits that could not be rescued "
        f"and may be lost; {detail}; proceeding with eviction",
        file=sys.stderr,
    )
    return True


def _bead_store_head_sha(repo_root: Path) -> str | None:
    from sase.sdd._repository_health import default_git_runner

    result = default_git_runner(
        repo_root,
        ["rev-parse", "--verify", "HEAD"],
        op="workspace.bead_safety.head_sha",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _workspace_bead_store_dirs(workspace_root: Path) -> list[Path]:
    """Return every bead store a workspace reset or eviction could destroy."""
    stores: list[Path] = []
    repos_root = workspace_root.joinpath(*SIDECAR_REPO_CLONES_SUBDIR)
    # Split-beads sidecar: the clone root itself is the bead store. Combined
    # sidecar: the bead store is the ``beads/`` subdirectory of the plans clone.
    for sidecar_store in (repos_root / "beads", repos_root / "plans" / "beads"):
        if has_bead_state(sidecar_store):
            stores.append(sidecar_store)
    in_repo_store = _top_level_beads_dir(workspace_root)
    if in_repo_store is not None:
        stores.append(in_repo_store)
    return stores


def _top_level_beads_dir(repo_root: Path) -> Path | None:
    beads_dir = repo_root / "beads"
    if beads_dir.is_dir():
        return beads_dir
    if has_bead_state(repo_root):
        return repo_root
    return None


def _bead_store_repo_root(
    beads_dir: Path,
    workspace_root: Path,
    git_root_for_path: Callable[[Path], Path | None],
) -> Path | None:
    """Return the Git root owning *beads_dir* when it is workspace-scoped.

    A sidecar bead store is its own Git repository nested inside the workspace,
    so accepting only the workspace repo itself would skip exactly the clones
    launch-time eviction destroys.
    """
    try:
        discovered_root = git_root_for_path(beads_dir)
    except Exception:  # noqa: BLE001 - safety preflight must not break non-git repos.
        return None
    if discovered_root is None:
        return None
    resolved_root = discovered_root.resolve()
    if resolved_root == workspace_root or workspace_root in resolved_root.parents:
        return resolved_root
    return None
