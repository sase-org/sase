"""Execute environment reconciliation steps for dev updates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from sase.dev_update.command import command_failure, run_recorded_command
from sase.dev_update.models import (
    DevCommandResult,
    DevCommandRunner,
    DevExecutedCommand,
    DevReconcileStep,
    DevRustPrebuildResult,
)
from sase.dev_update.prebuild import parse_outcome_marker
from sase.dev_update.progress import (
    NULL_PROGRESS,
    output_sink_for,
    reconcile_step_id,
    reconcile_step_title,
    record_command,
)
from sase.update_progress import StepSpec, UpdateProgress


def run_reconcile_steps(
    steps: tuple[DevReconcileStep, ...],
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    progress: UpdateProgress = NULL_PROGRESS,
) -> tuple[str | None, DevRustPrebuildResult]:
    """Run planned reconcile steps and return any failure and prebuild result."""
    pending_failure: str | None = None
    rust_prebuild = DevRustPrebuildResult()
    skip_next_rust_build = False
    for index, step in enumerate(steps):
        step_id = reconcile_step_id(index)
        progress.start(step_id, title=reconcile_step_title(step))
        if step.kind == "rust_health_check":
            health_failure = _run_rust_health_check_step(
                step,
                run,
                commands,
                clock,
                prior_failure=pending_failure,
                progress=progress,
                step_id=step_id,
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
                progress=progress,
                step_id=step_id,
            )
            continue

        if skip_next_rust_build and _is_rust_build_step(step):
            skip_next_rust_build = False
            progress.finish(step_id, "skipped", detail="prebuilt artifacts used")
            continue

        if not step.available:
            failure = step.reason or f"{step.label} unavailable"
            if _is_rust_build_step(step) and _has_later_rust_health_check(steps, index):
                pending_failure = _join_failures(pending_failure, failure)
                progress.finish(step_id, "warned", detail=failure)
                continue
            progress.finish(step_id, "failed", detail=failure)
            return failure, rust_prebuild
        result = _recorded(
            run,
            tuple(step.command),
            cwd=step.cwd,
            env=step.env,
            timeout=step.timeout_seconds,
            label=step.label,
            commands=commands,
            clock=clock,
            progress=progress,
            step_id=step_id,
        )
        if result.returncode != 0:
            failure = command_failure(f"{step.label} failed", result)
            if _is_rust_build_step(step) and _has_later_rust_health_check(steps, index):
                pending_failure = _join_failures(pending_failure, failure)
                progress.finish(step_id, "warned", detail=failure)
                continue
            progress.finish(step_id, "failed", detail=failure)
            return failure, rust_prebuild
        progress.finish(step_id, "done")
    return pending_failure, rust_prebuild


def _recorded(
    run: DevCommandRunner,
    argv: tuple[str, ...],
    *,
    cwd: str | None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    label: str,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    progress: UpdateProgress,
    step_id: str,
) -> DevCommandResult:
    """Run a reconcile command, streaming output into *step_id* when active."""
    record_command(progress, step_id, argv, cwd)
    return run_recorded_command(
        run,
        argv,
        cwd=Path(cwd) if cwd else None,
        env=env,
        timeout=timeout,
        on_output=output_sink_for(progress, step_id),
        label=label,
        commands=commands,
        clock=clock,
    )


def _run_rust_prebuild_step(
    step: DevReconcileStep,
    run: DevCommandRunner,
    commands: list[DevExecutedCommand],
    clock: Callable[[], float],
    *,
    progress: UpdateProgress,
    step_id: str,
) -> tuple[DevRustPrebuildResult, bool]:
    if not step.available:
        reason = step.reason or "stamp-missing"
        progress.finish(step_id, "warned", detail=f"cache miss · {reason}")
        return (
            DevRustPrebuildResult(
                attempted=True,
                hit=False,
                reason=reason,
            ),
            False,
        )
    result = _recorded(
        run,
        tuple(step.command),
        cwd=step.cwd,
        env=step.env,
        timeout=step.timeout_seconds,
        label=step.label,
        commands=commands,
        clock=clock,
        progress=progress,
        step_id=step_id,
    )
    parsed = parse_outcome_marker("\n".join((result.stdout, result.stderr)))
    if parsed is None:
        progress.finish(step_id, "warned", detail="cache miss · stamp-missing")
        return (
            DevRustPrebuildResult(
                attempted=True,
                hit=False,
                reason="stamp-missing",
            ),
            False,
        )
    dev_result = parsed.to_dev_result()
    if result.returncode == 0 and parsed.hit:
        progress.finish(step_id, "done", detail="cache hit")
    else:
        progress.finish(step_id, "warned", detail=f"cache miss · {dev_result.reason}")
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
    progress: UpdateProgress,
    step_id: str,
) -> str | None:
    if not step.available:
        failure = step.reason or f"{step.label} unavailable"
        return _finish_health(
            progress, step_id, _join_failures(prior_failure, failure), prior_failure
        )

    health = _recorded(
        run,
        tuple(step.command),
        cwd=step.cwd,
        label=step.label,
        commands=commands,
        clock=clock,
        progress=progress,
        step_id=step_id,
    )
    if health.returncode == 0:
        if prior_failure is None:
            progress.finish(step_id, "done")
            return None
        version = _version_from_health_check(health.stdout)
        suffix = "existing sase-core-rs remains importable"
        if version:
            suffix = f"{suffix} ({version})"
        failure = _join_failures(prior_failure, suffix)
        progress.finish(step_id, "warned", detail=failure)
        return failure

    health_failure = command_failure(f"{step.label} failed", health)
    if not step.repair_command:
        repair_reason = step.repair_reason or "repair command unavailable"
        failure = _join_failures(prior_failure, f"{health_failure}; {repair_reason}")
        return _finish_health(progress, step_id, failure, prior_failure)

    repair_label = step.repair_label or "Restore published sase-core-rs wheel"
    repair_step_id = f"{step_id}:repair"
    progress.declare((StepSpec(repair_step_id, repair_label, parent_id=step_id),))
    progress.start(repair_step_id, title=repair_label)
    repair = _recorded(
        run,
        tuple(step.repair_command),
        cwd=step.repair_cwd,
        label=repair_label,
        commands=commands,
        clock=clock,
        progress=progress,
        step_id=repair_step_id,
    )
    if repair.returncode != 0:
        progress.finish(repair_step_id, "failed")
        repair_failure = command_failure(f"{repair_label} failed", repair)
        failure = _join_failures(prior_failure, f"{health_failure}; {repair_failure}")
        return _finish_health(progress, step_id, failure, prior_failure)

    progress.finish(repair_step_id, "done")
    repaired_health = _recorded(
        run,
        tuple(step.command),
        cwd=step.cwd,
        label=f"{step.label} after repair",
        commands=commands,
        clock=clock,
        progress=progress,
        step_id=step_id,
    )
    if repaired_health.returncode != 0:
        repaired_failure = command_failure(
            f"{step.label} after repair failed", repaired_health
        )
        failure = _join_failures(prior_failure, f"{health_failure}; {repaired_failure}")
        return _finish_health(progress, step_id, failure, prior_failure)

    version = _version_from_health_check(repaired_health.stdout)
    restored = "environment restored to a published sase-core-rs wheel"
    if version:
        restored = f"environment restored to published sase-core-rs {version}"
    failure = _join_failures(prior_failure, f"{health_failure}; {restored}")
    progress.finish(step_id, "warned", detail=failure)
    return failure


def _finish_health(
    progress: UpdateProgress,
    step_id: str,
    failure: str,
    prior_failure: str | None,
) -> str:
    """Finish a failed health step: ``failed`` when it failed on its own."""
    progress.finish(
        step_id, "warned" if prior_failure is not None else "failed", detail=failure
    )
    return failure


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
