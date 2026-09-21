"""Execute planned install-mode switches."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from sase.dev_update.models import DevCommandResult, OutputSink
from sase.dev_update.execute import run_dev_update_command
from sase.dev_update.progress import (
    NULL_PROGRESS,
    output_sink_for,
    record_command,
    switch_step_id,
)
from sase.mode_switch.models import (
    ModeSwitchCommand,
    ModeSwitchOutcome,
    ModeSwitchResult,
    SwitchPlan,
)
from sase.mode_switch.plan import backup_payload
from sase.update_progress import StepSpec, UpdateProgress
from sase.uv_tool.errors import UvCommandFailedError, UvToolError
from sase.uv_tool.runner import UvChangeSet, run_uv


class RunUvFn(Protocol):
    """Run a ``uv`` argv and return its parsed change set.

    ``on_output`` streams sanitized output lines when a progress session
    is active; ``None`` keeps the legacy captured behavior.
    """

    def __call__(
        self, argv: list[str], *, on_output: OutputSink | None = None
    ) -> UvChangeSet: ...


RunCommandFn = Callable[..., DevCommandResult]


def execute_mode_switch(
    plan: SwitchPlan,
    *,
    run_uv_fn: RunUvFn = run_uv,
    run_command_fn: RunCommandFn = run_dev_update_command,
    progress: UpdateProgress = NULL_PROGRESS,
) -> ModeSwitchResult:
    """Run the commands in *plan* and return a structured result."""
    if not plan.changed:
        return ModeSwitchResult(
            plan=plan,
            changed=False,
            outcomes=(),
            commands=(),
        )

    _write_backup(plan)
    available = [
        (index, command)
        for index, command in enumerate(plan.commands)
        if command.available
    ]
    progress.declare(
        tuple(
            StepSpec(switch_step_id(index), command.label)
            for index, command in available
        )
    )
    executed: list[ModeSwitchCommand] = []
    for index, command in available:
        step_id = switch_step_id(index)
        progress.start(step_id, title=command.label)
        if command.kind == "uv_tool_install":
            try:
                _run_uv(run_uv_fn, command, progress=progress, step_id=step_id)
            except UvToolError as exc:
                progress.finish(step_id, "failed", detail=str(exc))
                raise _with_restore_hint(exc, plan) from exc
        else:
            _run_command(
                command,
                run_command_fn=run_command_fn,
                plan=plan,
                progress=progress,
                step_id=step_id,
            )
        progress.finish(step_id, "done")
        executed.append(command)

    outcomes = tuple(
        ModeSwitchOutcome(
            name=package.name,
            role=package.role,
            status="stayed-managed"
            if package.repo_action == "stays-managed"
            else "switched",
            old_version=package.current_version,
            new_version=package.target_version,
            source=package.source,
        )
        for package in plan.packages
    )
    return ModeSwitchResult(
        plan=plan,
        changed=True,
        outcomes=outcomes,
        commands=tuple(executed),
    )


def _run_uv(
    run_uv_fn: RunUvFn,
    command: ModeSwitchCommand,
    *,
    progress: UpdateProgress,
    step_id: str,
) -> UvChangeSet:
    """Run a uv switch command, streaming into *step_id* when active."""
    record_command(progress, step_id, command.command, None)
    sink = output_sink_for(progress, step_id)
    if sink is None:
        return run_uv_fn(list(command.command))
    return run_uv_fn(list(command.command), on_output=sink)


def _run_command(
    command: ModeSwitchCommand,
    *,
    run_command_fn: RunCommandFn,
    plan: SwitchPlan,
    progress: UpdateProgress = NULL_PROGRESS,
    step_id: str = "",
) -> None:
    cwd = Path(command.cwd) if command.cwd else None
    created_path: Path | None = None
    if command.kind == "git_clone" and len(command.command) >= 4:
        created_path = Path(command.command[-1])
    record_command(
        progress, step_id, command.command, str(cwd) if cwd is not None else None
    )
    sink = output_sink_for(progress, step_id)
    if sink is None:
        result = run_command_fn(command.command, cwd=cwd)
    else:
        result = run_command_fn(command.command, cwd=cwd, on_output=sink)
    if result.returncode == 0:
        return
    if command.kind == "git_clone" and created_path is not None:
        _cleanup_failed_clone(created_path)
    detail = (
        result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    )
    failure = f"{command.label} failed: {detail}"
    progress.finish(step_id, "failed", detail=failure)
    raise _with_restore_hint(UvToolError(failure), plan)


def _write_backup(plan: SwitchPlan) -> None:
    if not plan.backup_path:
        return
    path = Path(plan.backup_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(backup_payload(plan), indent=2), encoding="utf-8")
    except OSError:
        pass


def _cleanup_failed_clone(path: Path) -> None:
    try:
        if path.exists():
            shutil.rmtree(path)
    except OSError:
        pass


def _with_restore_hint(error: UvToolError, plan: SwitchPlan) -> UvToolError:
    command = " ".join(plan.restore_command)
    hint = f"{error}\nRestore command: {command}" if command else str(error)
    return UvCommandFailedError(
        argv=["sase", "update", "--to", plan.target_mode], stderr=hint
    )
