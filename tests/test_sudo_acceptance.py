"""Acceptance-style coverage for sudo request credential boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

from sase.feature_flags import override_flags
from sase.main.parser_sudo import register_sudo_parser
from sase.notification_gates.command_runner import run_owned_command
from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
from sase.notification_gates.durability import canonical_json_bytes, read_json_object
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.sudo import runner as sudo_runner
from sase.sudo.cli import handle_sudo_command
from sase.sudo.gate import APPROVE_OPTION_ID, build_sudo_gate_request

_CANARY_PREFIX = "SASE_CANARY_CREDENTIAL_VALUE_"
_CANARY = _CANARY_PREFIX + ("x" * (8119 - len(_CANARY_PREFIX)))


def _request() -> dict[str, Any]:
    executable = shutil.which("true")
    assert executable is not None
    return {
        "reason": "Need to refresh a reviewed root-owned cache",
        "commands": [
            {
                "id": "refresh",
                "argv": [executable, "--refresh"],
                "why": "Refresh the reviewed root-owned cache",
            }
        ],
        "run_as": "root",
        "cwd": "/tmp",
        "env": {"LC_ALL": "C"},
        "timeout_seconds": 30,
        "output_to_agent": "tail",
    }


def _runner_ledger(manifest: Mapping[str, Any], manifest_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": manifest["request_id"],
        "manifest_sha256": manifest_sha256,
        "outcome": "completed",
        "entries": [
            {
                "id": command["id"],
                "status": "ran",
                "exit_code": 0,
                "duration_seconds": 0.0,
                "output_tail": "",
            }
            for command in manifest["commands"]
        ],
        "diagnostic": None,
    }


def _runner_receipt(envelope: Mapping[str, Any]) -> dict[str, Any]:
    sudo_payload = envelope["payload"]["sudo"]
    manifest = sudo_payload["manifest"]
    return _runner_ledger(manifest, sudo_payload["manifest_sha256"])


def _sensitive_tokens(canary: str) -> dict[str, bytes]:
    return {
        "credential value": canary.encode("utf-8"),
        "credential sha256": hashlib.sha256(canary.encode("utf-8"))
        .hexdigest()
        .encode("ascii"),
        "credential length": str(len(canary)).encode("ascii"),
    }


def _assert_sensitive_tokens_absent(
    paths: Iterable[Path],
    *,
    canary: str,
) -> None:
    tokens = _sensitive_tokens(canary)
    for path in _iter_files(paths):
        raw = path.read_bytes()
        for label, token in tokens.items():
            assert token not in raw, f"{label} leaked into {path}"


def _iter_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (child for child in path.rglob("*") if child.is_file())


def test_sudo_local_flow_never_persists_canary_credentials(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    credential_tty = tmp_path / "review-terminal-input.txt"
    credential_tty.write_text(_CANARY, encoding="utf-8")
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    with override_flags(agent_sudo_requests=True):
        gate = create_gate(
            build_sudo_gate_request(_request(), request_id="sudo-canary-flow")
        )

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
        manifest: Mapping[str, Any],
        *,
        manifest_sha256: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        assert credential_tty.read_text(encoding="utf-8") == _CANARY
        manifest_bytes = canonical_json_bytes(dict(manifest))
        for token in _sensitive_tokens(_CANARY).values():
            assert token not in manifest_bytes
        return _runner_ledger(manifest, manifest_sha256)

    monkeypatch.setattr("sase.sudo.cli.run_sudo_runner", fake_runner)

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "answered"
    assert output["outcome"] == "completed"
    assert gate.response_path.is_file()
    assert (gate.bundle_path / DECISION_RECEIPT_FILENAME).is_file()
    _assert_sensitive_tokens_absent(
        (
            gate_home / "requests",
            gate_home / "notifications",
            gate_home / "pending.json",
            gate_home / "legacy.json",
            sase_home,
        ),
        canary=_CANARY,
    )


def test_sudo_runner_invocation_keeps_canary_out_of_process_argv_and_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not Path("/proc").is_dir():
        pytest.skip("/proc is required for argv and environment inspection")
    credential_tty = tmp_path / "review-terminal-input.txt"
    credential_tty.write_text(_CANARY, encoding="utf-8")
    fake_bin = tmp_path / "venv" / "bin"
    fake_bin.mkdir(parents=True)
    fake_runner = fake_bin / "sase_sudo_runner"
    fake_runner.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "import sys",
                "import time",
                "with open(os.environ['SASE_FAKE_TTY_PATH'], encoding='utf-8') as handle:",
                "    handle.read()",
                "time.sleep(0.25)",
                "sha = sys.argv[sys.argv.index('--expected-sha256') + 1]",
                "print(json.dumps({'ok': True, 'manifest_sha256': sha}))",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_runner.chmod(0o755)
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"schema_version": 1}\n', encoding="utf-8")
    captured: dict[str, bytes] = {}
    real_popen = subprocess.Popen

    def inspected_run(
        argv: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        process = real_popen(
            argv,
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            text=kwargs.get("text", False),
        )
        try:
            captured["cmdline"] = Path(f"/proc/{process.pid}/cmdline").read_bytes()
            captured["environ"] = Path(f"/proc/{process.pid}/environ").read_bytes()
            stdout, stderr = process.communicate(timeout=kwargs.get("timeout"))
        except BaseException:
            process.kill()
            raise
        return subprocess.CompletedProcess(
            argv,
            process.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(sudo_runner.sys, "executable", str(fake_bin / "python"))
    monkeypatch.setenv("SASE_FAKE_TTY_PATH", str(credential_tty))
    monkeypatch.setattr(sudo_runner.subprocess, "run", inspected_run)

    assert sudo_runner.run_sudo_runner_file(
        manifest,
        manifest_sha256="abc123",
    ) == {"ok": True, "manifest_sha256": "abc123"}
    _assert_sensitive_tokens_absent_bytes(captured.values(), canary=_CANARY)


def _assert_sensitive_tokens_absent_bytes(
    values: Iterable[bytes],
    *,
    canary: str,
) -> None:
    tokens = _sensitive_tokens(canary)
    for raw in values:
        for label, token in tokens.items():
            assert token not in raw, f"{label} leaked into process metadata"


@pytest.mark.parametrize(
    "source",
    (
        "durable_answer_proc",
        "mobile",
        "fleet_bridge",
        "detached_proc",
    ),
)
def test_sudo_headless_entrypoints_refuse_without_accepting_decision(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    receipt = _runner_receipt(read_json_object(gate.request_path))
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: False,
    )

    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(
            gate.bundle_path,
            [APPROVE_OPTION_ID],
            source=source,
            option_inputs={
                APPROVE_OPTION_ID: {
                    "command_ids": ["refresh"],
                    "receipt": receipt,
                }
            },
        )

    assert excinfo.value.code == "tty_required"
    assert not gate.response_path.exists()
    assert not (gate.bundle_path / DECISION_RECEIPT_FILENAME).exists()


def test_forged_sudo_headless_authorization_refuses_without_attempt_state(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    receipt = _runner_receipt(read_json_object(gate.request_path))
    sudo_payload = read_json_object(gate.request_path)["payload"]["sudo"]
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: False,
    )

    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(
            gate.bundle_path,
            [APPROVE_OPTION_ID],
            source="sudo_finalize",
            option_inputs={
                APPROVE_OPTION_ID: {
                    "command_ids": ["refresh"],
                    "receipt": receipt,
                }
            },
            sudo_headless_authorization={
                "authorized": True,
                "authorization_id": "f" * 64,
                "gate_id": gate.request_id,
                "manifest_sha256": sudo_payload["manifest_sha256"],
                "selected_command_ids": ["refresh"],
            },
        )

    assert excinfo.value.code == "tty_required"
    assert not gate.response_path.exists()
    assert not (gate.bundle_path / DECISION_RECEIPT_FILENAME).exists()


def test_sudo_runner_manifest_refusal_stays_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bin = tmp_path / "venv" / "bin"
    fake_bin.mkdir(parents=True)
    fake_runner = fake_bin / "sase_sudo_runner"
    fake_runner.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_runner.chmod(0o755)
    monkeypatch.setattr(sudo_runner.sys, "executable", str(fake_bin / "python"))
    monkeypatch.setattr(
        sudo_runner.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 13, stdout=""),
    )

    with pytest.raises(GateError) as excinfo:
        sudo_runner.run_sudo_runner_file(
            tmp_path / "tampered-manifest.json",
            manifest_sha256="reviewed-sha",
        )

    assert excinfo.value.code == "invalid_runner_input"


def test_sudo_command_file_swap_refuses_hash_mismatch(gate_home: Path) -> None:
    bundle = gate_home / "requests" / "sudo" / "sudo-command-swap"
    command = bundle / "commands" / "approve"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\nprintf '{\"ok\":true}\\n'\n", encoding="utf-8")
    command.chmod(0o755)
    expected_hash = hashlib.sha256(command.read_bytes()).hexdigest()
    command.write_text("#!/bin/sh\nprintf '{\"ok\":false}\\n'\n", encoding="utf-8")
    command.chmod(0o755)

    with pytest.raises(GateError) as excinfo:
        run_owned_command(
            bundle,
            ("commands/approve",),
            expected_hash=expected_hash,
            input_data={},
        )

    assert excinfo.value.code == "hash_mismatch"


_FAKE_CAPABLE_RUNNER = """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

if "--capabilities" in sys.argv:
    print(json.dumps({"schema_version": 1, "capabilities": ["detached_execution"]}))
    raise SystemExit(0)

detach_dir = Path(sys.argv[sys.argv.index("--detach-dir") + 1])
manifest_path = Path(sys.argv[sys.argv.index("--manifest") + 1])
sha = sys.argv[sys.argv.index("--expected-sha256") + 1]
log_path = detach_dir / "output.log"
ledger_path = detach_dir / "ledger.json"
sleep_for = float(os.environ.get("SASE_FAKE_EXEC_SLEEP", "0.15"))
pid = os.fork()
if pid == 0:
    time.sleep(0.02)
    log_path.write_text("starting reviewed command\\n", encoding="utf-8")
    deadline = time.time() + sleep_for
    while time.time() < deadline:
        if (detach_dir / "stop").exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            ledger_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "request_id": manifest["request_id"],
                        "manifest_sha256": sha,
                        "outcome": "cancelled",
                        "entries": [],
                        "diagnostic": "stopped",
                    }
                )
                + "\\n",
                encoding="utf-8",
            )
            os._exit(0)
        time.sleep(0.02)
    log_path.write_text("starting reviewed command\\ndone\\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ledger_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "request_id": manifest["request_id"],
                "manifest_sha256": sha,
                "outcome": "completed",
                "entries": [
                    {
                        "id": command["id"],
                        "status": "ran",
                        "exit_code": 0,
                        "duration_seconds": 0.0,
                        "output_tail": "done\\n",
                    }
                    for command in manifest["commands"]
                ],
                "diagnostic": None,
            }
        )
        + "\\n",
        encoding="utf-8",
    )
    os._exit(0)
print(
    json.dumps(
        {
            "schema_version": 1,
            "kind": "sudo_exec_started",
            "manifest_sha256": sha,
            "executor_pid": pid,
            "executor_identity": f"pid-{pid}",
            "ledger_path": str(ledger_path),
            "log_path": str(log_path),
            "started_at": time.time(),
        }
    )
)
"""


def _install_capable_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_bin = tmp_path / "venv" / "bin"
    fake_bin.mkdir(parents=True)
    runner = fake_bin / "sase_sudo_runner"
    runner.write_text(_FAKE_CAPABLE_RUNNER, encoding="utf-8")
    runner.chmod(0o755)
    monkeypatch.setattr(sudo_runner, "_resolve_runner_executable", lambda: str(runner))
    return runner


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
    monkeypatch.setattr("sase.sudo.ssh.subprocess.run", fake)
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
    monkeypatch.setattr("sase.sudo.ssh.subprocess.run", fake)
    monkeypatch.setattr("sase.sudo.ssh._REMOTE_POLL_SECONDS", 0.0)
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
