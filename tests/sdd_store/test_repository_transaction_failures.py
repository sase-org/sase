"""Injected repository-transaction failure and contention coverage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import subprocess

from sase.sdd._repository_transaction import (
    SddIntegrationStatus,
    integrate_machine_managed_sdd_repository,
    integrate_sdd_repository,
)
from tests.sdd_store._repository_transaction_helpers import (
    build_diverged_clones as _build_diverged_clones,
    run_git as _runner,
    snapshot as _snapshot,
)


def test_injected_rebase_failure_without_operation_restores_cleanly(
    tmp_path: Path,
) -> None:
    _remote, left, _right = _build_diverged_clones(
        tmp_path,
        relative_path="remote.md",
        local="local base\n",
        remote_text="remote base\n",
    )
    starting = _snapshot(left)

    def fail_rebase(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["rebase"]:
            return subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr="injected rebase failure"
            )
        return _runner(repo_root, args, op=op, network=network)

    outcome = integrate_sdd_repository(left, git_runner=fail_rebase)

    assert outcome.status is SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS
    assert outcome.restored is True
    assert "injected rebase failure" in (outcome.error or "")
    assert _snapshot(left) == starting


def test_injected_continue_failure_aborts_after_semantic_repair(
    tmp_path: Path,
) -> None:
    issue_base = '{"id":"item","title":"base"}\n'
    _remote, left, _right = _build_diverged_clones(
        tmp_path,
        relative_path="beads/issues.jsonl",
        base=issue_base,
        local='{"id":"item","title":"local"}\n',
        remote_text='{"id":"item","title":"remote"}\n',
    )
    starting = _snapshot(left)

    def fail_continue(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args[-2:] == ["rebase", "--continue"]:
            return subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr="injected continue failure"
            )
        return _runner(repo_root, args, op=op, network=network)

    outcome = integrate_sdd_repository(
        left,
        beads_dir=left / "beads",
        git_runner=fail_continue,
    )

    assert outcome.status is SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS
    assert outcome.restored is True
    assert "injected continue failure" in (outcome.error or "")
    assert _snapshot(left) == starting
    assert not (left / "beads/events/manifest.json").exists()


def test_injected_abort_failure_reports_primary_and_rollback_failures(
    tmp_path: Path,
) -> None:
    _remote, left, _right = _build_diverged_clones(tmp_path)

    def fail_abort(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rebase", "--abort"]:
            return subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr="injected abort failure"
            )
        return _runner(repo_root, args, op=op, network=network)

    outcome = integrate_sdd_repository(
        left,
        beads_dir=left / "beads",
        git_runner=fail_abort,
    )

    assert outcome.status is SddIntegrationStatus.UNRECOVERABLE
    assert outcome.structurally_healthy is False
    assert "git rebase failed" in (outcome.error or "")
    assert "injected abort failure" in (outcome.error or "")
    assert "rollback verification failed" in (outcome.error or "")
    assert (left / ".git/rebase-merge").exists() or (
        left / ".git/rebase-apply"
    ).exists()


def test_failed_conflict_probe_is_not_reported_as_no_conflicts(
    tmp_path: Path,
) -> None:
    """A probe that cannot answer must surface, not read as a clean index."""
    issue_base = '{"id":"item","title":"base"}\n'
    _remote, left, _right = _build_diverged_clones(
        tmp_path,
        relative_path="beads/issues.jsonl",
        base=issue_base,
        local='{"id":"item","title":"local"}\n',
        remote_text='{"id":"item","title":"remote"}\n',
    )
    starting = _snapshot(left)

    def fail_conflict_probe(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if op == "sdd.integrate.conflicts":
            return subprocess.CompletedProcess(
                ["git", *args],
                128,
                stdout="",
                stderr="fatal: Unable to create '.git/index.lock': File exists.",
            )
        return _runner(repo_root, args, op=op, network=network)

    outcome = integrate_sdd_repository(
        left,
        beads_dir=left / "beads",
        git_runner=fail_conflict_probe,
    )

    assert outcome.status is SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS
    assert outcome.restored is True
    assert "could not determine whether conflicts remain" in (outcome.error or "")
    assert "index.lock" in (outcome.error or "")
    assert outcome.resolved_files == ()
    assert _snapshot(left) == starting


def test_store_lock_contention_defers_instead_of_authorizing_recovery(
    tmp_path: Path,
) -> None:
    """A busy cooperating writer must never look like a broken clone.

    Classifying contention as ``UNRECOVERABLE`` is what let machine-managed
    recovery reset a shared clone out from under another writer's committed
    bead claims.
    """
    _remote, left, _right = _build_diverged_clones(tmp_path)
    starting = _snapshot(left)
    resets: list[list[str]] = []

    def record_destructive(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["reset"] or args[:1] == ["stash"]:
            resets.append(args)
        return _runner(repo_root, args, op=op, network=network)

    @contextmanager
    def never_acquired(repo_root: Path) -> Iterator[bool]:
        del repo_root
        yield False

    outcome = integrate_machine_managed_sdd_repository(
        left,
        beads_dir=left / "beads",
        git_runner=record_destructive,
        lock_factory=never_acquired,
        recovery_cooldown_seconds=0,
    )

    assert outcome.status is SddIntegrationStatus.LOCK_UNAVAILABLE
    assert outcome.structurally_healthy is True
    assert outcome.succeeded is False
    assert "store write lock" in (outcome.error or "")
    assert resets == []
    assert _snapshot(left) == starting
