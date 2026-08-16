"""Service-level tests for the unified proc-shell supervisor."""

from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.procs import (
    COMMAND_PROC_KIND,
    PROC_LIFECYCLE_PROC_SHELL,
    ProcSubmitError,
    ProcSubmitRequest,
    append_proc,
    get_proc,
    kill_proc,
    read_proc_log_tail,
    read_procs,
    reconcile_running_procs,
    submit_detached_proc,
    submit_proc,
    submit_proc_request,
    wait_for_proc,
)
from sase.procs.models import Proc
from sase.procs.runtime import (
    proc_settlement_sidecar_path,
    proc_started_path,
    read_json_object,
)

_SETTLEMENT_CRASH_CHECKPOINTS = (
    "command_gone",
    "output_closed",
    "claim_settled",
    "artifacts_settled",
    "followup_settled",
    "result_written",
)


def test_submit_records_a_proc_shell_and_settles_success(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc = submit_proc(
        [sys.executable, "-c", "print('ready', flush=True)"],
        label="Ready",
        cwd=tmp_path,
        origin="test",
    )
    finished = wait_for_proc(proc.proc_id, timeout=15)

    assert proc.lifecycle == PROC_LIFECYCLE_PROC_SHELL
    assert proc.argv == [sys.executable, "-c", "print('ready', flush=True)"]
    assert finished.status == "success"
    assert finished.settled_at is not None
    assert finished.result is not None
    assert finished.result["termination_reason"] == "success"
    assert "ready" in read_proc_log_tail(proc.proc_id, 10, log_path=proc.log_path)


def test_submit_request_replay_returns_the_active_row(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    request = ProcSubmitRequest(
        argv=[sys.executable, "-c", "import time; time.sleep(20)"],
        label="Named",
        cwd=tmp_path,
        origin="test",
        project="sase",
        shell_name="agent--build",
        request_fingerprint="sha256:same",
    )
    first = submit_proc_request(request)
    replayed = submit_proc_request(request)

    assert replayed.proc_id == first.proc_id
    assert replayed.status in {"pending", "running"}
    kill_proc(first.proc_id)
    wait_for_proc(first.proc_id, timeout=15)


def test_submit_request_normalizes_legacy_kind_to_command(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc = submit_proc_request(
        ProcSubmitRequest(
            argv=[sys.executable, "-c", "print('normalized', flush=True)"],
            label="Normalized",
            cwd=tmp_path,
            origin="test",
            kind="detached",
            session_id=None,
        )
    )
    finished = wait_for_proc(proc.proc_id, timeout=15)

    assert proc.kind == COMMAND_PROC_KIND
    assert finished.kind == COMMAND_PROC_KIND
    assert finished.session_id is None


def test_named_proc_shell_reuse_is_project_scoped_and_waits_for_settlement(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    argv = [sys.executable, "-c", "print('done', flush=True)"]
    first = submit_proc(
        argv,
        label="First",
        cwd=tmp_path,
        origin="test",
        project="sase",
        shell_name="agent--build",
        concurrency_keys=["docs"],
    )
    finished = wait_for_proc(first.proc_id, timeout=15)

    assert finished.status == "success"
    assert finished.shell_name == "agent--build"
    assert finished.concurrency_keys == ["docs"]
    assert "agent--build" not in finished.concurrency_keys

    other_project = submit_proc(
        argv,
        label="Other project",
        cwd=tmp_path,
        origin="test",
        project="other",
        shell_name="agent--build",
    )
    wait_for_proc(other_project.proc_id, timeout=15)
    assert other_project.proc_id != first.proc_id

    reused = submit_proc(
        argv,
        label="Reuse",
        cwd=tmp_path,
        origin="test",
        project="sase",
        shell_name="agent--build",
        concurrency_keys=["docs"],
    )
    wait_for_proc(reused.proc_id, timeout=15)
    assert reused.proc_id != first.proc_id

    active = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(20)"],
        label="Active",
        cwd=tmp_path,
        origin="test",
        project="sase",
        shell_name="agent--docs",
    )
    with pytest.raises(ProcSubmitError, match="shell_name"):
        submit_proc(
            argv,
            label="Conflict",
            cwd=tmp_path,
            origin="test",
            project="sase",
            shell_name="agent--docs",
        )
    kill_proc(active.proc_id)
    wait_for_proc(active.proc_id, timeout=15)


def test_submit_derives_bare_named_proc_shell(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_AGENT_NAME", "foo--code")
    proc = submit_proc(
        [sys.executable, "-c", "print('ok', flush=True)"],
        label="Bare",
        cwd=tmp_path,
        origin="test",
        project="sase",
        shell_name="build",
    )
    wait_for_proc(proc.proc_id, timeout=15)

    assert proc.shell_name == "foo--build"
    assert proc.concurrency_keys == []


def test_total_and_idle_timeouts_settle_as_errors(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    total = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Total",
        cwd=tmp_path,
        origin="test",
        timeout_seconds=1,
    )
    idle = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Idle",
        cwd=tmp_path,
        origin="test",
        idle_timeout_seconds=1,
    )

    total_done = wait_for_proc(total.proc_id, timeout=15)
    idle_done = wait_for_proc(idle.proc_id, timeout=15)

    assert total_done.status == "error"
    assert total_done.result is not None
    assert total_done.result["termination_reason"] == "total-timeout"
    assert idle_done.status == "error"
    assert idle_done.result is not None
    assert idle_done.result["termination_reason"] == "idle-timeout"


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


def test_ack_timeout_settles_as_launch_failure(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_PROC_BOOTSTRAP_IMPORT_DELAY_SECONDS", "30")
    monkeypatch.setenv("SASE_PROC_START_ACK_TIMEOUT_SECONDS", "0.2")

    with pytest.raises(ProcSubmitError, match="acknowledge"):
        submit_proc(["true"], label="Slow boot", cwd=tmp_path, origin="test")

    procs = [proc for proc in read_procs() if proc.label == "Slow boot"]
    assert len(procs) == 1
    assert procs[0].status == "error"
    assert procs[0].settled_at is not None
    assert (procs[0].result or {}).get("termination_reason") == "launch-failure"
    assert not proc_started_path(procs[0].proc_id).exists()


def test_barrier_timeout_does_not_run_the_command(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_PROC_LAUNCH_BARRIER_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setattr(
        "sase.procs.service.write_launch_barrier", lambda *_a, **_k: None
    )
    marker = tmp_path / "ran"
    proc = submit_proc(
        [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ran')"],
        label="Blocked",
        cwd=tmp_path,
        origin="test",
    )
    finished = wait_for_proc(proc.proc_id, timeout=15)

    assert finished.status == "error"
    assert finished.message is not None
    assert "barrier" in finished.message
    assert not marker.exists()


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
    assert finished.status in {"success", "error"}
    assert finished.settled_at is not None
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

    monkeypatch.setattr("sase.procs.service.supervisor_is_alive", stale_alive_once)
    assert reconcile_running_procs() == []
    if settling.pid is not None:
        _wait_for_process_exit(settling.pid)
    monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)

    finished = wait_for_proc(proc.proc_id, timeout=5)

    assert probes >= 2
    assert finished.status in {"success", "error"}
    assert finished.settled_at is not None
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

            assert finished.status in {"success", "error"}
            assert finished.settled_at is not None
            assert all(_settlement_checkpoints(proc.proc_id).values())
            assert marker in read_proc_log_tail(
                proc.proc_id,
                20,
                log_path=finished.log_path,
            )


def test_result_and_artifact_settlement_are_durable(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    artifacts = tmp_path / "artifacts"
    result_path = tmp_path / "result.json"
    artifacts.mkdir()
    finished = wait_for_proc(
        submit_proc_request(
            ProcSubmitRequest(
                argv=[sys.executable, "-c", "print('done', flush=True)"],
                label="Envelope",
                cwd=tmp_path,
                origin="test",
                artifacts_dir=artifacts,
                result_path=result_path,
                followup={"next": "echo hi"},
            )
        ).proc_id,
        timeout=15,
    )

    assert finished.status == "success"
    assert result_path.is_file()
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600
    assert (artifacts / ".proc_settled.json").is_file()
    assert finished.result is not None
    assert finished.result["followup"] == "pending"


def test_legacy_rows_still_reconcile_without_settlement(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    orphan = Proc(
        proc_id="legacyorphan",
        label="legacy",
        kind="command",
        status="running",
        command=["true"],
        cwd=str(tmp_path),
        origin="test",
        created_at="2020-01-01T00:00:00Z",
        log_path=str(tmp_path / "legacyorphan.log"),
        pid=999_999_999,
    )
    append_proc(orphan)

    reconciled = reconcile_running_procs()

    assert [proc.proc_id for proc in reconciled] == [orphan.proc_id]
    assert reconciled[0].status == "error"
    assert reconciled[0].lifecycle != PROC_LIFECYCLE_PROC_SHELL
    assert reconciled[0].settled_at is None


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
