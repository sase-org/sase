"""Execute planned editable-install dev updates."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from sase.dev_update.code_swap_lock import code_swap_writer_lock
from sase.dev_update.command import (
    DEV_UPDATE_COMMAND_TIMEOUT_SECONDS as DEV_UPDATE_COMMAND_TIMEOUT_SECONDS,
    command_failure,
    run_dev_update_command as run_dev_update_command,
    run_recorded_command,
)
from sase.dev_update.models import (
    DevCommandRunner,
    DevExecutedCommand,
    DevReconcileStep,
    DevRustPrebuildResult,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
    RepoCommitLog,
    RepoDiffStat,
)
from sase.dev_update.prebuild import parse_outcome_marker
from sase.dev_update.roots import (
    fetch_actionable_roots,
    merge_actionable_roots,
    preflight_actionable_roots,
)

__all__ = [
    "DEV_UPDATE_COMMAND_TIMEOUT_SECONDS",
    "execute_dev_update",
    "run_dev_update_command",
]


def execute_dev_update(
    plan: DevUpdatePlan,
    *,
    run: DevCommandRunner,
    clock: Callable[[], float] = time.monotonic,
) -> DevUpdateResult:
    """Execute ``plan`` with a fully injected subprocess runner."""
    start = clock()
    commands: list[DevExecutedCommand] = []
    rust_prebuild = DevRustPrebuildResult()

    def finish(result: DevUpdateResult) -> DevUpdateResult:
        return replace(result, duration_seconds=max(0.0, clock() - start))

    # Reconcile steps can exist without actionable checkouts (for example a
    # dev install restoring the editable sase-core-rs build over a published
    # wheel), so an empty root set alone does not make the plan a no-op.
    if not plan.actionable_roots and not plan.reconcile_steps:
        return finish(
            DevUpdateResult(
                changed=False,
                outcomes=_skipped_outcomes(plan),
                commands=(),
                rust_prebuild=rust_prebuild,
            )
        )

    fetch_failure = fetch_actionable_roots(plan.actionable_roots, run, commands, clock)
    if fetch_failure is not None:
        return finish(
            _failed_result(
                plan,
                fetch_failure,
                commands,
                changed=False,
                rust_prebuild=rust_prebuild,
            )
        )

    preflight_failure = preflight_actionable_roots(
        plan.actionable_roots, run, commands, clock
    )
    if preflight_failure is not None:
        return finish(
            _failed_result(
                plan,
                preflight_failure,
                commands,
                changed=False,
                rust_prebuild=rust_prebuild,
            )
        )

    with code_swap_writer_lock() as lock:
        if not lock.acquired:
            return finish(
                _failed_result(
                    plan,
                    _code_swap_deferred_reason(lock.blocked_by),
                    commands,
                    changed=False,
                    rust_prebuild=rust_prebuild,
                )
            )

        (
            merge_failure,
            merged_any,
            root_diffstats,
            root_commits,
        ) = merge_actionable_roots(plan.actionable_roots, run, commands, clock)
        if merge_failure is not None:
            return finish(
                _failed_result(
                    plan,
                    merge_failure,
                    commands,
                    changed=merged_any,
                    rust_prebuild=rust_prebuild,
                )
            )

        reconcile_failure, rust_prebuild = _run_reconcile_steps(
            plan.reconcile_steps, run, commands, clock
        )
        if reconcile_failure is not None:
            return finish(
                _failed_result(
                    plan,
                    reconcile_failure,
                    commands,
                    changed=merged_any or bool(commands),
                    rust_prebuild=rust_prebuild,
                )
            )

        return finish(
            DevUpdateResult(
                changed=True,
                outcomes=_success_outcomes(plan, root_diffstats, root_commits),
                commands=tuple(commands),
                rust_prebuild=rust_prebuild,
            )
        )


def _code_swap_deferred_reason(blocked_by: str | None) -> str:
    detail = blocked_by or "a running sase process"
    return (
        f"deferred: {detail} is running against this checkout; "
        "re-run `sase update` when it finishes"
    )


def _run_reconcile_steps(
    steps: tuple[DevReconcileStep, ...],
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
) -> tuple[str | None, DevRustPrebuildResult]:
    pending_failure: str | None = None
    rust_prebuild = DevRustPrebuildResult()
    skip_next_rust_build = False
    for index, step in enumerate(steps):
        if step.kind == "rust_health_check":
            health_failure = _run_rust_health_check_step(
                step,
                run,
                commands,
                clock,
                prior_failure=pending_failure,
            )
            if health_failure is not None:
                return health_failure, rust_prebuild
            continue

        if step.kind == "rust_prebuild_install":
            rust_prebuild, skip_next_rust_build = _run_rust_prebuild_step(
                step,
                run,
                commands,
                clock,
            )
            continue

        if skip_next_rust_build and _is_rust_build_step(step):
            skip_next_rust_build = False
            continue

        if not step.available:
            failure = step.reason or f"{step.label} unavailable"
            if _is_rust_build_step(step) and _has_later_rust_health_check(steps, index):
                pending_failure = _join_failures(pending_failure, failure)
                continue
            return failure, rust_prebuild
        result = run_recorded_command(
            run,
            step.command,
            cwd=Path(step.cwd) if step.cwd else None,
            env=step.env,
            label=step.label,
            commands=commands,
            clock=clock,
        )
        if result.returncode != 0:
            failure = command_failure(f"{step.label} failed", result)
            if _is_rust_build_step(step) and _has_later_rust_health_check(steps, index):
                pending_failure = _join_failures(pending_failure, failure)
                continue
            return failure, rust_prebuild
    return pending_failure, rust_prebuild


def _run_rust_prebuild_step(
    step: DevReconcileStep,
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
) -> tuple[DevRustPrebuildResult, bool]:
    if not step.available:
        return (
            DevRustPrebuildResult(
                attempted=True,
                hit=False,
                reason=step.reason or "stamp-missing",
            ),
            False,
        )
    result = run_recorded_command(
        run,
        step.command,
        cwd=Path(step.cwd) if step.cwd else None,
        env=step.env,
        label=step.label,
        commands=commands,
        clock=clock,
    )
    parsed = parse_outcome_marker("\n".join((result.stdout, result.stderr)))
    if parsed is None:
        return (
            DevRustPrebuildResult(
                attempted=True,
                hit=False,
                reason="stamp-missing",
            ),
            False,
        )
    dev_result = parsed.to_dev_result()
    return dev_result, result.returncode == 0 and parsed.hit


def _is_rust_build_step(step: DevReconcileStep) -> bool:
    return step.kind in {"rust_dev_install", "rust_install_uv_tool"}


def _has_later_rust_health_check(
    steps: tuple[DevReconcileStep, ...], current_index: int
) -> bool:
    return any(step.kind == "rust_health_check" for step in steps[current_index + 1 :])


def _run_rust_health_check_step(
    step: DevReconcileStep,
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    *,
    prior_failure: str | None,
) -> str | None:
    if not step.available:
        failure = step.reason or f"{step.label} unavailable"
        return _join_failures(prior_failure, failure)

    health = run_recorded_command(
        run,
        step.command,
        cwd=Path(step.cwd) if step.cwd else None,
        label=step.label,
        commands=commands,
        clock=clock,
    )
    if health.returncode == 0:
        if prior_failure is None:
            return None
        version = _version_from_health_check(health.stdout)
        suffix = "existing sase-core-rs remains importable"
        if version:
            suffix = f"{suffix} ({version})"
        return _join_failures(prior_failure, suffix)

    health_failure = command_failure(f"{step.label} failed", health)
    if not step.repair_command:
        repair_reason = step.repair_reason or "repair command unavailable"
        return _join_failures(prior_failure, f"{health_failure}; {repair_reason}")

    repair_label = step.repair_label or "Restore published sase-core-rs wheel"
    repair = run_recorded_command(
        run,
        step.repair_command,
        cwd=Path(step.repair_cwd) if step.repair_cwd else None,
        label=repair_label,
        commands=commands,
        clock=clock,
    )
    if repair.returncode != 0:
        repair_failure = command_failure(f"{repair_label} failed", repair)
        return _join_failures(prior_failure, f"{health_failure}; {repair_failure}")

    repaired_health = run_recorded_command(
        run,
        step.command,
        cwd=Path(step.cwd) if step.cwd else None,
        label=f"{step.label} after repair",
        commands=commands,
        clock=clock,
    )
    if repaired_health.returncode != 0:
        repaired_failure = command_failure(
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


def _success_outcomes(
    plan: DevUpdatePlan,
    root_diffstats: dict[str, RepoDiffStat | None],
    root_commits: dict[str, RepoCommitLog | None],
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
            commits=root_commits.get(pkg.git_root) if pkg.git_root else None,
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
    rust_prebuild: DevRustPrebuildResult | None = None,
) -> DevUpdateResult:
    rust_prebuild = rust_prebuild or DevRustPrebuildResult()
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
        rust_prebuild=rust_prebuild,
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
