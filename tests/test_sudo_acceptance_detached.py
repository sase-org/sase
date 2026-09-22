"""Sudo acceptance coverage for detached answer and finalize flows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from sase.feature_flags import override_flags
from sase.main.parser_sudo import register_sudo_parser
from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.service import create_gate
from sase.sudo.cli import handle_sudo_command
from sase.sudo.gate import build_sudo_gate_request
from tests._sudo_acceptance_helpers import (
    _install_capable_runner,
    _request,
    _runner_ledger,
)


def test_sudo_detached_answer_finalizes_like_synchronous(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    _install_capable_runner(tmp_path, monkeypatch)
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(
            build_sudo_gate_request(_request(), request_id="sudo-detach-flow")
        )
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )
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
    captured: dict[str, Any] = {}

    def fake_submit(request: Any) -> Any:
        captured["request"] = request
        return argparse.Namespace(proc_id="proc-detach-1")

    monkeypatch.setattr("sase.sudo.detach.submit_proc_request", fake_submit)
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    answer_args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--detach", "--json"]
    )

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(answer_args) == 0

    started = json.loads(capsys.readouterr().out)
    assert started["status"] == "execution_started"
    assert started["proc_id"] == "proc-detach-1"
    assert not gate.response_path.exists()
    request = captured["request"]
    assert request.shell_kind == "gate"
    assert request.operation == "sudo.finalize"
    assert request.operation_payload["handoff_dir"]
    sidecar = tmp_path / "finalize-request.json"
    from sase.ops.io import write_operation_request
    from sase.ops.models import DurableOperationRequest
    from sase.ops.names import SUDO_FINALIZE

    write_operation_request(
        sidecar,
        DurableOperationRequest(
            operation=SUDO_FINALIZE, payload=dict(request.operation_payload)
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

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(finalize_args) == 0

    raw = capsys.readouterr().out
    assert "starting reviewed command" in raw
    finished = json.loads(raw[raw.index("{") :])
    assert finished["status"] == "answered"
    assert finished["outcome"] == "completed"
    assert gate.response_path.is_file()
    assert (gate.bundle_path / DECISION_RECEIPT_FILENAME).is_file()
    handoff = Path(request.operation_payload["handoff_dir"])
    assert not handoff.exists()


def test_sudo_detached_finalize_is_idempotent_after_response(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
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
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    answer_args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--no-detach", "--json"]
    )
    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(answer_args) == 0
    capsys.readouterr()
    sidecar = tmp_path / "finalize-request.json"
    from sase.ops.io import write_operation_request
    from sase.ops.models import DurableOperationRequest
    from sase.ops.names import SUDO_FINALIZE

    write_operation_request(
        sidecar,
        DurableOperationRequest(
            operation=SUDO_FINALIZE,
            payload={
                "gate_id": gate.request_id,
                "selected_command_ids": ["refresh"],
            },
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
    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(finalize_args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "answered"


def test_sudo_detached_nonterminal_ledger_leaves_gate_pending(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--detach", "--json"]
    )
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.sudo.cli.runner_supports_detached_execution", lambda: True
    )
    monkeypatch.setattr(
        "sase.sudo.detach.run_sudo_runner_detached",
        lambda *_args, **kwargs: {
            "schema_version": 1,
            "request_id": "x",
            "manifest_sha256": kwargs["manifest_sha256"],
            "outcome": "auth_failed",
            "entries": [],
            "diagnostic": "no",
        },
    )
    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pending"
    assert output["code"] == "authentication_failed"
    assert not gate.response_path.exists()


def test_sudo_finalize_executor_death_without_ledger(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    from sase.sudo.execution import (
        SudoExecutionState,
        create_handoff_dir,
        write_execution_state,
    )
    from sase.sudo.manifest import selected_sudo_manifest

    sudo_payload = read_json_object(gate.request_path)["payload"]["sudo"]
    manifest, selected, digest = selected_sudo_manifest(
        dict(sudo_payload["manifest"]), ()
    )
    handoff = create_handoff_dir(gate.request_id, manifest)
    write_execution_state(
        gate.bundle_path,
        SudoExecutionState(
            gate_id=gate.request_id,
            selected_command_ids=selected,
            manifest_sha256=digest,
            handoff_dir=str(handoff),
            handshake={
                "executor_pid": 1_000_001,
                "executor_identity": "boot:1",
            },
            finalize_proc_id="proc-dead",
        ),
    )
    monkeypatch.setattr("sase.sudo.detach.executor_is_live", lambda _handshake: False)
    monkeypatch.setattr("sase.sudo.detach._EXECUTOR_DEATH_GRACE_SECONDS", 0.01)
    sidecar = tmp_path / "finalize-request.json"
    from sase.ops.io import write_operation_request
    from sase.ops.models import DurableOperationRequest
    from sase.ops.names import SUDO_FINALIZE

    write_operation_request(
        sidecar,
        DurableOperationRequest(
            operation=SUDO_FINALIZE,
            payload={
                "gate_id": gate.request_id,
                "handoff_dir": str(handoff),
                "handshake": {
                    "executor_pid": 1_000_001,
                    "executor_identity": "boot:1",
                },
                "manifest_sha256": digest,
                "selected_command_ids": list(selected),
            },
        ),
    )
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        [
            "sudo",
            "finalize",
            gate.request_id,
            "--json",
            "--request-path",
            str(sidecar),
        ]
    )
    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pending"
    assert output["code"] == "executor_died"
    assert not gate.response_path.exists()
