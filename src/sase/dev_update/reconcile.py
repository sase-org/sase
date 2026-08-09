"""Execute environment reconciliation steps for dev updates."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.dev_update.command import command_failure, run_recorded_command
from sase.dev_update.models import (
    DevCommandRunner,
    DevExecutedCommand,
    DevReconcileStep,
    DevRustPrebuildResult,
)
from sase.dev_update.prebuild import parse_outcome_marker


def run_reconcile_steps(
    steps: tuple[DevReconcileStep, ...],
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
) -> tuple[str | None, DevRustPrebuildResult]:
    """Run planned reconcile steps and return any failure and prebuild result."""
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
