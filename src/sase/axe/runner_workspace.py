"""Workspace preparation helpers shared by axe runners."""

import contextlib
from dataclasses import dataclass
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from pathlib import Path

from sase._linked_repo_paths import (
    EXTERNAL_REPO_CLONES_SUBDIR,
    LINKED_REPO_CLONES_SUBDIR,
    SIDECAR_REPO_CLONES_SUBDIR,
)
from sase.git_lock_retry import (
    STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS,
    git_index_lock_path,
)
from sase.sdd._bead_state import has_bead_state
from sase.vcs_provider import get_vcs_provider

logger = logging.getLogger(__name__)


class _WorkspaceBeadEvictionRefused(RuntimeError):
    """Raised when eviction would destroy unpublished sidecar commits."""


@dataclass(frozen=True)
class _SidecarPublicationResult:
    published: bool
    detail: str | None = None


@dataclass(frozen=True)
class _SidecarUpstreamTarget:
    branch: str
    remote: str


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
        cl_name: Display name for the Patch/project (used for backup diff name).
        update_target: What to checkout (Patch branch or "p4head").
        backup_suffix: Suffix appended to cl_name for the backup diff name
            (e.g., "ace" produces "{cl_name}-ace").
        project_basename: Project basename for resolving patch names to
            git branch names.

    Returns:
        True if successful, False otherwise.
    """
    with _agents_sidecar_sync_guard(workspace_dir) as acquired:
        if not acquired:
            print(
                "workspace preparation refused to clean the shared agents sidecar "
                f"clone at {workspace_dir}: agents sync lock is busy",
                file=sys.stderr,
            )
            return False
        return _prepare_workspace_locked(
            workspace_dir,
            cl_name,
            update_target,
            backup_suffix,
            project_basename,
        )


def _prepare_workspace_locked(
    workspace_dir: str,
    cl_name: str,
    update_target: str,
    backup_suffix: str,
    project_basename: str,
) -> bool:
    """Run the clean/checkout/sync pass that :func:`prepare_workspace` guards."""

    from sase.workflows.commit_utils import run_sase_hg_clean

    # An index.lock left behind by a crashed or SIGTERM-killed git process
    # blocks every subsequent operation in this clone ("Another git process
    # seems to be running..."), which would fail the clean/checkout below. This
    # runs against a workspace we have exclusively claimed, so a lock old enough
    # to predate the claim is abandoned; clear it as git itself instructs.
    clear_stale_git_index_lock(workspace_dir)

    if not _protect_unpushed_sidecar_commits(workspace_dir):
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


def _agents_sidecar_clone_root(workspace_dir: str | Path) -> Path | None:
    """Return *workspace_dir* when it is the machine-shared agents sidecar clone.

    The agents sidecar lives at one stable machine-level path per project
    (``~/.sase/projects/<key>/repos/agents``) that every numbered workspace
    shares, unlike the per-workspace sidecar clones under ``sase/repos/``.
    """

    from sase.core.paths import sase_projects_dir
    from sase.sdd.store import AGENTS_SIDECAR_ROLE

    path = Path(workspace_dir).expanduser().resolve(strict=False)
    if path.name != AGENTS_SIDECAR_ROLE or path.parent.name != "repos":
        return None
    try:
        projects_root = Path(sase_projects_dir()).expanduser().resolve(strict=False)
    except Exception:  # noqa: BLE001 - path resolution must not break preparation.
        return None
    if path.parent.parent.parent != projects_root:
        return None
    return path if (path / ".git").exists() else None


@contextlib.contextmanager
def _agents_sidecar_sync_guard(workspace_dir: str) -> Generator[bool, None, None]:
    """Hold the agents sync lock while preparing the shared agents sidecar.

    ``prepare_workspace`` runs ``git reset --hard HEAD``, ``git clean -fd``, and
    a checkout. Against the shared agents clone those steps race agents sync,
    which stages a whole regenerated payload in the worktree before committing
    it: a reset that rewrites a dirty tracked file unlinks it before recreating
    it, and a publication pass reading the owner manifest inside that window
    sees no file and republishes from an empty manifest, silently truncating it.
    Every agents-sync mutator already serializes on ``sase-agents-sync.lock``,
    so preparation takes the same lock instead of cleaning underneath one.

    Yields ``True`` for any other workspace, which needs no coordination.
    """

    repo = _agents_sidecar_clone_root(workspace_dir)
    if repo is None:
        yield True
        return

    from sase.agents_sync.git import run_git
    from sase.agents_sync.git_sync_ops import (
        agents_git_dir,
        bounded_agents_lock,
        configured_agents_lock_timeout,
    )

    lock_path = agents_git_dir(repo, run_git) / "sase-agents-sync.lock"
    with bounded_agents_lock(lock_path, configured_agents_lock_timeout()) as acquired:
        yield acquired


def _protect_unpushed_sidecar_commits(
    workspace_dir: str,
    *,
    refuse_on_unpublished: bool = False,
) -> bool:
    """Publish or rescue local sidecar commits before workspace preparation resets.

    Every direct sidecar clone under ``sase/repos/<role>`` is checked. Bead
    stores keep the specialized semantic-sync path, while other sidecar roles
    use a cheap upstream-ahead probe and direct push. When
    *refuse_on_unpublished* is set, an unpublishable sidecar fails preparation
    outright instead of warning and proceeding; the caller is about to destroy
    the clone that holds the only copy.
    """
    workspace_root = Path(workspace_dir).expanduser().resolve()

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
    for sidecar_root in _workspace_sidecar_repo_roots(workspace_root):
        if sidecar_root in unsafe_generic_roots:
            continue
        if not _protect_sidecar_repo(
            sidecar_root,
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


def _workspace_sidecar_repo_roots(workspace_root: Path) -> list[Path]:
    """Return direct Git sidecar clones under ``sase/repos/<role>``."""
    repos_root = workspace_root.joinpath(*SIDECAR_REPO_CLONES_SUBDIR)
    if not repos_root.is_dir():
        return []

    skipped_containers = {
        LINKED_REPO_CLONES_SUBDIR[-1],
        EXTERNAL_REPO_CLONES_SUBDIR[-1],
    }
    roots: list[Path] = []
    try:
        children = sorted(repos_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return []
    for child in children:
        if child.name in skipped_containers:
            continue
        if not child.is_dir():
            continue
        if not (child / ".git").exists():
            continue
        roots.append(child.resolve())
    return roots


def _protect_sidecar_repo(
    repo_root: Path,
    *,
    refuse_on_unpublished: bool,
) -> bool:
    """Publish or rescue one non-bead sidecar repo before cleanup."""
    local_commits, inspect_error = _unpushed_sidecar_commit_count(repo_root)
    if inspect_error is not None:
        if refuse_on_unpublished:
            _report_sidecar_eviction_failure(
                repo_root=repo_root,
                remaining=None,
                recovery_ref=None,
                detail=inspect_error,
            )
            print(
                "workspace preparation refused to evict sidecar repo "
                f"{repo_root}: could not verify publication state: {inspect_error}",
                file=sys.stderr,
            )
            return False
        print(
            f"Warning: could not verify sidecar publication state for {repo_root}: "
            f"{inspect_error}",
            file=sys.stderr,
        )
        return True
    if local_commits <= 0:
        return True

    print(
        "Found "
        f"{local_commits} unpushed local sidecar commit(s) in {repo_root}; "
        "publishing before workspace cleanup..."
    )
    publication = _publish_sidecar_repo(repo_root)
    remaining, remaining_error = _unpushed_sidecar_commit_count(repo_root)
    if remaining_error is not None:
        remaining = local_commits
    if remaining <= 0 and publication.published:
        return True
    if remaining <= 0:
        remaining = local_commits

    detail = (
        remaining_error
        or publication.detail
        or "git push reported success but local sidecar commits remain"
    )
    recovery_ref, recovery_error = _retain_current_head_recovery_ref(repo_root)
    if recovery_error is not None or recovery_ref is None:
        _report_sidecar_eviction_failure(
            repo_root=repo_root,
            remaining=remaining,
            recovery_ref=None,
            detail=f"{detail}; recovery ref failed: {recovery_error or 'unknown error'}",
        )
        print(
            "workspace preparation refused to discard "
            f"{remaining} unpushed local sidecar commit(s) in {repo_root}: "
            f"{detail}; recovery ref failed: {recovery_error or 'unknown error'}",
            file=sys.stderr,
        )
        return False

    _report_sidecar_eviction_failure(
        repo_root=repo_root,
        remaining=remaining,
        recovery_ref=recovery_ref,
        detail=detail,
    )
    if refuse_on_unpublished:
        print(
            f"workspace preparation refused to evict sidecar repo {repo_root}: "
            f"{remaining} unpublished local commit(s) retained at "
            f"{recovery_ref}; {detail}",
            file=sys.stderr,
        )
        return False

    print(
        "Warning: retained "
        f"{remaining} unpushed local sidecar commit(s) at {recovery_ref} before "
        f"workspace cleanup; {detail}",
        file=sys.stderr,
    )
    return True


def _unpushed_sidecar_commit_count(repo_root: Path) -> tuple[int, str | None]:
    """Return commits ahead of the configured upstream, or an error detail."""
    from sase.sdd._repository_health import default_git_runner, format_git_error

    result = default_git_runner(
        repo_root,
        ["rev-list", "--count", "@{upstream}..HEAD"],
        op="workspace.sidecar_safety.unpushed_count",
    )
    if result.returncode != 0:
        return 0, format_git_error(
            "could not count unpublished sidecar commits", result
        )
    try:
        return int(result.stdout.strip()), None
    except ValueError:
        return 0, f"git rev-list returned a non-integer count: {result.stdout!r}"


def _publish_sidecar_repo(repo_root: Path) -> _SidecarPublicationResult:
    """Publish the current sidecar branch, integrating retryable divergence."""
    from sase.core.sidecar_publication_facade import (
        SIDECAR_PUBLICATION_ACTION_INTEGRATE_AND_RETRY,
        SIDECAR_PUBLICATION_ACTION_STOP,
        SIDECAR_PUBLICATION_ACTION_SUCCESS,
        decide_sidecar_publication_after_push,
    )
    from sase.sdd._git_contention import store_git_write_lock_factory
    from sase.sdd._repository_transaction import integrate_sdd_repository

    attempt = 1
    while True:
        push = _run_sidecar_push(repo_root)
        try:
            decision = decide_sidecar_publication_after_push(
                returncode=push.returncode,
                stdout=push.stdout or "",
                stderr=push.stderr or "",
                attempt=attempt,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed and preserve.
            return _SidecarPublicationResult(
                published=False,
                detail=f"sidecar publication policy failed: {exc}",
            )

        if decision.action == SIDECAR_PUBLICATION_ACTION_SUCCESS:
            verification_error = _verify_sidecar_publication(repo_root)
            if verification_error is None:
                return _SidecarPublicationResult(published=True)
            return _SidecarPublicationResult(
                published=False,
                detail=(
                    f"sidecar publication verification failed after "
                    f"{attempt} push attempt(s): {verification_error}"
                ),
            )

        if decision.action == SIDECAR_PUBLICATION_ACTION_INTEGRATE_AND_RETRY:
            target, target_error = _sidecar_upstream_target(repo_root)
            if target_error is not None or target is None:
                return _SidecarPublicationResult(
                    published=False,
                    detail=(
                        "sidecar publication could not resolve the configured "
                        f"upstream after push attempt {attempt}: {target_error}"
                    ),
                )
            integration = integrate_sdd_repository(
                repo_root,
                upstream="@{upstream}",
                fetch_remote=target.remote,
                expected_branch=target.branch,
                op_prefix="workspace.sidecar_safety.integrate",
                lock_factory=store_git_write_lock_factory(
                    op="workspace.sidecar_safety.integrate.transaction",
                    mutates_worktree=True,
                ),
            )
            if not integration.succeeded:
                detail = (
                    integration.error
                    or f"SDD integration stopped with status {integration.status.value}"
                )
                return _SidecarPublicationResult(
                    published=False,
                    detail=(
                        f"sidecar integration failed after push attempt {attempt}: "
                        f"{detail}"
                    ),
                )
            attempt += 1
            continue

        if decision.action == SIDECAR_PUBLICATION_ACTION_STOP:
            return _SidecarPublicationResult(
                published=False,
                detail=_format_sidecar_push_failure(push, decision),
            )

        return _SidecarPublicationResult(
            published=False,
            detail=f"sidecar publication policy returned unknown action {decision.action!r}",
        )


def _run_sidecar_push(repo_root: Path) -> subprocess.CompletedProcess[str]:
    """Push the current sidecar branch to its configured upstream."""
    from sase.sdd._repository_health import default_git_runner

    result = default_git_runner(
        repo_root,
        ["push"],
        op="workspace.sidecar_safety.push",
        network=True,
    )
    if not isinstance(result.stdout, str) or not isinstance(result.stderr, str):
        return subprocess.CompletedProcess(
            result.args,
            result.returncode,
            stdout=str(result.stdout or ""),
            stderr=str(result.stderr or ""),
        )
    return result


def _sidecar_upstream_target(
    repo_root: Path,
) -> tuple[_SidecarUpstreamTarget | None, str | None]:
    """Return the configured upstream target for the current sidecar branch."""
    from sase.sdd._repository_health import default_git_runner, format_git_error

    branch_result = default_git_runner(
        repo_root,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        op="workspace.sidecar_safety.upstream_branch",
    )
    if branch_result.returncode != 0 or not branch_result.stdout.strip():
        return None, format_git_error(
            "could not resolve current sidecar branch", branch_result
        )
    branch = branch_result.stdout.strip()
    remote_result = default_git_runner(
        repo_root,
        ["config", "--get", f"branch.{branch}.remote"],
        op="workspace.sidecar_safety.upstream_remote",
    )
    if remote_result.returncode != 0 or not remote_result.stdout.strip():
        return None, format_git_error(
            f"could not resolve upstream remote for branch {branch!r}",
            remote_result,
        )
    merge_result = default_git_runner(
        repo_root,
        ["config", "--get", f"branch.{branch}.merge"],
        op="workspace.sidecar_safety.upstream_merge",
    )
    if merge_result.returncode != 0 or not merge_result.stdout.strip():
        return None, format_git_error(
            f"could not resolve upstream merge ref for branch {branch!r}",
            merge_result,
        )
    return (
        _SidecarUpstreamTarget(
            branch=branch,
            remote=remote_result.stdout.strip(),
        ),
        None,
    )


def _verify_sidecar_publication(repo_root: Path) -> str | None:
    """Prove the sidecar HEAD is published to its configured upstream."""
    from sase.sdd._repository_health import default_git_runner, format_git_error

    remaining, count_error = _unpushed_sidecar_commit_count(repo_root)
    if count_error is not None:
        return count_error
    if remaining > 0:
        return f"{remaining} local sidecar commit(s) still appear ahead of upstream"
    ancestor = default_git_runner(
        repo_root,
        ["merge-base", "--is-ancestor", "HEAD", "@{upstream}"],
        op="workspace.sidecar_safety.verify_published",
    )
    if ancestor.returncode != 0:
        return format_git_error(
            "could not verify sidecar HEAD is reachable from upstream", ancestor
        )
    return None


def _format_sidecar_push_failure(
    result: subprocess.CompletedProcess[str],
    decision: object,
) -> str:
    from sase.sdd._repository_health import format_git_error

    reason = getattr(decision, "reason", "sidecar publication stopped")
    classification = getattr(decision, "classification", "unknown")
    attempt = getattr(decision, "attempt", "?")
    max_attempts = getattr(decision, "max_attempts", "?")
    return (
        f"{format_git_error('git push failed', result)}; {reason} "
        f"(classification={classification}, attempt {attempt}/{max_attempts})"
    )


def _report_sidecar_eviction_failure(
    *,
    repo_root: Path,
    remaining: int | None,
    recovery_ref: str | None,
    detail: str,
) -> None:
    """Surface a launch-time sidecar protection failure to the notification inbox."""
    try:
        from sase.notifications import notify_workflow_complete

        notes = [
            f"Failed to publish sidecar before workspace cleanup: {repo_root.name}",
            detail,
            "The sidecar clone was preserved so local-only commits are not lost.",
        ]
        if remaining is not None:
            notes.insert(1, f"{remaining} commit(s) remained ahead of upstream.")
        if recovery_ref is not None:
            notes.append(f"Recovery ref: {recovery_ref}")
        notify_workflow_complete(
            "sidecar-protection",
            os.environ.get("SASE_AGENT_CL_NAME", ""),
            False,
            notes,
            extra_files=[str(repo_root)],
            tags=["sidecar"],
        )
    except Exception:
        logger.debug(
            "Failed to report sidecar eviction protection failure",
            exc_info=True,
        )


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


def prepare_launch_workspace_repos(
    workspace_dir: str,
    workspace_num: int,
) -> frozenset[str]:
    """Evict launch-scoped repos and strictly recreate required sidecars.

    The returned paths identify sidecars proven to have been freshly cloned by
    this launch, so later linked-repo setup can reuse them without another
    materialization or synchronization pass.

    Raises:
        _WorkspaceBeadEvictionRefused: when a sidecar clone holds commits that
            could not be published. Eviction would delete the only copy of
            those commits, so the launch fails instead.
    """
    from sase.linked_repos import clear_workspace_repos

    # Only numbered workspaces evict sidecars; the primary checkout's clones
    # survive ``clear_workspace_repos`` untouched.
    if workspace_num > 1 and not _protect_unpushed_sidecar_commits(
        workspace_dir, refuse_on_unpublished=True
    ):
        raise _WorkspaceBeadEvictionRefused(
            "refusing to evict workspace sidecar repos: at least one sidecar "
            "holds unpublished commits (see diagnostics above)"
        )

    clear_workspace_repos(workspace_dir, workspace_num)

    from sase.sdd._paths import get_primary_workspace_dir
    from sase.sdd._store_records import is_materialized_record, read_sdd_store_record
    from sase.sdd.store import auto_connect_sdd_store, ensure_workspace_sdd_clone

    primary = Path(get_primary_workspace_dir(workspace_dir, workspace_num))
    already_connected = is_materialized_record(read_sdd_store_record(primary))
    if auto_connect_sdd_store(workspace_dir, workspace_num) and not already_connected:
        print("Connected existing SDD sidecars for first use on this machine")

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
