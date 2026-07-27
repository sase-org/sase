"""Tests for remote bead synchronization."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from sase.bead.sync import (
    commit_bead_work_launch,
    git_sync,
    publish_bead_claim,
    push_bead_work_launch,
    refresh_bead_store,
    refresh_current_bead_store,
)
from sase.bead.sync_worker import run_managed_sync_worker
from sase.sdd._git_contention import (
    DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS,
    ENV_GIT_LOCK_RETRY_DELAYS,
    store_git_write_lock,
)
from sase.sdd._repository_recovery_markers import FAILED_INTEGRATION_MARKER

from .sync_test_helpers import configure_git_identity, init_git_repo


@pytest.mark.parametrize(
    ("is_in_tree", "remote_url"),
    [(True, "git@example.test:plans.git"), (False, None)],
)
def test_refresh_current_bead_store_skips_non_remote_locations(
    tmp_path,
    monkeypatch,
    is_in_tree,
    remote_url,
):
    location = SimpleNamespace(
        root=tmp_path,
        beads_dir=tmp_path / "beads",
        is_in_tree=is_in_tree,
        store=SimpleNamespace(remote_url=remote_url),
    )
    monkeypatch.setattr(
        "sase.bead.cli_common.resolve_beads_location",
        lambda **_kwargs: location,
    )

    def unexpected_integration(*_args, **_kwargs):
        raise AssertionError("non-remote stores must not integrate")

    monkeypatch.setattr(
        "sase.sdd._repository_transaction.integrate_sdd_repository",
        unexpected_integration,
    )

    refresh_current_bead_store()


def test_refresh_current_bead_store_integrates_without_push(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@example.test:plans.git"],
        cwd=tmp_path,
        check=True,
    )
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    location = SimpleNamespace(
        root=tmp_path,
        beads_dir=beads_dir,
        is_in_tree=False,
        store=SimpleNamespace(remote_url="git@example.test:plans.git"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_common.resolve_beads_location",
        lambda **_kwargs: location,
    )
    calls = []

    def integrate(repo_root, **kwargs):
        calls.append((repo_root, kwargs))
        return SimpleNamespace(succeeded=True)

    monkeypatch.setattr(
        "sase.sdd._repository_transaction.integrate_sdd_repository",
        integrate,
    )

    refresh_current_bead_store()

    assert len(calls) == 1
    repo_root, kwargs = calls[0]
    assert repo_root == tmp_path
    assert kwargs["beads_dir"] == beads_dir
    assert kwargs["op_prefix"] == "bead.refresh"
    assert callable(kwargs["lock_factory"])


def test_refresh_bead_store_clears_failed_integration_marker(
    tmp_path,
    monkeypatch,
):
    init_git_repo(tmp_path)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@example.test:plans.git"],
        cwd=tmp_path,
        check=True,
    )
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    marker = tmp_path / ".git" / FAILED_INTEGRATION_MARKER
    marker.write_text(
        json.dumps({"clone_path": str(tmp_path), "timestamp": 0.0}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.sdd._repository_transaction.integrate_sdd_repository",
        lambda *_args, **_kwargs: SimpleNamespace(succeeded=True),
    )

    refresh_bead_store(beads_dir)

    assert not marker.exists()


def test_refresh_current_bead_store_raises_on_failed_integration(
    tmp_path,
    monkeypatch,
):
    init_git_repo(tmp_path)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@example.test:plans.git"],
        cwd=tmp_path,
        check=True,
    )
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    location = SimpleNamespace(
        root=tmp_path,
        beads_dir=beads_dir,
        is_in_tree=False,
        store=SimpleNamespace(remote_url="git@example.test:plans.git"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_common.resolve_beads_location",
        lambda **_kwargs: location,
    )
    outcome = SimpleNamespace(
        succeeded=False,
        error="git fetch failed",
        status=SimpleNamespace(value="remote_unavailable_but_healthy"),
    )
    monkeypatch.setattr(
        "sase.sdd._repository_transaction.integrate_sdd_repository",
        lambda *_args, **_kwargs: outcome,
    )

    with pytest.raises(RuntimeError, match="git fetch failed"):
        refresh_current_bead_store()


def test_refresh_bead_store_lock_timeout_declines_a_contended_clone(
    tmp_path,
    monkeypatch,
):
    init_git_repo(tmp_path)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@example.test:plans.git"],
        cwd=tmp_path,
        check=True,
    )
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    monkeypatch.setattr(
        "sase.sdd._repository_transaction.integrate_sdd_repository",
        lambda *_args, **_kwargs: pytest.fail("contended refresh must not integrate"),
    )
    holder_acquired = threading.Event()
    release_holder = threading.Event()

    def hold_lock():
        with store_git_write_lock(
            tmp_path,
            op="test.hold",
            mutates_worktree=True,
        ) as acquired:
            assert acquired
            holder_acquired.set()
            release_holder.wait(timeout=30)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    try:
        assert holder_acquired.wait(timeout=10)
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="refresh lock"):
            refresh_bead_store(beads_dir, lock_timeout=0.5)
        elapsed = time.monotonic() - started
    finally:
        release_holder.set()
        holder.join(timeout=30)

    assert elapsed < DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS


def test_refresh_bead_store_skips_in_tree_store(tmp_path, monkeypatch):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)

    monkeypatch.setattr(
        "sase.bead.sync._find_git_root",
        lambda _beads_dir: pytest.fail("in-tree store must not inspect git"),
    )

    refresh_bead_store(beads_dir)


def test_publish_bead_claim_skips_in_tree_store(tmp_path, monkeypatch):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda _beads_dir: pytest.fail("in-tree claims must not be published"),
    )

    outcome = publish_bead_claim(beads_dir, "sase-1", "worker")

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is True
    assert outcome.error is None


def test_git_sync_retries_transient_index_lock(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    state_file = beads_dir / "issues.jsonl"
    state_file.write_text('{"id":"test"}\n', encoding="utf-8")
    lock_path = tmp_path / ".git/index.lock"
    lock_path.touch()
    monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, "0.01,0.02,0.04,0.08")
    release = threading.Timer(0.03, lambda: lock_path.unlink(missing_ok=True))
    release.start()

    try:
        git_sync(beads_dir)
    finally:
        release.cancel()
        lock_path.unlink(missing_ok=True)

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert staged == ["sdd/beads/issues.jsonl"]


def test_commit_bead_work_launch_retries_transient_index_lock(
    tmp_path,
    monkeypatch,
):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text(
        '{"id":"test"}\n',
        encoding="utf-8",
    )
    lock_path = tmp_path / ".git/index.lock"
    lock_path.touch()
    monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, "0.01,0.02,0.04,0.08")
    release = threading.Timer(0.03, lambda: lock_path.unlink(missing_ok=True))
    release.start()

    try:
        committed = commit_bead_work_launch(
            beads_dir,
            "sase-1",
            kind="epic",
        )
    finally:
        release.cancel()
        lock_path.unlink(missing_ok=True)

    assert committed is True


def test_push_bead_work_launch_skips_when_no_remote(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is True
    assert outcome.error is None


def test_push_bead_work_launch_skips_outside_git_repo(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is True
    assert outcome.error is None


def test_push_bead_work_launch_returns_error_when_git_root_probe_raises(
    tmp_path,
    monkeypatch,
):
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    monkeypatch.setattr(
        "sase.bead.sync._find_git_root",
        lambda _beads_dir: (_ for _ in ()).throw(
            RuntimeError("timed out probing git root")
        ),
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is False
    assert outcome.error == "timed out probing git root"


def test_push_bead_work_launch_pushes_to_remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        capture_output=True,
        check=True,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is True
    assert outcome.skipped_no_remote is False
    assert outcome.error is None

    local_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    remote_head = subprocess.run(
        ["git", "rev-parse", f"refs/heads/{branch}"],
        cwd=bare,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert local_head == remote_head


def test_push_bead_work_launch_rebases_and_retries_rejected_push(tmp_path, monkeypatch):
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
    )

    seed = tmp_path / "seed"
    seed.mkdir()
    init_git_repo(seed)
    subprocess.run(["git", "branch", "-M", "main"], cwd=seed, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=seed,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=seed,
        capture_output=True,
        check=True,
    )

    repo = tmp_path / "repo"
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(bare), str(repo)], capture_output=True, check=True
    )
    subprocess.run(
        ["git", "clone", str(bare), str(other)], capture_output=True, check=True
    )
    configure_git_identity(repo)
    configure_git_identity(other)

    (other / "remote.md").write_text("remote\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "remote.md"], cwd=other, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "remote change"],
        cwd=other,
        capture_output=True,
        check=True,
    )

    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"local"}\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "local bead change"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    from sase.sdd._repository_health import default_git_runner

    raced = False

    def push_remote_just_before_local_push(repo_root, args, *, op, network=False):
        nonlocal raced
        if args == ["push"] and not raced:
            raced = True
            subprocess.run(
                ["git", "push"],
                cwd=other,
                capture_output=True,
                check=True,
            )
        return default_git_runner(
            repo_root,
            args,
            op=op,
            network=network,
        )

    monkeypatch.setattr(
        "sase.bead.sync_worker._git",
        push_remote_just_before_local_push,
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is True
    assert outcome.skipped_no_remote is False
    assert outcome.error is None
    assert raced is True
    assert (repo / "remote.md").read_text(encoding="utf-8") == "remote\n"

    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", str(bare), str(verify)],
        capture_output=True,
        check=True,
    )
    assert (verify / "remote.md").read_text(encoding="utf-8") == "remote\n"
    assert (verify / "sdd/beads/issues.jsonl").read_text(encoding="utf-8") == (
        '{"id":"local"}\n'
    )


def test_push_bead_work_launch_returns_error_on_failure(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    subprocess.run(
        ["git", "remote", "add", "origin", str(tmp_path / "does-not-exist.git")],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is False
    assert outcome.error is not None
    assert "git fetch failed" in outcome.error


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
