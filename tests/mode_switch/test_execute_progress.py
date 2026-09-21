"""Progress-event tests for mode-switch execution."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from sase.dev_update.models import DevCommandResult, OutputSink
from sase.mode_switch.execute import execute_mode_switch
from sase.mode_switch.models import ModeSwitchCommand, SwitchPackagePlan, SwitchPlan
from sase.update_progress import StepSpec, StepStatus
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet


class RecordingProgress:
    """In-memory progress sink recording every event in order."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def declare(self, specs: Sequence[StepSpec]) -> None:
        self.events.append(
            ("declare", tuple((spec.id, spec.title, spec.parent_id) for spec in specs))
        )

    def start(
        self, id: str, *, title: str | None = None, detail: str | None = None
    ) -> None:
        self.events.append(("start", id, title, detail))

    def output(self, id: str, stream: str, line: str) -> None:
        self.events.append(("output", id, stream, line))

    def finish(self, id: str, status: StepStatus, *, detail: str | None = None) -> None:
        self.events.append(("finish", id, status, detail))

    def command(self, id: str, argv: Sequence[str], cwd: str | None = None) -> None:
        self.events.append(("command", id, tuple(argv), cwd))

    def finalize(self, status_for_pending: StepStatus = "skipped") -> None:
        self.events.append(("finalize", status_for_pending))

    def output_sink(self, id: str) -> OutputSink:
        def sink(stream: str, line: str) -> None:
            self.output(id, stream, line)

        return sink


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


def test_execute_mode_switch_streams_each_command_into_its_row(
    tmp_path: Path,
) -> None:
    plan = _switch_plan(tmp_path)
    progress = RecordingProgress()
    checkout = str(plan.packages[0].checkout_path)

    def run_command(
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        on_output: OutputSink | None = None,
    ) -> DevCommandResult:
        assert on_output is not None
        on_output("stderr", f"ran {' '.join(argv[1:3])}")
        return DevCommandResult(returncode=0)

    def run_uv(argv: list[str], *, on_output: OutputSink | None = None) -> UvChangeSet:
        assert on_output is not None
        on_output("stderr", "+ sase==0.8.1")
        return UvChangeSet()

    result = execute_mode_switch(
        plan, run_uv_fn=run_uv, run_command_fn=run_command, progress=progress
    )

    assert result.changed is True
    assert progress.events[0] == (
        "declare",
        (
            ("switch:0", "Fetch sase", None),
            ("switch:1", "Fast-forward sase", None),
            ("switch:2", "Install editable package set", None),
        ),
    )
    assert ("start", "switch:0", "Fetch sase", None) in progress.events
    assert ("finish", "switch:0", "done", None) in progress.events
    assert ("finish", "switch:1", "done", None) in progress.events
    assert ("finish", "switch:2", "done", None) in progress.events
    assert ("output", "switch:0", "stderr", "ran fetch --quiet") in progress.events
    assert ("output", "switch:2", "stderr", "+ sase==0.8.1") in progress.events
    assert (
        "command",
        "switch:0",
        plan.commands[0].command,
        checkout,
    ) in progress.events
    assert ("command", "switch:2", plan.commands[2].command, None) in progress.events


def test_execute_mode_switch_failure_marks_row_failed(tmp_path: Path) -> None:
    plan = _switch_plan(tmp_path)
    progress = RecordingProgress()

    def run_command(
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        on_output: OutputSink | None = None,
    ) -> DevCommandResult:
        del cwd, on_output
        if tuple(argv)[:3] == ("git", "merge", "--ff-only"):
            return DevCommandResult(returncode=1, stderr="not a fast-forward")
        return DevCommandResult(returncode=0)

    def run_uv(argv: list[str], *, on_output: OutputSink | None = None) -> UvChangeSet:
        del argv, on_output
        raise AssertionError("uv must not run after a failed merge")

    with pytest.raises(UvCommandFailedError, match="not a fast-forward"):
        execute_mode_switch(
            plan, run_uv_fn=run_uv, run_command_fn=run_command, progress=progress
        )

    finishes = [event for event in progress.events if event[0] == "finish"]
    assert finishes[0][:3] == ("finish", "switch:0", "done")
    assert finishes[1][1:3] == ("switch:1", "failed")
    assert "not a fast-forward" in finishes[1][3]
    assert not [
        event for event in progress.events if event[:2] == ("start", "switch:2")
    ]


def test_execute_mode_switch_skips_unavailable_commands(tmp_path: Path) -> None:
    plan = _switch_plan(tmp_path)
    commands = (
        plan.commands[0],
        ModeSwitchCommand(
            kind="git_merge_ff",
            label="Fast-forward sase",
            command=("git", "merge", "--ff-only", "origin/master"),
            available=False,
            reason="already current",
        ),
        plan.commands[2],
    )
    plan = SwitchPlan(
        current_mode=plan.current_mode,
        target_mode=plan.target_mode,
        dev_root=plan.dev_root,
        packages=plan.packages,
        commands=commands,
        restore_command=plan.restore_command,
        backup_path=plan.backup_path,
    )
    progress = RecordingProgress()
    calls: list[tuple[str, ...]] = []

    def run_command(
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        on_output: OutputSink | None = None,
    ) -> DevCommandResult:
        del cwd, on_output
        calls.append(tuple(argv))
        return DevCommandResult(returncode=0)

    def run_uv(argv: list[str], *, on_output: OutputSink | None = None) -> UvChangeSet:
        del on_output
        calls.append(tuple(argv))
        return UvChangeSet()

    result = execute_mode_switch(
        plan, run_uv_fn=run_uv, run_command_fn=run_command, progress=progress
    )

    assert [command.kind for command in result.commands] == [
        "git_fetch",
        "uv_tool_install",
    ]
    assert progress.events[0] == (
        "declare",
        (
            ("switch:0", "Fetch sase", None),
            ("switch:2", "Install editable package set", None),
        ),
    )
    assert calls == [plan.commands[0].command, plan.commands[2].command]
