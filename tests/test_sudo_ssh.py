"""Coverage for SSH sudo handoff helpers."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from sase.notification_gates.models import GateError
from sase.sudo.ssh import run_remote_sudo


def test_run_remote_sudo_stages_executes_fetches_and_cleans() -> None:
    manifest = {
        "schema_version": 1,
        "request_id": "sudo-1",
        "cwd": "/tmp/remote cwd",
    }
    ledger = {
        "schema_version": 1,
        "request_id": "sudo-1",
        "manifest_sha256": "abc",
        "outcome": "completed",
        "entries": [],
        "diagnostic": None,
    }
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def runner(
        argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str | bytes]:
        calls.append((list(argv), dict(kwargs)))
        if argv == ["ssh", "target", "sase", "sudo", "exec", "--contract"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"schema_version": 1})
            )
        if argv[:3] == ["ssh", "target", "sh"] and "input" in kwargs:
            assert (
                kwargs["input"]
                == json.dumps(manifest, sort_keys=True).encode("utf-8") + b"\n"
            )
            assert json.loads(kwargs["input"].decode("utf-8"))["cwd"] == (
                "/tmp/remote cwd"
            )
            return subprocess.CompletedProcess(argv, 0)
        if argv[:3] == ["ssh", "-t", "target"]:
            assert argv[3:6] == ["sase", "sudo", "exec"]
            assert "--expected-sha256" in argv
            assert "abc" in argv
            return subprocess.CompletedProcess(argv, 0)
        if argv[:3] == ["ssh", "target", "cat"]:
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(ledger))
        if argv[:3] == ["ssh", "target", "sh"]:
            return subprocess.CompletedProcess(argv, 0)
        raise AssertionError(f"unexpected ssh call: {argv}")

    assert (
        run_remote_sudo(
            "target",
            manifest,
            manifest_sha256="abc",
            command_runner=runner,
        )
        == ledger
    )

    assert calls[-1][0][:4] == ["ssh", "target", "sh", "-c"]
    assert calls[-1][0][4].startswith("rm -f /tmp/sase-sudo-")


def test_run_remote_sudo_rejects_contract_mismatch() -> None:
    def runner(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert argv == ["ssh", "target", "sase", "sudo", "exec", "--contract"]
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({}))

    with pytest.raises(GateError) as excinfo:
        run_remote_sudo(
            "target",
            {"schema_version": 1},
            manifest_sha256="abc",
            command_runner=runner,
        )

    assert excinfo.value.code == "remote_sudo_contract_mismatch"


def test_run_remote_sudo_timeout_leaves_gate_pending_and_cleans() -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(list(argv))
        if argv == ["ssh", "target", "sase", "sudo", "exec", "--contract"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"schema_version": 1})
            )
        if argv[:3] == ["ssh", "target", "sh"]:
            return subprocess.CompletedProcess(argv, 0)
        if argv[:3] == ["ssh", "-t", "target"]:
            raise subprocess.TimeoutExpired(argv, timeout=1.0)
        raise AssertionError(f"unexpected ssh call: {argv}")

    with pytest.raises(GateError) as excinfo:
        run_remote_sudo(
            "target",
            {"schema_version": 1},
            manifest_sha256="abc",
            command_runner=runner,
            timeout_seconds=1.0,
        )

    assert excinfo.value.code == "timeout"
    assert calls[-1][:4] == ["ssh", "target", "sh", "-c"]
    assert calls[-1][4].startswith("rm -f /tmp/sase-sudo-")
