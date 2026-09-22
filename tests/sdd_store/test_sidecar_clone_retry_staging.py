"""Staged promotion, clone permits, and concurrent materialization for sidecar clones."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from sase.sdd._store_clone_ops import clone_sdd_store, clone_sdd_store_from_primary
from sase.sdd._store_types import (
    SddMaterializationError,
    SddTransientMaterializationError,
)
from tests.sdd_store._helpers import (
    clone,
    git,
)

from ._clone_retry_helpers import (
    fake_clone_retryability,
    hold_remote_clone_slot,
    seed_remote,
    stage_clone_path,
    write_valid_clone,
)


@pytest.fixture(autouse=True)
def _fake_clone_retryability(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clone_retryability(monkeypatch)


def test_remote_clone_waits_for_host_clone_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    lock_dir = tmp_path / "clone-pool"
    held_fd = hold_remote_clone_slot(lock_dir)
    sleeps: list[float] = []
    released = False
    real_sleep = time.sleep

    def release_during_sleep(delay: float) -> None:
        nonlocal released
        # Patch targets stdlib time.sleep; intercept only the permit poll.
        if delay == 0.1:
            sleeps.append(delay)
            if not released:
                fcntl.flock(held_fd, fcntl.LOCK_UN)
                os.close(held_fd)
                released = True
            return
        real_sleep(delay)

    def successful_clone(args: list[str], **_kwargs):
        assert released
        write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setenv("SASE_SDD_REMOTE_CLONE_CONCURRENCY", "1")
    monkeypatch.setattr(
        "sase.sdd._store_clone_admission._remote_clone_lock_dir",
        lambda: lock_dir,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", successful_clone)
    monkeypatch.setattr(
        "sase.sdd._store_clone_admission.time.sleep", release_during_sleep
    )

    try:
        assert clone_sdd_store(remote, clone_dir, strict=True) is True
    finally:
        if not released:
            fcntl.flock(held_fd, fcntl.LOCK_UN)
            os.close(held_fd)

    assert sleeps == [0.1]


def test_remote_clone_permit_wait_respects_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    lock_dir = tmp_path / "clone-pool"
    held_fd = hold_remote_clone_slot(lock_dir)
    now = [10.0]
    calls = 0

    def advance_past_deadline(_delay: float) -> None:
        now[0] = 10.2

    def unexpected_clone(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setenv("SASE_SDD_REMOTE_CLONE_CONCURRENCY", "1")
    monkeypatch.setattr(
        "sase.sdd._store_clone_admission._remote_clone_lock_dir",
        lambda: lock_dir,
    )
    monkeypatch.setattr(
        "sase.sdd._store_clone_admission.time.monotonic", lambda: now[0]
    )
    monkeypatch.setattr(
        "sase.sdd._store_clone_admission.time.sleep", advance_past_deadline
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", unexpected_clone)

    try:
        with pytest.raises(
            SddTransientMaterializationError,
            match="timed out waiting for SDD remote clone permit",
        ):
            clone_sdd_store(remote, clone_dir, strict=True, deadline=10.1)
    finally:
        fcntl.flock(held_fd, fcntl.LOCK_UN)
        os.close(held_fd)

    assert calls == 0


def test_local_clone_bypasses_host_remote_clone_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = str(tmp_path / "remote.git")
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"

    def successful_clone(args: list[str], **_kwargs):
        write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_admission._remote_clone_lock_dir",
        lambda: pytest.fail("local clone tried to enter remote clone pool"),
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", successful_clone)

    assert clone_sdd_store(remote, clone_dir, strict=True) is True


def test_sidecar_clone_promotes_after_successful_staged_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = seed_remote(tmp_path)
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    from sase.sdd import _commit

    original_run_sdd_git = _commit.run_sdd_git
    clone_targets: list[Path] = []

    def assert_staged_clone(args: list[str], **kwargs):
        if args[:1] == ["clone"]:
            clone_targets.append(Path(args[-1]))
            assert not clone_dir.exists()
        return original_run_sdd_git(args, **kwargs)

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", assert_staged_clone)

    assert clone_sdd_store(str(remote), clone_dir, strict=True) is True

    assert len(clone_targets) == 1
    assert clone_targets[0] != clone_dir
    assert clone_targets[0].name == "clone"
    assert clone_dir.is_dir()
    assert (clone_dir / ".git").is_dir()
    assert not clone_targets[0].exists()


def test_primary_seeded_clone_uses_atomic_promotion(
    tmp_path: Path,
) -> None:
    remote = seed_remote(tmp_path)
    primary = tmp_path / "primary" / "sase" / "repos" / "plans"
    workspace = tmp_path / "workspace" / "sase" / "repos" / "plans"
    clone(remote, primary)

    assert (
        clone_sdd_store_from_primary(
            primary,
            workspace,
            remote_url=str(remote),
        )
        is True
    )

    assert workspace.is_dir()
    assert git(["remote", "get-url", "origin"], workspace).stdout.strip() == str(remote)
    assert (
        git(["rev-parse", "@{upstream}"], workspace).stdout.strip()
        == git(["rev-parse", "HEAD"], workspace).stdout.strip()
    )
    assert not [
        path
        for path in (workspace.parent / ".sase-sdd-clone-staging").iterdir()
        if path.is_dir()
    ]


def test_concurrent_healthy_destination_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = seed_remote(tmp_path)
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    clone_calls = 0

    def clone_and_materialize_destination(args: list[str], **_kwargs):
        nonlocal clone_calls
        clone_calls += 1
        write_valid_clone(args)
        clone(remote, clone_dir)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "sase.sdd._commit.run_sdd_git", clone_and_materialize_destination
    )

    assert clone_sdd_store(str(remote), clone_dir, strict=True) is True

    assert clone_calls == 1
    assert clone_dir.is_dir()
    assert git(["remote", "get-url", "origin"], clone_dir).stdout.strip() == str(remote)


def test_concurrent_mismatched_destination_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = seed_remote(tmp_path)
    other = seed_remote(tmp_path, "other.git")
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"

    def clone_and_materialize_wrong_destination(args: list[str], **_kwargs):
        write_valid_clone(args)
        clone(other, clone_dir)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "sase.sdd._commit.run_sdd_git",
        clone_and_materialize_wrong_destination,
    )

    with pytest.raises(SddMaterializationError, match="refusing to overwrite"):
        clone_sdd_store(str(remote), clone_dir, strict=True)

    assert git(["remote", "get-url", "origin"], clone_dir).stdout.strip() == str(other)


def test_successful_clone_fails_closed_when_health_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = str(tmp_path / "remote.git")
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"

    def clone_without_head(args: list[str], **_kwargs):
        target = stage_clone_path(args)
        target.mkdir(parents=True)
        git(["init", "-q", "-b", "main"], target)
        git(["remote", "add", "origin", args[-2]], target)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", clone_without_head)

    with pytest.raises(SddMaterializationError, match="resolvable HEAD"):
        clone_sdd_store(remote, clone_dir, strict=True)

    assert not clone_dir.exists()
    assert not [
        path
        for path in (clone_dir.parent / ".sase-sdd-clone-staging").iterdir()
        if path.is_dir()
    ]


def test_terminated_materializer_never_exposes_partial_canonical_clone(
    tmp_path: Path,
) -> None:
    remote = seed_remote(tmp_path)
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    marker = tmp_path / "fake-git-started"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        f"""#!{sys.executable}
from pathlib import Path
import os
import sys
import time

args = sys.argv[1:]
if "clone" in args:
    dest = Path(args[-1])
    dest.mkdir(parents=True, exist_ok=True)
    (dest / ".git").mkdir(exist_ok=True)
    (dest / ".git" / "HEAD").write_text("ref: refs/heads/.invalid\\n", encoding="utf-8")
    (dest / "partial").write_text("incomplete\\n", encoding="utf-8")
    Path(os.environ["FAKE_GIT_MARKER"]).write_text(str(dest), encoding="utf-8")
    time.sleep(60)
sys.exit(0)
""",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    code = (
        "from pathlib import Path\n"
        "from sase.sdd._store_clone_ops import clone_sdd_store\n"
        f"clone_sdd_store({str(remote)!r}, Path({str(clone_dir)!r}), strict=True)\n"
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_GIT_MARKER": str(marker),
    }
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=Path.cwd(),
        env=env,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5.0
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)  # sase-test-wait: poll fake git marker from subprocess
        assert marker.exists()
        staged = Path(marker.read_text(encoding="utf-8"))
        assert staged.exists()
        assert not clone_dir.exists()

        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)

    assert not clone_dir.exists()

    assert clone_sdd_store(str(remote), clone_dir, strict=True) is True

    assert clone_dir.is_dir()
    assert not staged.exists()
    assert not list(clone_dir.parent.glob(".sdd.recovery*"))
    assert not [
        path
        for path in (clone_dir.parent / ".sase-sdd-clone-staging").iterdir()
        if path.is_dir()
    ]
