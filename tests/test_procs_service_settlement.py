"""Stop, crash-recovery, and unobserved-loss tests for the named-proc supervisor.

Split from ``tests.test_procs_service``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.procs import (
    get_proc,
    kill_proc,
    read_proc_log_tail,
    reconcile_running_procs,
    request_proc_stop,
    submit_detached_proc,
    submit_proc,
    wait_for_proc,
)
from sase.procs.models import Proc, ProcObservedSettlementOutcome, ProcStopRequest
from sase.procs.runtime import (
    proc_settlement_sidecar_path,
    read_json_object,
)
from sase.procs.spawn import spawn_detached_supervisor

_SETTLEMENT_CRASH_CHECKPOINTS = (
    "settlement_begun",
    "command_gone",
    "output_closed",
    "claim_settled",
    "artifacts_settled",
    "followup_settled",
    "result_written",
)


def _wait_for_running(proc_id: str) -> Any:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        proc = get_proc(proc_id)
        assert proc is not None
        if proc.status == "running":
            return proc
        if proc.status not in {"pending", "running"}:
            pytest.fail(f"proc became {proc.status} before it was observed running")
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
    pytest.fail("proc did not enter running state")


def _wait_for_settling(proc_id: str) -> Proc:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        proc = get_proc(proc_id)
        assert proc is not None
        if proc.status == "settling":
            return proc
        if proc.status in {"success", "error", "killed"}:
            pytest.fail(f"proc became {proc.status} before settlement was observed")
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
    pytest.fail("proc did not enter settlement")


def _wait_for_settlement_supervisor_exit(proc_id: str) -> Proc:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        proc = get_proc(proc_id)
        assert proc is not None
        if proc.status == "settling" and (
            proc.pid is None or not is_process_running(proc.pid)
        ):
            return proc
        if proc.status in {"success", "error", "killed"}:
            pytest.fail(f"proc became {proc.status} before the injected crash")
        time.sleep(
            min(0.025, max(0.0, deadline - time.monotonic()))
        )  # sase-test-wait: poll for injected settlement crash
    pytest.fail("supervisor did not exit during settlement")


def _settlement_checkpoints(proc_id: str) -> dict[str, bool]:
    state = read_json_object(proc_settlement_sidecar_path(proc_id))
    checkpoints = state.get("checkpoints")
    assert isinstance(checkpoints, dict)
    return {str(key): bool(value) for key, value in checkpoints.items()}


def _wait_for_process_exit(pid: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not is_process_running(pid):
            return
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
    pytest.fail(f"process {pid} did not exit")


def _assert_successful_command_result(proc: Proc) -> None:
    assert proc.status == "success"
    assert proc.exit_code == 0
    assert proc.settled_at is not None
    assert (proc.result or {}).get("termination_reason") == "success"
    outcome = ProcObservedSettlementOutcome.from_dict(proc.settlement_outcome)
    assert outcome is not None
    assert outcome.status == "success"
    assert outcome.termination_reason == "success"
    assert outcome.exit_code == 0


def test_stop_records_intent_then_settles_killed(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc = submit_detached_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Stop me",
        cwd=tmp_path,
        origin="test",
    )
    running = _wait_for_running(proc.proc_id)
    killed = kill_proc(proc.proc_id)
    finished = wait_for_proc(proc.proc_id, timeout=15)

    assert killed.status == "killed"
    assert finished.status == "killed"
    assert finished.stop_requested_at is not None
    assert finished.result is not None
    assert finished.result["termination_reason"] == "stop"
    assert running.pid is not None
    _wait_for_process_exit(running.pid)


def test_settlement_resumes_after_an_injected_crash(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", "output_closed")
    proc = submit_proc(
        [sys.executable, "-c", "print('partial', flush=True)"],
        label="Crash",
        cwd=tmp_path,
        origin="test",
    )
    _wait_for_settlement_supervisor_exit(proc.proc_id)
    monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)

    reconciled = reconcile_running_procs()
    finished = get_proc(proc.proc_id)
    assert finished is not None
    assert finished.proc_id in {item.proc_id for item in reconciled} | {
        finished.proc_id
    }
    if finished.status not in {"success", "error"}:
        finished = wait_for_proc(proc.proc_id, timeout=10)
    _assert_successful_command_result(finished)
    assert all(_settlement_checkpoints(proc.proc_id).values())
    assert "partial" in read_proc_log_tail(proc.proc_id, 20, log_path=finished.log_path)


def test_wait_for_proc_recovers_after_an_early_settlement_reconcile(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", "output_closed")
    proc = submit_proc(
        [sys.executable, "-c", "print('partial', flush=True)"],
        label="Crash race",
        cwd=tmp_path,
        origin="test",
    )
    settling = _wait_for_settling(proc.proc_id)

    probes = 0

    def stale_alive_once(_pid: int | None, _supervisor_id: str | None) -> bool:
        nonlocal probes
        probes += 1
        return probes == 1

    monkeypatch.setattr("sase.procs.submission.supervisor_is_alive", stale_alive_once)
    assert reconcile_running_procs() == []
    if settling.pid is not None:
        _wait_for_process_exit(settling.pid)
    monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)

    finished = wait_for_proc(proc.proc_id, timeout=5)

    assert probes >= 2
    _assert_successful_command_result(finished)
    assert all(_settlement_checkpoints(proc.proc_id).values())
    assert "partial" in read_proc_log_tail(proc.proc_id, 20, log_path=finished.log_path)


def test_settlement_recovers_every_injected_crash_checkpoint_repeatedly(
    monkeypatch: Any, tmp_path: Path
) -> None:
    for checkpoint in _SETTLEMENT_CRASH_CHECKPOINTS:
        for attempt in range(3):
            run_root = tmp_path / checkpoint / str(attempt)
            run_root.mkdir(parents=True)
            marker = f"{checkpoint}-{attempt}"
            monkeypatch.setenv("SASE_HOME", str(run_root / "home"))
            monkeypatch.setenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", checkpoint)
            proc = submit_proc(
                [sys.executable, "-c", f"print({marker!r}, flush=True)"],
                label=f"Crash {checkpoint}",
                cwd=run_root,
                origin="test",
            )
            _wait_for_settlement_supervisor_exit(proc.proc_id)
            monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)

            reconcile_running_procs()
            finished = get_proc(proc.proc_id)
            assert finished is not None
            if finished.status not in {"success", "error", "killed"}:
                finished = wait_for_proc(proc.proc_id, timeout=5)

            _assert_successful_command_result(finished)
            assert all(_settlement_checkpoints(proc.proc_id).values())
            assert marker in read_proc_log_tail(
                proc.proc_id,
                20,
                log_path=finished.log_path,
            )


def test_supervisor_resume_keeps_frozen_success_after_settlement_crash(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", "output_closed")
    proc = submit_proc(
        [sys.executable, "-c", "print('resume', flush=True)"],
        label="Resume settling",
        cwd=tmp_path,
        origin="test",
    )
    _wait_for_settlement_supervisor_exit(proc.proc_id)
    monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)

    spawn_detached_supervisor(proc.proc_id)
    finished = wait_for_proc(proc.proc_id, timeout=15)

    _assert_successful_command_result(finished)
    assert "resume" in read_proc_log_tail(proc.proc_id, 20, log_path=finished.log_path)


def test_two_recovery_observers_publish_one_successful_result(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", "output_closed")
    proc = submit_proc(
        [sys.executable, "-c", "print('once', flush=True)"],
        label="Two observers",
        cwd=tmp_path,
        origin="test",
    )
    settling = _wait_for_settlement_supervisor_exit(proc.proc_id)
    monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)
    signaled: list[int] = []
    monkeypatch.setattr(
        "sase.procs.submission._signal_leftover_group",
        lambda pgid: signaled.append(pgid),
    )

    def recover() -> None:
        reconcile_running_procs()

    workers = [threading.Thread(target=recover) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    finished = get_proc(proc.proc_id)
    assert finished is not None
    if finished.status not in {"success", "error", "killed"}:
        finished = wait_for_proc(proc.proc_id, timeout=10)
    _assert_successful_command_result(finished)
    assert signaled == []
    if settling.pgid is not None:
        assert settling.pgid not in signaled


def test_known_outcome_survives_reboot_fallback(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", "output_closed")
    proc = submit_proc(
        [sys.executable, "-c", "print('frozen', flush=True)"],
        label="Reboot preserve",
        cwd=tmp_path,
        origin="test",
    )
    _wait_for_settlement_supervisor_exit(proc.proc_id)
    monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)
    monkeypatch.setattr(
        "sase.procs.submission.supervisor_from_previous_boot",
        lambda _supervisor_id: True,
    )

    reconcile_running_procs()
    finished = get_proc(proc.proc_id)
    assert finished is not None
    if finished.status not in {"success", "error", "killed"}:
        finished = wait_for_proc(proc.proc_id, timeout=10)
    _assert_successful_command_result(finished)
    assert "reboot" not in (finished.message or "").lower()


def test_nonzero_timeout_and_stop_survive_settlement_crash(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))

    monkeypatch.setenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", "output_closed")
    failed = submit_proc(
        [sys.executable, "-c", "raise SystemExit(3)"],
        label="Nonzero crash",
        cwd=tmp_path,
        origin="test",
    )
    _wait_for_settlement_supervisor_exit(failed.proc_id)
    monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)
    reconcile_running_procs()
    failed_done = get_proc(failed.proc_id)
    assert failed_done is not None
    if failed_done.status not in {"success", "error", "killed"}:
        failed_done = wait_for_proc(failed.proc_id, timeout=10)
    assert failed_done.status == "error"
    assert failed_done.exit_code == 3
    assert (failed_done.result or {}).get("termination_reason") == "error"

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "timeout-home"))
    monkeypatch.setenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", "output_closed")
    timed = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Timeout crash",
        cwd=tmp_path,
        origin="test",
        timeout_seconds=1,
    )
    _wait_for_settlement_supervisor_exit(timed.proc_id)
    monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)
    reconcile_running_procs()
    timed_done = get_proc(timed.proc_id)
    assert timed_done is not None
    if timed_done.status not in {"success", "error", "killed"}:
        timed_done = wait_for_proc(timed.proc_id, timeout=10)
    assert timed_done.status == "error"
    assert (timed_done.result or {}).get("termination_reason") == "total-timeout"

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "stop-home"))
    monkeypatch.setenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", "output_closed")
    stopped = submit_detached_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Stop crash",
        cwd=tmp_path,
        origin="test",
    )
    running = _wait_for_running(stopped.proc_id)
    request_proc_stop(
        ProcStopRequest(
            proc_id=stopped.proc_id,
            requested_by="test",
            requested_at=running.created_at,
            reason="stop",
        )
    )
    assert running.pid is not None
    os.kill(running.pid, signal.SIGTERM)
    _wait_for_settlement_supervisor_exit(stopped.proc_id)
    monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)
    reconcile_running_procs()
    stopped_done = get_proc(stopped.proc_id)
    assert stopped_done is not None
    if stopped_done.status not in {"success", "error", "killed"}:
        stopped_done = wait_for_proc(stopped.proc_id, timeout=10)
    assert stopped_done.status == "killed"
    assert (stopped_done.result or {}).get("termination_reason") == "stop"


def test_unobserved_same_boot_loss_does_not_claim_reboot(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Unknown same boot",
        cwd=tmp_path,
        origin="test",
    )
    running = _wait_for_running(proc.proc_id)
    assert running.pid is not None
    os.kill(running.pid, signal.SIGKILL)
    _wait_for_process_exit(running.pid)

    reconcile_running_procs()
    finished = get_proc(proc.proc_id)
    assert finished is not None
    if finished.status not in {"success", "error", "killed"}:
        finished = wait_for_proc(proc.proc_id, timeout=10)
    assert finished.status == "error"
    assert (finished.result or {}).get("termination_reason") == "supervisor-loss"
    assert "reboot" not in (finished.message or "").lower()


def test_unobserved_pre_reboot_command_stays_unknown(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Unknown reboot",
        cwd=tmp_path,
        origin="test",
    )
    running = _wait_for_running(proc.proc_id)
    assert running.pid is not None
    os.kill(running.pid, signal.SIGKILL)
    _wait_for_process_exit(running.pid)
    monkeypatch.setattr(
        "sase.procs.submission.supervisor_from_previous_boot",
        lambda _supervisor_id: True,
    )

    try:
        reconcile_running_procs()
        finished = get_proc(proc.proc_id)
        assert finished is not None
        if finished.status not in {"success", "error", "killed"}:
            finished = wait_for_proc(proc.proc_id, timeout=10)
        assert finished.status == "error"
        assert (finished.result or {}).get("termination_reason") == "reboot"
        assert "unknown" in (finished.message or "").lower()
    finally:
        leftover = get_proc(proc.proc_id)
        if leftover is not None and leftover.pgid is not None:
            try:
                os.killpg(leftover.pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
