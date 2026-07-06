from __future__ import annotations

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


def _clone_switch_plan(tmp_path: Path, checkout: Path | None = None) -> SwitchPlan:
    checkout = checkout or (tmp_path / "dev" / "sase-org" / "sase")
    return SwitchPlan(
        current_mode="managed",
        target_mode="dev",
        dev_root=str(tmp_path / "dev"),
        packages=(
            SwitchPackagePlan(
                name="sase",
                role="host",
                current_version="0.8.0",
                target_version="dev @ main (will clone)",
                source="clone sase-org/sase",
                repo_action="clone",
                checkout_path=str(checkout),
                repo_url="git@github.com:sase-org/sase.git",
            ),
        ),
        commands=(
            ModeSwitchCommand(
                kind="git_clone",
                label="Clone sase",
                command=("git", "clone", "git@example.invalid:sase.git", str(checkout)),
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
        argv: tuple[str, ...], *, cwd: Path | None = None
    ) -> DevCommandResult:
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


def test_execute_mode_switch_failed_merge_includes_restore_hint(
    tmp_path: Path,
) -> None:
    plan = _switch_plan(tmp_path)
    calls: list[tuple[str, ...]] = []

    def run_command(
        argv: tuple[str, ...], *, cwd: Path | None = None
    ) -> DevCommandResult:
        del cwd
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


def test_execute_mode_switch_failed_clone_preserves_preexisting_target(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "dev" / "sase-org" / "sase"
    checkout.mkdir(parents=True)
    sentinel = checkout / "keep.txt"
    sentinel.write_text("existing checkout data", encoding="utf-8")
    plan = _clone_switch_plan(tmp_path, checkout)

    def run_command(
        argv: tuple[str, ...], *, cwd: Path | None = None
    ) -> DevCommandResult:
        del argv, cwd
        return DevCommandResult(
            returncode=128,
            stderr=(
                f"fatal: destination path '{checkout}' already exists and is not "
                "an empty directory."
            ),
        )

    with pytest.raises(UvCommandFailedError):
        execute_mode_switch(plan, run_command_fn=run_command)

    assert sentinel.read_text(encoding="utf-8") == "existing checkout data"


def test_execute_mode_switch_failed_clone_existing_destination_race_is_not_deleted(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "dev" / "sase-org" / "sase"
    plan = _clone_switch_plan(tmp_path, checkout)

    def run_command(
        argv: tuple[str, ...], *, cwd: Path | None = None
    ) -> DevCommandResult:
        del argv, cwd
        checkout.mkdir(parents=True)
        (checkout / "created-by-other-process.txt").write_text(
            "do not delete", encoding="utf-8"
        )
        return DevCommandResult(
            returncode=128,
            stderr=(
                f"fatal: destination path '{checkout}' already exists and is not "
                "an empty directory."
            ),
        )

    with pytest.raises(UvCommandFailedError):
        execute_mode_switch(plan, run_command_fn=run_command)

    assert (checkout / "created-by-other-process.txt").read_text(
        encoding="utf-8"
    ) == "do not delete"
