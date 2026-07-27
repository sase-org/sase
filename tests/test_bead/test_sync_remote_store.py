"""Tests for remote bead store refresh and staging."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from sase.bead.sync import (
    commit_bead_work_launch,
    git_sync,
    publish_bead_claim,
    refresh_bead_store,
    refresh_current_bead_store,
)
from sase.sdd._git_contention import (
    DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS,
    ENV_GIT_LOCK_RETRY_DELAYS,
    store_git_write_lock,
)
from sase.sdd._repository_recovery_markers import FAILED_INTEGRATION_MARKER

from .sync_test_helpers import init_git_repo


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
