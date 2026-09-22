"""Sudo acceptance coverage for remote finalize flows."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest

from sase.feature_flags import override_flags
from sase.main.parser_sudo import register_sudo_parser
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.service import create_gate
from sase.sudo.cli import handle_sudo_command
from sase.sudo.gate import build_sudo_gate_request
from tests._sudo_acceptance_helpers import _request, _runner_ledger


def test_remote_finalize_headless_streams_output_and_settles_once(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(
            build_sudo_gate_request(_request(), request_id="sudo-remote-headless")
        )
    from sase.ops.io import write_operation_request
    from sase.ops.models import DurableOperationRequest
    from sase.ops.names import SUDO_FINALIZE
    from sase.sudo.execution import (
        SudoExecutionState,
        create_handoff_dir,
        load_execution_state,
        write_execution_state,
    )
    from sase.sudo.manifest import selected_sudo_manifest
    from tests._sudo_ssh_fake import FakeOpenSSHEndpoint, current_process_identity

    sudo_payload = read_json_object(gate.request_path)["payload"]["sudo"]
    manifest, selected, digest = selected_sudo_manifest(
        dict(sudo_payload["manifest"]), ()
    )
    handoff = create_handoff_dir(gate.request_id, manifest)
    remote_root = tmp_path / "remote cwd"
    remote_dir = remote_root / "sase-sudo-headless"
    remote_dir.mkdir(parents=True)
    remote_paths = {
        "directory": str(remote_dir),
        "handshake": str(remote_dir / "handshake.json"),
        "ledger": str(remote_dir / "ledger.json"),
        "log": str(remote_dir / "output.log"),
        "manifest": str(remote_dir / "manifest.json"),
        "stop": str(remote_dir / "stop"),
    }
    Path(remote_paths["log"]).write_text(
        "starting reviewed command\ndone\n", encoding="utf-8"
    )
    Path(remote_paths["ledger"]).write_text(
        json.dumps(_runner_ledger(manifest, digest)) + "\n", encoding="utf-8"
    )
    pid = os.getpid()
    handshake = {
        "schema_version": 1,
        "kind": "sudo_exec_started",
        "manifest_sha256": digest,
        "executor_pid": pid,
        "executor_identity": current_process_identity(pid),
        "ledger_path": remote_paths["ledger"],
        "log_path": remote_paths["log"],
        "started_at": 1_800_000_000.0,
    }
    write_execution_state(
        gate.bundle_path,
        SudoExecutionState(
            gate_id=gate.request_id,
            selected_command_ids=selected,
            manifest_sha256=digest,
            handoff_dir=str(handoff),
            handshake=handshake,
            finalize_proc_id="proc-remote-headless",
            target_kind="remote",
            target_host="apollo",
            startup_state="started",
            remote_handoff=remote_paths,
        ),
    )
    fake = FakeOpenSSHEndpoint(tmp_path)
    monkeypatch.setattr("sase.sudo.ssh_detached.subprocess.run", fake)
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
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: False,
    )
    sidecar = tmp_path / "finalize-request.json"
    write_operation_request(
        sidecar,
        DurableOperationRequest(
            operation=SUDO_FINALIZE,
            payload={
                "gate_id": gate.request_id,
                "handoff_dir": str(handoff),
                "handshake": handshake,
                "manifest_sha256": digest,
                "selected_command_ids": list(selected),
                "remote": {"host": "apollo", "paths": remote_paths},
            },
        ),
    )
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
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
    raw = capsys.readouterr().out
    assert "starting reviewed command" in raw
    finished = json.loads(raw[raw.index("{") :])
    assert finished["status"] == "answered"
    assert finished["outcome"] == "completed"
    assert gate.response_path.is_file()
    assert load_execution_state(gate.bundle_path) is None
    assert not remote_dir.exists()

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(finalize_args) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["status"] == "answered"


def test_remote_finalize_uncertain_error_keeps_recovery_state(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    from sase.ops.io import write_operation_request
    from sase.ops.models import DurableOperationRequest
    from sase.ops.names import SUDO_FINALIZE
    from sase.sudo.execution import (
        SudoExecutionState,
        create_handoff_dir,
        load_execution_state,
        write_execution_state,
    )
    from sase.sudo.manifest import selected_sudo_manifest
    from tests._sudo_ssh_fake import FakeOpenSSHEndpoint, current_process_identity

    sudo_payload = read_json_object(gate.request_path)["payload"]["sudo"]
    manifest, selected, digest = selected_sudo_manifest(
        dict(sudo_payload["manifest"]), ()
    )
    handoff = create_handoff_dir(gate.request_id, manifest)
    remote_dir = tmp_path / "recover" / "sase-sudo-keep"
    remote_dir.mkdir(parents=True)
    remote_paths = {
        "directory": str(remote_dir),
        "handshake": str(remote_dir / "handshake.json"),
        "ledger": str(remote_dir / "ledger.json"),
        "log": str(remote_dir / "output.log"),
        "manifest": str(remote_dir / "manifest.json"),
        "stop": str(remote_dir / "stop"),
    }
    Path(remote_paths["log"]).write_text(
        "starting reviewed command\n", encoding="utf-8"
    )
    pid = os.getpid()
    handshake = {
        "schema_version": 1,
        "kind": "sudo_exec_started",
        "manifest_sha256": digest,
        "executor_pid": pid,
        "executor_identity": current_process_identity(pid),
        "ledger_path": remote_paths["ledger"],
        "log_path": remote_paths["log"],
        "started_at": 1_800_000_000.0,
    }
    write_execution_state(
        gate.bundle_path,
        SudoExecutionState(
            gate_id=gate.request_id,
            selected_command_ids=selected,
            manifest_sha256=digest,
            handoff_dir=str(handoff),
            handshake=handshake,
            finalize_proc_id="proc-remote-keep",
            target_kind="remote",
            target_host="apollo",
            startup_state="started",
            remote_handoff=remote_paths,
        ),
    )
    fake = FakeOpenSSHEndpoint(tmp_path)
    fake.unreachable = True
    monkeypatch.setattr("sase.sudo.ssh_detached.subprocess.run", fake)
    monkeypatch.setattr("sase.sudo.ssh_detached.REMOTE_POLL_SECONDS", 0.0)
    monkeypatch.setattr(
        "sase.sudo.detach.runner_timeout_seconds", lambda _manifest: 0.05
    )
    sidecar = tmp_path / "finalize-request.json"
    write_operation_request(
        sidecar,
        DurableOperationRequest(
            operation=SUDO_FINALIZE,
            payload={
                "gate_id": gate.request_id,
                "handoff_dir": str(handoff),
                "handshake": handshake,
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
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: False,
    )
    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pending"
    assert output["code"] == "timeout"
    assert not gate.response_path.exists()
    state = load_execution_state(gate.bundle_path)
    assert state is not None
    assert state.remote_handoff == remote_paths
    assert remote_dir.is_dir()
