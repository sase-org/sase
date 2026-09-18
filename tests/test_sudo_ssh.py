"""Coverage for SSH sudo handoff helpers."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from typing import Any

import pytest

from sase.notification_gates.models import GateError
from sase.sudo.ssh import (
    remote_supports_detached_execution,
    run_remote_sudo,
    run_remote_sudo_detached,
    wait_for_remote_sudo_ledger,
)


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
                argv, 0, stdout=json.dumps({"schema_version": 1, "capabilities": []})
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
    assert calls[-1][0][4].startswith("rm -rf /tmp/sase-sudo-")


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
                argv, 0, stdout=json.dumps({"schema_version": 1, "capabilities": []})
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
    assert calls[-1][4].startswith("rm -rf /tmp/sase-sudo-")


def test_remote_supports_detached_execution_reads_capability() -> None:
    def runner(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert argv == ["ssh", "target", "sase", "sudo", "exec", "--contract"]
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {"schema_version": 1, "capabilities": ["detached_execution"]}
            ),
        )

    assert remote_supports_detached_execution("target", command_runner=runner) is True


def test_run_remote_sudo_detached_fetches_handshake_and_leaves_files() -> None:
    manifest = {"schema_version": 1, "request_id": "sudo-1"}
    handshake = {
        "schema_version": 1,
        "kind": "sudo_exec_started",
        "manifest_sha256": "abc",
        "executor_pid": 123,
        "executor_identity": "boot:1",
        "ledger_path": "/tmp/sase-sudo-x/ledger.json",
        "log_path": "/tmp/sase-sudo-x/output.log",
        "started_at": 1.0,
    }
    calls: list[list[str]] = []

    def runner(
        argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str | bytes]:
        calls.append(list(argv))
        if argv == ["ssh", "target", "sase", "sudo", "exec", "--contract"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {"schema_version": 1, "capabilities": ["detached_execution"]}
                ),
            )
        if argv[:3] == ["ssh", "target", "sh"] and "input" in kwargs:
            return subprocess.CompletedProcess(argv, 0)
        if argv[:3] == ["ssh", "-t", "target"]:
            assert "--detach" in argv
            assert "--handshake" in argv
            return subprocess.CompletedProcess(argv, 0)
        if argv[:3] == ["ssh", "target", "cat"] and argv[3].endswith("/handshake.json"):
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(handshake))
        raise AssertionError(f"unexpected ssh call: {argv}")

    payload, paths = run_remote_sudo_detached(
        "target",
        manifest,
        manifest_sha256="abc",
        command_runner=runner,
    )

    assert payload == handshake
    assert paths["handshake"].endswith("/handshake.json")
    assert not any(
        call[:4] == ["ssh", "target", "sh", "-c"] and "rm -rf" in call[4]
        for call in calls
    )


def test_run_remote_sudo_detached_auth_failure_fetches_ledger_and_cleans() -> None:
    ledger = {
        "schema_version": 1,
        "request_id": "sudo-1",
        "manifest_sha256": "abc",
        "outcome": "auth_failed",
        "entries": [],
        "diagnostic": "no",
    }
    calls: list[list[str]] = []

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        del kwargs
        calls.append(list(argv))
        if argv == ["ssh", "target", "sase", "sudo", "exec", "--contract"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {"schema_version": 1, "capabilities": ["detached_execution"]}
                ),
            )
        if argv[:3] == ["ssh", "target", "sh"] and "rm -rf" not in argv[-1]:
            return subprocess.CompletedProcess(argv, 0)
        if argv[:3] == ["ssh", "-t", "target"]:
            return subprocess.CompletedProcess(argv, 10)
        if argv[:3] == ["ssh", "target", "cat"] and argv[3].endswith("/handshake.json"):
            return subprocess.CompletedProcess(argv, 1, stdout="")
        if argv[:3] == ["ssh", "target", "cat"] and argv[3].endswith("/ledger.json"):
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(ledger))
        if argv[:3] == ["ssh", "target", "sh"] and "rm -rf" in argv[-1]:
            return subprocess.CompletedProcess(argv, 0)
        raise AssertionError(f"unexpected ssh call: {argv}")

    payload, _paths = run_remote_sudo_detached(
        "target",
        {"schema_version": 1},
        manifest_sha256="abc",
        command_runner=runner,
    )

    assert payload == ledger
    assert calls[-1][:4] == ["ssh", "target", "sh", "-c"]
    assert "rm -rf /tmp/sase-sudo-" in calls[-1][4]


def test_wait_for_remote_sudo_ledger_polls_until_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.sudo.ssh._REMOTE_POLL_SECONDS", 0.0)
    paths = {
        "directory": "/tmp/sase-sudo-test",
        "handshake": "/tmp/sase-sudo-test/handshake.json",
        "ledger": "/tmp/sase-sudo-test/ledger.json",
        "log": "/tmp/sase-sudo-test/output.log",
        "manifest": "/tmp/sase-sudo-test/manifest.json",
        "stop": "/tmp/sase-sudo-test/stop",
    }
    ledger = {
        "schema_version": 1,
        "request_id": "sudo-1",
        "manifest_sha256": "abc",
        "outcome": "completed",
        "entries": [],
        "diagnostic": None,
    }
    polls = {"ledger": 0}

    def runner(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if argv[:3] == ["ssh", "target", "cat"]:
            polls["ledger"] += 1
            if polls["ledger"] == 1:
                return subprocess.CompletedProcess(argv, 1, stdout="")
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(ledger))
        if argv[:4] == ["ssh", "target", "sh", "-c"]:
            return subprocess.CompletedProcess(argv, 0)
        raise AssertionError(f"unexpected ssh call: {argv}")

    assert (
        wait_for_remote_sudo_ledger(
            "target",
            paths,
            handshake={"executor_pid": 123, "executor_identity": "boot:1"},
            command_runner=runner,
            timeout_seconds=1.0,
        )
        == ledger
    )
    assert polls["ledger"] == 2


def test_wait_for_remote_sudo_ledger_stop_writes_remote_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.sudo.ssh._REMOTE_POLL_SECONDS", 0.0)
    monkeypatch.setattr("sase.sudo.ssh._REMOTE_STOP_GRACE_SECONDS", 0.01)
    paths = {
        "directory": "/tmp/sase-sudo-test",
        "handshake": "/tmp/sase-sudo-test/handshake.json",
        "ledger": "/tmp/sase-sudo-test/ledger.json",
        "log": "/tmp/sase-sudo-test/output.log",
        "manifest": "/tmp/sase-sudo-test/manifest.json",
        "stop": "/tmp/sase-sudo-test/stop",
    }
    calls: list[list[str]] = []
    polls = {"ledger": 0}

    def runner(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[Any]:
        calls.append(list(argv))
        if argv[:3] == ["ssh", "target", "cat"]:
            polls["ledger"] += 1
            if polls["ledger"] == 1:
                os.kill(os.getpid(), signal.SIGTERM)
            return subprocess.CompletedProcess(argv, 1, stdout="")
        if argv[:4] == ["ssh", "target", "sh", "-c"]:
            return subprocess.CompletedProcess(argv, 0)
        raise AssertionError(f"unexpected ssh call: {argv}")

    with pytest.raises(GateError) as excinfo:
        wait_for_remote_sudo_ledger(
            "target",
            paths,
            handshake={"executor_pid": 123, "executor_identity": "boot:1"},
            command_runner=runner,
            timeout_seconds=1.0,
        )

    assert excinfo.value.code == "killed"
    assert any(
        call[:4] == ["ssh", "target", "sh", "-c"] and call[4].endswith("/stop")
        for call in calls
    )
