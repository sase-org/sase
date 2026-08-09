"""Tests for dev-update Git execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from sase.dev_update.execute import execute_dev_update
from sase.dev_update.code_swap_lock import code_swap_reader_lock
from sase.dev_update.models import (
    DevCommandResult,
    DevReconcileStep,
    DevUpdatePlan,
    RepoCommit,
    RepoCommitLog,
    RepoDiffStat,
)
from tests.dev_update._execute_helpers import (
    FakeRunner,
    SequenceRunner,
    package,
    plan,
    root,
)


def test_execute_dev_update_fetches_preflights_merges_and_reconciles() -> None:
    step = DevReconcileStep(
        kind="uv_tool_install",
        label="Reinstall uv-tool editable Python packages",
        command=("uv", "tool", "install", "sase"),
        cwd="/repo",
    )
    runner = FakeRunner()

    result = execute_dev_update(plan(reconcile=(step,)), run=runner)

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
                "+refs/heads/main:refs/remotes/origin/main",
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
        (
            (
                "git",
                "-C",
                "/repo",
                "rev-list",
                "--count",
                "abc123..abc123",
            ),
            None,
        ),
        (("uv", "tool", "install", "sase"), Path("/repo")),
    ]


def test_execute_dev_update_records_command_and_total_durations() -> None:
    step = DevReconcileStep(
        kind="uv_tool_install",
        label="Reinstall uv-tool editable Python packages",
        command=("uv", "tool", "install", "sase"),
        cwd="/repo",
    )
    update_plan = DevUpdatePlan(
        packages=(package("sase", status="skipped"),),
        roots=(),
        reconcile_steps=(step,),
    )
    ticks = iter([10.0, 11.0, 13.5, 16.0])

    result = execute_dev_update(
        update_plan,
        run=FakeRunner(),
        clock=lambda: next(ticks),
    )

    assert result.duration_seconds == 6.0
    assert result.commands[0].label == "Reinstall uv-tool editable Python packages"
    assert result.commands[0].duration_seconds == 2.5


def test_execute_dev_update_preflights_all_roots_before_merging() -> None:
    plan = DevUpdatePlan(
        packages=(package("sase"),),
        roots=(
            root("/repo/a"),
            root("/repo/b"),
        ),
        reconcile_steps=(),
    )

    class MultiRootRunner(FakeRunner):
        def __call__(
            self,
            argv: Sequence[str],
            *,
            cwd: Path | None = None,
            env: Mapping[str, str] | None = None,
        ) -> DevCommandResult:
            command = tuple(argv)
            self.calls.append((command, cwd))
            self.env_calls.append(
                (command, cwd, dict(env) if env is not None else None)
            )
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
        "rev-list",
        "rev-parse",
        "merge",
        "rev-parse",
        "diff",
        "rev-list",
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

    result = execute_dev_update(plan(), run=runner)

    assert result.changed is True
    assert result.outcomes[0].diffstat == RepoDiffStat(
        files_changed=2,
        insertions=5,
        deletions=2,
    )


def test_execute_dev_update_attaches_capped_commit_log_from_merge_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.dev_update.execute.DEV_UPDATE_COMMIT_LOG_CAPTURE_LIMIT",
        2,
    )
    runner = SequenceRunner(
        sequences={
            ("git", "-C", "/repo", "rev-parse", "HEAD"): [
                DevCommandResult(0, stdout="abc123\n"),
                DevCommandResult(0, stdout="def456\n"),
            ],
        },
        responses={
            (
                "git",
                "-C",
                "/repo",
                "rev-list",
                "--count",
                "abc123..def456",
            ): DevCommandResult(0, stdout="3\n"),
            (
                "git",
                "-C",
                "/repo",
                "log",
                "-n2",
                "--format=%h%x1f%s%x1e",
                "abc123..def456",
            ): DevCommandResult(
                0,
                stdout=(
                    "def456\x1ffeat: add commit receipt\x1e\n"
                    "cafe123\x1ffix: preserve providers\x1e\n"
                ),
            ),
        },
    )

    result = execute_dev_update(plan(), run=runner)

    assert result.outcomes[0].commits == RepoCommitLog(
        total=3,
        commits=(
            RepoCommit("def456", "feat: add commit receipt"),
            RepoCommit("cafe123", "fix: preserve providers"),
        ),
    )
    assert result.outcomes[0].commits.extra == 1


def test_execute_dev_update_commit_count_failure_leaves_log_absent() -> None:
    runner = FakeRunner(
        {
            (
                "git",
                "-C",
                "/repo",
                "rev-list",
                "--count",
                "abc123..abc123",
            ): DevCommandResult(1, stderr="bad revision"),
        }
    )

    result = execute_dev_update(plan(), run=runner)

    assert result.changed is True
    assert result.outcomes[0].commits is None


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

    result = execute_dev_update(plan(), run=runner)

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

    result = execute_dev_update(plan(), run=runner)

    assert result.changed is True
    assert result.outcomes[0].status == "updated"
    assert result.outcomes[0].diffstat is None
    assert result.outcomes[0].commits is None
    assert not any(call[0][3:5] == ("diff", "--numstat") for call in runner.calls)
    assert not any(call[0][3:5] == ("rev-list", "--count") for call in runner.calls)


def test_execute_dev_update_dirty_preflight_aborts_before_merge() -> None:
    runner = FakeRunner(
        {
            ("git", "-C", "/repo", "status", "--porcelain"): DevCommandResult(
                0, stdout=" M src/sase/__init__.py"
            )
        }
    )

    result = execute_dev_update(plan(), run=runner)

    assert result.changed is False
    assert result.outcomes[0].status == "failed"
    assert "local changes" in result.outcomes[0].reason
    assert ("git", "-C", "/repo", "merge", "--ff-only", "origin/main") not in [
        call[0] for call in runner.calls
    ]


def test_execute_dev_update_defers_before_merge_when_reader_is_active() -> None:
    runner = FakeRunner()

    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ) as reader:
        assert reader.acquired is True
        result = execute_dev_update(plan(), run=runner)

    assert result.changed is False
    assert result.outcomes[0].status == "failed"
    assert "deferred:" in result.outcomes[0].reason
    assert "sase bead work" in result.outcomes[0].reason
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
                "+refs/heads/main:refs/remotes/origin/main",
            ): DevCommandResult(1, stderr="network down")
        }
    )

    result = execute_dev_update(plan(), run=runner)

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

    result = execute_dev_update(plan(), run=runner)

    assert result.changed is False
    assert result.outcomes[0].status == "failed"
    assert "not possible to fast-forward" in result.outcomes[0].reason
