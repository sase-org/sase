"""Tests for dev-update reconciliation and package restoration."""

from __future__ import annotations

from pathlib import Path

from sase.dev_update.execute import execute_dev_update
from sase.dev_update.models import DevCommandResult, DevReconcileStep, DevUpdatePlan
from tests.dev_update._execute_helpers import (
    FakeRunner,
    SequenceRunner,
    package,
    plan,
    stale_core_package,
)


def test_execute_dev_update_missing_reconcile_step_fails_after_merge() -> None:
    step = DevReconcileStep(
        kind="uv_tool_install",
        label="Reinstall uv-tool editable Python packages",
        command=(),
        reason="uv tool receipt unavailable",
    )

    result = execute_dev_update(plan(reconcile=(step,)), run=FakeRunner())

    assert result.changed is True
    assert result.outcomes[0].status == "failed"
    assert result.outcomes[0].reason == "uv tool receipt unavailable"


def test_execute_dev_update_repairs_failed_core_health_check() -> None:
    rust_step = DevReconcileStep(
        kind="rust_dev_install",
        label="Rebuild Rust dev artifacts into the uv-tool venv",
        command=("just", "rust-dev-install-uv-tool"),
        cwd="/repo",
    )
    health_command = (
        "/tool/bin/python",
        "-c",
        "import importlib.metadata as m; import sase_core_rs; "
        "print(m.version('sase-core-rs'))",
    )
    repair_command = (
        "uv",
        "pip",
        "install",
        "--python",
        "/tool/bin/python",
        "--force-reinstall",
        "sase-core-rs<0.4.0,>=0.3.2",
    )
    health_step = DevReconcileStep(
        kind="rust_health_check",
        label="Verify sase-core-rs imports in the uv-tool venv",
        command=health_command,
        repair_command=repair_command,
        repair_label="Restore published sase-core-rs wheel",
    )
    runner = SequenceRunner(
        {
            ("just", "rust-dev-install-uv-tool"): [
                DevCommandResult(1, stderr="maturin failed")
            ],
            health_command: [
                DevCommandResult(1, stderr="No module named sase_core_rs"),
                DevCommandResult(0, stdout="0.3.7\n"),
            ],
        }
    )

    result = execute_dev_update(plan(reconcile=(rust_step, health_step)), run=runner)

    assert result.changed is True
    assert result.outcomes[0].status == "failed"
    assert "maturin failed" in result.outcomes[0].reason
    assert "environment restored to published sase-core-rs 0.3.7" in (
        result.outcomes[0].reason
    )
    reconcile_commands = [
        (command.label, command.returncode)
        for command in result.commands
        if not command.label.startswith("git ")
    ]
    assert reconcile_commands == [
        ("Rebuild Rust dev artifacts into the uv-tool venv", 1),
        ("Verify sase-core-rs imports in the uv-tool venv", 1),
        ("Restore published sase-core-rs wheel", 0),
        ("Verify sase-core-rs imports in the uv-tool venv after repair", 0),
    ]


def test_execute_dev_update_runs_unified_rust_install_before_core_health_check() -> (
    None
):
    rust_step = DevReconcileStep(
        kind="rust_dev_install",
        label="Rebuild Rust dev artifacts into the uv-tool venv",
        command=("just", "rust-dev-install-uv-tool"),
        cwd="/host",
        env={"SASE_RUST_DEV_PROFILE": "release"},
    )
    health_step = DevReconcileStep(
        kind="rust_health_check",
        label="Verify sase-core-rs imports in the uv-tool venv",
        command=("/tool/bin/python", "-c", "import sase_core_rs"),
    )
    runner = FakeRunner()

    result = execute_dev_update(
        plan(reconcile=(rust_step, health_step)),
        run=runner,
    )

    assert result.changed is True
    assert result.outcomes[0].status == "updated"
    reconcile_commands = [
        (command.label, command.cwd, command.returncode)
        for command in result.commands
        if not command.label.startswith("git ")
    ]
    assert reconcile_commands == [
        ("Rebuild Rust dev artifacts into the uv-tool venv", "/host", 0),
        ("Verify sase-core-rs imports in the uv-tool venv", None, 0),
    ]
    assert [
        call
        for call in runner.env_calls
        if call[0] == ("just", "rust-dev-install-uv-tool")
    ] == [
        (
            ("just", "rust-dev-install-uv-tool"),
            Path("/host"),
            {"SASE_RUST_DEV_PROFILE": "release"},
        )
    ]


def test_execute_dev_update_no_actionable_roots_returns_skips() -> None:
    update_plan = DevUpdatePlan(
        packages=(package("sase", status="skipped"),),
        roots=(),
        reconcile_steps=(),
    )

    result = execute_dev_update(update_plan, run=FakeRunner())

    assert result.changed is False
    assert result.outcomes[0].status == "skipped"


def test_execute_dev_update_runs_core_restore_without_actionable_roots() -> None:
    step = DevReconcileStep(
        kind="rust_dev_install",
        label="Rebuild Rust dev artifacts into the uv-tool venv",
        command=("just", "rust-dev-install-uv-tool"),
        cwd="/host",
    )
    update_plan = DevUpdatePlan(
        packages=(package("sase", status="skipped"), stale_core_package()),
        roots=(),
        reconcile_steps=(step,),
    )
    runner = FakeRunner()

    result = execute_dev_update(update_plan, run=runner)

    assert runner.calls == [(("just", "rust-dev-install-uv-tool"), Path("/host"))]
    assert result.changed is True
    statuses = {outcome.record.name: outcome.status for outcome in result.outcomes}
    assert statuses == {"sase-core-rs": "updated", "sase": "skipped"}
    core_outcome = next(
        outcome for outcome in result.outcomes if outcome.record.name == "sase-core-rs"
    )
    assert core_outcome.old_version == "0.4.1"
    assert core_outcome.new_version == "0.5.0"


def test_execute_dev_update_core_restore_failure_reports_failed_core() -> None:
    step = DevReconcileStep(
        kind="rust_dev_install",
        label="Rebuild Rust dev artifacts into the uv-tool venv",
        command=("just", "rust-dev-install-uv-tool"),
        cwd="/host",
    )
    update_plan = DevUpdatePlan(
        packages=(stale_core_package(),),
        roots=(),
        reconcile_steps=(step,),
    )
    runner = FakeRunner(
        responses={
            ("just", "rust-dev-install-uv-tool"): DevCommandResult(
                1, stderr="cargo build failed"
            )
        }
    )

    result = execute_dev_update(update_plan, run=runner)

    assert result.changed is True
    assert result.outcomes[0].status == "failed"
    assert "cargo build failed" in result.outcomes[0].reason
