"""Tests for dev-update execution."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sase.dev_update.execute import execute_dev_update
from sase.dev_update.models import (
    DevCommandResult,
    DevReconcileStep,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateRootPlan,
)
from sase.version._models import VersionPackageRecord


def _record(name: str) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role="host",
        display_version="0.5.0+1.gaaaaaaaaa",
        distribution_version="0.5.0",
        source_version="0.5.0",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root="/repo",
        distribution_location=None,
        install_type="editable",
        git=None,
    )


def _package(name: str, *, status: str = "actionable") -> DevUpdatePackagePlan:
    return DevUpdatePackagePlan(
        record=_record(name),
        status=status,  # type: ignore[arg-type]
        reason="behind upstream by 2 commit(s)"
        if status == "actionable"
        else "already current",
        current_version="0.5.0+1.gaaaaaaaaa",
        latest_version="0.5.0+3.gbbbbbbbbb",
        git_root="/repo",
        upstream="origin/main",
        remote="origin",
        remote_branch="main",
        ahead=0,
        behind=2,
    )


def _root(path: str = "/repo") -> DevUpdateRootPlan:
    return DevUpdateRootPlan(
        git_root=path,
        status="actionable",
        reason="behind upstream by 2 commit(s)",
        upstream="origin/main",
        remote="origin",
        remote_branch="main",
        packages=("sase",),
        ahead=0,
        behind=2,
    )


def _plan(*, reconcile: tuple[DevReconcileStep, ...] = ()) -> DevUpdatePlan:
    return DevUpdatePlan(
        packages=(_package("sase"),),
        roots=(_root(),),
        reconcile_steps=reconcile,
    )


class FakeRunner:
    def __init__(
        self, responses: dict[tuple[str, ...], DevCommandResult] | None = None
    ) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[tuple[str, ...], Path | None]] = []

    def __call__(
        self, argv: Sequence[str], *, cwd: Path | None = None
    ) -> DevCommandResult:
        command = tuple(argv)
        self.calls.append((command, cwd))
        if command in self.responses:
            return self.responses[command]
        if command[:5] == ("git", "-C", "/repo", "status", "--porcelain"):
            return DevCommandResult(0, stdout="")
        if command[:6] == (
            "git",
            "-C",
            "/repo",
            "rev-list",
            "--left-right",
            "--count",
        ):
            return DevCommandResult(0, stdout="0 2")
        return DevCommandResult(0)


def test_execute_dev_update_fetches_preflights_merges_and_reconciles() -> None:
    step = DevReconcileStep(
        kind="uv_tool_install",
        label="Reinstall uv-tool editable Python packages",
        command=("uv", "tool", "install", "sase"),
        cwd="/repo",
    )
    runner = FakeRunner()

    result = execute_dev_update(_plan(reconcile=(step,)), run=runner)

    assert result.changed is True
    assert [(outcome.record.name, outcome.status) for outcome in result.outcomes] == [
        ("sase", "updated")
    ]
    assert runner.calls == [
        (("git", "-C", "/repo", "fetch", "--quiet", "origin", "main"), None),
        (("git", "-C", "/repo", "status", "--porcelain"), None),
        (
            (
                "git",
                "-C",
                "/repo",
                "rev-list",
                "--left-right",
                "--count",
                "HEAD...origin/main",
            ),
            None,
        ),
        (("git", "-C", "/repo", "merge", "--ff-only", "origin/main"), None),
        (("uv", "tool", "install", "sase"), Path("/repo")),
    ]


def test_execute_dev_update_preflights_all_roots_before_merging() -> None:
    plan = DevUpdatePlan(
        packages=(_package("sase"),),
        roots=(
            _root("/repo/a"),
            _root("/repo/b"),
        ),
        reconcile_steps=(),
    )

    class MultiRootRunner(FakeRunner):
        def __call__(
            self, argv: Sequence[str], *, cwd: Path | None = None
        ) -> DevCommandResult:
            command = tuple(argv)
            self.calls.append((command, cwd))
            if command[3:5] == ("status", "--porcelain"):
                return DevCommandResult(0, stdout="")
            if command[3:6] == ("rev-list", "--left-right", "--count"):
                return DevCommandResult(0, stdout="0 1")
            return DevCommandResult(0)

    runner = MultiRootRunner()

    result = execute_dev_update(plan, run=runner)

    assert result.changed is True
    labels = [call[0][3] for call in runner.calls]
    assert labels == [
        "fetch",
        "fetch",
        "status",
        "rev-list",
        "status",
        "rev-list",
        "merge",
        "merge",
    ]


def test_execute_dev_update_dirty_preflight_aborts_before_merge() -> None:
    runner = FakeRunner(
        {
            ("git", "-C", "/repo", "status", "--porcelain"): DevCommandResult(
                0, stdout=" M src/sase/__init__.py"
            )
        }
    )

    result = execute_dev_update(_plan(), run=runner)

    assert result.changed is False
    assert result.outcomes[0].status == "failed"
    assert "local changes" in result.outcomes[0].reason
    assert ("git", "-C", "/repo", "merge", "--ff-only", "origin/main") not in [
        call[0] for call in runner.calls
    ]


def test_execute_dev_update_fetch_failure_aborts_before_preflight() -> None:
    runner = FakeRunner(
        {
            (
                "git",
                "-C",
                "/repo",
                "fetch",
                "--quiet",
                "origin",
                "main",
            ): DevCommandResult(1, stderr="network down")
        }
    )

    result = execute_dev_update(_plan(), run=runner)

    assert result.changed is False
    assert result.outcomes[0].status == "failed"
    assert "network down" in result.outcomes[0].reason
    assert len(runner.calls) == 1


def test_execute_dev_update_first_merge_failure_does_not_mark_changed() -> None:
    runner = FakeRunner(
        {
            (
                "git",
                "-C",
                "/repo",
                "merge",
                "--ff-only",
                "origin/main",
            ): DevCommandResult(1, stderr="not possible to fast-forward")
        }
    )

    result = execute_dev_update(_plan(), run=runner)

    assert result.changed is False
    assert result.outcomes[0].status == "failed"
    assert "not possible to fast-forward" in result.outcomes[0].reason


def test_execute_dev_update_missing_reconcile_step_fails_after_merge() -> None:
    step = DevReconcileStep(
        kind="uv_tool_install",
        label="Reinstall uv-tool editable Python packages",
        command=(),
        reason="uv tool receipt unavailable",
    )

    result = execute_dev_update(_plan(reconcile=(step,)), run=FakeRunner())

    assert result.changed is True
    assert result.outcomes[0].status == "failed"
    assert result.outcomes[0].reason == "uv tool receipt unavailable"


def test_execute_dev_update_no_actionable_roots_returns_skips() -> None:
    plan = DevUpdatePlan(
        packages=(_package("sase", status="skipped"),),
        roots=(),
        reconcile_steps=(),
    )

    result = execute_dev_update(plan, run=FakeRunner())

    assert result.changed is False
    assert result.outcomes[0].status == "skipped"
