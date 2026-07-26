"""Health inspection and Git helpers for SDD repositories."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

from sase.sdd._git import SddGitCommandTimeout, network_git_timeout
from sase.sdd._repository_types import GitRunner, SddRepositoryState


class SddRepositoryHealthError(RuntimeError):
    """Raised when an SDD Git repository is structurally unsafe to write."""


_OPERATION_PATHS: tuple[tuple[str, str], ...] = (
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
    ("BISECT_LOG", "bisect"),
    ("BISECT_START", "bisect"),
    ("sequencer", "sequencer"),
)
_CREDENTIALS_IN_URL = re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE)


def require_sdd_repository_health(
    repo_root: Path,
    *,
    expected_branch: str | None = None,
    runner: GitRunner | None = None,
) -> SddRepositoryState:
    """Fail closed unless *repo_root* is attached and free of Git operations."""
    root = repo_root.expanduser().resolve()
    state = inspect_sdd_repository(root, runner or default_git_runner)
    blockers = sdd_state_blockers(state, expected_branch)
    if blockers:
        raise SddRepositoryHealthError(health_error(root, blockers))
    return state


def inspect_sdd_repository(repo_root: Path, runner: GitRunner) -> SddRepositoryState:
    worktree = runner(
        repo_root,
        ["rev-parse", "--is-inside-work-tree"],
        op="sdd.health.worktree",
    )
    valid_worktree = worktree.returncode == 0 and worktree.stdout.strip() == "true"

    git_dir_result = runner(
        repo_root,
        ["rev-parse", "--git-dir"],
        op="sdd.health.git_dir",
    )
    raw_git_dir = (
        git_dir_result.stdout.strip() if git_dir_result.returncode == 0 else ".git"
    )
    git_dir = Path(raw_git_dir or ".git")
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir

    branch_result = runner(
        repo_root,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        op="sdd.health.branch",
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    branch = branch or None

    head_result = runner(
        repo_root,
        ["rev-parse", "--verify", "HEAD"],
        op="sdd.health.head",
    )
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    head = head or None

    markers = tuple(
        dict.fromkeys(
            label
            for relative, label in _OPERATION_PATHS
            if (git_dir / relative).exists()
        )
    )
    unmerged = unmerged_paths(repo_root, runner, "sdd.health")
    status_result = runner(
        repo_root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        op="sdd.health.status",
    )
    if status_result.returncode != 0:
        valid_worktree = False
    return SddRepositoryState(
        repo_root=repo_root,
        git_dir=git_dir,
        branch=branch,
        head=head,
        operation_markers=markers,
        unmerged_paths=unmerged,
        status_porcelain=status_result.stdout if status_result.returncode == 0 else "",
        valid_worktree=valid_worktree,
    )


def unmerged_paths(
    repo_root: Path,
    runner: GitRunner,
    op_prefix: str,
) -> tuple[str, ...]:
    result = runner(
        repo_root,
        ["diff", "--name-only", "--diff-filter=U", "-z"],
        op=f"{op_prefix}.conflicts",
    )
    if result.returncode != 0:
        return ()
    return tuple(sorted(path for path in result.stdout.split("\0") if path))


def tracked_changes_error(
    repo_root: Path,
    runner: GitRunner,
    op_prefix: str,
) -> str | None:
    for args, label in (
        (["diff", "--quiet"], "tracked worktree changes"),
        (["diff", "--cached", "--quiet"], "staged changes"),
    ):
        result = runner(repo_root, args, op=f"{op_prefix}.clean")
        if result.returncode == 1:
            return (
                f"SDD repository {repo_root} needs integration but has {label}; "
                "commit or restore those changes and retry"
            )
        if result.returncode != 0:
            return format_git_error("could not inspect local SDD changes", result)
    return None


def default_git_runner(
    repo_root: Path,
    args: list[str],
    *,
    op: str,
    network: bool = False,
) -> subprocess.CompletedProcess[str]:
    from sase.sdd._git_contention import run_sdd_git_write

    try:
        return run_sdd_git_write(
            args,
            cwd=repo_root,
            op=op,
            timeout=network_git_timeout() if network else None,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, SddGitCommandTimeout) as exc:
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=124,
            stdout="",
            stderr=str(exc),
        )


def health_error(repo_root: Path, blockers: list[str]) -> str:
    detail = "; ".join(dict.fromkeys(blockers))
    return (
        f"SDD repository {repo_root} is not safe to write: {detail}. "
        "Finish or abort the existing Git operation in that repository, verify "
        "an attached branch and clean index, then retry; SASE did not modify it"
    )


def sdd_state_blockers(
    state: SddRepositoryState,
    expected_branch: str | None,
) -> list[str]:
    blockers = list(state.blockers)
    if expected_branch is not None and state.branch != expected_branch:
        blockers.append(
            f"expected branch {expected_branch!r}, found "
            f"{state.branch or 'detached HEAD'!r}"
        )
    return blockers


def sdd_rollback_mismatch(
    starting: SddRepositoryState,
    final: SddRepositoryState,
) -> str | None:
    """Return mismatches for repository state SASE owns during rollback.

    A shared SDD checkout can acquire unrelated worktree or untracked changes
    while an integration is being aborted. Those observations are deliberately
    excluded here; callers can surface them with
    :func:`sdd_rollback_observation_delta` without declaring the checkout
    unrecoverable.
    """
    mismatches: list[str] = []
    if final.blockers:
        mismatches.extend(final.blockers)
    if final.branch != starting.branch:
        mismatches.append(f"branch is {final.branch!r}, expected {starting.branch!r}")
    if final.head != starting.head:
        mismatches.append(f"HEAD is {final.head!r}, expected {starting.head!r}")
    if final.operation_markers != starting.operation_markers:
        mismatches.append("Git operation markers differ from the starting state")
    if final.unmerged_paths != starting.unmerged_paths:
        mismatches.append("unmerged index entries differ from the starting state")
    starting_index, _starting_observations = _porcelain_states(
        starting.status_porcelain
    )
    final_index, _final_observations = _porcelain_states(final.status_porcelain)
    if final_index != starting_index:
        mismatches.append("staged index entries differ from the starting state")
    return ", ".join(dict.fromkeys(mismatches)) or None


def sdd_rollback_observation_delta(
    starting: SddRepositoryState,
    final: SddRepositoryState,
) -> str | None:
    """Describe non-owned worktree/untracked churn observed across rollback."""
    _starting_index, starting_observations = _porcelain_states(
        starting.status_porcelain
    )
    _final_index, final_observations = _porcelain_states(final.status_porcelain)
    if final_observations == starting_observations:
        return None
    return (
        "worktree or untracked observations changed during rollback "
        f"(before={starting_observations!r}, after={final_observations!r})"
    )


def _porcelain_states(
    status_porcelain: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split porcelain v1 -z output into index state and worktree observations."""
    index_entries: list[str] = []
    observations: list[str] = []
    records = status_porcelain.split("\0")
    record_index = 0
    while record_index < len(records):
        record = records[record_index]
        record_index += 1
        if not record:
            continue
        if len(record) < 3:
            observations.append(record)
            continue
        index_status, worktree_status = record[0], record[1]
        path = record[3:] if len(record) > 3 else ""
        source_path: str | None = None
        if index_status in {"R", "C"} or worktree_status in {"R", "C"}:
            if record_index < len(records):
                source_path = records[record_index] or None
                record_index += 1
        path_display = f"{source_path!r} -> {path!r}" if source_path else repr(path)
        if index_status not in {" ", "?", "!"}:
            index_entries.append(f"{index_status} {path_display}")
        if (index_status, worktree_status) == ("?", "?"):
            observations.append(f"?? {path_display}")
        elif worktree_status not in {" ", "?", "!"}:
            observations.append(f"{worktree_status} {path_display}")
    return tuple(sorted(index_entries)), tuple(sorted(observations))


def format_git_error(
    message: str,
    result: subprocess.CompletedProcess[str],
) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        return f"{message}: {_redact_credentials(detail)}"
    return f"{message} with exit code {result.returncode}"


def safe_git_error_text(exc: BaseException) -> str:
    return _redact_credentials(str(exc) or type(exc).__name__)


def _redact_credentials(value: str) -> str:
    return _CREDENTIALS_IN_URL.sub(r"\1<redacted>@", value)
