"""Execute planned editable-install dev updates."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from sase.dev_update.diffstat import parse_git_numstat
from sase.dev_update.models import (
    DevCommandResult,
    DevCommandRunner,
    DevExecutedCommand,
    DevReconcileStep,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
    DevUpdateRootPlan,
    RepoDiffStat,
)
from sase.git_lock_retry import run_with_git_lock_retry
from sase.version._git import GitUpstreamStatus, fetch_git_upstream, merge_git_ff_only
from sase.workspace_provider.utils import non_interactive_git_env

DEV_UPDATE_COMMAND_TIMEOUT_SECONDS = 300.0


def execute_dev_update(
    plan: DevUpdatePlan, *, run: DevCommandRunner
) -> DevUpdateResult:
    """Execute ``plan`` with a fully injected subprocess runner."""
    commands: list[DevExecutedCommand] = []
    # Reconcile steps can exist without actionable checkouts (for example a
    # dev install restoring the editable sase-core-rs build over a published
    # wheel), so an empty root set alone does not make the plan a no-op.
    if not plan.actionable_roots and not plan.reconcile_steps:
        return DevUpdateResult(
            changed=False,
            outcomes=_skipped_outcomes(plan),
            commands=(),
        )

    fetch_failure = _fetch_actionable_roots(plan.actionable_roots, run, commands)
    if fetch_failure is not None:
        return _failed_result(plan, fetch_failure, commands, changed=False)

    preflight_failure = _preflight_actionable_roots(
        plan.actionable_roots, run, commands
    )
    if preflight_failure is not None:
        return _failed_result(plan, preflight_failure, commands, changed=False)

    merge_failure, merged_any, root_diffstats = _merge_actionable_roots(
        plan.actionable_roots, run, commands
    )
    if merge_failure is not None:
        return _failed_result(plan, merge_failure, commands, changed=merged_any)

    reconcile_failure = _run_reconcile_steps(plan.reconcile_steps, run, commands)
    if reconcile_failure is not None:
        return _failed_result(
            plan, reconcile_failure, commands, changed=merged_any or bool(commands)
        )

    return DevUpdateResult(
        changed=True,
        outcomes=_success_outcomes(plan, root_diffstats),
        commands=tuple(commands),
    )


def run_dev_update_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = DEV_UPDATE_COMMAND_TIMEOUT_SECONDS,
) -> DevCommandResult:
    """Default command runner for callers that want real subprocess execution."""
    command = list(argv)
    git_env, git_stdin = _non_interactive_git_subprocess_options(command)

    def attempt() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=git_env,
            stdin=git_stdin,
        )

    try:
        if command and command[0] == "git":
            completed, _outcome = run_with_git_lock_retry(
                attempt,
                cwd=_git_command_cwd(command, cwd),
            )
        else:
            completed = attempt()
    except FileNotFoundError as exc:
        return DevCommandResult(returncode=127, stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return DevCommandResult(
            returncode=124,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr="command timed out",
        )
    except OSError as exc:
        return DevCommandResult(returncode=1, stderr=str(exc))
    return DevCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _fetch_actionable_roots(
    roots: tuple[DevUpdateRootPlan, ...],
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
) -> str | None:
    for root in roots:
        try:
            fetch_git_upstream(
                _root_status_for_fetch(root),
                run_git_fn=_git_text_runner(run, commands, label="git fetch"),
            )
        except _GitCommandFailure as exc:
            return str(exc)
    return None


def _preflight_actionable_roots(
    roots: tuple[DevUpdateRootPlan, ...],
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
) -> str | None:
    for root in roots:
        dirty = _run(
            run,
            ("git", "-C", root.git_root, "status", "--porcelain"),
            cwd=None,
            label="git status",
            commands=commands,
        )
        if dirty.returncode != 0:
            return _command_failure("git status failed", dirty)
        if dirty.stdout.strip():
            return f"{root.git_root}: checkout has local changes"

        if root.upstream is None:
            return f"{root.git_root}: checkout has no upstream"
        rev_list = _run(
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
        )
        if rev_list.returncode != 0:
            return _command_failure("git ancestry preflight failed", rev_list)
        ahead, behind = _parse_ahead_behind(rev_list.stdout)
        if ahead is None or behind is None:
            return f"{root.git_root}: upstream ancestry unavailable"
        if ahead > 0 and behind > 0:
            return f"{root.git_root}: checkout has diverged from upstream"
        if ahead > 0:
            return f"{root.git_root}: checkout is ahead of upstream"
        if behind <= 0:
            return f"{root.git_root}: already current"
    return None


def _merge_actionable_roots(
    roots: tuple[DevUpdateRootPlan, ...],
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
) -> tuple[str | None, bool, dict[str, RepoDiffStat | None]]:
    merged_any = False
    root_diffstats: dict[str, RepoDiffStat | None] = {}
    for root in roots:
        if root.upstream is None:
            return (
                f"{root.git_root}: checkout has no upstream",
                merged_any,
                root_diffstats,
            )
        old_head = _best_effort_head(root.git_root, run, commands)
        try:
            merge_git_ff_only(
                Path(root.git_root),
                root.upstream,
                run_git_fn=_git_text_runner(run, commands, label="git merge --ff-only"),
            )
        except _GitCommandFailure as exc:
            return str(exc), merged_any, root_diffstats
        merged_any = True
        new_head = _best_effort_head(root.git_root, run, commands)
        root_diffstats[root.git_root] = _best_effort_diffstat(
            root.git_root,
            old_head,
            new_head,
            run,
            commands,
        )
    return None, merged_any, root_diffstats


def _run_reconcile_steps(
    steps: tuple[DevReconcileStep, ...],
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
) -> str | None:
    pending_failure: str | None = None
    for index, step in enumerate(steps):
        if step.kind == "rust_health_check":
            health_failure = _run_rust_health_check_step(
                step,
                run,
                commands,
                prior_failure=pending_failure,
            )
            if health_failure is not None:
                return health_failure
            continue

        if not step.available:
            failure = step.reason or f"{step.label} unavailable"
            if step.kind == "rust_install_uv_tool" and _has_later_rust_health_check(
                steps, index
            ):
                pending_failure = _join_failures(pending_failure, failure)
                continue
            return failure
        result = _run(
            run,
            step.command,
            cwd=Path(step.cwd) if step.cwd else None,
            label=step.label,
            commands=commands,
        )
        if result.returncode != 0:
            failure = _command_failure(f"{step.label} failed", result)
            if step.kind == "rust_install_uv_tool" and _has_later_rust_health_check(
                steps, index
            ):
                pending_failure = _join_failures(pending_failure, failure)
                continue
            return failure
    return pending_failure


def _has_later_rust_health_check(
    steps: tuple[DevReconcileStep, ...], current_index: int
) -> bool:
    return any(step.kind == "rust_health_check" for step in steps[current_index + 1 :])


def _run_rust_health_check_step(
    step: DevReconcileStep,
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    *,
    prior_failure: str | None,
) -> str | None:
    if not step.available:
        failure = step.reason or f"{step.label} unavailable"
        return _join_failures(prior_failure, failure)

    health = _run(
        run,
        step.command,
        cwd=Path(step.cwd) if step.cwd else None,
        label=step.label,
        commands=commands,
    )
    if health.returncode == 0:
        if prior_failure is None:
            return None
        version = _version_from_health_check(health.stdout)
        suffix = "existing sase-core-rs remains importable"
        if version:
            suffix = f"{suffix} ({version})"
        return _join_failures(prior_failure, suffix)

    health_failure = _command_failure(f"{step.label} failed", health)
    if not step.repair_command:
        repair_reason = step.repair_reason or "repair command unavailable"
        return _join_failures(prior_failure, f"{health_failure}; {repair_reason}")

    repair_label = step.repair_label or "Restore published sase-core-rs wheel"
    repair = _run(
        run,
        step.repair_command,
        cwd=Path(step.repair_cwd) if step.repair_cwd else None,
        label=repair_label,
        commands=commands,
    )
    if repair.returncode != 0:
        repair_failure = _command_failure(f"{repair_label} failed", repair)
        return _join_failures(prior_failure, f"{health_failure}; {repair_failure}")

    repaired_health = _run(
        run,
        step.command,
        cwd=Path(step.cwd) if step.cwd else None,
        label=f"{step.label} after repair",
        commands=commands,
    )
    if repaired_health.returncode != 0:
        repaired_failure = _command_failure(
            f"{step.label} after repair failed", repaired_health
        )
        return _join_failures(prior_failure, f"{health_failure}; {repaired_failure}")

    version = _version_from_health_check(repaired_health.stdout)
    restored = "environment restored to a published sase-core-rs wheel"
    if version:
        restored = f"environment restored to published sase-core-rs {version}"
    return _join_failures(prior_failure, f"{health_failure}; {restored}")


def _join_failures(first: str | None, second: str) -> str:
    if not first:
        return second
    return f"{first}; {second}"


def _version_from_health_check(stdout: str) -> str | None:
    for line in stdout.splitlines():
        candidate = line.strip()
        if candidate:
            return candidate
    return None


def _run(
    run: DevCommandRunner,
    argv: Sequence[str],
    *,
    cwd: Path | None,
    label: str,
    commands: list[DevExecutedCommand],
) -> DevCommandResult:
    result = run(argv, cwd=cwd)
    commands.append(
        DevExecutedCommand(
            label=label,
            command=tuple(argv),
            cwd=str(cwd) if cwd else None,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    )
    return result


def _non_interactive_git_subprocess_options(
    argv: Sequence[str],
) -> tuple[dict[str, str] | None, int | None]:
    if not argv or argv[0] != "git":
        return None, None
    return non_interactive_git_env(), subprocess.DEVNULL


def _git_command_cwd(argv: Sequence[str], cwd: Path | None) -> Path:
    try:
        index = argv.index("-C")
        configured = Path(argv[index + 1])
    except (ValueError, IndexError):
        return Path.cwd() if cwd is None else cwd
    if configured.is_absolute() or cwd is None:
        return configured
    return cwd / configured


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
) -> Callable[..., str]:
    def runner(root: Path, *args: str, **_kwargs: object) -> str:
        result = _run(
            run,
            ("git", "-C", str(root), *args),
            cwd=None,
            label=label,
            commands=commands,
        )
        if result.returncode != 0:
            raise _GitCommandFailure(_command_failure(f"{label} failed", result))
        return result.stdout.strip()

    return runner


def _best_effort_head(
    git_root: str,
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
) -> str | None:
    result = _run(
        run,
        ("git", "-C", git_root, "rev-parse", "HEAD"),
        cwd=None,
        label="git rev-parse HEAD",
        commands=commands,
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
) -> RepoDiffStat | None:
    if old_head is None or new_head is None:
        return None
    result = _run(
        run,
        ("git", "-C", git_root, "diff", "--numstat", old_head, new_head),
        cwd=None,
        label="git diff --numstat",
        commands=commands,
    )
    if result.returncode != 0:
        return None
    return parse_git_numstat(result.stdout)


def _success_outcomes(
    plan: DevUpdatePlan,
    root_diffstats: dict[str, RepoDiffStat | None],
) -> tuple[DevUpdateOutcome, ...]:
    outcomes = [
        DevUpdateOutcome(
            record=pkg.record,
            status="updated",
            reason=pkg.reason,
            old_version=pkg.current_version,
            new_version=pkg.latest_version,
            git_root=pkg.git_root,
            diffstat=root_diffstats.get(pkg.git_root) if pkg.git_root else None,
        )
        for pkg in plan.actionable
    ]
    outcomes.extend(_skipped_outcomes(plan))
    return tuple(outcomes)


def _skipped_outcomes(plan: DevUpdatePlan) -> tuple[DevUpdateOutcome, ...]:
    return tuple(_skipped_outcome(pkg) for pkg in plan.skipped)


def _failed_result(
    plan: DevUpdatePlan,
    reason: str,
    commands: list[DevExecutedCommand],
    *,
    changed: bool,
) -> DevUpdateResult:
    outcomes = [
        DevUpdateOutcome(
            record=pkg.record,
            status="failed",
            reason=reason,
            old_version=pkg.current_version,
            new_version=pkg.latest_version,
            git_root=pkg.git_root,
        )
        for pkg in plan.actionable
    ]
    outcomes.extend(_skipped_outcomes(plan))
    return DevUpdateResult(
        changed=changed,
        outcomes=tuple(outcomes),
        commands=tuple(commands),
    )


def _skipped_outcome(pkg: DevUpdatePackagePlan) -> DevUpdateOutcome:
    return DevUpdateOutcome(
        record=pkg.record,
        status="skipped",
        reason=pkg.reason,
        old_version=pkg.current_version,
        new_version=pkg.latest_version,
        git_root=pkg.git_root,
    )


def _command_failure(prefix: str, result: DevCommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip()
    if detail:
        return f"{prefix}: {detail}"
    return f"{prefix}: exit {result.returncode}"


def _parse_ahead_behind(text: str) -> tuple[int | None, int | None]:
    parts = text.split()
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None
