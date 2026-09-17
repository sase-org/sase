"""Coverage for feature-flagged sudo notification gates."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.agent.gate_intent import list_gate_intents
from sase.feature_flags import override_flags
from sase.gate_shell.models import GateShellRecord
from sase.main.parser import create_parser
from sase.main.parser_sudo import register_sudo_parser
from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.sudo.cli import handle_sudo_command
from sase.sudo import cli as sudo_cli
from sase.sudo.cli import _shell_payload as sudo_shell_payload
from sase.sudo.gate import APPROVE_OPTION_ID, DENY_OPTION_ID, build_sudo_gate_request
from sase.sudo.lease import _sudo_auth_state_path, sudo_auth_lease
from sase.sudo.manifest import selected_sudo_manifest
from sase.sudo.models import normalize_sudo_request


def _request() -> dict[str, Any]:
    executable = shutil.which("true")
    assert executable is not None
    return {
        "reason": "Need to refresh root-owned package metadata",
        "commands": [
            {
                "id": "refresh",
                "argv": [executable],
                "why": "Refresh package metadata",
            }
        ],
        "run_as": "root",
        "cwd": "/tmp",
        "env": {"LC_ALL": "C"},
        "timeout_seconds": 30,
        "stop_policy": "terminate",
        "output_policy": "bounded",
    }


def _multi_command_request() -> dict[str, Any]:
    executable = shutil.which("true")
    assert executable is not None
    request = _request()
    request["commands"] = [
        {"id": "alpha", "argv": [executable, "--alpha"], "why": "Run alpha"},
        {"id": "beta", "argv": [executable, "--beta"], "why": "Run beta"},
        {"id": "gamma", "argv": [executable, "--gamma"], "why": "Run gamma"},
    ]
    return request


def _runner_ledger(manifest: dict[str, Any], manifest_sha256: str) -> dict[str, Any]:
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


def _auth_failed_ledger(
    manifest: dict[str, Any], manifest_sha256: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": manifest["request_id"],
        "manifest_sha256": manifest_sha256,
        "outcome": "auth_failed",
        "entries": [],
        "diagnostic": "authentication failed",
    }


def _runner_error_ledger(
    manifest: dict[str, Any], manifest_sha256: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": manifest["request_id"],
        "manifest_sha256": manifest_sha256,
        "outcome": "runner_error",
        "entries": [
            {
                "id": command["id"],
                "status": "skipped",
                "exit_code": None,
                "duration_seconds": 0.0,
                "output_tail": "",
            }
            for command in manifest["commands"]
        ],
        "diagnostic": "failed to start sudo command in cwd /missing",
    }


def _runner_receipt(envelope: dict[str, Any]) -> dict[str, Any]:
    sudo_payload = envelope["payload"]["sudo"]
    manifest = sudo_payload["manifest"]
    return _runner_ledger(manifest, sudo_payload["manifest_sha256"])


def test_sudo_gate_creation_is_feature_flagged(gate_home: Path) -> None:
    del gate_home
    spec = build_sudo_gate_request(_request())

    with override_flags(agent_sudo_requests=False):
        with pytest.raises(GateError) as excinfo:
            create_gate(spec)

    assert excinfo.value.code == "feature_disabled"


def test_sudo_gate_contains_tty_approve_and_headless_deny(
    gate_home: Path,
) -> None:
    del gate_home

    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))

    request = read_json_object(gate.request_path)
    options = {option["id"]: option for option in request["options"]}
    assert options[APPROVE_OPTION_ID]["requires_tty"] is True
    assert options[DENY_OPTION_ID]["requires_tty"] is False
    assert request["presentation"]["chip"]["label"] == "sudo"
    assert request["shell"]["pending_status"] == "SUDO"
    assert request["shell"]["settled_status"] == "SUDOED"


def test_sudo_manifest_subset_rehashes_in_reviewed_order() -> None:
    spec = build_sudo_gate_request(_multi_command_request())
    sudo_payload = spec["payload"]["sudo"]
    manifest = sudo_payload["manifest"]

    subset, command_ids, manifest_sha256 = selected_sudo_manifest(
        manifest,
        ("gamma", "alpha"),
    )

    assert command_ids == ("alpha", "gamma")
    assert [command["id"] for command in subset["commands"]] == ["alpha", "gamma"]
    assert manifest_sha256 != sudo_payload["manifest_sha256"]


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
    row = GateShellRecord(
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
    with override_flags(agent_sudo_requests=True):
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
    with override_flags(agent_sudo_requests=True):
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


def test_sudo_request_validation_rejects_shorthand_and_unsafe_forms() -> None:
    executable = _request()["commands"][0]["argv"][0]

    with pytest.raises(GateError) as shorthand:
        normalize_sudo_request({"reason": "missing ids", "commands": [[executable]]})
    assert shorthand.value.code == "invalid_sudo_request"

    nested = _request()
    nested["commands"] = [{"id": "nested", "argv": ["/usr/bin/sudo", "id"]}]
    with pytest.raises(GateError) as nested_error:
        normalize_sudo_request(nested)
    assert nested_error.value.code == "nested_privilege_tool"

    bad_env = _request()
    bad_env["env"] = {"SUDO_ASKPASS": "/tmp/prompt"}
    with pytest.raises(GateError) as env_error:
        normalize_sudo_request(bad_env)
    assert env_error.value.code == "forbidden_env"


def test_sudo_request_writes_intent_before_reading_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    args = argparse.Namespace(origin_agent=None, json=True)

    def _read_stdin_object() -> dict[str, Any]:
        intents = list_gate_intents(tmp_path)
        assert len(intents) == 1
        assert intents[0].kind == "sudo"
        assert intents[0].request_id is None
        assert intents[0].source == "sase sudo request"
        assert intents[0].pid == os.getpid()
        raise GateError("invalid_json", "stdin", "bad stdin")

    monkeypatch.setattr(sudo_cli, "_read_stdin_object", _read_stdin_object)

    with pytest.raises(GateError, match="bad stdin"):
        sudo_cli._request(args)

    assert list_gate_intents(tmp_path) == []


def test_sudo_request_invalid_stdin_clears_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    args = argparse.Namespace(origin_agent=None, json=True)
    monkeypatch.setattr(
        sudo_cli,
        "_read_stdin_object",
        lambda: (_ for _ in ()).throw(GateError("invalid_json", "stdin", "bad stdin")),
    )

    with pytest.raises(GateError, match="bad stdin"):
        sudo_cli._request(args)

    assert list_gate_intents(tmp_path) == []


def test_sudo_manifest_hash_is_part_of_kind_validation(gate_home: Path) -> None:
    del gate_home
    spec = build_sudo_gate_request(_request())
    tampered = copy.deepcopy(spec)
    tampered["payload"]["sudo"]["manifest"]["commands"][0]["why"] = "tampered"

    with override_flags(agent_sudo_requests=True):
        with pytest.raises(GateError) as excinfo:
            create_gate(tampered)

    assert excinfo.value.code == "invalid_sudo_payload"
    assert excinfo.value.target == "payload.sudo.manifest"


def test_sudo_runner_auth_failure_leaves_gate_answerable(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "answer", gate.request_id, "--approve"])
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.sudo.cli.run_sudo_runner",
        lambda manifest, **kwargs: _auth_failed_ledger(
            manifest,
            str(kwargs["manifest_sha256"]),
        ),
    )

    with override_flags(agent_sudo_requests=True):
        with pytest.raises(GateError) as excinfo:
            handle_sudo_command(args)

    assert excinfo.value.code == "authentication_failed"
    assert not gate.response_path.exists()
    assert not (gate.bundle_path / DECISION_RECEIPT_FILENAME).exists()


def test_sudo_answer_runs_reviewed_command_subset(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_multi_command_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        [
            "sudo",
            "answer",
            gate.request_id,
            "--run",
            "--command",
            "gamma",
            "--command",
            "alpha",
            "--json",
        ]
    )
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )
    captured_runner_payload: dict[str, Any] = {}

    def fake_runner(
        manifest: dict[str, Any],
        *,
        manifest_sha256: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured_runner_payload["manifest"] = manifest
        captured_runner_payload["manifest_sha256"] = manifest_sha256
        return _runner_ledger(manifest, manifest_sha256)

    monkeypatch.setattr("sase.sudo.cli.run_sudo_runner", fake_runner)

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["selected_option_ids"] == [APPROVE_OPTION_ID]
    assert output["selected_command_ids"] == ["alpha", "gamma"]
    assert [
        command["id"] for command in captured_runner_payload["manifest"]["commands"]
    ] == [
        "alpha",
        "gamma",
    ]
    response = read_json_object(gate.response_path)
    [approve_result] = response["option_results"]
    assert approve_result["result"]["command_ids"] == ["alpha", "gamma"]
    assert (
        approve_result["result"]["receipt"]["manifest_sha256"]
        == captured_runner_payload["manifest_sha256"]
    )


def test_sudo_answer_preserves_reviewed_cwd_in_runner_manifest(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    cwd = tmp_path / "review cwd"
    cwd.mkdir()
    request = _request()
    request["cwd"] = str(cwd)
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(request))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "answer", gate.request_id, "--run", "--json"])
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.notification_gates.executor.has_controlling_tty",
        lambda: True,
    )
    captured_manifest: dict[str, Any] = {}

    def fake_runner(
        manifest: dict[str, Any],
        *,
        manifest_sha256: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured_manifest.update(manifest)
        return _runner_ledger(manifest, manifest_sha256)

    monkeypatch.setattr("sase.sudo.cli.run_sudo_runner", fake_runner)

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 0

    assert captured_manifest["cwd"] == str(cwd)


def test_sudo_answer_command_option_does_not_clobber_root_command() -> None:
    args = create_parser().parse_args(
        [
            "sudo",
            "answer",
            "sudo-123",
            "--run",
            "--json",
            "--command",
            "refresh",
        ]
    )

    assert args.command == "sudo"
    assert args.sudo_subcommand == "answer"
    assert args.sudo_command == ["refresh"]


def test_sudo_answer_json_auth_failure_reports_pending_gate(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "answer", gate.request_id, "--run", "--json"])
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.sudo.cli.run_sudo_runner",
        lambda manifest, **kwargs: _auth_failed_ledger(
            manifest,
            str(kwargs["manifest_sha256"]),
        ),
    )

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 2

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pending"
    assert output["settled"] is False
    assert output["outcome"] == "authentication_failed"
    assert not gate.response_path.exists()
    assert not (gate.bundle_path / DECISION_RECEIPT_FILENAME).exists()


def test_sudo_runner_error_ledger_leaves_gate_pending(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "answer", gate.request_id, "--run", "--json"])
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: True)
    monkeypatch.setattr(
        "sase.sudo.cli.run_sudo_runner",
        lambda manifest, **kwargs: _runner_error_ledger(
            manifest,
            str(kwargs["manifest_sha256"]),
        ),
    )

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 1

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pending"
    assert output["settled"] is False
    assert output["outcome"] == "runner_error"
    assert output["code"] == "runner_failed"
    assert not gate.response_path.exists()
    assert not (gate.bundle_path / DECISION_RECEIPT_FILENAME).exists()


def test_sudo_answer_json_feature_disabled_reports_pending_gate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "answer", "sudo-123", "--run", "--json"])

    with override_flags(agent_sudo_requests=False):
        assert handle_sudo_command(args) == 1

    output = json.loads(capsys.readouterr().out)
    assert output["request_id"] == "sudo-123"
    assert output["status"] == "pending"
    assert output["outcome"] == "runner_error"
    assert output["code"] == "feature_disabled"
    assert "agent_sudo_requests beta flag" in output["message"]
    assert "sase flag enable agent_sudo_requests" in output["message"]


def test_sudo_answer_json_unknown_ref_reports_not_found(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "answer", "missing-sudo", "--deny", "--json"])

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 1

    output = json.loads(capsys.readouterr().out)
    assert output["request_id"] == "missing-sudo"
    assert output["status"] == "pending"
    assert output["code"] == "not_found"


def test_sudo_answer_json_missing_tty_reports_pending_gate(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "answer", gate.request_id, "--json"])
    monkeypatch.setattr("sase.sudo.cli.has_controlling_tty", lambda: False)

    with override_flags(agent_sudo_requests=True):
        assert handle_sudo_command(args) == 2

    output = json.loads(capsys.readouterr().out)
    assert output["request_id"] == gate.request_id
    assert output["status"] == "pending"
    assert output["outcome"] == "missing_tty"
    assert output["code"] == "tty_required"


def test_sudo_answer_human_feature_disabled_stays_loud(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "answer", "sudo-123", "--run"])

    with override_flags(agent_sudo_requests=False):
        with pytest.raises(GateError) as excinfo:
            handle_sudo_command(args)

    assert excinfo.value.code == "feature_disabled"
    assert capsys.readouterr().out == ""


def test_sudo_list_json_feature_disabled_reports_error_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["sudo", "list", "--json"])

    with override_flags(agent_sudo_requests=False):
        assert handle_sudo_command(args) == 1

    output = json.loads(capsys.readouterr().out)
    assert output["request_id"] == "sudo"
    assert output["status"] == "pending"
    assert output["code"] == "feature_disabled"


def test_sudo_command_resource_requires_runner_receipt(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
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
    with override_flags(agent_sudo_requests=True):
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
