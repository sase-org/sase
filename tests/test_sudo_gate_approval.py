"""Sudo gate approval guards, auth lease, and shell-payload coverage."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.feature_flags import override_flags
from sase.gate_shell.models import GateShellRecord
from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.sudo.cli import _shell_payload as sudo_shell_payload
from sase.sudo.gate import APPROVE_OPTION_ID, DENY_OPTION_ID, build_sudo_gate_request
from sase.sudo.lease import _sudo_auth_state_path, sudo_auth_lease
from tests._sudo_gate_helpers import _request, _runner_receipt


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
