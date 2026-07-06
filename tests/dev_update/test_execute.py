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
    RepoDiffStat,
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
        if command[:5] == ("git", "-C", "/repo", "rev-parse", "HEAD"):
            return DevCommandResult(0, stdout="abc123\n")
        return DevCommandResult(0)


class SequenceRunner(FakeRunner):
    def __init__(
        self,
        sequences: dict[tuple[str, ...], list[DevCommandResult]],
        responses: dict[tuple[str, ...], DevCommandResult] | None = None,
    ) -> None:
        super().__init__(responses)
        self.sequences = sequences

    def __call__(
        self, argv: Sequence[str], *, cwd: Path | None = None
    ) -> DevCommandResult:
        command = tuple(argv)
        if command in self.sequences and self.sequences[command]:
            self.calls.append((command, cwd))
            return self.sequences[command].pop(0)
        return super().__call__(argv, cwd=cwd)


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
        (
            (
                "git",
                "-C",
                "/repo",
                "fetch",
                "--quiet",
                "--tags",
                "--force",
                "origin",
                "main",
            ),
            None,
        ),
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
        (("git", "-C", "/repo", "rev-parse", "HEAD"), None),
        (("git", "-C", "/repo", "merge", "--ff-only", "origin/main"), None),
        (("git", "-C", "/repo", "rev-parse", "HEAD"), None),
        (
            (
                "git",
                "-C",
                "/repo",
                "diff",
                "--numstat",
                "abc123",
                "abc123",
            ),
            None,
        ),
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
            if command[3:5] == ("rev-parse", "HEAD"):
                return DevCommandResult(0, stdout="abc123\n")
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
        "rev-parse",
        "merge",
        "rev-parse",
        "diff",
        "rev-parse",
        "merge",
        "rev-parse",
        "diff",
    ]


def test_execute_dev_update_attaches_numstat_diffstat() -> None:
    runner = FakeRunner(
        {
            ("git", "-C", "/repo", "rev-parse", "HEAD"): DevCommandResult(
                0, stdout="abc123\n"
            ),
            (
                "git",
                "-C",
                "/repo",
                "diff",
                "--numstat",
                "abc123",
                "abc123",
            ): DevCommandResult(
                0,
                stdout="5\t2\tsrc/sase/a.py\n-\t-\tassets/logo.png\n",
            ),
        }
    )

    result = execute_dev_update(_plan(), run=runner)

    assert result.changed is True
    assert result.outcomes[0].diffstat == RepoDiffStat(
        files_changed=2,
        insertions=5,
        deletions=2,
    )


def test_execute_dev_update_diff_failure_leaves_stats_absent() -> None:
    runner = FakeRunner(
        {
            ("git", "-C", "/repo", "rev-parse", "HEAD"): DevCommandResult(
                0, stdout="abc123\n"
            ),
            (
                "git",
                "-C",
                "/repo",
                "diff",
                "--numstat",
                "abc123",
                "abc123",
            ): DevCommandResult(1, stderr="bad revision"),
        }
    )

    result = execute_dev_update(_plan(), run=runner)

    assert result.changed is True
    assert result.outcomes[0].status == "updated"
    assert result.outcomes[0].diffstat is None


def test_execute_dev_update_head_failure_leaves_stats_absent() -> None:
    runner = FakeRunner(
        {
            ("git", "-C", "/repo", "rev-parse", "HEAD"): DevCommandResult(
                1, stderr="not a git repository"
            ),
        }
    )

    result = execute_dev_update(_plan(), run=runner)

    assert result.changed is True
    assert result.outcomes[0].status == "updated"
    assert result.outcomes[0].diffstat is None
    assert not any(call[0][3:5] == ("diff", "--numstat") for call in runner.calls)


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
                "--tags",
                "--force",
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


def test_execute_dev_update_repairs_failed_core_health_check() -> None:
    rust_step = DevReconcileStep(
        kind="rust_install_uv_tool",
        label="Rebuild sase-core-rs into the uv-tool venv",
        command=("just", "rust-install-uv-tool"),
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
        "sase-core-rs<0.4.0,>=0.3.0",
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
            ("just", "rust-install-uv-tool"): [
                DevCommandResult(1, stderr="maturin failed")
            ],
            health_command: [
                DevCommandResult(1, stderr="No module named sase_core_rs"),
                DevCommandResult(0, stdout="0.3.7\n"),
            ],
        }
    )

    result = execute_dev_update(_plan(reconcile=(rust_step, health_step)), run=runner)

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
        ("Rebuild sase-core-rs into the uv-tool venv", 1),
        ("Verify sase-core-rs imports in the uv-tool venv", 1),
        ("Restore published sase-core-rs wheel", 0),
        ("Verify sase-core-rs imports in the uv-tool venv after repair", 0),
    ]


def test_execute_dev_update_no_actionable_roots_returns_skips() -> None:
    plan = DevUpdatePlan(
        packages=(_package("sase", status="skipped"),),
        roots=(),
        reconcile_steps=(),
    )

    result = execute_dev_update(plan, run=FakeRunner())

    assert result.changed is False
    assert result.outcomes[0].status == "skipped"
