"""Coverage for sudo settlement fitting and finalize-failure notifications."""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from sase.main.gate_handler import handle_gate_command
from sase.main.parser_sudo import register_sudo_parser
from sase.notification_gates.durability import canonical_json_bytes, read_json_object
from sase.notification_gates.input_bounds import MAX_INPUT_BYTES
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.notifications.store import load_notifications
from sase.sudo.answer_ops import apply_approved_receipt, settle_shell
from sase.sudo.cli import handle_sudo_command
from sase.sudo.detach_finalize import _record_finalize_failure
from sase.sudo.execution_handoff import LEDGER_FILENAME
from sase.sudo.execution_state import SudoExecutionState
from sase.sudo.finalize_notifications import VIEW_ERROR_REPORT_ACTION
from sase.sudo.gate import build_sudo_gate_request
from sase.sudo.manifest import selected_sudo_manifest
from tests._sudo_gate_helpers import (
    _incident_request,
    _oversized_runner_ledger,
    _request,
    _runner_ledger,
)
from tests.gate_turn._settlement_followup_helpers import make_gate_turn_member
from tests.main.parser_cli_helpers import parse_sase_args


def _sudo_gate_with_turn(*, request_id: str) -> tuple[Any, dict[str, Any], Any, str]:
    request = _request()
    request["next_prompt"] = "Review the sudo results."
    gate = create_gate(build_sudo_gate_request(request, request_id=request_id))
    envelope = read_json_object(gate.bundle_path / "request.json")
    artifacts_dir = make_gate_turn_member(
        request_id,
        gate.bundle_path,
        turn=envelope["turn"],
        branches=(("approve",), ("deny",)),
        gate_kind="sudo",
        label="Sudo request",
    )
    from sase.gate_turn.store import read_gate_turn_marker

    record = read_gate_turn_marker("proj", artifacts_dir)
    assert record is not None
    return gate, envelope, record, artifacts_dir


def _apply_sudo_receipt(gate: Any, envelope: dict[str, Any]) -> dict[str, Any]:
    sudo_payload = envelope["payload"]["sudo"]
    manifest, selected, manifest_sha256 = selected_sudo_manifest(
        dict(sudo_payload["manifest"]), ()
    )
    receipt = _runner_ledger(manifest, manifest_sha256)
    from sase.notification_gates.cli_support import resolve_gate_cli_bundle

    return apply_approved_receipt(
        resolve_gate_cli_bundle("sudo", gate.request_id),
        receipt,
        selected_command_ids=selected,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        feedback=None,
        retry=None,
    )


def _handshake_for_digest(manifest_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "sudo_exec_started",
        "manifest_sha256": manifest_sha256,
        "executor_pid": 1_000_000,
        "executor_identity": "boot-test:1",
        "ledger_path": "/tmp/ledger.json",
        "log_path": "/tmp/output.log",
        "started_at": 1_800_000_000.0,
    }


def _patch_handshake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.sudo.core._RustSudoCoreBinding.validate_handshake",
        lambda self, handshake, manifest=None: dict(handshake),
    )
    monkeypatch.setattr(
        "sase.sudo.core._RustSudoCoreBinding.authorize_settlement",
        lambda self, request: {
            "authorized": True,
            "authorization_id": "e" * 64,
            "gate_id": request["attempt"]["gate_id"],
            "manifest_sha256": request["attempt"]["manifest_sha256"],
            "schema_version": 1,
            "selected_command_ids": request["attempt"]["selected_command_ids"],
            "status": "authorized",
        },
    )


def _sudo_failure_rows() -> list[Any]:
    return [
        row
        for row in load_notifications(include_dismissed=True)
        if row.action == VIEW_ERROR_REPORT_ACTION
        and row.action_data.get("request_kind") == "sudo"
    ]


def test_oversized_ledger_finalize_settles_with_fitted_receipt(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    gate = create_gate(build_sudo_gate_request(_incident_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "answer", gate.request_id, "--run", "--json"])
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )
    monkeypatch.setattr(
        "sase.sudo.cli.runner_supports_detached_execution", lambda: True
    )
    _patch_handshake(monkeypatch)
    captured: dict[str, Any] = {}

    def fake_detached(
        manifest_path: Path,
        *,
        manifest_sha256: str,
        detach_dir: Path,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        del manifest_path
        captured["detach_dir"] = Path(detach_dir)
        captured["manifest_sha256"] = manifest_sha256
        return _handshake_for_digest(manifest_sha256)

    def fake_submit(request: Any) -> Any:
        captured["request"] = request
        return argparse.Namespace(proc_id="proc-sudo-fit-1")

    monkeypatch.setattr("sase.sudo.detach.run_sudo_runner_detached", fake_detached)
    monkeypatch.setattr("sase.sudo.detach.submit_proc_request", fake_submit)

    assert handle_sudo_command(args) == 0
    capsys.readouterr()

    envelope = read_json_object(gate.bundle_path / "request.json")
    sudo_payload = envelope["payload"]["sudo"]
    ledger = _oversized_runner_ledger(
        sudo_payload["manifest"], captured["manifest_sha256"]
    )
    command_ids = [entry["id"] for entry in ledger["entries"]]
    approve_input = {"command_ids": command_ids, "receipt": ledger}
    assert len(canonical_json_bytes(approve_input)) > MAX_INPUT_BYTES
    handoff = captured["detach_dir"]
    (handoff / LEDGER_FILENAME).write_text(json.dumps(ledger), encoding="utf-8")

    sidecar = tmp_path / "finalize-request.json"
    from sase.ops.io import write_operation_request
    from sase.ops.models import DurableOperationRequest
    from sase.ops.names import SUDO_FINALIZE

    write_operation_request(
        sidecar,
        DurableOperationRequest(
            operation=SUDO_FINALIZE,
            payload=dict(captured["request"].operation_payload),
        ),
    )
    finalize_args = parser.parse_args(
        [
            "sudo",
            "finalize",
            gate.request_id,
            "--json",
            "--request-path",
            str(sidecar),
        ]
    )
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: False,
    )
    monkeypatch.setattr(
        "sase.sudo.answer_ops.settle_shell",
        lambda gate_id, *, retry: "deferred",
    )

    assert handle_sudo_command(finalize_args) == 0

    raw = capsys.readouterr().out
    finished = json.loads(raw[raw.index("{") :])
    assert finished["status"] == "answered"
    assert finished["outcome"] == "completed"
    assert finished["settlement"] == "deferred"
    from sase.sudo.execution_state import load_execution_state

    assert load_execution_state(gate.bundle_path) is None
    assert not handoff.exists()
    response = read_json_object(gate.response_path)
    [approve_result] = response["option_results"]
    fitted = approve_result["result"]["receipt"]
    fitted_input = {
        "command_ids": approve_result["result"]["command_ids"],
        "receipt": fitted,
    }
    assert len(canonical_json_bytes(fitted_input)) <= MAX_INPUT_BYTES
    by_id = {entry["id"]: entry for entry in fitted["entries"]}
    assert by_id["verify-units"]["output_tail"] == "v" * 375
    assert by_id["daemon-reload"]["output_tail"] == ""
    assert by_id["nft-ruleset"]["output_tail"].startswith("[sase sudo: ")
    assert "omitted to fit the settlement budget" in by_id["nft-ruleset"]["output_tail"]
    assert not _sudo_failure_rows()


def test_sudo_answer_waits_for_concurrent_reclaimer_without_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    gate, envelope, record, artifacts_dir = _sudo_gate_with_turn(
        request_id="sudo-followup-race"
    )
    import sase.gate_turn.settlement as settlement_module

    monkeypatch.setattr(settlement_module, "FOLLOWUP_LOCK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        settlement_module, "CREATOR_LIVE_FOLLOWUP_LOCK_TIMEOUT_SECONDS", 1.0
    )
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty", lambda: True
    )
    monkeypatch.setattr(
        settlement_module, "hold_gate_turn_claim_for_settlement", lambda *a, **k: None
    )
    monkeypatch.setattr(
        settlement_module, "finalize_turn_workflow_state", lambda *_args: None
    )
    monkeypatch.setattr(
        settlement_module, "touch_turn_refresh_pulse", lambda *_args: None
    )

    answer_written = threading.Event()
    launch_started = threading.Event()
    release_launch = threading.Event()
    launch_calls: list[str] = []
    thread_errors: list[BaseException] = []

    def blocked_followup(
        called_dir: str,
        meta: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        del called_dir, kwargs
        launch_calls.append("launched")
        meta["gate_followup_agent"] = "sudo-followup"
        meta["gate_followup_outcome"] = "launched"
        launch_started.set()
        timer = threading.Timer(0.15, release_launch.set)
        timer.start()
        release_launch.wait(timeout=2)

    monkeypatch.setattr(
        settlement_module, "launch_or_record_followup", blocked_followup
    )
    from sase.sudo import answer_ops

    real_execute = answer_ops.execute_gate_selection

    def execute_then_wait_for_reclaimer(*args: Any, **kwargs: Any) -> Any:
        result = real_execute(*args, **kwargs)
        answer_written.set()
        assert launch_started.wait(timeout=2)
        return result

    monkeypatch.setattr(
        answer_ops, "execute_gate_selection", execute_then_wait_for_reclaimer
    )

    def reclaim() -> None:
        try:
            assert answer_written.wait(timeout=2)
            settlement_module.settle_gate_turn(
                record, gate_state="answered", reason="gate answered"
            )
        except BaseException as exc:
            thread_errors.append(exc)

    reclaim_thread = threading.Thread(target=reclaim)
    reclaim_thread.start()
    try:
        payload = _apply_sudo_receipt(gate, envelope)
    finally:
        release_launch.set()
        reclaim_thread.join(timeout=2)

    assert not reclaim_thread.is_alive()
    assert thread_errors == []
    assert payload["settlement"] == "settled"
    assert launch_calls == ["launched"]
    from sase.gate_turn.store import read_gate_turn_marker

    settled = read_gate_turn_marker("proj", artifacts_dir)
    assert settled is not None and settled.gate_state == "answered"
    assert _sudo_failure_rows() == []


def test_sudo_answer_defers_after_long_lock_timeout_and_reclaim_settles_later(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    gate, envelope, record, artifacts_dir = _sudo_gate_with_turn(
        request_id="sudo-followup-deferred"
    )
    import sase.gate_turn.settlement as settlement_module
    from sase.gate_turn.handoff import with_gate_followup_lock

    monkeypatch.setattr(settlement_module, "FOLLOWUP_LOCK_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(
        settlement_module, "CREATOR_LIVE_FOLLOWUP_LOCK_TIMEOUT_SECONDS", 0.05
    )
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty", lambda: True
    )
    monkeypatch.setattr(
        settlement_module, "hold_gate_turn_claim_for_settlement", lambda *a, **k: None
    )
    monkeypatch.setattr(
        settlement_module, "finalize_turn_workflow_state", lambda *_args: None
    )
    monkeypatch.setattr(
        settlement_module, "touch_turn_refresh_pulse", lambda *_args: None
    )

    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_lock() -> None:
        with with_gate_followup_lock(artifacts_dir, timeout=1.0):
            lock_held.set()
            release_lock.wait(timeout=2)

    lock_thread = threading.Thread(target=hold_lock)
    lock_thread.start()
    assert lock_held.wait(timeout=2)
    try:
        payload = _apply_sudo_receipt(gate, envelope)
    finally:
        release_lock.set()
        lock_thread.join(timeout=2)

    assert not lock_thread.is_alive()
    assert payload["settlement"] == "deferred"
    assert _sudo_failure_rows() == []

    launches: list[str] = []

    def record_followup(
        called_dir: str,
        meta: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        del called_dir, kwargs
        launches.append("launched")
        meta["gate_followup_agent"] = "sudo-followup"
        meta["gate_followup_outcome"] = "launched"

    monkeypatch.setattr(settlement_module, "launch_or_record_followup", record_followup)
    settlement_module.settle_gate_turn(
        record, gate_state="answered", reason="gate answered"
    )
    from sase.gate_turn.store import read_gate_turn_marker

    settled = read_gate_turn_marker("proj", artifacts_dir)
    assert settled is not None and settled.gate_state == "answered"
    assert launches == ["launched"]


def test_sudo_answered_shell_resume_does_not_rerun_approved_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    gate, envelope, record, _artifacts_dir = _sudo_gate_with_turn(
        request_id="sudo-resume-no-rerun"
    )
    monkeypatch.setattr(
        "sase.sudo.answer_ops.settle_shell", lambda gate_id, *, retry: "settled"
    )
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty", lambda: True
    )
    _apply_sudo_receipt(gate, envelope)
    settle_kwargs: list[dict[str, object]] = []

    def recording_settle(gate_record: Any, **kwargs: Any) -> Any:
        settle_kwargs.append(dict(kwargs))
        return gate_record

    monkeypatch.setattr(
        "sase.notification_gates.cli_answer_resume.find_gate_turn_by_gate_id",
        lambda *args, **kwargs: record,
    )
    monkeypatch.setattr(
        "sase.notification_gates.cli_answer_resume.settle_gate_turn",
        recording_settle,
    )
    monkeypatch.setattr(
        "sase.notification_gates.cli_answer_resume.execute_gate_selection",
        lambda *args, **kwargs: pytest.fail(
            "resuming an answered sudo shell must not rerun the approved commands"
        ),
    )
    args = parse_sase_args(
        [
            "gate",
            "answer",
            "--kind",
            "sudo",
            "--id",
            gate.request_id,
            "--option",
            "approve",
            "--resume",
        ]
    )
    with pytest.raises(SystemExit) as exit_info:
        handle_gate_command(args)

    assert exit_info.value.code == 0
    assert settle_kwargs[0]["wait_out_contention"] is True


def test_finalize_failure_notification_dedupes_and_settlement_dismisses(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del capsys
    gate = create_gate(build_sudo_gate_request(_request()))
    envelope = read_json_object(gate.bundle_path / "request.json")
    sudo_payload = envelope["payload"]["sudo"]
    receipt = _runner_ledger(sudo_payload["manifest"], sudo_payload["manifest_sha256"])
    state = SudoExecutionState(
        gate_id=gate.request_id,
        selected_command_ids=tuple(entry["id"] for entry in receipt["entries"]),
        manifest_sha256=sudo_payload["manifest_sha256"],
        handoff_dir=str(tmp_path / "handoff"),
        finalize_proc_id="proc-sudo-fail-1",
        target_kind="local",
    )
    error = GateError(
        "input_too_large",
        "option approve input",
        "forced finalize failure",
    )
    _record_finalize_failure(gate.bundle_path, error, receipt=receipt, state=state)
    _record_finalize_failure(gate.bundle_path, error, receipt=receipt, state=state)

    rows = _sudo_failure_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.dismissed is False
    assert row.action == VIEW_ERROR_REPORT_ACTION
    assert row.action_data["request_id"] == gate.request_id
    assert row.action_data["request_kind"] == "sudo"
    assert row.plus_one_count >= 1
    assert any("commands ran:" in note for note in row.notes)
    assert any("sase sudo answer" in note for note in row.notes)
    assert any("--run reruns the selected commands" in note for note in row.notes)

    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--no-detach", "--json"]
    )
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )
    monkeypatch.setattr(
        "sase.sudo.cli.run_sudo_runner",
        lambda manifest, **kwargs: _runner_ledger(
            manifest, str(kwargs["manifest_sha256"])
        ),
    )
    assert handle_sudo_command(args) == 0

    settled = _sudo_failure_rows()
    assert len(settled) == 1
    assert settled[0].dismissed is True


def test_finalize_failure_with_durable_answer_points_to_handoff_resume(
    gate_home: Path,
) -> None:
    gate = create_gate(build_sudo_gate_request(_request()))
    gate.response_path.write_text('{"selected_option_ids": ["approve"]}\n')
    _record_finalize_failure(
        gate.bundle_path,
        GateError("side_effect_failed", "approve", "post-answer failure"),
        receipt=None,
        state=None,
    )

    [row] = _sudo_failure_rows()
    note = " ".join(row.notes)
    assert "the answer is recorded" in note
    assert "do not rerun the commands" in note
    assert "sase gate answer --kind sudo --id" in note
    assert "--option approve --resume" in note
    assert "--run reruns the selected commands" not in note


def test_settle_shell_defers_only_lock_timeout(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    record = object()
    monkeypatch.setattr(
        "sase.sudo.answer_ops.find_gate_turn_by_gate_id",
        lambda *args, **kwargs: record,
    )

    def timeout(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise GateError("lock_timeout", "gate_followup.lock", "held by pid 123")

    monkeypatch.setattr("sase.sudo.answer_ops.settle_gate_turn", timeout)
    assert settle_shell("sudo-test", retry=None) == "deferred"
    assert "sudo-test" in caplog.text
    assert "held by pid 123" in caplog.text

    failure = GateError("invalid_gate", "gate", "unexpected settlement error")

    def fail(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise failure

    monkeypatch.setattr("sase.sudo.answer_ops.settle_gate_turn", fail)
    with pytest.raises(GateError) as exc_info:
        settle_shell("sudo-test", retry=None)
    assert exc_info.value is failure
