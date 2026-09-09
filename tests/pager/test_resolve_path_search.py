"""Tests for Git-backed file-path search helpers used by pager resolution."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sase.pager._resolve_path_search import (
    _capture_bounded_process_output,
    _git_ls_files,
)
from sase.pager.resolve import resolve_link, resolve_ref

from ._resolve_helpers import _context, _write


def test_resolve_ref_uses_a_unique_git_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    live = _write(workspace / "lib" / "pkg" / "deep.py")
    git_calls: list[Path] = []

    def fake_git_ls_files(directory: Path) -> tuple[str, ...] | None:
        git_calls.append(directory)
        return ("lib/pkg/deep.py",)

    monkeypatch.setattr(
        "sase.pager._resolve_path_search._git_ls_files", fake_git_ls_files
    )

    target = resolve_ref("pkg/deep.py", context=_context(workspace))

    assert target is not None
    assert target.edit_path == live.resolve()
    assert git_calls == [workspace.resolve()]


def test_resolve_ref_dead_ends_on_an_ambiguous_git_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(
        "sase.pager._resolve_path_search._git_ls_files",
        lambda _directory: ("lib/pkg/deep.py", "other/pkg/deep.py"),
    )

    assert resolve_ref("pkg/deep.py", context=_context(workspace)) is None


def test_resolve_ref_does_not_run_git_when_a_direct_probe_hits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _write(tmp_path / "src" / "foo.py")

    def fail_git(_directory: Path) -> tuple[str, ...] | None:
        raise AssertionError("git ls-files should not run after a direct hit")

    monkeypatch.setattr("sase.pager._resolve_path_search._git_ls_files", fail_git)

    target = resolve_ref("src/foo.py", context=_context(tmp_path))

    assert target is not None
    assert target.edit_path == live.resolve()


def test_resolve_ref_caches_git_ls_files_per_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    live = _write(workspace / "lib" / "pkg" / "deep.py")
    git_calls: list[Path] = []

    def fake_git_ls_files(directory: Path) -> tuple[str, ...] | None:
        git_calls.append(directory)
        return ("lib/pkg/deep.py",)

    monkeypatch.setattr(
        "sase.pager._resolve_path_search._git_ls_files", fake_git_ls_files
    )

    target = resolve_ref("a/pkg/deep.py", context=_context(workspace))

    assert target is not None
    assert target.edit_path == live.resolve()
    assert git_calls == [workspace.resolve()]


def test_missing_path_runs_git_once_per_anchor_across_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    git_calls: list[Path] = []

    def fake_git_ls_files(directory: Path) -> tuple[str, ...] | None:
        git_calls.append(directory)
        return ()

    monkeypatch.setattr(
        "sase.pager._resolve_path_search._git_ls_files", fake_git_ls_files
    )

    resolution = resolve_link("a/pkg/deep.py", context=_context(workspace))

    assert resolution.target is None
    assert git_calls == [workspace.resolve()]
    assert resolution.unresolved_message is not None
    assert "searched" in resolution.unresolved_message


def _python_stdout_proc(script: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def test_capture_accepts_output_at_the_byte_limit() -> None:
    payload = b"src/a.py\0lib/b.py\0"
    proc = _python_stdout_proc(
        "import sys; sys.stdout.buffer.write(" + repr(payload) + ")"
    )

    captured = _capture_bounded_process_output(
        proc, max_bytes=len(payload), timeout_seconds=2.0
    )

    assert captured == payload
    assert proc.poll() is not None


def test_capture_rejects_output_over_the_byte_limit_without_keeping_it() -> None:
    payload = b"x" * 32
    proc = _python_stdout_proc(
        "import sys; sys.stdout.buffer.write(" + repr(payload) + ")"
    )

    captured = _capture_bounded_process_output(proc, max_bytes=16, timeout_seconds=2.0)

    assert captured is None
    assert proc.poll() is not None


def test_capture_times_out_and_reaps_the_child() -> None:
    proc = _python_stdout_proc("import time; time.sleep(30)")

    captured = _capture_bounded_process_output(
        proc, max_bytes=1024, timeout_seconds=0.2
    )

    assert captured is None
    assert proc.poll() is not None


def test_git_ls_files_sets_prompt_free_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}
    real_popen = subprocess.Popen

    def spy(argv: object, **kwargs: object) -> subprocess.Popen[bytes]:
        del argv
        seen["env"] = kwargs.get("env")
        return real_popen(
            [sys.executable, "-c", ""],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            env=kwargs.get("env"),  # type: ignore[arg-type]
        )

    monkeypatch.setattr("sase.pager._resolve_path_search.subprocess.Popen", spy)
    _git_ls_files(tmp_path)
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_git_ls_files_accepts_output_at_the_byte_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"src/a.py\0"
    monkeypatch.setattr(
        "sase.pager._resolve_path_search._GIT_LS_FILES_MAX_BYTES", len(payload)
    )
    real_popen = subprocess.Popen
    held: list[subprocess.Popen[bytes]] = []

    def spy(argv: object, **kwargs: object) -> subprocess.Popen[bytes]:
        del argv
        proc = real_popen(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(" + repr(payload) + ")",
            ],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            env=kwargs.get("env"),  # type: ignore[arg-type]
        )
        held.append(proc)
        return proc

    monkeypatch.setattr("sase.pager._resolve_path_search.subprocess.Popen", spy)
    files = _git_ls_files(tmp_path)
    assert files == ("src/a.py",)
    assert held[0].poll() is not None


def test_git_ls_files_rejects_overflow_and_reaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"src/a.py\0extra\0"
    monkeypatch.setattr("sase.pager._resolve_path_search._GIT_LS_FILES_MAX_BYTES", 8)
    real_popen = subprocess.Popen
    held: list[subprocess.Popen[bytes]] = []

    def spy(argv: object, **kwargs: object) -> subprocess.Popen[bytes]:
        del argv
        proc = real_popen(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(" + repr(payload) + ")",
            ],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            env=kwargs.get("env"),  # type: ignore[arg-type]
        )
        held.append(proc)
        return proc

    monkeypatch.setattr("sase.pager._resolve_path_search.subprocess.Popen", spy)
    assert _git_ls_files(tmp_path) is None
    assert held[0].poll() is not None


def test_git_ls_files_timeout_reaps_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.pager._resolve_path_search._GIT_LS_FILES_TIMEOUT_SECONDS", 0.2
    )
    real_popen = subprocess.Popen
    held: list[subprocess.Popen[bytes]] = []

    def spy(argv: object, **kwargs: object) -> subprocess.Popen[bytes]:
        del argv
        proc = real_popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            env=kwargs.get("env"),  # type: ignore[arg-type]
        )
        held.append(proc)
        return proc

    monkeypatch.setattr("sase.pager._resolve_path_search.subprocess.Popen", spy)
    assert _git_ls_files(tmp_path) is None
    assert held[0].poll() is not None
