"""Workspace checkout, launch eviction, and unpublished-commit orchestration."""

import contextlib
import logging
import sys
import time
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

from sase.axe.runner_workspace_beads import protect_workspace_bead_stores
from sase.axe.runner_workspace_sidecar import (
    protect_sidecar_repos,
    retain_current_head_recovery_ref,
)
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


class WorkspacePreparationError(RuntimeError):
    """Raised when workspace preparation fails, carrying the underlying reason.

    Attributes:
        reason: The underlying git/update/guard failure text (command
            stderr, exit detail, or guard refusal message).
        step: Which preparation step failed (``clean``, ``checkout``,
            ``sync``, ``fetch``, ``verify``, ``heal``,
            ``sidecar-protection``, or ``agents-sync-guard``).
        workspace_dir: The workspace that could not be prepared.
        reclone_eligible: Whether the failure is a local-state failure the
            reclone phase may repair by re-creating the workspace. Fetch and
            network failures, and every failure outside self-heal mode, are
            never eligible.
    """

    def __init__(
        self,
        reason: str,
        *,
        step: str = "",
        workspace_dir: str = "",
        reclone_eligible: bool = False,
    ) -> None:
        self.reason = reason
        self.step = step
        self.workspace_dir = workspace_dir
        self.reclone_eligible = reclone_eligible
        location = f" {workspace_dir}" if workspace_dir else ""
        detail = f" during {step}" if step else ""
        super().__init__(f"Failed to prepare workspace{location}{detail}: {reason}")


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
    with _agents_sidecar_sync_guard(workspace_dir) as acquired:
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

    if not _protect_unpushed_sidecar_commits(workspace_dir):
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
        rescued = _rescue_heal_state(workspace_dir, workspace_num, inspection)
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
            _rescue_checkout_for_heal(
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
        checkout_ok, checkout_err = _heal_checkout_rung(
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
            _heal_sync_rung(
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
        _verify_healed_checkout(provider, workspace_dir, expected_branch)

    print("Workspace ready")


def _rescue_checkout_for_heal(
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


def _rescue_heal_state(
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
    record = _rescue_checkout_for_heal(
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


def _heal_checkout_rung(
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


def _heal_sync_rung(
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
    record = _rescue_checkout_for_heal(
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


def _verify_healed_checkout(
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
    evicting: bool = False,
    workspace_num: int = 1,
) -> bool:
    """Publish or rescue local sidecar commits before workspace preparation resets.

    Every direct sidecar clone under ``sase/repos/<role>`` is checked. Bead
    stores keep the specialized semantic-sync path, while other sidecar roles
    use a cheap upstream-ahead probe and direct push. When *evicting*, the
    caller is about to destroy the clones that hold the only copies, so
    unpublishable state is rescued to the durable rescue store outside the
    workspace and eviction always proceeds instead of failing the launch.
    """
    workspace_root = Path(workspace_dir).expanduser().resolve()
    beads_ok, handled_bead_roots = protect_workspace_bead_stores(
        workspace_root,
        evicting=evicting,
        workspace_num=workspace_num,
    )
    sidecar_ok = protect_sidecar_repos(
        workspace_root,
        evicting=evicting,
        workspace_num=workspace_num,
        skip_roots=handled_bead_roots,
    )
    return beads_ok and sidecar_ok


def prepare_launch_workspace_repos(
    workspace_dir: str,
    workspace_num: int,
) -> frozenset[str]:
    """Evict launch-scoped repos and strictly recreate required sidecars.

    The returned paths identify sidecars proven to have been freshly cloned by
    this launch, so later linked-repo setup can reuse them without another
    materialization or synchronization pass.

    Launch-time sidecar protection publishes once, rescues unpublishable
    state to the durable rescue store outside the workspace, and always
    proceeds with eviction: leftover state from an earlier run never fails a
    new launch.
    """
    from sase.linked_repos import clear_workspace_repos

    # Only numbered workspaces evict sidecars; the primary checkout's clones
    # survive ``clear_workspace_repos`` untouched.
    if workspace_num > 1:
        _protect_unpushed_sidecar_commits(
            workspace_dir, evicting=True, workspace_num=workspace_num
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
