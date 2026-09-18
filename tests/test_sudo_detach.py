"""Coverage for detached sudo answer and finalize."""

from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path
from typing import Any

import pytest

from sase.feature_flags import override_flags
from sase.main.parser_sudo import register_sudo_parser
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.sudo import cli as sudo_cli
from sase.sudo.cli import handle_sudo_command
from sase.sudo.gate import build_sudo_gate_request
from tests.test_sudo_gate import _request, _runner_ledger


def _handshake_for(manifest_sha256: str) -> dict[str, Any]:
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


def test_sudo_answer_detach_returns_execution_started(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--detach", "--json"]
    )
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
        captured["detach_dir"] = Path(detach_dir)
        captured["manifest_path"] = Path(manifest_path)
        captured["manifest_sha256"] = manifest_sha256
        return _handshake_for(manifest_sha256)

    def fake_submit(request: Any) -> Any:
        captured["request"] = request
        return argparse.Namespace(proc_id="proc-sudo-1")

    monkeypatch.setattr("sase.sudo.detach.run_sudo_runner_detached", fake_detached)
    monkeypatch.setattr("sase.sudo.detach.submit_proc_request", fake_submit)

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 0

    output = json.loads(capsys.readouterr().out)
    request = captured["request"]
    assert output["status"] == "execution_started"
    assert output["proc_id"] == "proc-sudo-1"
    assert output["request_id"] == gate.request_id
    assert not gate.response_path.exists()
    assert captured["manifest_path"].name == "manifest.json"
    assert captured["detach_dir"].is_dir()
    assert request.argv == [
        "sase",
        "sudo",
        "finalize",
        gate.request_id,
        "--json",
    ]
    assert request.shell_kind == "gate"
    assert request.operation == "sudo.finalize"
    assert request.origin == "sudo-answer-detach"
    assert "handoff_dir" in request.operation_payload
    assert request.operation_payload["handshake"]["kind"] == "sudo_exec_started"


def test_sudo_answer_no_detach_stays_synchronous(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
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

    def fake_runner(
        manifest: dict[str, Any],
        *,
        manifest_sha256: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return _runner_ledger(manifest, manifest_sha256)

    monkeypatch.setattr("sase.sudo.cli.run_sudo_runner", fake_runner)
    monkeypatch.setattr(
        "sase.sudo.detach.run_sudo_runner_detached",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("detached")),
    )

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "answered"
    assert gate.response_path.is_file()


def test_sudo_answer_detach_falls_back_for_old_runner(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--detach", "--json"]
    )
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )
    monkeypatch.setattr(
        "sase.sudo.cli.runner_supports_detached_execution", lambda: False
    )
    monkeypatch.setattr(
        "sase.sudo.cli.run_sudo_runner",
        lambda manifest, **kwargs: _runner_ledger(
            manifest, str(kwargs["manifest_sha256"])
        ),
    )

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["status"] == "answered"
    assert "detached_execution" in captured.err
    assert gate.response_path.is_file()


def test_sudo_answer_detach_refuses_remote_target(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
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
    original = sudo_cli._sudo_payload

    def remote_payload(envelope: dict[str, Any]) -> dict[str, Any]:
        payload = original(envelope)
        payload["target"] = {"remote": True, "host": "other-host"}
        return payload

    monkeypatch.setattr("sase.sudo.cli._sudo_payload", remote_payload)

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 2

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pending"
    assert output["code"] == "detach_unsupported"
    assert "without --detach" in output["message"]
    assert not gate.response_path.exists()


def test_sudo_answer_detach_rejects_live_duplicate(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
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
    _patch_handshake(monkeypatch)
    monkeypatch.setattr(
        "sase.sudo.detach.run_sudo_runner_detached",
        lambda *_args, **kwargs: _handshake_for(str(kwargs["manifest_sha256"])),
    )
    monkeypatch.setattr(
        "sase.sudo.detach.submit_proc_request",
        lambda _request: argparse.Namespace(proc_id="proc-live"),
    )
    monkeypatch.setattr("sase.sudo.execution._proc_is_live", lambda _proc_id: True)

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 0
        capsys.readouterr()
        assert handle_sudo_command(args) == 2

    output = json.loads(capsys.readouterr().out)
    assert output["code"] == "execution_in_progress"
    assert "proc-live" in output["message"]
    assert output["status"] == "pending"


def test_sudo_show_and_list_include_executing_state(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    from sase.sudo.execution import SudoExecutionState, write_execution_state

    write_execution_state(
        gate.bundle_path,
        SudoExecutionState(
            gate_id=gate.request_id,
            selected_command_ids=("refresh",),
            manifest_sha256="a" * 64,
            handoff_dir=str(tmp_path / "handoff"),
            handshake={"executor_pid": 9, "executor_identity": "boot:1"},
            finalize_proc_id="proc-show",
        ),
    )
    monkeypatch.setattr("sase.sudo.execution.execution_is_live", lambda _state: True)
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    show_args = parser.parse_args(["sudo", "show", gate.request_id, "--json"])
    list_args = parser.parse_args(["sudo", "list", "--json"])

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(show_args) == 0
        show_payload = json.loads(capsys.readouterr().out)
        assert handle_sudo_command(list_args) == 0
        list_payload = json.loads(capsys.readouterr().out)

    assert show_payload["status"] == "pending"
    assert show_payload["sudo"]["executing"] is True
    assert show_payload["sudo"]["finalize_proc_id"] == "proc-show"
    matching = [
        row for row in list_payload["gates"] if row["gate_id"] == gate.request_id
    ]
    if matching:
        assert matching[0]["executing"] is True
        assert matching[0]["finalize_proc_id"] == "proc-show"
        assert matching[0]["state"] == "pending"


def test_sudo_finalize_json_requires_operation_sidecar(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "finalize", gate.request_id, "--json"])

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 1

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pending"
    assert output["code"] == "invalid_sudo_finalize"


def test_sudo_finalize_wait_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    from sase.sudo.detach import _wait_for_executor_ledger
    from sase.sudo.execution import create_handoff_dir

    handoff = create_handoff_dir("sudo-wait-timeout", {"schema_version": 1})
    monkeypatch.setattr("sase.sudo.detach.executor_is_live", lambda _handshake: True)
    monkeypatch.setattr("sase.sudo.detach.read_handoff_ledger", lambda _path: None)
    monkeypatch.setattr(
        "sase.sudo.detach.copy_output_log",
        lambda *_args, **kwargs: kwargs.get("offset", 0),
    )

    with pytest.raises(GateError) as excinfo:
        _wait_for_executor_ledger(
            handoff,
            handshake={"executor_pid": 9, "executor_identity": "boot:1"},
            timeout_seconds=0.05,
        )

    assert excinfo.value.code == "timeout"


def test_sudo_finalize_sigterm_writes_stop_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    from sase.sudo.detach import _wait_for_executor_ledger
    from sase.sudo.execution import STOP_FILENAME, create_handoff_dir

    handoff = create_handoff_dir("sudo-wait-stop", {"schema_version": 1})
    monkeypatch.setattr("sase.sudo.detach._STOP_GRACE_SECONDS", 0.05)
    monkeypatch.setattr("sase.sudo.detach.executor_is_live", lambda _handshake: True)
    monkeypatch.setattr("sase.sudo.detach.read_handoff_ledger", lambda _path: None)
    polls = {"n": 0}

    def fake_copy(*_args: object, **kwargs: Any) -> int:
        polls["n"] += 1
        if polls["n"] == 1:
            os.kill(os.getpid(), signal.SIGTERM)
        return int(kwargs.get("offset") or 0)

    monkeypatch.setattr("sase.sudo.detach.copy_output_log", fake_copy)

    with pytest.raises(GateError) as excinfo:
        _wait_for_executor_ledger(
            handoff,
            handshake={"executor_pid": 9, "executor_identity": "boot:1"},
            timeout_seconds=2.0,
        )

    assert excinfo.value.code == "killed"
    assert (handoff / STOP_FILENAME).is_file()
