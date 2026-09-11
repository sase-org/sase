"""Sidecar clone publication and recovery for axe workspace preparation."""

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


def protect_sidecar_repos(
    workspace_root: Path,
    *,
    refuse_on_unpublished: bool,
    skip_roots: set[Path] | None = None,
) -> bool:
    """Publish or rescue non-bead sidecar clones before workspace cleanup."""
    protected = True
    skipped = skip_roots or set()
    for sidecar_root in _workspace_sidecar_repo_roots(workspace_root):
        if sidecar_root in skipped:
            continue
        if not _protect_sidecar_repo(
            sidecar_root,
            refuse_on_unpublished=refuse_on_unpublished,
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
    recovery_ref, recovery_error = retain_current_head_recovery_ref(repo_root)
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
