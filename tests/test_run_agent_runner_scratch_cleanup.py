from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from sase.axe import run_agent_runner_scratch as scratch
from sase.core.dismissed_agent_completion import GATE_OUTCOME, MONITOR_OUTCOME
from sase.env_contracts import SASE_LAUNCH_SCRATCH_KEY_ENV


def _write_payload(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "payload.txt").write_text("scratch", encoding="utf-8")


def _prepare_launch_scratch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    scratch_key: str = "proj-ws7-260914_120000",
) -> tuple[Path, Path, Path]:
    managed_root = tmp_path / "managed"
    cargo = managed_root / "cargo-targets" / scratch_key
    tmpdir = managed_root / "agent-tmp" / scratch_key
    _write_payload(cargo)
    _write_payload(tmpdir)
    monkeypatch.setattr(scratch, "managed_tmpdir_root", lambda: managed_root)
    monkeypatch.setenv(SASE_LAUNCH_SCRATCH_KEY_ENV, scratch_key)
    monkeypatch.setenv("CARGO_TARGET_DIR", str(cargo))
    monkeypatch.setenv("CARGO_BUILD_BUILD_DIR", str(cargo / "build"))
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setenv("TMP", str(tmpdir))
    monkeypatch.setenv("TEMP", str(tmpdir))
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    return proc_root, cargo, tmpdir


def _fake_process(
    proc_root: Path,
    *,
    pid: int | None = None,
    environ: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> None:
    pid = os.getpid() + 1_000_000 if pid is None else pid
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir()
    if environ is not None:
        payload = b"\0".join(
            f"{key}={value}".encode() for key, value in environ.items()
        )
        (pid_dir / "environ").write_bytes(payload + b"\0")
    if cwd is not None:
        cwd.mkdir(parents=True, exist_ok=True)
        (pid_dir / "cwd").symlink_to(cwd, target_is_directory=True)


def test_cleanup_launch_scratch_removes_launch_assigned_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root, cargo, tmpdir = _prepare_launch_scratch(monkeypatch, tmp_path)

    scratch.cleanup_launch_scratch(exec_outcome="completed", proc_root=proc_root)

    assert not cargo.exists()
    assert not tmpdir.exists()


@pytest.mark.parametrize("outcome", [MONITOR_OUTCOME, GATE_OUTCOME])
def test_cleanup_launch_scratch_skips_shell_handoff_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    outcome: str,
) -> None:
    proc_root, cargo, tmpdir = _prepare_launch_scratch(monkeypatch, tmp_path)

    scratch.cleanup_launch_scratch(exec_outcome=outcome, proc_root=proc_root)

    assert cargo.is_dir()
    assert tmpdir.is_dir()


@pytest.mark.parametrize(
    ("env_var", "under"),
    [
        ("CARGO_TARGET_DIR", "cargo"),
        ("TMPDIR", "tmpdir"),
    ],
)
def test_cleanup_launch_scratch_keeps_both_directories_when_environ_is_live(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env_var: str,
    under: str,
) -> None:
    proc_root, cargo, tmpdir = _prepare_launch_scratch(monkeypatch, tmp_path)
    live_root = cargo if under == "cargo" else tmpdir
    _fake_process(proc_root, environ={env_var: str(live_root / "nested")})

    scratch.cleanup_launch_scratch(exec_outcome="completed", proc_root=proc_root)

    assert cargo.is_dir()
    assert tmpdir.is_dir()


def test_cleanup_launch_scratch_keeps_both_directories_when_cwd_is_live(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root, cargo, tmpdir = _prepare_launch_scratch(monkeypatch, tmp_path)
    _fake_process(proc_root, cwd=tmpdir / "session")

    scratch.cleanup_launch_scratch(exec_outcome="completed", proc_root=proc_root)

    assert cargo.is_dir()
    assert tmpdir.is_dir()


def test_cleanup_launch_scratch_skips_without_key_or_procfs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root, cargo, tmpdir = _prepare_launch_scratch(monkeypatch, tmp_path)
    monkeypatch.delenv(SASE_LAUNCH_SCRATCH_KEY_ENV)

    scratch.cleanup_launch_scratch(exec_outcome="completed", proc_root=proc_root)

    assert cargo.is_dir()
    assert tmpdir.is_dir()

    monkeypatch.setenv(SASE_LAUNCH_SCRATCH_KEY_ENV, "proj-ws7-260914_120000")
    scratch.cleanup_launch_scratch(
        exec_outcome="completed",
        proc_root=tmp_path / "missing-proc",
    )

    assert cargo.is_dir()
    assert tmpdir.is_dir()


def test_cleanup_launch_scratch_preserves_overridden_and_bucket_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root, cargo, tmpdir = _prepare_launch_scratch(monkeypatch, tmp_path)
    managed_root = tmp_path / "managed"
    bucket = managed_root / "cargo-targets"
    other_child = bucket / "other-launch"
    _write_payload(other_child)
    monkeypatch.setenv("CARGO_TARGET_DIR", str(other_child))
    monkeypatch.setenv("TMPDIR", str(managed_root / "agent-tmp"))

    scratch.cleanup_launch_scratch(exec_outcome="completed", proc_root=proc_root)

    assert cargo.is_dir()
    assert tmpdir.is_dir()
    assert other_child.is_dir()
    assert bucket.is_dir()


def test_cleanup_launch_scratch_preserves_symlink_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink test requires os.symlink")
    proc_root, cargo, tmpdir = _prepare_launch_scratch(monkeypatch, tmp_path)
    shutil.rmtree(cargo)
    outside = tmp_path / "outside"
    outside.mkdir()
    cargo.symlink_to(outside, target_is_directory=True)

    scratch.cleanup_launch_scratch(exec_outcome="completed", proc_root=proc_root)

    assert cargo.is_symlink()
    assert outside.is_dir()
    assert not tmpdir.exists()


def test_cleanup_launch_scratch_swallows_rmtree_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root, cargo, tmpdir = _prepare_launch_scratch(monkeypatch, tmp_path)

    def fail_rmtree(_path: Path) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(scratch.shutil, "rmtree", fail_rmtree)

    scratch.cleanup_launch_scratch(exec_outcome="completed", proc_root=proc_root)

    assert cargo.is_dir()
    assert tmpdir.is_dir()
