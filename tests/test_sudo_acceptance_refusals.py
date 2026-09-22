"""Sudo acceptance coverage for headless refusals and integrity checks."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from sase.feature_flags import override_flags
from sase.notification_gates.command_runner import run_owned_command
from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.sudo import runner as sudo_runner
from sase.sudo.gate import APPROVE_OPTION_ID, build_sudo_gate_request
from tests._sudo_acceptance_helpers import _request, _runner_receipt


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
