"""Workspace preparation helpers shared by axe runners."""

import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

from sase._linked_repo_paths import SIDECAR_REPO_CLONES_SUBDIR
from sase.git_lock_retry import (
    STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS,
    git_index_lock_path,
)
from sase.sdd._bead_state import has_bead_state
from sase.vcs_provider import get_vcs_provider

logger = logging.getLogger(__name__)


class WorkspaceBeadEvictionRefused(RuntimeError):
    """Raised when eviction would destroy unpublished canonical bead commits."""


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
) -> bool:
    """Clean and update workspace before running agent or workflow.

    Args:
        workspace_dir: The workspace directory.
        cl_name: Display name for the ChangeSpec/project (used for backup diff name).
        update_target: What to checkout (ChangeSpec branch or "p4head").
        backup_suffix: Suffix appended to cl_name for the backup diff name
            (e.g., "ace" produces "{cl_name}-ace").
        project_basename: Project basename for resolving changespec names to
            git branch names.

    Returns:
        True if successful, False otherwise.
    """
    from sase.workflows.commit_utils import run_sase_hg_clean

    # An index.lock left behind by a crashed or SIGTERM-killed git process
    # blocks every subsequent operation in this clone ("Another git process
    # seems to be running..."), which would fail the clean/checkout below. This
    # runs against a workspace we have exclusively claimed, so a lock old enough
    # to predate the claim is abandoned; clear it as git itself instructs.
    clear_stale_git_index_lock(workspace_dir)

    if not _protect_unpushed_sidecar_bead_commits(workspace_dir):
        return False

    # Clean workspace (saves any existing changes to a diff file)
    print("Cleaning workspace...")
    success, error = run_sase_hg_clean(workspace_dir, f"{cl_name}-{backup_suffix}")
    if not success:
        print(f"sase_hg_clean failed: {error}", file=sys.stderr)
        return False

    # Update workspace to target
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    provider = get_vcs_provider(workspace_dir)
    is_default_parent = update_target == VCS_DEFAULT_REVISION
    if is_default_parent:
        update_target = provider.get_default_parent_revision(workspace_dir)
    elif project_basename:
        update_target = provider.resolve_revision(
            update_target, project_basename, workspace_dir
        )
    print(f"Updating workspace to {update_target}...")
    checkout_ok, checkout_err = provider.checkout(update_target, workspace_dir)
    if not checkout_ok:
        print(f"sase_hg_update failed: {checkout_err}", file=sys.stderr)
        return False

    if is_default_parent:
        try:
            sync_ok, sync_err = provider.sync_workspace(workspace_dir)
        except NotImplementedError:
            sync_ok, sync_err = True, None
        if not sync_ok:
            print(f"sync_workspace failed: {sync_err}", file=sys.stderr)
            return False

    print("Workspace ready")
    return True


def _protect_unpushed_sidecar_bead_commits(
    workspace_dir: str,
    *,
    refuse_on_unpublished: bool = False,
) -> bool:
    """Publish or rescue local bead commits before workspace preparation resets.

    Every bead store reachable from *workspace_dir* is checked, including the
    sidecar-repos clones under ``sase/repos/`` that live in their own Git
    repositories. When *refuse_on_unpublished* is set, an unpublishable store
    fails the preparation outright instead of warning and proceeding — the
    caller is about to destroy the clone that holds the only copy.
    """
    workspace_root = Path(workspace_dir).expanduser().resolve()

    from sase.bead.sync import bead_store_git_root

    protected = True
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
    return protected


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
    recovery_ref, recovery_error = _retain_current_head_recovery_ref(repo_root)
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


def _retain_current_head_recovery_ref(repo_root: Path) -> tuple[str | None, str | None]:
    from sase.sdd._repository_health import default_git_runner, format_git_error
    from sase.sdd._repository_recovery_git import (
        recovery_ref,
        update_and_verify_ref,
    )

    branch_result = default_git_runner(
        repo_root,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        op="workspace.bead_safety.branch",
    )
    if branch_result.returncode != 0 or not branch_result.stdout.strip():
        return (
            None,
            format_git_error(
                "could not resolve the branch for bead recovery", branch_result
            ),
        )
    head_result = default_git_runner(
        repo_root,
        ["rev-parse", "--verify", "HEAD"],
        op="workspace.bead_safety.head",
    )
    if head_result.returncode != 0 or not head_result.stdout.strip():
        return (
            None,
            format_git_error("could not resolve HEAD for bead recovery", head_result),
        )

    branch = branch_result.stdout.strip()
    head = head_result.stdout.strip()
    ref = recovery_ref(repo_root, branch, head, time.time())
    error = update_and_verify_ref(
        repo_root,
        ref,
        head,
        default_git_runner,
        "workspace.bead_safety",
    )
    if error is not None:
        return None, error
    return ref, None


def prepare_launch_workspace_repos(
    workspace_dir: str,
    workspace_num: int,
) -> frozenset[str]:
    """Evict launch-scoped repos and strictly recreate required sidecars.

    The returned paths identify sidecars proven to have been freshly cloned by
    this launch, so later linked-repo setup can reuse them without another
    materialization or synchronization pass.

    Raises:
        WorkspaceBeadEvictionRefused: when a sidecar bead clone holds canonical
            bead commits that could not be published. Eviction would delete the
            only copy of those commits, so the launch fails instead.
    """
    from sase.linked_repos import clear_workspace_repos

    # Only numbered workspaces evict sidecars; the primary checkout's clones
    # survive ``clear_workspace_repos`` untouched.
    if workspace_num > 1 and not _protect_unpushed_sidecar_bead_commits(
        workspace_dir, refuse_on_unpublished=True
    ):
        raise WorkspaceBeadEvictionRefused(
            "refusing to evict workspace sidecar repos: a bead store holds "
            "unpublished canonical bead commits (see diagnostics above)"
        )

    clear_workspace_repos(workspace_dir, workspace_num)

    from sase.sdd.store import ensure_workspace_sdd_clone

    ensure_workspace_sdd_clone(
        workspace_dir,
        workspace_num,
        strict=workspace_num > 1,
    )

    if workspace_num <= 1:
        return frozenset()
    plans = Path(workspace_dir).expanduser() / "sase" / "repos" / "plans"
    if not (plans / ".git").is_dir():
        return frozenset()
    return frozenset({str(plans.resolve())})
