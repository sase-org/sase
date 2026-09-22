"""Sudo answer-CLI and list-CLI gate coverage."""

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
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.sudo.cli import handle_sudo_command
from sase.sudo.gate import APPROVE_OPTION_ID, build_sudo_gate_request
from tests._sudo_gate_helpers import (
    _auth_failed_ledger,
    _multi_command_request,
    _request,
    _runner_error_ledger,
    _runner_ledger,
)


def test_sudo_runner_auth_failure_leaves_gate_answerable(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    with override_flags(agent_sudo_requests=True):
        gate = create_gate(build_sudo_gate_request(_request()))
    parser = argparse.ArgumentParser(prog="sase")
    register_sudo_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--approve", "--no-detach"]
    )
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
            "--no-detach",
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
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--no-detach", "--json"]
    )
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
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--no-detach", "--json"]
    )
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
    args = parser.parse_args(
        ["sudo", "answer", gate.request_id, "--run", "--no-detach", "--json"]
    )
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
    args = parser.parse_args(
        ["sudo", "answer", "sudo-123", "--run", "--no-detach", "--json"]
    )

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
    args = parser.parse_args(["sudo", "answer", "sudo-123", "--run", "--no-detach"])

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
