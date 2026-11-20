"""Progress-event tests for dev-update execution and reconciliation.

Uses the recording :class:`UpdateProgress` fake plus a streaming-capable
command runner to assert event order, statuses, details, and output
routing for execution, prebuilt-artifact consumption, and repair rows.
"""

from __future__ import annotations

import time

from sase.dev_update import prebuild
from sase.dev_update.code_swap_lock import code_swap_reader_lock
from sase.dev_update.execute import execute_dev_update
from sase.dev_update.models import (
    DevCommandResult,
    DevExecutedCommand,
    DevReconcileStep,
    DevUpdatePlan,
)
from sase.dev_update.reconcile import run_reconcile_steps
from sase.update_progress import StepSpec
from sase.update_progress.timeline import TimelineModel
from tests.dev_update._execute_helpers import package, plan
from tests.dev_update._progress_helpers import RecordingProgress, StreamingRunner


def test_execute_success_streams_output_into_running_steps() -> None:
    step = DevReconcileStep(
        kind="uv_tool_install",
        label="Reinstall uv-tool editable Python packages",
        command=("uv", "tool", "install", "sase"),
        cwd="/repo",
    )
    runner = StreamingRunner(
        emit={("uv", "tool", "install", "sase"): [("stderr", "Resolved 3 packages")]},
    )
    progress = RecordingProgress()

    result = execute_dev_update(plan(reconcile=(step,)), run=runner, progress=progress)

    assert result.changed is True
    assert progress.events[0] == (
        "declare",
        (
            ("merge", "Fast-forward checkouts", None),
            ("merge:/repo", "Fast-forward repo", "merge"),
            ("reconcile:0", "Reinstall editable Python packages", None),
        ),
    )
    assert progress.finishes("merge") == [("finish", "merge", "done", None)]
    merge_finish = progress.finishes("merge:/repo")
    assert len(merge_finish) == 1
    assert merge_finish[0][2] == "done"
    assert merge_finish[0][3] is not None and "→" in merge_finish[0][3]
    assert progress.finishes("reconcile:0") == [("finish", "reconcile:0", "done", None)]
    assert progress.outputs("reconcile:0") == [
        ("output", "reconcile:0", "stderr", "Resolved 3 packages")
    ]
    assert (
        "command",
        "merge:/repo",
        ("git", "-C", "/repo", "status", "--porcelain"),
        None,
    ) in progress.events
    assert all(used for _, used in runner.sink_calls)


def test_execute_prebuild_hit_skips_rebuild_with_progress() -> None:
    prebuild_command = ("python", "-m", "sase.dev_update.prebuild", "consume")
    rust_command = ("just", "rust-dev-install-uv-tool")
    update_plan = plan(
        reconcile=(
            DevReconcileStep(
                kind="rust_prebuild_install",
                label="Install prebuilt Rust dev artifacts into the uv-tool venv",
                command=prebuild_command,
                cwd="/host",
            ),
            DevReconcileStep(
                kind="rust_dev_install",
                label="Rebuild Rust dev artifacts into the uv-tool venv",
                command=rust_command,
                cwd="/host",
            ),
            DevReconcileStep(
                kind="rust_health_check",
                label="Verify sase-core-rs imports in the uv-tool venv",
                command=("/tool/bin/python", "-c", "import sase_core_rs"),
            ),
        )
    )
    runner = StreamingRunner(
        responses={
            prebuild_command: DevCommandResult(
                0,
                stdout=prebuild._outcome_marker(  # noqa: SLF001
                    prebuild._RustPrebuildConsumeOutcome(  # noqa: SLF001
                        True,
                        "hit",
                        set_key="cache-key",
                    )
                ),
            )
        }
    )
    progress = RecordingProgress()

    result = execute_dev_update(update_plan, run=runner, progress=progress)

    assert result.changed is True
    assert progress.finishes("reconcile:0") == [
        ("finish", "reconcile:0", "done", "cache hit")
    ]
    assert progress.finishes("reconcile:1") == [
        ("finish", "reconcile:1", "skipped", "prebuilt artifacts used")
    ]
    assert progress.finishes("reconcile:2") == [("finish", "reconcile:2", "done", None)]
    assert rust_command not in [call[0] for call in runner.calls]


def test_execute_prebuild_miss_records_miss_and_rebuilds() -> None:
    prebuild_command = ("python", "-m", "sase.dev_update.prebuild", "consume")
    rust_command = ("just", "rust-dev-install-uv-tool")
    update_plan = plan(
        reconcile=(
            DevReconcileStep(
                kind="rust_prebuild_install",
                label="Install prebuilt Rust dev artifacts into the uv-tool venv",
                command=prebuild_command,
                cwd="/host",
            ),
            DevReconcileStep(
                kind="rust_dev_install",
                label="Rebuild Rust dev artifacts into the uv-tool venv",
                command=rust_command,
                cwd="/host",
            ),
            DevReconcileStep(
                kind="rust_health_check",
                label="Verify sase-core-rs imports in the uv-tool venv",
                command=("/tool/bin/python", "-c", "import sase_core_rs"),
            ),
        )
    )
    runner = StreamingRunner(
        responses={
            prebuild_command: DevCommandResult(
                0,
                stdout=prebuild._outcome_marker(  # noqa: SLF001
                    prebuild._RustPrebuildConsumeOutcome(  # noqa: SLF001
                        False,
                        "commit-mismatch",
                    )
                ),
            )
        }
    )
    progress = RecordingProgress()

    result = execute_dev_update(update_plan, run=runner, progress=progress)

    assert result.changed is True
    assert result.rust_prebuild.reason == "commit-mismatch"
    assert progress.finishes("reconcile:0") == [
        ("finish", "reconcile:0", "miss", "cache miss · commit-mismatch")
    ]
    assert progress.finishes("reconcile:1") == [("finish", "reconcile:1", "done", None)]
    assert rust_command in [call[0] for call in runner.calls]


def test_execute_prebuild_consume_error_records_warned_and_rebuilds() -> None:
    prebuild_command = ("python", "-m", "sase.dev_update.prebuild", "consume")
    rust_command = ("just", "rust-dev-install-uv-tool")
    update_plan = plan(
        reconcile=(
            DevReconcileStep(
                kind="rust_prebuild_install",
                label="Install prebuilt Rust dev artifacts into the uv-tool venv",
                command=prebuild_command,
                cwd="/host",
            ),
            DevReconcileStep(
                kind="rust_dev_install",
                label="Rebuild Rust dev artifacts into the uv-tool venv",
                command=rust_command,
                cwd="/host",
            ),
            DevReconcileStep(
                kind="rust_health_check",
                label="Verify sase-core-rs imports in the uv-tool venv",
                command=("/tool/bin/python", "-c", "import sase_core_rs"),
            ),
        )
    )
    runner = StreamingRunner(
        responses={
            prebuild_command: DevCommandResult(
                1,
                stdout=prebuild._outcome_marker(  # noqa: SLF001
                    prebuild._RustPrebuildConsumeOutcome(  # noqa: SLF001
                        False,
                        "health-check-failed",
                    )
                ),
            )
        }
    )
    progress = RecordingProgress()

    result = execute_dev_update(update_plan, run=runner, progress=progress)

    assert result.rust_prebuild.reason == "health-check-failed"
    assert progress.finishes("reconcile:0") == [
        ("finish", "reconcile:0", "warned", "cache error · health-check-failed")
    ]
    assert rust_command in [call[0] for call in runner.calls]


def test_execute_preflight_dirty_failure_marks_child_failed() -> None:
    runner = StreamingRunner(
        responses={
            ("git", "-C", "/repo", "status", "--porcelain"): DevCommandResult(
                0, stdout=" M src/sase/__init__.py"
            )
        }
    )
    progress = RecordingProgress()

    result = execute_dev_update(plan(), run=runner, progress=progress)

    assert result.changed is False
    assert progress.finishes("merge:/repo")[0][2] == "failed"
    assert "local changes" in progress.finishes("merge:/repo")[0][3]
    assert progress.finishes("merge")[0][2] == "failed"


def test_execute_code_swap_deferral_warns_merge() -> None:
    progress = RecordingProgress()

    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        result = execute_dev_update(plan(), run=StreamingRunner(), progress=progress)

    assert result.changed is False
    assert progress.finishes("merge") == [
        ("finish", "merge", "warned", result.outcomes[0].reason)
    ]


def test_execute_noop_plan_emits_no_events() -> None:
    update_plan = DevUpdatePlan(
        packages=(package("sase", status="skipped"),),
        roots=(),
        reconcile_steps=(),
    )
    progress = RecordingProgress()

    result = execute_dev_update(update_plan, run=StreamingRunner(), progress=progress)

    assert result.changed is False
    assert progress.events == []


def test_execute_health_check_repair_has_child_row() -> None:
    health_command = ("/tool/bin/python", "-c", "import sase_core_rs")
    repair_command = ("uv", "pip", "install", "--force-reinstall", "sase-core-rs")
    update_plan = plan(
        reconcile=(
            DevReconcileStep(
                kind="rust_health_check",
                label="Verify sase-core-rs imports in the uv-tool venv",
                command=health_command,
                repair_command=repair_command,
                repair_label="Restore published sase-core-rs wheel",
            ),
        )
    )
    runner = StreamingRunner(
        sequences={
            health_command: [
                DevCommandResult(1, stderr="No module named sase_core_rs"),
                DevCommandResult(0, stdout="0.3.7\n"),
            ],
        },
        emit={repair_command: [("stderr", "Installed sase-core-rs")]},
    )
    progress = RecordingProgress()

    result = execute_dev_update(update_plan, run=runner, progress=progress)

    assert result.changed is True
    assert result.outcomes[0].status == "failed"
    assert progress.finishes("reconcile:0:repair") == [
        ("finish", "reconcile:0:repair", "done", None)
    ]
    assert progress.outputs("reconcile:0:repair") == [
        ("output", "reconcile:0:repair", "stderr", "Installed sase-core-rs")
    ]
    assert progress.finishes("reconcile:0")[0][2] == "warned"


def test_health_check_repair_row_parented_in_timeline_snapshot() -> None:
    health_command = ("/tool/bin/python", "-c", "import sase_core_rs")
    repair_command = ("uv", "pip", "install", "--force-reinstall", "sase-core-rs")
    steps = (
        DevReconcileStep(
            kind="rust_health_check",
            label="Verify sase-core-rs imports in the uv-tool venv",
            command=health_command,
            repair_command=repair_command,
            repair_label="Restore published sase-core-rs wheel",
        ),
    )
    runner = StreamingRunner(
        sequences={
            health_command: [
                DevCommandResult(1, stderr="No module named sase_core_rs"),
                DevCommandResult(0, stdout="0.3.7\n"),
            ],
        },
        emit={repair_command: [("stderr", "Installed sase-core-rs")]},
    )
    model = TimelineModel()
    model.declare(
        (StepSpec("reconcile:0", "Verify sase-core-rs imports in the uv-tool venv"),)
    )
    commands: list[DevExecutedCommand] = []

    failure, _, _ = run_reconcile_steps(
        steps, runner, commands, time.monotonic, progress=model
    )

    assert failure is not None
    snapshot = model.snapshot()
    assert [row.id for row in snapshot] == ["reconcile:0"]
    parent = snapshot[0]
    assert [child.id for child in parent.children] == ["reconcile:0:repair"]
