"""Sudo gate approval guards, auth lease, and shell-payload coverage."""

from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.gate_turn.models import GateTurnRecord
from sase.main.parser_sudo import register_sudo_parser
from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.sudo import cli as sudo_cli
from sase.sudo.cli import _shell_payload as sudo_shell_payload
from sase.sudo.cli import handle_sudo_command
from sase.sudo.commands import sudo_approve_entrypoint
from sase.sudo.gate import APPROVE_OPTION_ID, DENY_OPTION_ID, build_sudo_gate_request
from sase.sudo.lease import _sudo_auth_state_path, sudo_auth_lease
from sase.sudo.snapshot import ExecutableSnapshot, tcc_failure_hint
from sase.sudo.ssh_snapshot import _RemoteExecutableSnapshot
from tests._sudo_gate_helpers import _request, _runner_ledger, _runner_receipt

_REMOTE_HASH = "ab" * 32
_SCUTIL = "/usr/sbin/scutil"


def test_sudo_auth_lease_writes_and_releases_non_secret_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))

    with sudo_auth_lease(
        request_id="sudo-one",
        run_as="root",
        cwd="/tmp",
        command_ids=("alpha", "beta"),
    ):
        state = read_json_object(_sudo_auth_state_path())
        assert state["request_id"] == "sudo-one"
        assert state["run_as"] == "root"
        assert state["cwd"] == "/tmp"
        assert state["command_count"] == 2
        assert "command_ids" not in state

    assert not _sudo_auth_state_path().exists()


def test_sudo_auth_lease_rejects_concurrent_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))

    with sudo_auth_lease(
        request_id="sudo-one",
        run_as="root",
        cwd="/tmp",
        command_ids=("alpha",),
    ):
        with pytest.raises(GateError) as excinfo:
            with sudo_auth_lease(
                request_id="sudo-two",
                run_as="root",
                cwd="/tmp",
                command_ids=("beta",),
            ):
                pass

    assert excinfo.value.code == "auth_lease_busy"
    assert "sudo-one" in str(excinfo.value)


def test_sudo_shell_payload_uses_typed_status_label() -> None:
    row = GateTurnRecord(
        gate_id="sudo-1",
        member_agent_name="agent--gate",
        lane="agent",
        project_name="sase",
        artifacts_dir="/tmp/agent",
        timestamp="2026-09-14T00:00:00+00:00",
        kind="sudo",
        gate_state="pending",
        start_status="SUDO",
        stop_status="SUDOED",
        accent="#FFAF5F",
        label="sudo",
        reason="refresh metadata",
        creator_agent=None,
        bundle_path=None,
        notification_id=None,
        timeout_seconds=30.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )

    assert sudo_shell_payload(row)["status"] == "SUDO"
    assert sudo_shell_payload(replace(row, gate_state="answered"))["status"] == "SUDOED"


def test_sudo_approval_requires_controlling_tty_before_accepting_decision(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
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
            source="sudo_cli",
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


def test_sudo_approval_must_use_sudo_cli_even_with_tty(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    gate = create_gate(build_sudo_gate_request(_request()))
    receipt = _runner_receipt(read_json_object(gate.request_path))
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )

    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(
            gate.bundle_path,
            [APPROVE_OPTION_ID],
            source="mobile",
            option_inputs={
                APPROVE_OPTION_ID: {
                    "command_ids": ["refresh"],
                    "receipt": receipt,
                }
            },
        )

    assert excinfo.value.code == "unsupported_sudo_approval"
    assert not gate.response_path.exists()
    assert not (gate.bundle_path / DECISION_RECEIPT_FILENAME).exists()


def test_sudo_deny_is_headless_safe(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    gate = create_gate(build_sudo_gate_request(_request()))
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: False,
    )

    execution = execute_gate_selection(
        gate.bundle_path,
        [DENY_OPTION_ID],
        source="mobile",
        feedback="not needed",
    )

    assert execution.response["selected_option_ids"] == [DENY_OPTION_ID]
    assert gate.response_path.is_file()


def test_sudo_command_resource_requires_runner_receipt(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    gate = create_gate(build_sudo_gate_request(_request()))
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )

    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(
            gate.bundle_path,
            [APPROVE_OPTION_ID],
            source="sudo_cli",
            option_inputs={
                APPROVE_OPTION_ID: {"command_ids": ["refresh"], "receipt": {}}
            },
        )

    assert excinfo.value.code == "invalid_sudo_ledger"
    assert not gate.response_path.exists()
    assert not (gate.bundle_path / DECISION_RECEIPT_FILENAME).exists()


def test_sudo_approval_requires_command_ids_before_accepting_decision(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    gate = create_gate(build_sudo_gate_request(_request()))
    receipt = _runner_receipt(read_json_object(gate.request_path))
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )

    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(
            gate.bundle_path,
            [APPROVE_OPTION_ID],
            source="sudo_cli",
            option_inputs={APPROVE_OPTION_ID: {"receipt": receipt}},
        )

    assert excinfo.value.code == "invalid_sudo_selection"
    assert not gate.response_path.exists()
    assert not (gate.bundle_path / DECISION_RECEIPT_FILENAME).exists()


def _remote_snapshot(
    path: str = _SCUTIL,
    *,
    sha256: str = _REMOTE_HASH,
    platform: str = "darwin",
    full_disk_access: bool | None = False,
) -> _RemoteExecutableSnapshot:
    return _RemoteExecutableSnapshot(
        host_facts={"full_disk_access": full_disk_access, "platform": platform},
        executables=(ExecutableSnapshot(path=path, sha256=sha256),),
    )


def _remote_request() -> dict[str, Any]:
    request = _request()
    request["machine"] = "mac"
    request["commands"][0]["id"] = "refresh"
    request["commands"][0]["argv"] = [_SCUTIL]
    return request


def _build_remote_gate(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: _RemoteExecutableSnapshot | None = None,
) -> Any:
    monkeypatch.setattr(
        "sase.sudo.gate.snapshot_remote_executables",
        lambda *_args, **_kwargs: snapshot or _remote_snapshot(),
    )
    return create_gate(build_sudo_gate_request(_remote_request()))


def test_remote_approval_snapshot_mismatch_leaves_gate_pending(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    gate = _build_remote_gate(monkeypatch)
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--no-detach"]
    )
    exec_calls: list[str] = []
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )
    monkeypatch.setattr(
        "sase.sudo.cli.run_remote_sudo",
        lambda *_args, **_kwargs: exec_calls.append("exec") or {},
    )
    monkeypatch.setattr(
        "sase.sudo.cli.reverify_remote_command_snapshots",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            GateError(
                "snapshot_mismatch",
                "commands[refresh].executable_sha256",
                "sudo command executable no longer matches the reviewed snapshot",
            )
        ),
    )

    with pytest.raises(GateError) as excinfo:
        handle_sudo_command(args)

    assert excinfo.value.code == "snapshot_mismatch"
    assert exec_calls == []
    assert not gate.response_path.exists()


def test_legacy_remote_payload_skips_snapshot_reverify(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    gate = create_gate(build_sudo_gate_request(_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--no-detach", "--json"]
    )
    original = sudo_cli._sudo_payload

    def remote_payload(envelope: dict[str, Any]) -> dict[str, Any]:
        payload = original(envelope)
        payload["target"] = {"remote": True, "host": "other-host"}
        return payload

    from sase.sudo.ssh_snapshot import (
        reverify_remote_command_snapshots as real_reverify,
    )

    results: list[object] = []

    def tracking(
        payload: dict[str, Any], ids: tuple[str, ...], **kwargs: Any
    ) -> object:
        result = real_reverify(payload, ids, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )
    monkeypatch.setattr("sase.sudo.cli._sudo_payload", remote_payload)
    monkeypatch.setattr("sase.sudo.cli.reverify_remote_command_snapshots", tracking)
    monkeypatch.setattr(
        "sase.sudo.cli.run_remote_sudo",
        lambda _host, manifest, **kwargs: _runner_ledger(
            manifest, str(kwargs["manifest_sha256"])
        ),
    )

    assert handle_sudo_command(args) == 0
    assert results == [None]
    assert gate.response_path.exists()


def test_darwin_approval_prints_fda_warning_and_proceeds(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    gate = _build_remote_gate(monkeypatch)
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
        "sase.sudo.cli.reverify_remote_command_snapshots",
        lambda *_args, **_kwargs: {
            "full_disk_access": False,
            "platform": "darwin",
        },
    )
    monkeypatch.setattr(
        "sase.sudo.cli.run_remote_sudo",
        lambda _host, manifest, **kwargs: _runner_ledger(
            manifest, str(kwargs["manifest_sha256"])
        ),
    )

    assert handle_sudo_command(args) == 0

    captured = capsys.readouterr()
    assert "Full Disk Access" in captured.err
    assert json.loads(captured.out)["status"] == "answered"
    assert gate.response_path.exists()


def test_tcc_failure_hint_for_darwin_eperm_ledger() -> None:
    target = {
        "host": "mac",
        "remote": True,
        "snapshot": {
            "taken_on": "target",
            "host_facts": {"platform": "darwin", "full_disk_access": False},
        },
    }
    ledger = [
        {
            "id": "backup",
            "status": "failed",
            "output_tail": "cp: /etc/postfix/main.cf.bak: Operation not permitted",
        }
    ]
    hint = tcc_failure_hint(target, ledger)
    assert hint is not None
    assert "backup" in hint
    assert "is macOS TCC" in hint
    assert "likely" not in hint
    assert "not SIP" in hint

    target["snapshot"]["host_facts"]["full_disk_access"] = None
    likely = tcc_failure_hint(target, ledger)
    assert likely is not None
    assert "is likely macOS TCC" in likely

    linux = dict(target)
    linux["snapshot"] = {
        "taken_on": "target",
        "host_facts": {"platform": "linux", "full_disk_access": None},
    }
    assert tcc_failure_hint(linux, ledger) is None
    assert (
        tcc_failure_hint(target, [{"id": "ok", "status": "ran", "output_tail": ""}])
        is None
    )
    empty_tail = {
        "id": "backup",
        "status": "failed",
        "output_tail": "",
    }
    assert tcc_failure_hint(target, [empty_tail]) is None


def test_sudo_approve_entrypoint_adds_tcc_hints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = {
        "payload": {
            "sudo": {
                "manifest": {
                    "commands": [
                        {
                            "id": "backup",
                            "argv": ["/bin/cp"],
                            "why": "x",
                            "shell": False,
                        }
                    ]
                },
                "target": {
                    "host": "mac",
                    "remote": True,
                    "snapshot": {
                        "taken_on": "target",
                        "host_facts": {
                            "platform": "darwin",
                            "full_disk_access": False,
                        },
                    },
                },
            }
        }
    }
    (tmp_path / "request.json").write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.sudo.commands.selected_sudo_manifest",
        lambda *_args, **_kwargs: ({}, ("backup",), "abc"),
    )
    monkeypatch.setattr(
        "sase.sudo.commands.validate_sudo_receipt",
        lambda *_args, **_kwargs: {
            "entries": [
                {
                    "id": "backup",
                    "status": "failed",
                    "output_tail": "Operation not permitted",
                }
            ]
        },
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"command_ids": ["backup"], "receipt": {}})),
    )

    with pytest.raises(SystemExit) as excinfo:
        sudo_approve_entrypoint()

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hints"]
    assert "macOS TCC" in payload["hints"][0]


def test_sudo_approve_entrypoint_omits_hints_for_linux(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = {
        "payload": {
            "sudo": {
                "manifest": {
                    "commands": [
                        {
                            "id": "backup",
                            "argv": ["/bin/cp"],
                            "why": "x",
                            "shell": False,
                        }
                    ]
                },
                "target": {
                    "host": "apollo",
                    "remote": True,
                    "snapshot": {
                        "taken_on": "target",
                        "host_facts": {
                            "platform": "linux",
                            "full_disk_access": None,
                        },
                    },
                },
            }
        }
    }
    (tmp_path / "request.json").write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.sudo.commands.selected_sudo_manifest",
        lambda *_args, **_kwargs: ({}, ("backup",), "abc"),
    )
    monkeypatch.setattr(
        "sase.sudo.commands.validate_sudo_receipt",
        lambda *_args, **_kwargs: {
            "entries": [
                {
                    "id": "backup",
                    "status": "failed",
                    "output_tail": "Operation not permitted",
                }
            ]
        },
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"command_ids": ["backup"], "receipt": {}})),
    )

    with pytest.raises(SystemExit) as excinfo:
        sudo_approve_entrypoint()

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "hints" not in payload
