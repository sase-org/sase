from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from sase.dev_update.models import DevCommandResult
from sase.mode_switch.execute import execute_mode_switch
from sase.mode_switch.models import ModeSwitchCommand, SwitchPackagePlan, SwitchPlan
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet


def _switch_plan(tmp_path: Path) -> SwitchPlan:
    checkout = tmp_path / "dev" / "sase-org" / "sase"
    return SwitchPlan(
        current_mode="managed",
        target_mode="dev",
        dev_root=str(tmp_path / "dev"),
        packages=(
            SwitchPackagePlan(
                name="sase",
                role="host",
                current_version="0.8.0",
                target_version="0.8.1+1.gabcdef123",
                source=f"reuse {checkout}",
                repo_action="reuse",
                checkout_path=str(checkout),
                repo_url="git@github.com:sase-org/sase.git",
            ),
        ),
        commands=(
            ModeSwitchCommand(
                kind="git_fetch",
                label="Fetch sase",
                command=("git", "fetch", "--quiet", "--tags", "--force"),
                cwd=str(checkout),
            ),
            ModeSwitchCommand(
                kind="git_merge_ff",
                label="Fast-forward sase",
                command=("git", "merge", "--ff-only", "origin/master"),
                cwd=str(checkout),
            ),
            ModeSwitchCommand(
                kind="uv_tool_install",
                label="Install editable package set",
                command=("uv", "tool", "install", "--editable", str(checkout)),
            ),
        ),
        restore_command=("uv", "tool", "install", "sase"),
        backup_path=str(tmp_path / "backup.json"),
    )


def test_execute_mode_switch_runs_merge_before_uv_install(tmp_path: Path) -> None:
    plan = _switch_plan(tmp_path)
    calls: list[tuple[str, tuple[str, ...], Path | None]] = []

    def run_command(
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> DevCommandResult:
        del env, timeout
        calls.append(("cmd", tuple(argv), cwd))
        return DevCommandResult(returncode=0)

    def run_uv(argv: list[str]) -> UvChangeSet:
        calls.append(("uv", tuple(argv), None))
        return UvChangeSet()

    result = execute_mode_switch(
        plan,
        run_uv_fn=run_uv,
        run_command_fn=run_command,
    )

    checkout = Path(plan.packages[0].checkout_path or "")
    assert calls == [
        ("cmd", plan.commands[0].command, checkout),
        ("cmd", plan.commands[1].command, checkout),
        ("uv", plan.commands[2].command, None),
    ]
    assert [command.kind for command in result.commands] == [
        "git_fetch",
        "git_merge_ff",
        "uv_tool_install",
    ]


def test_execute_mode_switch_forwards_rust_env_and_timeout(
    tmp_path: Path,
) -> None:
    plan = _switch_plan(tmp_path)
    rust_command = ModeSwitchCommand(
        kind="rust_dev_install",
        label="Rebuild Rust dev artifacts into the uv-tool venv",
        command=("just", "rust-dev-install-uv-tool"),
        cwd=str(tmp_path / "dev"),
        env={"SASE_RUST_DEV_PROFILE": "dev-update"},
        timeout_seconds=3600.0,
    )
    plan = SwitchPlan(
        current_mode=plan.current_mode,
        target_mode=plan.target_mode,
        dev_root=plan.dev_root,
        packages=plan.packages,
        commands=(*plan.commands, rust_command),
        warnings=plan.warnings,
        restore_command=plan.restore_command,
        backup_path=plan.backup_path,
    )
    seen: dict[str, object] = {}

    def run_command(
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> DevCommandResult:
        del cwd
        if tuple(argv)[:2] == ("just", "rust-dev-install-uv-tool"):
            seen["env"] = env
            seen["timeout"] = timeout
        return DevCommandResult(returncode=0)

    def run_uv(argv: list[str]) -> UvChangeSet:
        return UvChangeSet()

    execute_mode_switch(
        plan,
        run_uv_fn=run_uv,
        run_command_fn=run_command,
    )

    assert seen == {
        "env": {"SASE_RUST_DEV_PROFILE": "dev-update"},
        "timeout": 3600.0,
    }


def test_execute_mode_switch_failed_merge_includes_restore_hint(
    tmp_path: Path,
) -> None:
    plan = _switch_plan(tmp_path)
    calls: list[tuple[str, ...]] = []

    def run_command(
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> DevCommandResult:
        del cwd, env, timeout
        calls.append(tuple(argv))
        if argv[:3] == ("git", "merge", "--ff-only"):
            return DevCommandResult(returncode=1, stderr="not a fast-forward")
        return DevCommandResult(returncode=0)

    def run_uv(_argv: list[str]) -> UvChangeSet:
        raise AssertionError("uv must not run after a failed merge")

    with pytest.raises(UvCommandFailedError) as excinfo:
        execute_mode_switch(
            plan,
            run_uv_fn=run_uv,
            run_command_fn=run_command,
        )

    assert calls == [plan.commands[0].command, plan.commands[1].command]
    text = str(excinfo.value)
    assert "Fast-forward sase failed: not a fast-forward" in text
    assert excinfo.value.stderr is not None
    assert "Restore command: uv tool install sase" in excinfo.value.stderr
