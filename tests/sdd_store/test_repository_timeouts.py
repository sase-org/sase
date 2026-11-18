"""Timeouts are unknown state, never repository damage."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from sase.sdd._deadline_git_runner import (
    DeadlineGitRunner,
    SDD_ROLLBACK_GRACE_SECONDS,
    rollback_runner,
)
from sase.sdd._git import SddGitCommandTimeout
from sase.sdd._repository_health import default_git_runner
from sase.sdd._repository_transaction import (
    SddIntegrationStatus,
    integrate_machine_managed_sdd_repository,
    integrate_sdd_repository_transaction,
)
from sase.sdd._repository_types import SddGitTimeoutResult, is_git_timeout
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo
from tests.sdd_store._repository_transaction_helpers import (
    build_diverged_clones,
    run_git,
    snapshot,
)


def _timeout_runner(reason: str = "deadline"):
    def _run(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        del repo_root, args, op, network
        return SddGitTimeoutResult(
            ["git"],
            returncode=124,
            stdout="",
            stderr="deadline expired before git operation",
            timeout_reason=reason,  # type: ignore[arg-type]
        )

    return _run


def test_every_op_timeout_is_timed_out_not_unsafe(tmp_path: Path) -> None:
    _remote, left, _right = build_diverged_clones(tmp_path)
    starting = snapshot(left)

    outcome = integrate_sdd_repository_transaction(
        left,
        git_runner=_timeout_runner("deadline"),
        lock_factory=lambda _root: _unlocked(),
    )

    assert outcome.status is SddIntegrationStatus.TIMED_OUT
    assert outcome.succeeded is False
    assert outcome.structurally_healthy is True
    assert "not safe to write" not in (outcome.error or "")
    assert "not a valid Git worktree" not in (outcome.error or "")
    assert snapshot(left) == starting


def test_machine_managed_every_op_timeout_skips_recovery(tmp_path: Path) -> None:
    _remote, left, _right = build_diverged_clones(tmp_path)
    starting = snapshot(left)

    outcome = integrate_machine_managed_sdd_repository(
        left,
        git_runner=_timeout_runner("deadline"),
    )

    assert outcome.status is SddIntegrationStatus.TIMED_OUT
    assert snapshot(left) == starting
    assert not list((left / ".git").glob("sase-sdd-recovery-attempt*"))
    assert git(["for-each-ref", "refs/sase/recovery"], left).stdout == ""


def test_pull_sdd_clone_deadline_expiry_after_entry_is_quiet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)

    from sase.sdd import _store_integration

    calls = {"count": 0}

    def _expiry(deadline: float | None) -> bool:
        calls["count"] += 1
        # First check (entry) passes; second check (pre-integration) expires.
        return calls["count"] >= 2 and deadline is not None

    monkeypatch.setattr(_store_integration, "_deadline_expired", _expiry)
    errors: list[dict] = []
    monkeypatch.setattr("sase.axe.state.append_error", errors.append)

    from sase.sdd._store_link import _pull_sdd_clone

    assert _pull_sdd_clone(clone_dir, deadline=time.monotonic() + 60.0) is False
    assert errors == []
    assert not (clone_dir / ".git" / "sase-sdd-integration-failure.json").exists()


def test_health_conflicts_wall_clock_timeout_is_timed_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _remote, left, _right = build_diverged_clones(tmp_path)

    real_runner = default_git_runner

    def _raising(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if op.endswith(".health.conflicts"):
            raise SddGitCommandTimeout("injected wall-clock timeout")
        return real_runner(repo_root, args, op=op, network=network)

    outcome = integrate_sdd_repository_transaction(
        left,
        git_runner=_raising,
        lock_factory=lambda _root: _unlocked(),
    )

    assert outcome.status is SddIntegrationStatus.TIMED_OUT
    assert outcome.structurally_healthy is True


def test_timed_out_upstream_verify_is_not_success(tmp_path: Path) -> None:
    _remote, left, _right = build_diverged_clones(tmp_path)

    def _run(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if op.endswith(".upstream"):
            return SddGitTimeoutResult(
                ["git", *args],
                returncode=124,
                stdout="",
                stderr="injected upstream timeout",
                timeout_reason="deadline",  # type: ignore[arg-type]
            )
        return run_git(repo_root, args, op=op, network=network)

    outcome = integrate_sdd_repository_transaction(
        left,
        git_runner=_run,
        lock_factory=lambda _root: _unlocked(),
    )

    assert outcome.status is SddIntegrationStatus.TIMED_OUT
    assert outcome.succeeded is False


def test_machine_alignment_status_timeout_skips_recovery(tmp_path: Path) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    starting = snapshot(clone_dir)

    def _run(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if op.endswith(".alignment.status"):
            return SddGitTimeoutResult(
                ["git", *args],
                returncode=124,
                stdout="",
                stderr="injected alignment timeout",
                timeout_reason="wall_clock",  # type: ignore[arg-type]
            )
        return run_git(repo_root, args, op=op, network=network)

    outcome = integrate_machine_managed_sdd_repository(
        clone_dir,
        git_runner=_run,
        require_upstream_alignment=True,
    )

    assert outcome.status is SddIntegrationStatus.TIMED_OUT
    assert snapshot(clone_dir) == starting
    assert git(["for-each-ref", "refs/sase/recovery"], clone_dir).stdout == ""


def test_mid_rebase_expiry_aborts_to_starting_state(tmp_path: Path) -> None:
    _remote, left, _right = build_diverged_clones(tmp_path)
    git(["fetch", "origin"], left)
    starting = snapshot(left)

    def _run(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if op.endswith(".rebase") and args[:1] == ["rebase"]:
            run_git(repo_root, args, op=op, network=network)
            raise SddGitCommandTimeout("injected mid-rebase timeout")
        return run_git(repo_root, args, op=op, network=network)

    outcome = integrate_sdd_repository_transaction(
        left,
        git_runner=_run,
        lock_factory=lambda _root: _unlocked(),
    )

    assert outcome.status is SddIntegrationStatus.TIMED_OUT
    assert outcome.restored is True
    assert outcome.upstream_present is True
    assert snapshot(left) == starting
    assert not (left / ".git" / "rebase-merge").exists()
    assert not (left / ".git" / "rebase-apply").exists()


def test_recovery_starting_inspection_timeout_defers(tmp_path: Path) -> None:
    _remote, left, _right = build_diverged_clones(tmp_path)
    git(["checkout", "--detach", "HEAD"], left)

    from sase.sdd._repository_recovery import recover_machine_managed_sdd_repository
    from sase.sdd._repository_types import SddIntegrationOutcome

    original = SddIntegrationOutcome(SddIntegrationStatus.UNRECOVERABLE)
    outcome = recover_machine_managed_sdd_repository(
        left,
        original=original,
        beads_dir=None,
        expected_branch=None,
        op_prefix="sdd.test",
        git_runner=_timeout_runner("deadline"),
        lock_factory=lambda _root: _unlocked(),
        clock=None,
        recovery_cooldown_seconds=0,
        event_logger=None,
    )

    assert outcome.status is SddIntegrationStatus.TIMED_OUT
    assert "recovery deferred" in (outcome.error or "")


def test_recovery_fetch_timeout_never_resets(tmp_path: Path) -> None:
    _remote, left, right = build_diverged_clones(tmp_path)
    git(["fetch", "origin"], left)
    started = subprocess.run(
        ["git", "rebase", "origin/main"],
        cwd=left,
        check=False,
        capture_output=True,
        text=True,
    )
    assert started.returncode != 0
    assert (left / ".git" / "rebase-merge").exists() or (
        left / ".git" / "rebase-apply"
    ).exists()
    local_head = git(["rev-parse", "refs/heads/main"], left).stdout.strip()
    upstream_head = git(["rev-parse", "HEAD"], right).stdout.strip()
    assert local_head != upstream_head

    from sase.sdd._repository_recovery import recover_machine_managed_sdd_repository
    from sase.sdd._repository_types import SddIntegrationOutcome

    def _run(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if op.endswith(".recovery.fetch"):
            return SddGitTimeoutResult(
                ["git", *args],
                returncode=124,
                stdout="",
                stderr="injected recovery fetch timeout",
                timeout_reason="wall_clock",  # type: ignore[arg-type]
            )
        return run_git(repo_root, args, op=op, network=network)

    original = SddIntegrationOutcome(SddIntegrationStatus.UNRECOVERABLE)
    outcome = recover_machine_managed_sdd_repository(
        left,
        original=original,
        beads_dir=None,
        expected_branch=None,
        op_prefix="sdd.test",
        git_runner=_run,
        lock_factory=lambda _root: _unlocked(),
        clock=None,
        recovery_cooldown_seconds=0,
        event_logger=None,
    )

    assert outcome.status is SddIntegrationStatus.TIMED_OUT
    # The managed branch was never reset to upstream.
    assert git(["rev-parse", "refs/heads/main"], left).stdout.strip() == local_head
    assert git(["rev-parse", "refs/heads/main"], left).stdout.strip() != upstream_head


def test_genuine_unsafe_states_stay_unrecoverable(tmp_path: Path) -> None:
    _remote, left, _right = build_diverged_clones(tmp_path)
    git(["checkout", "--detach", "HEAD"], left)

    outcome = integrate_sdd_repository_transaction(
        left,
        git_runner=run_git,
        lock_factory=lambda _root: _unlocked(),
    )

    assert outcome.status is SddIntegrationStatus.UNRECOVERABLE
    assert "detached HEAD" in (outcome.error or "")

    _remote2, left2, _right2 = build_diverged_clones(tmp_path / "second")
    git(["fetch", "origin"], left2)
    subprocess.run(
        ["git", "merge", "--no-ff", "--no-commit", "origin/main"],
        cwd=left2,
        check=False,
        capture_output=True,
        text=True,
    )
    merge_outcome = integrate_sdd_repository_transaction(
        left2,
        git_runner=run_git,
        lock_factory=lambda _root: _unlocked(),
    )
    assert merge_outcome.status is SddIntegrationStatus.UNRECOVERABLE


def test_deadline_runner_unit_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    expired = DeadlineGitRunner(time.monotonic() - 1.0)
    result = expired(Path("/tmp"), ["status"], op="sdd.test")
    assert is_git_timeout(result)
    assert result.timeout_reason == "deadline"  # type: ignore[attr-defined]

    def _raising(
        args: list[str],
        *,
        cwd: Path,
        op: str,
        timeout: float | None = None,
        deadline: float | None = None,
        check: bool,
        capture_output: bool,
        text: bool,
        env: dict | None = None,
        output_previews: bool = True,
    ):
        raise SddGitCommandTimeout("injected wall clock")

    monkeypatch.setattr("sase.sdd._git_contention.run_sdd_git_write_network", _raising)
    generous = DeadlineGitRunner(time.monotonic() + 3600.0)
    wall = generous(Path("/tmp"), ["fetch"], op="sdd.test", network=True)
    assert is_git_timeout(wall)
    assert wall.timeout_reason == "wall_clock"  # type: ignore[attr-defined]

    assert SDD_ROLLBACK_GRACE_SECONDS == 20.0
    graced = expired.with_grace(5.0)
    assert graced.deadline > time.monotonic()
    assert rollback_runner(run_git) is run_git


class _unlocked:
    def __init__(self) -> None:
        pass

    def __call__(self, root: Path):  # type: ignore[no-untyped-def]
        return self

    def __enter__(self) -> bool:
        return True

    def __exit__(self, *exc) -> bool:  # type: ignore[no-untyped-def]
        return False
