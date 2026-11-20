"""Launches that overlap a code swap wait for it and retry once, fresh."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from sase.agent import launch_swap_retry
from sase.agent.launch_swap_retry import (
    ENV_CODE_SWAP_RETRY,
    arm_code_swap_retry,
    defer_launch_for_code_swap,
    reexec_after_code_swap,
    retry_launch_after_code_swap,
    sase_cli_argv,
)
from sase.core import code_swap_epoch
from sase.dev_update.code_swap_lock import code_swap_writer_lock


class _ExecRecorder:
    def __init__(self, error: OSError | None = None) -> None:
        self.calls: list[tuple[str, list[str], str | None]] = []
        self._error = error

    def __call__(self, path: str, argv: list[str]) -> None:
        self.calls.append((path, argv, os.environ.get(ENV_CODE_SWAP_RETRY)))
        if self._error is not None:
            raise self._error


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.delenv("SASE_DISABLE_CODE_SWAP_LOCK", raising=False)
    monkeypatch.delenv(ENV_CODE_SWAP_RETRY, raising=False)
    monkeypatch.setattr(code_swap_epoch, "_boot_epoch", None)
    monkeypatch.setattr(launch_swap_retry, "_armed", False)
    monkeypatch.setattr(launch_swap_retry, "_retry_spent", False)
    return home


@pytest.fixture
def armed(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Arm the retry the way a real (non-pytest) entry point would."""
    monkeypatch.setattr(launch_swap_retry, "pytest_context_detected", lambda: False)
    arm_code_swap_retry()
    return sandbox


def _swap() -> None:
    with code_swap_writer_lock() as lock:
        assert lock.acquired


def _no_wait(monkeypatch: pytest.MonkeyPatch, *, cleared: bool = True) -> list[str]:
    waits: list[str] = []

    def fake_wait(**kwargs: object) -> bool:
        waits.append("wait")
        return cleared

    monkeypatch.setattr(launch_swap_retry, "wait_for_code_swap_writer", fake_wait)
    return waits


# -- arming ---------------------------------------------------------------------


def test_a_pytest_process_never_arms(sandbox: Path) -> None:
    arm_code_swap_retry()
    execv = _ExecRecorder()

    reexec_after_code_swap(["python", "-m", "sase"], reason="test", execv=execv)

    assert execv.calls == []


def test_arming_consumes_the_retry_marker_so_children_never_inherit_it(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_CODE_SWAP_RETRY, "1")
    monkeypatch.setattr(launch_swap_retry, "pytest_context_detected", lambda: False)
    _no_wait(monkeypatch)
    execv = _ExecRecorder()

    arm_code_swap_retry()
    reexec_after_code_swap(["python", "-m", "sase"], reason="again", execv=execv)

    assert ENV_CODE_SWAP_RETRY not in os.environ
    assert execv.calls == []


def test_sase_cli_argv_reruns_the_same_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["/home/u/.local/bin/sase", "run", "do x"])

    assert sase_cli_argv() == [sys.executable, "-m", "sase", "run", "do x"]


# -- re-exec ----------------------------------------------------------------------


def test_reexec_waits_then_execs_once_with_the_marker(
    armed: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    waits = _no_wait(monkeypatch)
    execv = _ExecRecorder()
    argv = ["/venv/python", "-m", "sase", "run"]

    reexec_after_code_swap(argv, reason="a code swap is in progress", execv=execv)
    reexec_after_code_swap(argv, reason="a second swap", execv=execv)

    assert waits == ["wait"]
    assert execv.calls == [("/venv/python", argv, "1")]
    assert "retrying in a fresh process after a code swap" in capsys.readouterr().err


def test_reexec_gives_up_when_the_swap_outlasts_the_wait(
    armed: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _no_wait(monkeypatch, cleared=False)
    execv = _ExecRecorder()

    reexec_after_code_swap(["python"], reason="slow swap", execv=execv)

    assert execv.calls == []
    assert "not retrying" in capsys.readouterr().err


def test_failed_exec_returns_and_clears_the_marker(
    armed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_wait(monkeypatch)
    execv = _ExecRecorder(error=FileNotFoundError("python vanished"))

    reexec_after_code_swap(["python"], reason="swap", execv=execv)

    assert len(execv.calls) == 1
    assert ENV_CODE_SWAP_RETRY not in os.environ


def test_reexec_never_execs_while_a_real_writer_stays_live(armed: Path) -> None:
    execv = _ExecRecorder()

    with code_swap_writer_lock() as lock:
        assert lock.acquired
        reexec_after_code_swap(["python"], reason="live", wait_seconds=0.0, execv=execv)

    assert execv.calls == []


# -- proactive deferral -------------------------------------------------------------


def test_defer_reexecs_when_a_writer_is_live(
    armed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_wait(monkeypatch)
    monkeypatch.setattr(launch_swap_retry, "code_swap_writer_live", lambda: True)
    execv = _ExecRecorder()

    defer_launch_for_code_swap(["python", "-m", "sase", "run"], execv=execv)

    assert [call[1] for call in execv.calls] == [["python", "-m", "sase", "run"]]


def test_defer_reexecs_after_a_swap_since_boot(
    armed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_wait(monkeypatch)
    _swap()
    execv = _ExecRecorder()

    defer_launch_for_code_swap(["python", "-m", "sase", "run"], execv=execv)

    assert len(execv.calls) == 1


def test_defer_is_a_no_op_without_a_swap(armed: Path) -> None:
    execv = _ExecRecorder()

    defer_launch_for_code_swap(["python", "-m", "sase", "run"], execv=execv)

    assert execv.calls == []


# -- reactive retry -------------------------------------------------------------------


def test_skew_failure_after_a_swap_since_boot_retries(
    armed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_wait(monkeypatch)
    _swap()
    execv = _ExecRecorder()
    exc = ImportError(
        "cannot import name 'BeforeSpawnCallback' from "
        "'sase.agent.launch_executor_types'"
    )

    retry_launch_after_code_swap(exc, ["python", "-m", "sase", "run"], execv=execv)

    assert len(execv.calls) == 1


def test_wrapped_skew_failure_text_also_counts(
    armed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_wait(monkeypatch)
    monkeypatch.setattr(launch_swap_retry, "code_swap_in_play", lambda: "in grace")
    execv = _ExecRecorder()
    exc = RuntimeError(
        "sase_core_rs artifact-reference wire is stale: expected 3, got 4"
    )

    retry_launch_after_code_swap(exc, ["python"], execv=execv)

    assert len(execv.calls) == 1


def test_skew_failure_with_no_swap_in_play_fails_as_before(armed: Path) -> None:
    execv = _ExecRecorder()

    retry_launch_after_code_swap(
        ModuleNotFoundError("No module named 'sase_core_rs'"), ["python"], execv=execv
    )

    assert execv.calls == []


def test_ordinary_failure_during_a_swap_is_not_retried(
    armed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch_swap_retry, "code_swap_in_play", lambda: "in play")
    execv = _ExecRecorder()

    retry_launch_after_code_swap(ValueError("bad prompt"), ["python"], execv=execv)

    assert execv.calls == []


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ImportError("cannot import name 'X' from 'sase.y'"), True),
        (ModuleNotFoundError("No module named 'sase_core_rs'"), True),
        (RuntimeError("ImportError: cannot import name 'X'"), True),
        (ValueError("invalid prompt"), False),
    ],
)
def test_skew_classification_reuses_the_shared_patterns(
    exc: BaseException, expected: bool
) -> None:
    assert launch_swap_retry._looks_like_swap_skew(exc) is expected
