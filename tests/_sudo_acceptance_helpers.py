"""Shared helpers for sudo acceptance coverage."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

from sase.sudo import runner as sudo_runner

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


def _assert_sensitive_tokens_absent_bytes(
    values: Iterable[bytes],
    *,
    canary: str,
) -> None:
    tokens = _sensitive_tokens(canary)
    for raw in values:
        for label, token in tokens.items():
            assert token not in raw, f"{label} leaked into process metadata"


def _iter_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (child for child in path.rglob("*") if child.is_file())


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
