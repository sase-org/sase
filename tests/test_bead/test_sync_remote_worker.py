"""Tests for the managed remote bead sync worker."""

from __future__ import annotations

import fcntl
import json
import subprocess
import threading
import time
from contextlib import contextmanager

import pytest

from sase.bead.sync_worker import _ManagedSyncOutcome, run_managed_sync_worker

from .sync_test_helpers import configure_git_identity, init_git_repo


def test_managed_sync_worker_default_lock_wait_skips_immediately(
    tmp_path,
    monkeypatch,
):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    lock_file = open(tmp_path / ".git/sase-bead-sync.lock", "a+", encoding="utf-8")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(
        "sase.bead.sync_worker._run_locked_sync",
        lambda *_args, **_kwargs: pytest.fail("locked worker must not run"),
    )

    try:
        started = time.monotonic()
        outcome = run_managed_sync_worker(
            tmp_path,
            beads_dir,
            log_path=tmp_path / "sync.log",
        )
        elapsed = time.monotonic() - started
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

    assert elapsed < 0.1
    assert outcome.pushed is False
    assert outcome.skipped_locked is True
    records = _read_records(tmp_path / "sync.log")
    assert records[-1]["event"] == "skipped"
    assert records[-1]["reason"] == "worker_already_running"


def test_managed_sync_worker_positive_lock_wait_acquires_after_release(
    tmp_path,
    monkeypatch,
):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    lock_file = open(tmp_path / ".git/sase-bead-sync.lock", "a+", encoding="utf-8")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def release_lock() -> None:
        time.sleep(0.03)  # sase-test-wait: held flock overlap window
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    release = threading.Thread(target=release_lock)
    release.start()
    monkeypatch.setattr(
        "sase.bead.sync_worker._run_locked_sync",
        lambda *_args, **_kwargs: _ManagedSyncOutcome(
            pushed=True,
            integrated=False,
        ),
    )

    try:
        outcome = run_managed_sync_worker(
            tmp_path,
            beads_dir,
            log_path=tmp_path / "sync.log",
            worker_lock_wait=0.2,
        )
    finally:
        release.join(timeout=5)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

    assert outcome.pushed is True
    records = _read_records(tmp_path / "sync.log")
    acquired = [
        record for record in records if record["event"] == "worker_lock_acquired"
    ]
    assert acquired
    assert acquired[-1]["waited_seconds"] > 0


def test_managed_sync_worker_positive_lock_wait_times_out_with_waited_seconds(
    tmp_path,
    monkeypatch,
):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    lock_file = open(tmp_path / ".git/sase-bead-sync.lock", "a+", encoding="utf-8")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(
        "sase.bead.sync_worker._run_locked_sync",
        lambda *_args, **_kwargs: pytest.fail("timed-out worker must not run"),
    )

    try:
        outcome = run_managed_sync_worker(
            tmp_path,
            beads_dir,
            log_path=tmp_path / "sync.log",
            worker_lock_wait=0.02,
        )
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

    assert outcome.pushed is False
    assert outcome.skipped_locked is True
    records = _read_records(tmp_path / "sync.log")
    assert records[-1]["event"] == "skipped"
    assert records[-1]["reason"] == "worker_already_running"
    assert records[-1]["waited_seconds"] >= 0.0


def test_managed_sync_worker_converges_sidecar_store_mutations(tmp_path, monkeypatch):
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    init_git_repo(seed)
    subprocess.run(["git", "branch", "-M", "main"], cwd=seed, check=True)
    (seed / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname="beads") as project:
        first = project.create("First", IssueType.PLAN)
        second = project.create("Second", IssueType.PLAN)
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "commit", "-m", "seed beads"],
        cwd=seed,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=seed, check=True)
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=seed,
        check=True,
        capture_output=True,
    )

    left = tmp_path / "left"
    right = tmp_path / "right"
    subprocess.run(
        ["git", "clone", str(bare), str(left)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "clone", str(bare), str(right)], check=True, capture_output=True
    )
    configure_git_identity(left)
    configure_git_identity(right)

    with BeadProject(left, beads_dirname="beads") as project:
        project.update(first.id, title="First from left")
    subprocess.run(["git", "add", "beads"], cwd=left, check=True)
    subprocess.run(
        ["git", "commit", "-m", "left mutation"],
        cwd=left,
        check=True,
        capture_output=True,
    )

    with BeadProject(right, beads_dirname="beads") as project:
        project.update(second.id, title="Second from right")
    subprocess.run(["git", "add", "beads"], cwd=right, check=True)
    subprocess.run(
        ["git", "commit", "-m", "right mutation"],
        cwd=right,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "push"], cwd=right, check=True, capture_output=True)

    lock_path = left / ".git" / "index.lock"
    lock_path.touch()
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001")
    monkeypatch.delenv("SASE_SDD_GIT_LOCK_RETRY_DELAYS", raising=False)

    log_path = tmp_path / "managed-sync.log"
    outcome = run_managed_sync_worker(
        left,
        left / "beads",
        log_path=log_path,
    )

    assert outcome.pushed is True
    assert outcome.integrated is True
    assert not lock_path.exists()
    assert not (left / ".git/rebase-merge").exists()
    assert not (left / ".git/rebase-apply").exists()
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=left,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    verify = tmp_path / "verify-convergence"
    subprocess.run(
        ["git", "clone", str(bare), str(verify)], check=True, capture_output=True
    )
    with BeadProject(verify, beads_dirname="beads") as project:
        assert project.show(first.id).title == "First from left"
        assert project.show(second.id).title == "Second from right"
    log_events = [
        json.loads(line)["event"]
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert log_events[-1] == "completed"


def test_managed_sync_worker_locks_local_integration_only(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    lock_active = False
    operations: list[tuple[str, bool, bool]] = []

    @contextmanager
    def probe_store_write_lock(repo_root, *, op=None, mutates_worktree=False):
        nonlocal lock_active
        assert repo_root == tmp_path.resolve()
        assert op == "bead.sync.transaction"
        assert mutates_worktree is True
        assert lock_active is False
        lock_active = True
        try:
            yield True
        finally:
            lock_active = False

    def fake_git(repo_root, args, *, op, network=False):
        del repo_root
        operations.append((op, lock_active, network))
        returncode = 1 if op == "bead.sync.ancestor" else 0
        stdout_by_op = {
            "bead.sync.upstream": "upstream\n",
            "sdd.health.worktree": "true\n",
            "sdd.health.git_dir": ".git\n",
            "sdd.health.branch": "master\n",
            "sdd.health.head": "starting-head\n",
        }
        stdout = stdout_by_op.get(op, "")
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=returncode,
            stdout=stdout,
            stderr="",
        )

    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        probe_store_write_lock,
    )
    monkeypatch.setattr("sase.bead.sync_worker._git", fake_git)

    outcome = run_managed_sync_worker(
        tmp_path,
        beads_dir,
        log_path=tmp_path / "sync.log",
    )

    assert outcome.pushed is True
    assert outcome.integrated is True
    by_op = {op: (locked, network) for op, locked, network in operations}
    assert by_op["bead.sync.fetch"] == (False, True)
    assert by_op["bead.sync.upstream"] == (True, False)
    assert by_op["bead.sync.ancestor"] == (True, False)
    assert by_op["sdd.health.status"] == (True, False)
    assert by_op["bead.sync.rebase"] == (True, False)
    assert by_op["bead.sync.push"] == (False, True)


def _read_records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
