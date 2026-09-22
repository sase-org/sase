"""Sidecar clone publication and rescue for axe workspace preparation."""

from dataclasses import dataclass
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from sase._linked_repo_paths import (
    EXTERNAL_REPO_CLONES_SUBDIR,
    LINKED_REPO_CLONES_SUBDIR,
    SIDECAR_REPO_CLONES_SUBDIR,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SidecarPublicationResult:
    published: bool
    detail: str | None = None


@dataclass(frozen=True)
class _SidecarUpstreamTarget:
    branch: str
    remote: str


@dataclass(frozen=True)
class _SidecarCommitCountResult:
    count: int
    error: str | None = None
    damaged: bool = False


#: Publication failures keyed by ``(repo_root, HEAD sha)``. The eviction pass
#: must not re-publish a sidecar whose publication already failed at the same
#: HEAD earlier in this launch: one publication attempt per sidecar per
#: launch, then rescue. Entries are keyed by HEAD so a genuinely new commit
#: still gets its own publication attempt.
_FAILED_PUBLICATIONS: dict[tuple[str, str], str] = {}


def prior_publication_failure(repo_root: Path, head_sha: str | None) -> str | None:
    """Return the earlier failure detail when this HEAD already failed to publish."""
    if head_sha is None:
        return None
    return _FAILED_PUBLICATIONS.get((str(repo_root), head_sha))


def record_publication_failure(
    repo_root: Path, head_sha: str | None, detail: str
) -> None:
    """Memoize a publication failure so a later pass rescues instead of retrying."""
    if head_sha is None:
        return
    _FAILED_PUBLICATIONS[(str(repo_root), head_sha)] = detail


def _current_head_sha(repo_root: Path) -> str | None:
    from sase.sdd._repository_health import default_git_runner

    result = default_git_runner(
        repo_root,
        ["rev-parse", "--verify", "HEAD"],
        op="workspace.sidecar_safety.head_sha",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def protect_sidecar_repos(
    workspace_root: Path,
    *,
    evicting: bool,
    workspace_num: int = 1,
    skip_roots: set[Path] | None = None,
) -> bool:
    """Publish or rescue non-bead sidecar clones before workspace cleanup.

    When *evicting* (launch-time eviction is about to destroy these clones),
    unpublishable state is rescued to the durable rescue store and eviction
    always proceeds: this never fails closed. Otherwise it warns and proceeds,
    failing only when even an in-clone recovery ref could not be written.
    """
    protected = True
    skipped = skip_roots or set()
    for sidecar_root in _workspace_sidecar_repo_roots(workspace_root):
        if sidecar_root in skipped:
            continue
        if not _protect_sidecar_repo(
            sidecar_root,
            evicting=evicting,
            workspace_dir=workspace_root,
            workspace_num=workspace_num,
        ):
            protected = False
    return protected


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
    evicting: bool,
    workspace_dir: Path,
    workspace_num: int,
) -> bool:
    """Publish or rescue one non-bead sidecar repo before cleanup."""
    inspected = _unpushed_sidecar_commit_count(repo_root)
    if inspected.error is not None:
        if inspected.damaged:
            return _rescue_damaged_sidecar_repo(
                repo_root,
                inspected.error,
                evicting=evicting,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
            )
        if not evicting:
            print(
                f"Warning: could not verify sidecar publication state for {repo_root}: "
                f"{inspected.error}",
                file=sys.stderr,
            )
            return True
        # Unknown publication state: rescue before evict instead of assuming
        # the clone is safe to destroy.
        return _rescue_unpublished_sidecar_repo(
            repo_root,
            remaining=None,
            detail=(f"could not verify sidecar publication state: {inspected.error}"),
            evicting=True,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
        )
    local_commits = inspected.count
    if local_commits <= 0:
        return True

    print(
        "Found "
        f"{local_commits} unpushed local sidecar commit(s) in {repo_root}; "
        "publishing before workspace cleanup..."
    )
    head_sha = _current_head_sha(repo_root)
    prior_detail = prior_publication_failure(repo_root, head_sha)
    if prior_detail is not None:
        publication = _SidecarPublicationResult(
            published=False,
            detail=f"{prior_detail} (publication already failed at this HEAD)",
        )
    else:
        publication = _publish_sidecar_repo(repo_root)
    remaining_inspected = _unpushed_sidecar_commit_count(repo_root)
    remaining = remaining_inspected.count
    if remaining_inspected.error is not None:
        remaining = local_commits
    if remaining <= 0 and publication.published:
        return True
    if remaining <= 0:
        remaining = local_commits

    detail = (
        remaining_inspected.error
        or publication.detail
        or "git push reported success but local sidecar commits remain"
    )
    if not publication.published:
        record_publication_failure(repo_root, head_sha, detail)
    return _rescue_unpublished_sidecar_repo(
        repo_root,
        remaining=remaining,
        detail=detail,
        evicting=evicting,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
    )


def _rescue_damaged_sidecar_repo(
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


def _rescue_unpublished_sidecar_repo(
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


def _unpushed_sidecar_commit_count(repo_root: Path) -> _SidecarCommitCountResult:
    """Return commits ahead of the configured upstream, or an error detail."""
    from sase.sdd._repository_health import default_git_runner, format_git_error

    damaged_error = _uncountable_sidecar_state(repo_root)
    if damaged_error is not None:
        return _SidecarCommitCountResult(
            count=0,
            error=damaged_error,
            damaged=True,
        )

    result = default_git_runner(
        repo_root,
        ["rev-list", "--count", "@{upstream}..HEAD"],
        op="workspace.sidecar_safety.unpushed_count",
    )
    if result.returncode != 0:
        return _SidecarCommitCountResult(
            count=0,
            error=format_git_error(
                "could not count unpublished sidecar commits", result
            ),
        )
    try:
        return _SidecarCommitCountResult(count=int(result.stdout.strip()))
    except ValueError:
        return _SidecarCommitCountResult(
            count=0,
            error=f"git rev-list returned a non-integer count: {result.stdout!r}",
        )


def _uncountable_sidecar_state(repo_root: Path) -> str | None:
    """Return a damage detail when HEAD/upstream cannot be resolved."""
    from sase.sdd._repository_health import default_git_runner, format_git_error

    branch_result = default_git_runner(
        repo_root,
        ["symbolic-ref", "-q", "--short", "HEAD"],
        op="workspace.sidecar_safety.countability_branch",
    )
    if branch_result.returncode != 0 or not branch_result.stdout.strip():
        return format_git_error(
            "could not resolve current sidecar branch",
            branch_result,
        )
    branch = branch_result.stdout.strip()

    head_result = default_git_runner(
        repo_root,
        ["rev-parse", "--verify", "HEAD"],
        op="workspace.sidecar_safety.countability_head",
    )
    if head_result.returncode != 0 or not head_result.stdout.strip():
        return format_git_error(
            "could not resolve sidecar HEAD",
            head_result,
        )

    remote_result = default_git_runner(
        repo_root,
        ["config", "--get", f"branch.{branch}.remote"],
        op="workspace.sidecar_safety.countability_upstream_remote",
    )
    if remote_result.returncode != 0 or not remote_result.stdout.strip():
        return format_git_error(
            f"could not resolve upstream remote for branch {branch!r}",
            remote_result,
        )

    merge_result = default_git_runner(
        repo_root,
        ["config", "--get", f"branch.{branch}.merge"],
        op="workspace.sidecar_safety.countability_upstream_merge",
    )
    if merge_result.returncode != 0 or not merge_result.stdout.strip():
        return format_git_error(
            f"could not resolve upstream merge ref for branch {branch!r}",
            merge_result,
        )

    upstream_result = default_git_runner(
        repo_root,
        ["rev-parse", "--verify", "@{upstream}"],
        op="workspace.sidecar_safety.countability_upstream_ref",
    )
    if upstream_result.returncode != 0 or not upstream_result.stdout.strip():
        return format_git_error(
            f"could not resolve upstream ref for branch {branch!r}",
            upstream_result,
        )
    return None


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

    remaining = _unpushed_sidecar_commit_count(repo_root)
    if remaining.error is not None:
        return remaining.error
    if remaining.count > 0:
        return (
            f"{remaining.count} local sidecar commit(s) still appear ahead of upstream"
        )
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
