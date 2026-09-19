from __future__ import annotations

import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from sase.sdd._git import run_sdd_git
from sase.sdd._store_clone_ops import clone_sdd_store, clone_sdd_store_from_primary
from sase.sdd._store_link import ensure_sidecar_sdd_clone
from sase.sdd._store_types import (
    SddMaterializationError,
    SddTransientMaterializationError,
)
from tests.sdd_store._helpers import (
    clone,
    commit_all,
    git,
    init_bare_repo,
    init_git_identity,
)


def _hold_remote_clone_slot(lock_dir: Path) -> int:
    lock_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_dir / "slot-0.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def _stage_clone_path(args: list[str]) -> Path:
    return Path(args[-1])


def _write_partial_clone(args: list[str]) -> Path:
    target = _stage_clone_path(args)
    target.mkdir(parents=True, exist_ok=True)
    (target / "partial").write_text("incomplete", encoding="utf-8")
    return target


def _write_valid_clone(args: list[str]) -> Path:
    target = _stage_clone_path(args)
    remote = args[-2]
    target.mkdir(parents=True, exist_ok=True)
    git(["init", "-q", "-b", "main"], target)
    init_git_identity(target)
    (target / "README.md").write_text("# staged clone\n", encoding="utf-8")
    commit_all(target, "Initialize staged clone")
    git(["remote", "add", "origin", remote], target)
    git(["update-ref", "refs/remotes/origin/main", "HEAD"], target)
    git(["branch", "--set-upstream-to=origin/main", "main"], target)
    return target


def _normalized_clone_calls(
    calls: list[list[str]],
    clone_dir: Path,
) -> list[list[str]]:
    normalized: list[list[str]] = []
    for args in calls:
        stage = _stage_clone_path(args)
        assert stage != clone_dir
        assert stage.name == "clone"
        assert stage.parent.parent == clone_dir.parent / ".sase-sdd-clone-staging"
        normalized.append([*args[:-1], str(clone_dir)])
    return normalized


def _seed_remote(tmp_path: Path, name: str = "remote.git") -> Path:
    remote = tmp_path / name
    seed = tmp_path / f"{name}-seed"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    return remote


@pytest.fixture(autouse=True)
def _fake_clone_retryability(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_is_retryable(detail: str) -> bool:
        folded = detail.casefold()
        return "early eof" in folded or "unexpected disconnect" in folded

    monkeypatch.setattr(
        "sase.sdd._store_clone_ops.is_retryable_git_clone_failure",
        fake_is_retryable,
    )


def test_run_sdd_git_records_margin_and_supplied_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[dict[str, object]] = []
    monkeypatch.setattr("sase.logs.log_tui_git_operation", records.append)

    run_sdd_git(
        ["--version"],
        cwd=tmp_path,
        op="sdd.clone.remote",
        timeout=10.0,
        check=True,
        capture_output=True,
        text=True,
        always_log=True,
        telemetry={
            "retry_attempt_index": 2,
            "retry_attempts_total": 4,
            "reference_repo_used": False,
            "sdd_store_name": "plans",
        },
    )

    assert len(records) == 1
    record = records[0]
    assert record["retry_attempt_index"] == 2
    assert record["retry_attempts_total"] == 4
    assert record["reference_repo_used"] is False
    assert record["sdd_store_name"] == "plans"
    assert record["duration_limit_ratio"] >= 0
    assert record["duration_limit_margin_ms"] <= 10_000.0


def test_sidecar_clone_failure_removes_partial_target_and_surfaces_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    attempts = 0

    def failed_clone(args: list[str], **_kwargs):
        nonlocal attempts
        attempts += 1
        _write_partial_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr="authentication failed for plans remote",
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", failed_clone)
    monkeypatch.setattr(
        "sase.sdd._store_link._clone_sdd_store_from_primary",
        lambda *_args: pytest.fail("clone failure used a local fallback"),
    )

    with pytest.raises(
        SddMaterializationError, match="authentication failed for plans remote"
    ):
        ensure_sidecar_sdd_clone(clone_dir, remote, strict=True)

    assert not clone_dir.exists()
    assert attempts == 1


def test_sidecar_clone_retries_transient_transport_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    attempts = 0
    sleeps: list[float] = []

    def flaky_clone(args: list[str], **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            _write_partial_clone(args)
            return subprocess.CompletedProcess(
                args=["git", "clone"],
                returncode=128,
                stdout="",
                stderr=(
                    "Connection to ssh.example.test closed by remote host.\n"
                    "fetch-pack: unexpected disconnect while reading sideband packet\n"
                    "fatal: early EOF\n"
                    "fatal: fetch-pack: invalid index-pack output"
                ),
            )
        _write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", flaky_clone)
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.sleep", sleeps.append)

    ensure_sidecar_sdd_clone(clone_dir, remote, strict=True)

    assert attempts == 3
    assert sleeps == [0.25, 1.0]
    assert not (clone_dir / "partial").exists()


def test_remote_clone_waits_for_host_clone_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    lock_dir = tmp_path / "clone-pool"
    held_fd = _hold_remote_clone_slot(lock_dir)
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
        _write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setenv("SASE_SDD_REMOTE_CLONE_CONCURRENCY", "1")
    monkeypatch.setattr(
        "sase.sdd._store_clone_ops._remote_clone_lock_dir",
        lambda: lock_dir,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", successful_clone)
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.sleep", release_during_sleep)

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
    held_fd = _hold_remote_clone_slot(lock_dir)
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
        "sase.sdd._store_clone_ops._remote_clone_lock_dir",
        lambda: lock_dir,
    )
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.monotonic", lambda: now[0])
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.sleep", advance_past_deadline)
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
        _write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_ops._remote_clone_lock_dir",
        lambda: pytest.fail("local clone tried to enter remote clone pool"),
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", successful_clone)

    assert clone_sdd_store(remote, clone_dir, strict=True) is True


def test_sidecar_clone_promotes_after_successful_staged_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = _seed_remote(tmp_path)
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
    remote = _seed_remote(tmp_path)
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
    remote = _seed_remote(tmp_path)
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    clone_calls = 0

    def clone_and_materialize_destination(args: list[str], **_kwargs):
        nonlocal clone_calls
        clone_calls += 1
        _write_valid_clone(args)
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
    remote = _seed_remote(tmp_path)
    other = _seed_remote(tmp_path, "other.git")
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"

    def clone_and_materialize_wrong_destination(args: list[str], **_kwargs):
        _write_valid_clone(args)
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
        target = _stage_clone_path(args)
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
    remote = _seed_remote(tmp_path)
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


def test_sidecar_clone_timeout_retries_without_reference_and_cleans_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    reference = tmp_path / "primary" / "sase" / "repos" / "plans"
    calls: list[list[str]] = []
    from sase.sdd._commit import SddGitCommandTimeout

    def timeout_then_success(args: list[str], **_kwargs):
        calls.append(list(args))
        if len(calls) == 1:
            _write_partial_clone(args)
            raise SddGitCommandTimeout("injected timeout")
        assert not _stage_clone_path(calls[0]).exists()
        _write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_ops._matching_clone_reference",
        lambda _reference_repo, _remote_url: reference,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", timeout_then_success)

    assert (
        clone_sdd_store(
            remote,
            clone_dir,
            reference_repo=reference,
            strict=True,
        )
        is True
    )

    assert _normalized_clone_calls(calls, clone_dir) == [
        [
            "clone",
            "--reference-if-able",
            str(reference),
            "--dissociate",
            remote,
            str(clone_dir),
        ],
        ["clone", remote, str(clone_dir)],
    ]


def test_sidecar_clone_timeout_retries_with_no_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    calls: list[list[str]] = []
    sleeps: list[float] = []
    from sase.sdd._commit import SddGitCommandTimeout

    def timeout_then_success(args: list[str], **_kwargs):
        calls.append(list(args))
        if len(calls) == 1:
            _write_partial_clone(args)
            raise SddGitCommandTimeout("injected timeout")
        assert not _stage_clone_path(calls[0]).exists()
        _write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", timeout_then_success)
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.sleep", sleeps.append)

    assert clone_sdd_store(remote, clone_dir, strict=True) is True

    assert _normalized_clone_calls(calls, clone_dir) == [
        ["clone", remote, str(clone_dir)],
        ["clone", remote, str(clone_dir)],
    ]
    assert sleeps == [0.25]


def test_sidecar_clone_passes_attempt_telemetry_to_git_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    reference = tmp_path / "primary" / "sase" / "repos" / "plans"
    telemetry: list[dict[str, object]] = []

    def fail_then_success(args: list[str], **kwargs):
        telemetry.append(dict(kwargs["telemetry"]))
        if len(telemetry) == 1:
            _write_partial_clone(args)
            return subprocess.CompletedProcess(
                args=["git", "clone"],
                returncode=128,
                stdout="",
                stderr="fatal: early EOF",
            )
        _write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_ops._matching_clone_reference",
        lambda _reference_repo, _remote_url: reference,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", fail_then_success)
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.sleep", lambda _delay: None)

    assert clone_sdd_store(remote, clone_dir, reference_repo=reference, strict=True)

    assert telemetry[0]["retry_attempt_index"] == 0
    assert telemetry[0]["retry_attempts_total"] == 4
    assert telemetry[0]["reference_repo_used"] is True
    assert telemetry[0]["sdd_store_name"] == "plans"
    assert Path(str(telemetry[0]["sdd_clone_stage_path"])).name == "clone"
    assert telemetry[1]["retry_attempt_index"] == 1
    assert telemetry[1]["reference_repo_used"] is False


def test_sidecar_clone_timeout_budget_escalates_across_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    timeouts: list[float] = []
    from sase.sdd._commit import SddGitCommandTimeout

    def timeout_twice_then_success(args: list[str], timeout: float, **_kwargs):
        timeouts.append(timeout)
        if len(timeouts) < 3:
            _write_partial_clone(args)
            raise SddGitCommandTimeout("injected timeout")
        _write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.network_git_timeout", lambda: 120.0)
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", timeout_twice_then_success)
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.sleep", lambda _delay: None)

    assert clone_sdd_store(remote, clone_dir, strict=True) is True

    assert timeouts == [120.0, 180.0, 240.0]


def test_sidecar_clone_timeout_retry_honors_deadline_exhaustion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    now = [100.0]
    calls = 0
    from sase.sdd._commit import SddGitCommandTimeout

    def timeout_clone(args: list[str], **_kwargs):
        nonlocal calls
        calls += 1
        _write_partial_clone(args)
        now[0] = 105.0
        raise SddGitCommandTimeout("injected timeout")

    monkeypatch.setattr("sase.sdd._commit.network_git_timeout", lambda: 120.0)
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", timeout_clone)
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.monotonic", lambda: now[0])
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.sleep", lambda _delay: None)

    with pytest.raises(
        SddMaterializationError,
        match="deadline expired before retrying SDD clone",
    ):
        clone_sdd_store(
            remote,
            clone_dir,
            strict=True,
            deadline=105.0,
        )

    assert calls == 1
    assert not clone_dir.exists()


@pytest.mark.parametrize("strict", [False, True])
def test_sidecar_clone_timeout_reference_fallback_then_retry_schedule_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    reference = tmp_path / "primary" / "sase" / "repos" / "plans"
    calls: list[list[str]] = []
    from sase.sdd._commit import SddGitCommandTimeout

    def timeout_clone(args: list[str], **_kwargs):
        calls.append(list(args))
        _write_partial_clone(args)
        raise SddGitCommandTimeout("injected timeout")

    monkeypatch.setattr(
        "sase.sdd._store_clone_ops._matching_clone_reference",
        lambda _reference_repo, _remote_url: reference,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", timeout_clone)
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.sleep", lambda _delay: None)

    if strict:
        with pytest.raises(
            SddMaterializationError,
            match="timed out cloning SDD store",
        ):
            clone_sdd_store(
                remote,
                clone_dir,
                reference_repo=reference,
                strict=True,
            )
    else:
        assert (
            clone_sdd_store(
                remote,
                clone_dir,
                reference_repo=reference,
                strict=False,
            )
            is False
        )

    assert _normalized_clone_calls(calls, clone_dir) == [
        [
            "clone",
            "--reference-if-able",
            str(reference),
            "--dissociate",
            remote,
            str(clone_dir),
        ],
        ["clone", remote, str(clone_dir)],
        ["clone", remote, str(clone_dir)],
        ["clone", remote, str(clone_dir)],
    ]
    assert not clone_dir.exists()


def test_sidecar_clone_checkout_failure_retries_without_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    reference = tmp_path / "primary" / "sase" / "repos" / "plans"
    calls: list[list[str]] = []
    sleeps: list[float] = []

    def checkout_failure_then_success(args: list[str], **_kwargs):
        calls.append(list(args))
        if len(calls) == 1:
            _write_partial_clone(args)
            return subprocess.CompletedProcess(
                args=["git", "clone"],
                returncode=128,
                stdout="",
                stderr=(
                    "fatal: unable to parse commit "
                    "8c09ae950bbf8201016911d1c9c90726b426e11b\n"
                    "warning: Clone succeeded, but checkout failed."
                ),
            )
        assert not _stage_clone_path(calls[0]).exists()
        _write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_ops._matching_clone_reference",
        lambda _reference_repo, _remote_url: reference,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", checkout_failure_then_success)
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.sleep", sleeps.append)

    assert (
        clone_sdd_store(
            remote,
            clone_dir,
            reference_repo=reference,
            strict=True,
        )
        is True
    )

    assert "--reference-if-able" in calls[0]
    assert "--reference-if-able" not in calls[1]
    assert sleeps == []


def test_sidecar_clone_reference_fallback_is_capped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    reference = tmp_path / "primary" / "sase" / "repos" / "plans"
    calls: list[list[str]] = []
    diagnostic = (
        "fatal: unable to parse commit "
        "8c09ae950bbf8201016911d1c9c90726b426e11b\n"
        "warning: Clone succeeded, but checkout failed."
    )

    def always_fail(args: list[str], **_kwargs):
        calls.append(list(args))
        _write_partial_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr=diagnostic,
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_ops._matching_clone_reference",
        lambda _reference_repo, _remote_url: reference,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", always_fail)

    with pytest.raises(SddMaterializationError, match="unable to parse commit"):
        clone_sdd_store(
            remote,
            clone_dir,
            reference_repo=reference,
            strict=True,
        )

    assert _normalized_clone_calls(calls, clone_dir) == [
        [
            "clone",
            "--reference-if-able",
            str(reference),
            "--dissociate",
            remote,
            str(clone_dir),
        ],
        ["clone", remote, str(clone_dir)],
    ]
    assert not clone_dir.exists()
