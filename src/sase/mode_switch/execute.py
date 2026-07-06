"""Execute planned install-mode switches."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from sase.dev_update.models import DevCommandResult
from sase.dev_update.execute import run_dev_update_command
from sase.mode_switch.models import (
    ModeSwitchCommand,
    ModeSwitchOutcome,
    ModeSwitchResult,
    SwitchPlan,
)
from sase.mode_switch.plan import backup_payload
from sase.uv_tool.errors import UvCommandFailedError, UvToolError
from sase.uv_tool.runner import UvChangeSet, run_uv

RunUvFn = Callable[[list[str]], UvChangeSet]
RunCommandFn = Callable[..., DevCommandResult]


def execute_mode_switch(
    plan: SwitchPlan,
    *,
    run_uv_fn: RunUvFn = run_uv,
    run_command_fn: RunCommandFn = run_dev_update_command,
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
    executed: list[ModeSwitchCommand] = []
    for command in plan.commands:
        if not command.available:
            continue
        if command.kind == "uv_tool_install":
            try:
                run_uv_fn(list(command.command))
            except UvToolError as exc:
                raise _with_restore_hint(exc, plan) from exc
        else:
            _run_command(command, run_command_fn=run_command_fn, plan=plan)
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


def _run_command(
    command: ModeSwitchCommand,
    *,
    run_command_fn: RunCommandFn,
    plan: SwitchPlan,
) -> None:
    cwd = Path(command.cwd) if command.cwd else None
    created_path: Path | None = None
    clone_target_existed = False
    if command.kind == "git_clone" and len(command.command) >= 4:
        created_path = Path(command.command[-1])
        clone_target_existed = created_path.exists()
    result = run_command_fn(command.command, cwd=cwd)
    if result.returncode == 0:
        return
    if (
        command.kind == "git_clone"
        and created_path is not None
        and not clone_target_existed
        and not _clone_failed_because_target_exists(result)
    ):
        _cleanup_failed_clone(created_path)
    detail = (
        result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    )
    raise _with_restore_hint(UvToolError(f"{command.label} failed: {detail}"), plan)


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


def _clone_failed_because_target_exists(result: DevCommandResult) -> bool:
    text = f"{result.stderr}\n{result.stdout}".casefold()
    return (
        "destination path" in text
        and "already exists" in text
        and "not an empty directory" in text
    )


def _with_restore_hint(error: UvToolError, plan: SwitchPlan) -> UvToolError:
    command = " ".join(plan.restore_command)
    hint = f"{error}\nRestore command: {command}" if command else str(error)
    return UvCommandFailedError(
        argv=["sase", "update", "--to", plan.target_mode], stderr=hint
    )
