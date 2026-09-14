"""Coverage for feature-flagged sudo notification gates."""

from __future__ import annotations

import argparse
import copy
import shutil
from pathlib import Path
from typing import Any

import pytest

from sase.feature_flags import override_flags
from sase.main.parser_sudo import register_sudo_parser
from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.sudo.cli import handle_sudo_command
from sase.sudo.gate import APPROVE_OPTION_ID, DENY_OPTION_ID, build_sudo_gate_request
from sase.sudo.models import normalize_sudo_request


def _request() -> dict[str, Any]:
    executable = shutil.which("true")
    assert executable is not None
    return {
        "reason": "Need to refresh root-owned package metadata",
        "commands": [{"id": "refresh", "argv": [executable]}],
        "run_as": "root",
        "cwd": "/tmp",
        "env": {"LC_ALL": "C"},
        "timeout_seconds": 30,
        "stop_policy": "terminate",
        "output_policy": "bounded",
    }


def _runner_receipt(envelope: dict[str, Any]) -> dict[str, Any]:
    sudo_payload = envelope["payload"]["sudo"]
    manifest = sudo_payload["manifest"]
    return {
        "manifest_sha256": sudo_payload["manifest_sha256"],
        "ledger": [
            {"id": command["id"], "status": "ran"} for command in manifest["commands"]
        ],
    }


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
            option_inputs={APPROVE_OPTION_ID: {"receipt": receipt}},
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
            option_inputs={APPROVE_OPTION_ID: {"receipt": receipt}},
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


def test_sudo_manifest_hash_is_part_of_kind_validation(gate_home: Path) -> None:
    del gate_home
    spec = build_sudo_gate_request(_request())
    tampered = copy.deepcopy(spec)
    tampered["payload"]["sudo"]["manifest"]["timeout_seconds"] = 999

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
        lambda _payload: {"status": "authentication_failed"},
    )

    with override_flags(agent_sudo_requests=True):
        with pytest.raises(GateError) as excinfo:
            handle_sudo_command(args)

    assert excinfo.value.code == "authentication_failed"
    assert not gate.response_path.exists()
    assert not (gate.bundle_path / DECISION_RECEIPT_FILENAME).exists()


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
            option_inputs={APPROVE_OPTION_ID: {"receipt": {}}},
        )

    assert excinfo.value.code == "receipt_hash_mismatch"
    assert not gate.response_path.exists()
    assert not (gate.bundle_path / DECISION_RECEIPT_FILENAME).exists()
