"""Supervisor settlement around versioned operation contracts."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from sase.ops import (
    DurableOperationResult,
    read_operation_request,
    read_operation_result,
    write_operation_result,
)
from sase.procs import (
    ProcSubmitRequest,
    get_proc,
    reconcile_running_procs,
    submit_proc_request,
    wait_for_proc,
)
from sase.procs.runtime import proc_settlement_sidecar_path, read_json_object


def _settlement_checkpoints(proc_id: str) -> dict[str, bool]:
    state = read_json_object(proc_settlement_sidecar_path(proc_id))
    checkpoints = state.get("checkpoints") or {}
    return {str(name): bool(value) for name, value in checkpoints.items()}


def test_operation_request_is_written_before_launch_and_result_round_trips(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    result_path = tmp_path / "typed-result.json"
    request_path = tmp_path / "typed-request.json"
    writer = tmp_path / "write_result.py"
    writer.write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "path = Path(os.environ['SASE_PROC_RESULT_PATH'])\n"
        "path.write_text(json.dumps({\n"
        "  'schema_version': 1,\n"
        "  'operation': os.environ['SASE_PROC_OPERATION'],\n"
        "  'proc_id': os.environ['SASE_PROC_ID'],\n"
        "  'success': True,\n"
        "  'message': 'status updated',\n"
        "  'error': None,\n"
        "  'payload': {'status': 'Ready'},\n"
        "}))\n"
        "os.chmod(path, 0o600)\n",
        encoding="utf-8",
    )
    finished = wait_for_proc(
        submit_proc_request(
            ProcSubmitRequest(
                argv=[sys.executable, str(writer)],
                label="Typed",
                cwd=tmp_path,
                origin="test",
                operation="patch.status",
                operation_payload={"name": "demo", "status": "Ready"},
                request_path=request_path,
                result_path=result_path,
            )
        ).proc_id,
        timeout=15,
    )

    assert finished.status == "success"
    loaded = read_operation_request(request_path, expected_operation="patch.status")
    assert loaded.payload == {"name": "demo", "status": "Ready"}
    assert stat.S_IMODE(request_path.stat().st_mode) == 0o600
    result = read_operation_result(
        result_path,
        expected_operation="patch.status",
        expected_proc_id=finished.proc_id,
    )
    assert result.success is True
    assert result.payload == {"status": "Ready"}
    assert all(_settlement_checkpoints(finished.proc_id).values())


def test_successful_command_without_result_settles_as_durable_error(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    result_path = tmp_path / "missing-result.json"
    finished = wait_for_proc(
        submit_proc_request(
            ProcSubmitRequest(
                argv=[sys.executable, "-c", "print('ok', flush=True)"],
                label="Missing result",
                cwd=tmp_path,
                origin="test",
                operation="patch.status",
                operation_payload={"name": "demo"},
                result_path=result_path,
            )
        ).proc_id,
        timeout=15,
    )

    assert finished.status == "error"
    assert finished.result is not None
    assert finished.result["termination_reason"] == "missing-result"
    result = read_operation_result(
        result_path,
        expected_operation="patch.status",
        expected_proc_id=finished.proc_id,
    )
    assert result.success is False
    assert "missing" in (result.error or result.message)


def test_command_failure_writes_error_envelope_without_log_inference(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    result_path = tmp_path / "failed-result.json"
    finished = wait_for_proc(
        submit_proc_request(
            ProcSubmitRequest(
                argv=[sys.executable, "-c", "raise SystemExit(3)"],
                label="Fail",
                cwd=tmp_path,
                origin="test",
                operation="patch.revert",
                result_path=result_path,
            )
        ).proc_id,
        timeout=15,
    )

    assert finished.status == "error"
    result = read_operation_result(
        result_path,
        expected_operation="patch.revert",
        expected_proc_id=finished.proc_id,
    )
    assert result.success is False
    assert result.payload is None
    assert "secret-from-logs" not in (result.message or "")


def test_legacy_submission_without_operation_stays_compatible(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    result_path = tmp_path / "legacy.json"
    finished = wait_for_proc(
        submit_proc_request(
            ProcSubmitRequest(
                argv=[sys.executable, "-c", "print('done', flush=True)"],
                label="Legacy",
                cwd=tmp_path,
                origin="test",
                result_path=result_path,
            )
        ).proc_id,
        timeout=15,
    )

    assert finished.status == "success"
    assert result_path.is_file()
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600
    envelope = json_load(result_path)
    assert envelope["termination_reason"] == "success"
    assert envelope["proc_id"] == finished.proc_id


def test_result_before_terminal_crash_after_publication(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", "result_written")
    result_path = tmp_path / "crash-result.json"
    writer = tmp_path / "write_result.py"
    writer.write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "path = Path(os.environ['SASE_PROC_RESULT_PATH'])\n"
        "payload = {\n"
        "  'schema_version': 1,\n"
        "  'operation': os.environ['SASE_PROC_OPERATION'],\n"
        "  'proc_id': os.environ['SASE_PROC_ID'],\n"
        "  'success': True,\n"
        "  'message': 'published',\n"
        "  'error': None,\n"
        "  'payload': {},\n"
        "}\n"
        "path.write_text(json.dumps(payload))\n"
        "os.chmod(path, 0o600)\n",
        encoding="utf-8",
    )
    proc = submit_proc_request(
        ProcSubmitRequest(
            argv=[sys.executable, str(writer)],
            label="Crash after result",
            cwd=tmp_path,
            origin="test",
            operation="patch.status",
            result_path=result_path,
        )
    )
    _wait_for_supervisor_exit(proc.proc_id)
    monkeypatch.delenv("SASE_PROC_SUPERVISOR_CRASH_AFTER", raising=False)

    published = read_operation_result(
        result_path, expected_operation="patch.status", expected_proc_id=proc.proc_id
    )
    assert published.success is True
    reconcile_running_procs()
    finished = get_proc(proc.proc_id)
    assert finished is not None
    if finished.status not in {"success", "error"}:
        finished = wait_for_proc(proc.proc_id, timeout=10)
    assert finished.status == "success"
    assert finished.settled_at is not None
    assert all(_settlement_checkpoints(proc.proc_id).values())


def test_overlapping_concurrency_keys_conflict(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    first = submit_proc_request(
        ProcSubmitRequest(
            argv=[sys.executable, "-c", "import time; time.sleep(20)"],
            label="First",
            cwd=tmp_path,
            origin="test",
            concurrency_keys=["ace:patch:demo"],
            request_fingerprint="sha256:first",
        )
    )
    with pytest.raises(Exception, match="concurrency"):
        submit_proc_request(
            ProcSubmitRequest(
                argv=[sys.executable, "-c", "print('nope')"],
                label="Second",
                cwd=tmp_path,
                origin="test",
                concurrency_keys=["ace:patch:demo"],
                request_fingerprint="sha256:second",
            )
        )
    from sase.procs import kill_proc

    kill_proc(first.proc_id)
    wait_for_proc(first.proc_id, timeout=15)


def json_load(path: Path) -> dict[str, Any]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _wait_for_supervisor_exit(proc_id: str) -> None:
    import time

    from sase.procs.runtime import proc_settlement_sidecar_path

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = get_proc(proc_id)
        assert current is not None
        if (
            current.status == "settling"
            or proc_settlement_sidecar_path(proc_id).exists()
        ):
            if current.pid is None:
                return
            try:
                os.kill(current.pid, 0)
            except OSError:
                return
        time.sleep(0.05)  # sase-test-wait: poll for injected settlement crash
