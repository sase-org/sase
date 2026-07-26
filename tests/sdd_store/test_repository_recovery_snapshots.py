"""Machine-managed recovery snapshot and policy regression coverage."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.sdd._repository_recovery_snapshot import snapshot_managed_changes
from sase.sdd._repository_transaction import (
    SddIntegrationStatus,
    integrate_machine_managed_sdd_repository,
    integrate_sdd_repository,
)
from tests.sdd_store._helpers import (
    clone,
    commit_all,
    git,
    init_bare_repo,
)
from tests.sdd_store._repository_transaction_helpers import (
    build_diverged_clones as _build_diverged_clones,
    run_git as _runner,
    snapshot as _snapshot,
)


def test_noop_recovery_stash_proceeds_after_foreign_file_disappears(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    transient = clone_dir / "foreign-writer.tmp"
    transient.write_text("foreign\n", encoding="utf-8")

    def remove_foreign_file_before_stash(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["stash", "push"]:
            transient.unlink()
        return _runner(repo_root, args, op=op, network=network)

    with caplog.at_level("WARNING"):
        snapshot_ref, snapshot_error, snapshot_safe = snapshot_managed_changes(
            clone_dir,
            branch="main",
            recovery_ref="refs/sase/recovery/test-noop",
            runner=remove_foreign_file_before_stash,
            op_prefix="sdd.test",
        )

    assert snapshot_ref == "refs/sase/recovery/test-noop"
    assert snapshot_error is None
    assert snapshot_safe is True
    assert git(["status", "--porcelain"], clone_dir).stdout == ""
    assert git(["for-each-ref", "refs/sase/recovery"], clone_dir).stdout == ""
    assert "worktree or untracked observations changed" in caplog.text


def test_generic_integration_preserves_dirty_state_without_recovery(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    (seed / "remote.md").write_text("remote\n", encoding="utf-8")
    commit_all(seed, "advance remote")
    git(["push"], seed)

    (clone_dir / "README.md").write_text("keep dirty\n", encoding="utf-8")
    starting = _snapshot(clone_dir)

    outcome = integrate_sdd_repository(clone_dir)

    assert outcome.status is SddIntegrationStatus.LOCAL_CHANGES
    assert _snapshot(clone_dir) == starting
    assert git(["for-each-ref", "refs/sase/recovery"], clone_dir).stdout == ""


@pytest.mark.parametrize("failure_stage", ["create", "verify", "verify_after_stash"])
def test_failed_recovery_snapshot_does_not_reset_managed_branch(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    (seed / "remote.md").write_text("remote\n", encoding="utf-8")
    commit_all(seed, "advance remote")
    git(["push"], seed)
    (clone_dir / "README.md").write_text("keep dirty\n", encoding="utf-8")
    starting = _snapshot(clone_dir)

    recovery_verifications = 0

    def fail_snapshot_ref(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal recovery_verifications
        fail_create = failure_stage == "create" and args[:1] == ["update-ref"]
        recovery_verify = args[:2] == ["rev-parse", "--verify"] and args[-1].startswith(
            "refs/sase/recovery/"
        )
        if recovery_verify:
            recovery_verifications += 1
        fail_verify = recovery_verify and (
            (failure_stage == "verify" and recovery_verifications == 1)
            or (failure_stage == "verify_after_stash" and recovery_verifications == 2)
        )
        if fail_create or fail_verify:
            return subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr="injected snapshot failure"
            )
        return _runner(repo_root, args, op=op, network=network)

    outcome = integrate_machine_managed_sdd_repository(
        clone_dir,
        git_runner=fail_snapshot_ref,
        recovery_cooldown_seconds=0,
    )

    assert outcome.status is SddIntegrationStatus.RECOVERY_FAILED
    if failure_stage == "create":
        assert "injected snapshot failure" in (outcome.error or "")
    else:
        assert "could not verify the recovery ref" in (outcome.error or "")
    assert _snapshot(clone_dir) == starting


def test_recovery_attempt_cooldown_is_durable_and_reopens_after_window(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    (clone_dir / "README.md").write_text("keep dirty\n", encoding="utf-8")

    attempts: list[list[str]] = []
    now = [100.0]

    def fail_snapshot_ref(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["update-ref"]:
            attempts.append(args)
            return subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr="injected snapshot failure"
            )
        return _runner(repo_root, args, op=op, network=network)

    def recover():
        return integrate_machine_managed_sdd_repository(
            clone_dir,
            git_runner=fail_snapshot_ref,
            clock=lambda: now[0],
            recovery_cooldown_seconds=10,
        )

    assert recover().status is SddIntegrationStatus.RECOVERY_FAILED
    assert recover().status is SddIntegrationStatus.RECOVERY_COOLDOWN
    assert len(attempts) == 1

    now[0] = 111.0
    assert recover().status is SddIntegrationStatus.RECOVERY_FAILED
    assert len(attempts) == 2


def test_machine_managed_recovery_refuses_unrelated_git_operation(
    tmp_path: Path,
) -> None:
    _remote, left, _right = _build_diverged_clones(tmp_path)
    git(["fetch", "origin"], left)
    started = subprocess.run(
        ["git", "merge", "origin/main"],
        cwd=left,
        check=False,
        capture_output=True,
        text=True,
    )
    assert started.returncode != 0
    assert (left / ".git/MERGE_HEAD").exists()
    starting = _snapshot(left)

    outcome = integrate_machine_managed_sdd_repository(left)

    assert outcome.status is SddIntegrationStatus.UNRECOVERABLE
    assert "refuses unrelated Git operations: merge" in (outcome.error or "")
    assert _snapshot(left) == starting
    assert (left / ".git/MERGE_HEAD").exists()
    assert git(["for-each-ref", "refs/sase/recovery"], left).stdout == ""
