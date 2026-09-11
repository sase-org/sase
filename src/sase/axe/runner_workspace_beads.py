"""Bead-store protection for axe workspace preparation."""

import sys
from collections.abc import Callable
from pathlib import Path

from sase._linked_repo_paths import SIDECAR_REPO_CLONES_SUBDIR
from sase.axe.runner_workspace_sidecar import retain_current_head_recovery_ref
from sase.sdd._bead_state import has_bead_state


def protect_workspace_bead_stores(
    workspace_root: Path,
    *,
    refuse_on_unpublished: bool,
) -> tuple[bool, set[Path]]:
    """Publish or rescue workspace bead stores before cleanup.

    Returns whether every store is safe to reset, plus Git roots that still
    hold unpublished bead commits so generic sidecar protection can skip them.
    """
    from sase.bead.sync import bead_store_git_root

    protected = True
    unsafe_generic_roots: set[Path] = set()
    for beads_dir in _workspace_bead_store_dirs(workspace_root):
        store_root = _bead_store_repo_root(
            beads_dir, workspace_root, bead_store_git_root
        )
        if store_root is None:
            continue
        if not _protect_bead_store(
            beads_dir,
            store_root,
            refuse_on_unpublished=refuse_on_unpublished,
        ):
            protected = False
            unsafe_generic_roots.add(store_root)
    return protected, unsafe_generic_roots


def _protect_bead_store(
    beads_dir: Path,
    repo_root: Path,
    *,
    refuse_on_unpublished: bool,
) -> bool:
    """Publish or rescue one bead store's local-only canonical commits."""
    from sase.bead.sync import push_bead_work_launch, unpushed_bead_commit_count

    local_bead_commits = unpushed_bead_commit_count(repo_root, beads_dir)
    if local_bead_commits <= 0:
        return True

    print(
        "Found "
        f"{local_bead_commits} unpushed local bead commit(s) in {repo_root}; "
        "publishing before workspace cleanup..."
    )
    outcome = push_bead_work_launch(beads_dir)
    remaining = unpushed_bead_commit_count(repo_root, beads_dir)
    if remaining <= 0:
        return True

    detail = outcome.error
    if detail is None:
        detail = (
            "managed bead sync reported success but local bead commits remain"
            if outcome.pushed
            else "managed bead sync did not publish"
        )
    if outcome.log_path is not None:
        detail = f"{detail} (managed sync log: {outcome.log_path})"
    recovery_ref, recovery_error = retain_current_head_recovery_ref(repo_root)
    if recovery_error is not None or recovery_ref is None:
        print(
            "workspace preparation refused to discard "
            f"{remaining} unpushed local bead commit(s) in {repo_root}: "
            f"{detail}; recovery ref failed: {recovery_error or 'unknown error'}",
            file=sys.stderr,
        )
        return False

    if refuse_on_unpublished:
        print(
            f"workspace preparation refused to evict the bead store at {repo_root}: "
            f"{remaining} unpublished local bead commit(s) retained at "
            f"{recovery_ref}; {detail}",
            file=sys.stderr,
        )
        return False

    print(
        "Warning: retained "
        f"{remaining} unpushed local bead commit(s) at {recovery_ref} before "
        f"workspace cleanup; {detail}",
        file=sys.stderr,
    )
    return True


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
