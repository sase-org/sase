"""Ownership preservation and push-retry repairs."""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path

from sase.agents_sync.git import run_git
from sase.agents_sync.publication_state_repair import repair_project_run_states
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.git_sync_fixtures import git, setup_repo, target

from tests.agents_sync.test_publication_state_repair._helpers import (
    OWNER,
    SeedBuilder,
    commit_push,
    inv_run,
    make_loader,
    remote_head,
    remote_state,
    setup_repair,
)


def test_foreign_owner_preservation(tmp_path: Path) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    alice = SeedBuilder(sidecar)
    alice.add_run("foo", "foo.job", "run-1", "active")
    alice.write_manifest()
    bob_owner = AgentOwnerIdentity("bob", "zeus")
    bob = SeedBuilder(sidecar, owner=bob_owner)
    bob.add_run("other", "other", "run-9", "active")
    bob.write_manifest()
    commit_push(sidecar)
    bob_snapshot_before = (
        sidecar
        / "users"
        / "bob"
        / "machines"
        / "zeus"
        / "hoods"
        / "other"
        / "snapshot.json"
    ).read_bytes()
    sync_target = target(tmp_path, remote, sidecar)

    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([inv_run("run-1", "foo.job", "completed")], []),
    )

    assert report.error is None and report.changed == 1
    assert (
        sidecar
        / "users"
        / "bob"
        / "machines"
        / "zeus"
        / "hoods"
        / "other"
        / "snapshot.json"
    ).read_bytes() == bob_snapshot_before
    assert remote_state(remote, "alice.athena.foo.job") == "completed"
    assert remote_state(remote, "bob.zeus.other") == "active"


def test_published_terminal_preserved_against_stale_active(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "completed")]
    )
    before = remote_head(remote)
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([inv_run("run-1", "foo.job", "active")], []),
    )

    assert report.error is None
    assert (report.changed, report.already_current) == (0, 1)
    assert remote_head(remote) == before
    assert remote_state(remote, "alice.athena.foo.job") == "completed"


def test_reused_name_different_identity_never_borrows(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    before = remote_head(remote)
    conflicting = inv_run("run-1", "fooo", "completed")
    assert conflicting.global_name == "alice.athena.fooo"
    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([conflicting], []),
    )

    assert report.error is None
    assert (report.changed, report.unresolved) == (0, 1)
    assert remote_head(remote) == before
    assert remote_state(remote, "alice.athena.foo.job") == "active"


def test_non_fast_forward_push_recomputes_and_retries(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    intruder = tmp_path / "intruder"
    git(tmp_path, "clone", str(remote), str(intruder))
    git(intruder, "config", "user.name", "Intruder")
    git(intruder, "config", "user.email", "intruder@example.test")
    push_calls = 0

    def rejecting_runner(
        cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        nonlocal push_calls
        if args == ["push"]:
            push_calls += 1
            if push_calls == 1:
                (intruder / "remote.txt").write_text("remote\n")
                git(intruder, "add", "remote.txt")
                git(intruder, "commit", "-m", "remote race")
                git(intruder, "push")
        return run_git(cwd, args, network=network, op=op)

    report = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=make_loader([inv_run("run-1", "foo.job", "completed")], []),
        git_runner=rejecting_runner,
    )

    assert report.error is None
    assert report.push_attempts == 2
    assert report.pushed and report.changed == 1
    assert remote_state(remote, "alice.athena.foo.job") == "completed"
    assert not (sync_target.sidecar_path / ".git" / "rebase-merge").exists()
    assert not (sync_target.sidecar_path / ".git" / "rebase-apply").exists()


def test_lock_busy_is_benign_skip(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    before = remote_head(remote)
    lock_path = sync_target.sidecar_path / ".git" / "sase-agents-sync.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        report = repair_project_run_states(
            sync_target,
            OWNER,
            apply=True,
            inventory_loader=make_loader(
                [inv_run("run-1", "foo.job", "completed")], []
            ),
            lock_timeout_seconds=0,
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert report.error is None
    assert report.skip_reason == "agents sync lock is busy"
    assert report.next_cursor is None
    assert remote_head(remote) == before


def test_push_failure_then_retry_converges(tmp_path: Path) -> None:
    remote, sync_target = setup_repair(
        tmp_path, runs=[("foo", "foo.job", "run-1", "active")]
    )
    before = remote_head(remote)

    def failing_runner(
        cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        if args == ["push"]:
            return subprocess.CompletedProcess(
                ["git", "push"],
                1,
                "",
                " ! [remote rejected] main -> main (pre-receive hook declined)\n"
                "error: failed to push some refs",
            )
        return run_git(cwd, args, network=network, op=op)

    loader = make_loader([inv_run("run-1", "foo.job", "completed")], [])
    failed = repair_project_run_states(
        sync_target,
        OWNER,
        apply=True,
        inventory_loader=loader,
        git_runner=failing_runner,
    )
    assert failed.error is not None
    assert failed.next_cursor is None
    assert remote_head(remote) == before

    retried = repair_project_run_states(
        sync_target, OWNER, apply=True, inventory_loader=loader
    )
    assert retried.error is None
    assert remote_state(remote, "alice.athena.foo.job") == "completed"
