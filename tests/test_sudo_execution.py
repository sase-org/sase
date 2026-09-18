"""Coverage for detached sudo execution records and handoff lifecycle."""

from __future__ import annotations

import os
import stat
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from sase.notification_gates.models import GateError
from sase.sudo.execution import (
    HANDOFF_DIR_MODE,
    HANDOFF_FILE_MODE,
    LOG_FILENAME,
    MANIFEST_FILENAME,
    STOP_FILENAME,
    SudoExecutionState,
    claim_execution_record,
    cleanup_handoff,
    copy_output_log,
    create_handoff_dir,
    execution_is_live,
    load_execution_state,
    project_execution,
    recover_dead_attempt,
    write_execution_state,
    write_stop_file,
)


def _manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "sudo-exec-1",
        "commands": [{"id": "refresh", "argv": ["/usr/bin/true"]}],
    }


def _state(
    tmp_path: Path,
    *,
    proc_id: str | None = "proc-1",
    handshake: dict[str, Any] | None = None,
) -> SudoExecutionState:
    return SudoExecutionState(
        gate_id="sudo-exec-1",
        selected_command_ids=("refresh",),
        manifest_sha256="a" * 64,
        handoff_dir=str(tmp_path / "handoff"),
        handshake=handshake,
        finalize_proc_id=proc_id,
    )


def test_create_handoff_dir_is_user_owned_0700(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    handoff = create_handoff_dir("sudo-exec-1", _manifest())
    metadata = handoff.stat()
    manifest = handoff / MANIFEST_FILENAME

    assert stat.S_IMODE(metadata.st_mode) == HANDOFF_DIR_MODE
    assert metadata.st_uid == os.getuid()
    assert manifest.is_file()
    assert stat.S_IMODE(manifest.stat().st_mode) == HANDOFF_FILE_MODE
    assert not manifest.is_symlink()


def test_execution_state_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    state = _state(tmp_path, handshake={"executor_pid": 11, "executor_identity": "b:1"})
    write_execution_state(bundle, state)

    loaded = load_execution_state(bundle)
    path = bundle / "execution-state.json"

    assert loaded == state
    assert stat.S_IMODE(path.stat().st_mode) == HANDOFF_FILE_MODE


def test_claim_rejects_live_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_execution_state(bundle, _state(tmp_path))
    monkeypatch.setattr("sase.sudo.execution._proc_is_live", lambda _proc_id: True)
    monkeypatch.setattr(
        "sase.sudo.execution.executor_is_live", lambda _handshake: False
    )

    claimed = claim_execution_record(bundle, gate_id="sudo-exec-1")

    assert claimed is not None
    assert claimed.finalize_proc_id == "proc-1"


def test_claim_clears_stale_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    handoff = create_handoff_dir("sudo-exec-1", _manifest())
    write_execution_state(bundle, _state(tmp_path, proc_id="proc-dead", handshake=None))
    # Point the record at the real handoff so stale cleanup can remove it.
    write_execution_state(
        bundle,
        SudoExecutionState(
            gate_id="sudo-exec-1",
            selected_command_ids=("refresh",),
            manifest_sha256="a" * 64,
            handoff_dir=str(handoff),
        ),
    )
    monkeypatch.setattr("sase.sudo.execution._proc_is_live", lambda _proc_id: False)
    monkeypatch.setattr(
        "sase.sudo.execution.executor_is_live", lambda _handshake: False
    )

    claimed = claim_execution_record(bundle, gate_id="sudo-exec-1")

    assert claimed is None
    assert load_execution_state(bundle) is None
    assert not handoff.exists()
    assert "cleared stale sudo execution record" in capsys.readouterr().err


def test_cleanup_refuses_unowned_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    outsider = tmp_path / "not-sase"
    outsider.mkdir()
    marker = outsider / "keep"
    marker.write_text("safe\n", encoding="utf-8")

    cleanup_handoff(outsider)

    assert marker.is_file()


def test_copy_output_log_is_incremental(tmp_path: Path) -> None:
    log_path = tmp_path / LOG_FILENAME
    log_path.write_bytes(b"one\n")
    dest = BytesIO()

    offset = copy_output_log(log_path, offset=0, dest=dest)
    log_path.write_bytes(b"one\ntwo\n")
    offset = copy_output_log(log_path, offset=offset, dest=dest)

    assert dest.getvalue() == b"one\ntwo\n"
    assert offset == len(b"one\ntwo\n")


def test_write_stop_file_is_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    handoff = create_handoff_dir("sudo-exec-1", _manifest())
    write_stop_file(handoff)
    stop = handoff / STOP_FILENAME

    assert stop.is_file()
    assert stat.S_IMODE(stop.stat().st_mode) == HANDOFF_FILE_MODE


def test_project_execution_only_when_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_execution_state(
        bundle,
        _state(tmp_path, handshake={"executor_pid": 44, "executor_identity": "b:1"}),
    )
    liveness = {"classification": "live"}

    def classify(
        _self: object,
        _attempt: dict[str, Any],
        _facts: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "classification": liveness["classification"],
            "reason": "test",
        }

    monkeypatch.setattr(
        "sase.sudo.core._RustSudoCoreBinding.classify_attempt_liveness",
        classify,
    )

    live = project_execution(bundle)
    liveness["classification"] = "dead"
    dead = project_execution(bundle)

    assert live.executing is True
    assert live.finalize_proc_id == "proc-1"
    assert live.executor_pid == 44
    assert dead.executing is False
    assert dead.finalize_proc_id is None


def test_project_execution_remote_unknown_does_not_probe_local_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_execution_state(
        bundle,
        SudoExecutionState(
            gate_id="sudo-exec-1",
            selected_command_ids=("refresh",),
            manifest_sha256="a" * 64,
            handoff_dir=str(tmp_path / "handoff"),
            handshake={"executor_pid": 44, "executor_identity": "b:1"},
            finalize_proc_id="proc-remote",
            target_kind="remote",
            target_host="apollo",
            startup_state="started",
        ),
    )

    def classify(
        _self: object,
        _attempt: dict[str, Any],
        facts: dict[str, Any],
    ) -> dict[str, Any]:
        assert facts["executor_pid_live"] is None
        assert facts["executor_identity_matches"] is None
        return {
            "schema_version": 1,
            "classification": "unknown",
            "reason": "remote",
        }

    monkeypatch.setattr(
        "sase.sudo.core._RustSudoCoreBinding.classify_attempt_liveness",
        classify,
    )
    monkeypatch.setattr(
        "sase.sudo.execution._pid_is_running",
        lambda _pid: (_ for _ in ()).throw(AssertionError("local pid probe")),
    )

    projection = project_execution(bundle)

    assert projection.executing is True
    assert projection.executor_pid is None
    assert projection.liveness == "unknown"


def test_recover_dead_attempt_keeps_live_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_execution_state(bundle, _state(tmp_path))
    monkeypatch.setattr(
        "sase.sudo.core._RustSudoCoreBinding.classify_attempt_liveness",
        lambda _self, _attempt, _facts: {
            "schema_version": 1,
            "classification": "live",
            "reason": "test",
        },
    )

    recover_dead_attempt(bundle)

    assert load_execution_state(bundle) is not None


def test_live_execution_error_names_proc(tmp_path: Path) -> None:
    from sase.sudo.execution import live_execution_error

    error = live_execution_error(_state(tmp_path, proc_id="proc-live"))

    assert error.code == "execution_in_progress"
    assert error.target == "proc-live"
    assert "proc-live" in str(error)


def test_execution_is_live_when_proc_or_executor_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("sase.sudo.execution._proc_is_live", lambda _proc_id: True)
    assert execution_is_live(_state(tmp_path)) is True

    monkeypatch.setattr("sase.sudo.execution._proc_is_live", lambda _proc_id: False)
    monkeypatch.setattr("sase.sudo.execution._pid_is_running", lambda _pid: True)
    monkeypatch.setattr(
        "sase.sudo.execution.process_identity_matches",
        lambda _pid, _identity: True,
    )
    assert (
        execution_is_live(
            _state(
                tmp_path,
                proc_id=None,
                handshake={
                    "schema_version": 1,
                    "kind": "sudo_exec_started",
                    "manifest_sha256": "a" * 64,
                    "executor_pid": 44,
                    "executor_identity": "boot:1",
                    "ledger_path": "/tmp/ledger.json",
                    "log_path": "/tmp/output.log",
                    "started_at": 1_800_000_000.0,
                },
            )
        )
        is True
    )

    monkeypatch.setattr("sase.sudo.execution._pid_is_running", lambda _pid: False)
    monkeypatch.setattr(
        "sase.sudo.execution.executor_is_live", lambda _handshake: False
    )
    assert execution_is_live(_state(tmp_path, proc_id=None)) is False
