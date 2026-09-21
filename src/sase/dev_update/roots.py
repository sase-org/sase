"""Git-root operations for editable-install dev updates."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from sase.dev_update.command import command_failure, run_recorded_command
from sase.dev_update.diffstat import parse_git_numstat
from sase.dev_update.models import (
    DevCommandResult,
    DevCommandRunner,
    DevExecutedCommand,
    DevUpdateRootPlan,
    RepoCommit,
    RepoCommitLog,
    RepoDiffStat,
)
from sase.dev_update.progress import (
    NULL_PROGRESS,
    format_merge_detail,
    merge_child_id,
    output_sink_for,
    record_command,
)
from sase.update_progress import UpdateProgress
from sase.version._git import GitUpstreamStatus, fetch_git_upstream, merge_git_ff_only

DEV_UPDATE_COMMIT_LOG_CAPTURE_LIMIT = 20

_COMMIT_LOG_UNIT_SEP = "\x1f"
_COMMIT_LOG_RECORD_SEP = "\x1e"
_COMMIT_LOG_FORMAT = "%h%x1f%s%x1e"


def fetch_actionable_roots(
    roots: tuple[DevUpdateRootPlan, ...],
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    progress: UpdateProgress = NULL_PROGRESS,
) -> str | None:
    """Fetch every actionable root, returning the first failure."""
    for root in roots:
        step_id = merge_child_id(root.git_root)
        progress.start(step_id, detail="fetching…")
        try:
            fetch_git_upstream(
                _root_status_for_fetch(root),
                run_git_fn=_git_text_runner(
                    run,
                    commands,
                    label="git fetch",
                    clock=clock,
                    progress=progress,
                    step_id=step_id,
                ),
            )
        except _GitCommandFailure as exc:
            progress.finish(step_id, "failed", detail=str(exc))
            return str(exc)
    return None


def preflight_actionable_roots(
    roots: tuple[DevUpdateRootPlan, ...],
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    progress: UpdateProgress = NULL_PROGRESS,
) -> str | None:
    """Verify every actionable root is safe and ready to fast-forward."""
    for root in roots:
        step_id = merge_child_id(root.git_root)
        progress.start(step_id, detail="checking…")
        dirty = _recorded(
            run,
            ("git", "-C", root.git_root, "status", "--porcelain"),
            cwd=None,
            label="git status",
            commands=commands,
            clock=clock,
            progress=progress,
            step_id=step_id,
        )
        if dirty.returncode != 0:
            failure = command_failure("git status failed", dirty)
            progress.finish(step_id, "failed", detail=failure)
            return failure
        if dirty.stdout.strip():
            failure = f"{root.git_root}: checkout has local changes"
            progress.finish(step_id, "failed", detail=failure)
            return failure

        if root.upstream is None:
            failure = f"{root.git_root}: checkout has no upstream"
            progress.finish(step_id, "failed", detail=failure)
            return failure
        rev_list = _recorded(
            run,
            (
                "git",
                "-C",
                root.git_root,
                "rev-list",
                "--left-right",
                "--count",
                f"HEAD...{root.upstream}",
            ),
            cwd=None,
            label="git preflight ancestry",
            commands=commands,
            clock=clock,
            progress=progress,
            step_id=step_id,
        )
        if rev_list.returncode != 0:
            failure = command_failure("git ancestry preflight failed", rev_list)
            progress.finish(step_id, "failed", detail=failure)
            return failure
        ahead, behind = _parse_ahead_behind(rev_list.stdout)
        if ahead is None or behind is None:
            failure = f"{root.git_root}: upstream ancestry unavailable"
            progress.finish(step_id, "failed", detail=failure)
            return failure
        if ahead > 0 and behind > 0:
            failure = f"{root.git_root}: checkout has diverged from upstream"
            progress.finish(step_id, "failed", detail=failure)
            return failure
        if ahead > 0:
            failure = f"{root.git_root}: checkout is ahead of upstream"
            progress.finish(step_id, "failed", detail=failure)
            return failure
        if behind <= 0:
            failure = f"{root.git_root}: already current"
            progress.finish(step_id, "failed", detail=failure)
            return failure
    return None


def merge_actionable_roots(
    roots: tuple[DevUpdateRootPlan, ...],
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    progress: UpdateProgress = NULL_PROGRESS,
) -> tuple[
    str | None,
    bool,
    dict[str, RepoDiffStat | None],
    dict[str, RepoCommitLog | None],
]:
    """Fast-forward roots and capture best-effort change summaries."""
    merged_any = False
    root_diffstats: dict[str, RepoDiffStat | None] = {}
    root_commits: dict[str, RepoCommitLog | None] = {}
    for root in roots:
        step_id = merge_child_id(root.git_root)
        progress.start(step_id, detail="merging…")
        if root.upstream is None:
            failure = f"{root.git_root}: checkout has no upstream"
            progress.finish(step_id, "failed", detail=failure)
            return (
                failure,
                merged_any,
                root_diffstats,
                root_commits,
            )
        old_head = _best_effort_head(
            root.git_root, run, commands, clock, progress, step_id
        )
        try:
            merge_git_ff_only(
                Path(root.git_root),
                root.upstream,
                run_git_fn=_git_text_runner(
                    run,
                    commands,
                    label="git merge --ff-only",
                    clock=clock,
                    progress=progress,
                    step_id=step_id,
                ),
            )
        except _GitCommandFailure as exc:
            progress.finish(step_id, "failed", detail=str(exc))
            return str(exc), merged_any, root_diffstats, root_commits
        merged_any = True
        new_head = _best_effort_head(
            root.git_root, run, commands, clock, progress, step_id
        )
        root_diffstats[root.git_root] = _best_effort_diffstat(
            root.git_root,
            old_head,
            new_head,
            run,
            commands,
            clock,
            progress,
            step_id,
        )
        root_commits[root.git_root] = _best_effort_commit_log(
            root.git_root,
            old_head,
            new_head,
            run,
            commands,
            clock,
            progress,
            step_id,
            limit=DEV_UPDATE_COMMIT_LOG_CAPTURE_LIMIT,
        )
        detail = format_merge_detail(
            old_head,
            new_head,
            root_commits[root.git_root],
            root_diffstats[root.git_root],
        )
        progress.finish(
            step_id,
            "done",
            # Never leave the transient "merging…" detail behind: an empty
            # merge summary still replaces it with a final detail.
            detail=detail if detail is not None else "fast-forwarded",
        )
    return None, merged_any, root_diffstats, root_commits


def _recorded(
    run: DevCommandRunner,
    argv: Sequence[str],
    *,
    cwd: Path | None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    label: str,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    progress: UpdateProgress,
    step_id: str,
) -> DevCommandResult:
    """Run a command, streaming output into *step_id* when progress is active.

    With the null sink this degrades to :func:`run_recorded_command` with
    ``on_output=None``, so injected fakes that do not accept ``on_output``
    keep working.
    """
    record_command(progress, step_id, argv, str(cwd) if cwd is not None else None)
    return run_recorded_command(
        run,
        argv,
        cwd=cwd,
        env=env,
        timeout=timeout,
        on_output=output_sink_for(progress, step_id),
        label=label,
        commands=commands,
        clock=clock,
    )


def _root_status_for_fetch(root: DevUpdateRootPlan) -> GitUpstreamStatus:
    return GitUpstreamStatus(
        root=root.git_root,
        upstream=root.upstream,
        remote=root.remote,
        remote_branch=root.remote_branch,
        detached=False,
        dirty=False,
        ahead=root.ahead,
        behind=root.behind,
    )


class _GitCommandFailure(Exception):
    pass


def _git_text_runner(
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    *,
    label: str,
    clock: Callable[[], float],
    progress: UpdateProgress = NULL_PROGRESS,
    step_id: str = "",
) -> Callable[..., str]:
    def runner(root: Path, *args: str, **_kwargs: object) -> str:
        result = _recorded(
            run,
            ("git", "-C", str(root), *args),
            cwd=None,
            label=label,
            commands=commands,
            clock=clock,
            progress=progress,
            step_id=step_id,
        )
        if result.returncode != 0:
            raise _GitCommandFailure(command_failure(f"{label} failed", result))
        return result.stdout.strip()

    return runner


def _best_effort_head(
    git_root: str,
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    progress: UpdateProgress = NULL_PROGRESS,
    step_id: str = "",
) -> str | None:
    result = _recorded(
        run,
        ("git", "-C", git_root, "rev-parse", "HEAD"),
        cwd=None,
        label="git rev-parse HEAD",
        commands=commands,
        clock=clock,
        progress=progress,
        step_id=step_id,
    )
    if result.returncode != 0:
        return None
    head = result.stdout.strip()
    return head or None


def _best_effort_diffstat(
    git_root: str,
    old_head: str | None,
    new_head: str | None,
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    progress: UpdateProgress = NULL_PROGRESS,
    step_id: str = "",
) -> RepoDiffStat | None:
    if old_head is None or new_head is None:
        return None
    result = _recorded(
        run,
        ("git", "-C", git_root, "diff", "--numstat", old_head, new_head),
        cwd=None,
        label="git diff --numstat",
        commands=commands,
        clock=clock,
        progress=progress,
        step_id=step_id,
    )
    if result.returncode != 0:
        return None
    return parse_git_numstat(result.stdout)


def _best_effort_commit_log(
    git_root: str,
    old_head: str | None,
    new_head: str | None,
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    progress: UpdateProgress = NULL_PROGRESS,
    step_id: str = "",
    *,
    limit: int,
) -> RepoCommitLog | None:
    if old_head is None or new_head is None:
        return None
    rev_range = f"{old_head}..{new_head}"
    count_result = _recorded(
        run,
        ("git", "-C", git_root, "rev-list", "--count", rev_range),
        cwd=None,
        label="git rev-list --count",
        commands=commands,
        clock=clock,
        progress=progress,
        step_id=step_id,
    )
    if count_result.returncode != 0:
        return None
    try:
        total = int(count_result.stdout.strip() or "0")
    except ValueError:
        return None
    if total < 0:
        return None

    commits: tuple[RepoCommit, ...] = ()
    capped_limit = max(0, limit)
    if total > 0 and capped_limit > 0:
        log_result = _recorded(
            run,
            (
                "git",
                "-C",
                git_root,
                "log",
                f"-n{capped_limit}",
                f"--format={_COMMIT_LOG_FORMAT}",
                rev_range,
            ),
            cwd=None,
            label="git log applied commits",
            commands=commands,
            clock=clock,
            progress=progress,
            step_id=step_id,
        )
        if log_result.returncode != 0:
            return None
        commits = _parse_commit_log(log_result.stdout)[:capped_limit]
    return RepoCommitLog(total=total, commits=commits)


def _parse_commit_log(text: str) -> tuple[RepoCommit, ...]:
    commits: list[RepoCommit] = []
    for raw_record in text.split(_COMMIT_LOG_RECORD_SEP):
        record = raw_record.strip("\r\n")
        if not record or _COMMIT_LOG_UNIT_SEP not in record:
            continue
        short_sha, subject = record.split(_COMMIT_LOG_UNIT_SEP, 1)
        short_sha = short_sha.strip()
        subject = subject.strip()
        if short_sha and subject:
            commits.append(RepoCommit(short_sha=short_sha, subject=subject))
    return tuple(commits)


def _parse_ahead_behind(text: str) -> tuple[int | None, int | None]:
    parts = text.split()
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None
