"""Coverage for sudo settlement fitting and finalize-failure notifications."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from sase.main.parser_sudo import register_sudo_parser
from sase.notification_gates.durability import canonical_json_bytes, read_json_object
from sase.notification_gates.input_bounds import MAX_INPUT_BYTES
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.notifications.store import load_notifications
from sase.sudo.cli import handle_sudo_command
from sase.sudo.detach_finalize import _record_finalize_failure
from sase.sudo.execution_handoff import LEDGER_FILENAME
from sase.sudo.execution_state import SudoExecutionState
from sase.sudo.finalize_notifications import VIEW_ERROR_REPORT_ACTION
from sase.sudo.gate import build_sudo_gate_request
from tests._sudo_gate_helpers import (
    _incident_request,
    _oversized_runner_ledger,
    _request,
    _runner_ledger,
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

    assert handle_sudo_command(finalize_args) == 0

    raw = capsys.readouterr().out
    finished = json.loads(raw[raw.index("{") :])
    assert finished["status"] == "answered"
    assert finished["outcome"] == "completed"
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
