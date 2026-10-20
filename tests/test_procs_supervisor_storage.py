"""Fault injection for full-disk supervisor observation and settlement."""

from __future__ import annotations

import errno
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.procs import settlement, submission, supervisor, supervisor_storage
from sase.procs.models import Proc
from sase.procs.runtime import (
    proc_go_path,
    proc_runtime_dir,
    proc_settlement_sidecar_path,
    read_json_object,
)
from sase.procs.spawn import SUPERVISOR_LOG_NAME
from sase.procs.store import append_proc, get_proc


@pytest.fixture
def recorded_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Proc:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(supervisor.signal, "signal", lambda *_args: None)
    proc = Proc(
        proc_id="storage-test",
        label="Storage failure",
        kind="command",
        status="pending",
        lifecycle="named-proc",
        command=[sys.executable, "-c", "raise SystemExit(101)"],
        cwd=str(tmp_path),
        origin="test",
        created_at="2026-10-20T12:00:00Z",
        log_path=str(tmp_path / "output.log"),
        request_fingerprint="storage-test",
        reserved_by="test",
    )
    append_proc(proc)
    proc_go_path(proc.proc_id).parent.mkdir(parents=True, exist_ok=True)
    proc_go_path(proc.proc_id).touch()
    return proc


@pytest.mark.parametrize(
    ("status", "exit_code", "reason"),
    [
        ("error", 101, "error"),
        ("success", 0, "success"),
        ("error", -15, "total-timeout"),
        ("killed", -15, "stop"),
    ],
)
def test_close_error_preserves_observed_command_result(
    recorded_proc: Proc,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    exit_code: int,
    reason: str,
) -> None:
    monkeypatch.setattr(
        supervisor,
        "_run_command",
        lambda *_args: {
            "status": status,
            "exit_code": exit_code,
            "termination_reason": reason,
            "message": f"observed {reason}",
        },
    )
    original_close = supervisor.BoundedLogPipe.close

    def full_disk_on_close(pipe: supervisor.BoundedLogPipe) -> None:
        original_close(pipe)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(supervisor.BoundedLogPipe, "close", full_disk_on_close)
    assert supervisor.run_supervisor(recorded_proc.proc_id) == (
        0 if exit_code == 0 else 1
    )
    finished = get_proc(recorded_proc.proc_id)
    assert finished is not None
    assert finished.status == status
    assert finished.exit_code == exit_code
    assert finished.result is not None
    assert finished.result["termination_reason"] == reason
    assert finished.message == (
        f"observed {reason}; output log incomplete: [Errno 28] No space left on device"
    )


def test_close_error_without_command_observation_stays_supervisor_loss(
    recorded_proc: Proc, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        supervisor, "_wait_for_launch_barrier", lambda *_args: "barrier failed"
    )
    original_close = supervisor.BoundedLogPipe.close

    def fail_close(pipe: supervisor.BoundedLogPipe) -> None:
        original_close(pipe)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(supervisor.BoundedLogPipe, "close", fail_close)
    supervisor.run_supervisor(recorded_proc.proc_id)
    finished = get_proc(recorded_proc.proc_id)
    assert finished is not None
    assert finished.exit_code is None
    assert (finished.result or {})["termination_reason"] == "supervisor-loss"


@pytest.mark.parametrize("failure_point", ["begin", "partial"])
def test_supervisor_retries_storage_exhaustion_and_resumes_checkpoints(
    recorded_proc: Proc,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_point: str,
) -> None:
    attempts = 0
    completed_effects: list[str] = []
    original_begin = settlement.begin_proc_settlement

    def fail_twice(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise ValueError(
                "failed to serialize proc: No space left on device (os error 28)"
            )
        if failure_point == "begin":
            return original_begin(*args, **kwargs)
        return None

    monkeypatch.setattr(
        settlement,
        "_settle_workspace_claim",
        lambda _state: completed_effects.append("claim"),
    )
    if failure_point == "begin":
        monkeypatch.setattr(settlement, "begin_proc_settlement", fail_twice)
    else:
        monkeypatch.setattr(settlement, "_settle_artifacts", fail_twice)
    pauses: list[float] = []
    monkeypatch.setattr(
        supervisor_storage,
        "time",
        SimpleNamespace(monotonic=lambda: 0, sleep=pauses.append),
    )

    assert supervisor.run_supervisor(recorded_proc.proc_id) == 1

    finished = get_proc(recorded_proc.proc_id)
    assert finished is not None
    assert finished.status == "error"
    assert finished.exit_code == 101
    assert finished.message == "exited with code 101"
    assert (finished.result or {})["termination_reason"] == "error"
    state = read_json_object(proc_settlement_sidecar_path(recorded_proc.proc_id))
    assert all(state["checkpoints"].values())
    assert completed_effects == ["claim"]
    assert attempts == 3
    assert pauses == [1, 2]
    assert capsys.readouterr().err.count("settlement storage exhausted; retrying") == 2


@pytest.mark.parametrize(
    "failure",
    [
        OSError(errno.ENOSPC, "full"),
        OSError(errno.EDQUOT, "quota"),
        ValueError("store failed (os error 28)"),
        ValueError(f"store failed (os error {errno.EDQUOT})"),
    ],
)
def test_storage_retry_window_and_backoff_are_bounded(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    now = 0.0
    pauses: list[float] = []
    attempts = 0

    def advance(seconds: float) -> None:
        nonlocal now
        pauses.append(seconds)
        now += seconds

    def fail(*_args: Any, **_kwargs: Any) -> Proc:
        nonlocal attempts
        attempts += 1
        raise failure

    def stderr_full(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(errno.ENOSPC, "stderr is full too")

    monkeypatch.setattr(supervisor_storage, "settle_named_proc", fail)
    monkeypatch.setattr(
        supervisor_storage,
        "time",
        SimpleNamespace(monotonic=lambda: now, sleep=advance),
    )
    monkeypatch.setattr(
        supervisor_storage,
        "sys",
        SimpleNamespace(stderr=SimpleNamespace(write=stderr_full)),
    )
    with pytest.raises(type(failure)) as raised:
        supervisor_storage.settle_with_storage_retry(
            "p1",
            supervisor_id="owner",
            status="error",
            message="exited with code 101",
            termination_reason="error",
            exit_code=101,
        )
    assert raised.value is failure
    assert sum(pauses) == 70 * 60
    assert max(pauses) == 60
    assert pauses[:7] == [1, 2, 4, 8, 16, 32, 60]
    assert attempts == len(pauses) + 1


@pytest.mark.parametrize(
    "failure", [OSError(errno.EACCES, "denied"), ValueError("invalid outcome")]
)
def test_nonstorage_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> Proc:
        raise failure

    monkeypatch.setattr(supervisor_storage, "settle_named_proc", fail)
    monkeypatch.setattr(
        supervisor_storage,
        "time",
        SimpleNamespace(
            monotonic=lambda: 0, sleep=lambda _: pytest.fail("unexpected retry")
        ),
    )
    with pytest.raises(type(failure)) as raised:
        supervisor_storage.settle_with_storage_retry(
            "p1",
            supervisor_id="owner",
            status="error",
            message="exited with code 101",
            termination_reason="error",
            exit_code=101,
        )
    assert raised.value is failure


@pytest.mark.parametrize(
    ("log", "expected"),
    [
        (
            b"old error\nValueError: store failed (os error 28)\n\n",
            "ValueError: store failed (os error 28) (disk full)",
        ),
        (
            b"Traceback\nOSError: No space left on device\n",
            "OSError: No space left on device (disk full)",
        ),
        (b"earlier\nlast\tfailure\xff\n \n", "last failure\ufffd"),
        (b"x" * 10000 + b"final error\n", "…" + "x" * 488 + "final error"),
        (None, None),
        (b"\n \t\n", None),
    ],
    ids=[
        "rust-enospc",
        "os-enospc",
        "invalid-utf8",
        "bounded-tail",
        "missing",
        "empty",
    ],
)
def test_reconcile_includes_bounded_last_supervisor_error(
    recorded_proc: Proc, log: bytes | None, expected: str | None
) -> None:
    claimed = supervisor._claim_supervisor(recorded_proc, "test-owner")
    if log is not None:
        (proc_runtime_dir(claimed.proc_id) / SUPERVISOR_LOG_NAME).write_bytes(log)
    finished = submission._reconcile_named_proc(claimed)
    message = submission.SUPERVISOR_LOSS_MESSAGE
    if expected is not None:
        message += f"; last supervisor error: {expected}"
    assert finished.message == message
    assert (finished.result or {})["message"] == message
    assert (finished.result or {})["termination_reason"] == "supervisor-loss"


def test_unreadable_supervisor_log_keeps_generic_loss(
    recorded_proc: Proc, monkeypatch: pytest.MonkeyPatch
) -> None:
    claimed = supervisor._claim_supervisor(recorded_proc, "test-owner")
    original_open = Path.open

    def unreadable(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.name == SUPERVISOR_LOG_NAME:
            raise PermissionError(errno.EACCES, "unreadable")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unreadable)
    finished = submission._reconcile_named_proc(claimed)
    assert finished.message == submission.SUPERVISOR_LOSS_MESSAGE
