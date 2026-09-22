"""Sudo gate creation, manifest validation, and request-intent coverage."""

from __future__ import annotations

import argparse
import copy
import os
from pathlib import Path
from typing import Any

import pytest

from sase.agent.gate_intent import list_gate_intents
from sase.feature_flags import override_flags
from sase.main.parser import create_parser
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.sudo import cli as sudo_cli
from sase.sudo.gate import APPROVE_OPTION_ID, DENY_OPTION_ID, build_sudo_gate_request
from sase.sudo.manifest import selected_sudo_manifest
from sase.sudo.models import normalize_sudo_request
from tests._sudo_gate_helpers import _multi_command_request, _request


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
    tampered["payload"]["sudo"]["manifest"]["commands"][0]["why"] = "tampered"

    with override_flags(agent_sudo_requests=True):
        with pytest.raises(GateError) as excinfo:
            create_gate(tampered)

    assert excinfo.value.code == "invalid_sudo_payload"
    assert excinfo.value.target == "payload.sudo.manifest"


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
