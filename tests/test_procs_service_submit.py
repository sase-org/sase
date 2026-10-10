"""Submit, reuse, timeout, and launch-failure tests for the named-proc supervisor.

Split from ``tests.test_procs_service``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from sase.procs import (
    COMMAND_PROC_KIND,
    PROC_LIFECYCLE_NAMED_PROC,
    ProcSubmitError,
    ProcSubmitRequest,
    append_proc,
    kill_proc,
    read_proc_log_tail,
    read_procs,
    reconcile_running_procs,
    submit_proc,
    submit_proc_request,
    wait_for_proc,
)
from sase.procs.models import Proc
from sase.procs.runtime import proc_started_path


def test_submit_records_a_named_proc_and_settles_success(
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

    assert proc.lifecycle == PROC_LIFECYCLE_NAMED_PROC
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
        proc_name="agent--build",
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


def test_named_named_proc_reuse_is_project_scoped_and_waits_for_settlement(
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
        proc_name="agent--build",
        concurrency_keys=["docs"],
    )
    finished = wait_for_proc(first.proc_id, timeout=15)

    assert finished.status == "success"
    assert finished.proc_name == "agent--build"
    assert finished.concurrency_keys == ["docs"]
    assert "agent--build" not in finished.concurrency_keys

    other_project = submit_proc(
        argv,
        label="Other project",
        cwd=tmp_path,
        origin="test",
        project="other",
        proc_name="agent--build",
    )
    wait_for_proc(other_project.proc_id, timeout=15)
    assert other_project.proc_id != first.proc_id

    reused = submit_proc(
        argv,
        label="Reuse",
        cwd=tmp_path,
        origin="test",
        project="sase",
        proc_name="agent--build",
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
        proc_name="agent--docs",
    )
    # Pre-flip cores report the conflict on `shell_name`; the contract flip
    # (sase-1ab.7) reports it on `proc_name`. Accept either spelling.
    with pytest.raises(ProcSubmitError, match="shell_name|proc_name"):
        submit_proc(
            argv,
            label="Conflict",
            cwd=tmp_path,
            origin="test",
            project="sase",
            proc_name="agent--docs",
        )
    kill_proc(active.proc_id)
    wait_for_proc(active.proc_id, timeout=15)


def test_submit_derives_bare_named_named_proc(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_AGENT_NAME", "foo--code")
    proc = submit_proc(
        [sys.executable, "-c", "print('ok', flush=True)"],
        label="Bare",
        cwd=tmp_path,
        origin="test",
        project="sase",
        proc_name="build",
    )
    wait_for_proc(proc.proc_id, timeout=15)

    assert proc.proc_name == "foo--build"
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
        "sase.procs.submission.write_launch_barrier", lambda *_a, **_k: None
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
    assert reconciled[0].lifecycle != PROC_LIFECYCLE_NAMED_PROC
    assert reconciled[0].settled_at is None
