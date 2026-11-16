"""Gate commands do not inherit the answering proc's operation sidecars."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sase.notification_gates.command_runner import (
    GATE_COMMAND_ENV,
    run_owned_command,
)

_ENV_KEYS = (
    "SASE_PROC_REQUEST_PATH",
    "SASE_PROC_RESULT_PATH",
    "SASE_PROC_OPERATION",
    "SASE_PROC_ID",
    "SASE_PROC_LOG_PATH",
    "SASE_PROC_SESSION_ID",
)

_ECHO_ENV = (
    "#!/usr/bin/env python3\n"
    "import json\n"
    "import os\n"
    f"keys = {list(_ENV_KEYS + (GATE_COMMAND_ENV,))!r}\n"
    "print(json.dumps({key: os.environ.get(key) for key in keys}))\n"
)


def _command_bundle(root: Path) -> tuple[Path, str]:
    """Write one env-echoing gate command and return its bundle and hash."""
    commands = root / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    command = commands / "proceed"
    command.write_text(_ECHO_ENV, encoding="utf-8")
    command.chmod(0o700)
    return root, hashlib.sha256(command.read_bytes()).hexdigest()


def _seed_proc_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_PROC_REQUEST_PATH", str(tmp_path / "request.json"))
    monkeypatch.setenv("SASE_PROC_RESULT_PATH", str(tmp_path / "result.json"))
    monkeypatch.setenv("SASE_PROC_OPERATION", "gate.answer")
    monkeypatch.setenv("SASE_PROC_ID", "proc-1")
    monkeypatch.setenv("SASE_PROC_LOG_PATH", str(tmp_path / "proc.log"))
    monkeypatch.setenv("SASE_PROC_SESSION_ID", "session-1")


def test_owned_command_scrubs_proc_sidecar_env(monkeypatch, tmp_path: Path) -> None:
    """The ``subprocess.run`` path drops only the sidecar trio."""
    _seed_proc_env(monkeypatch, tmp_path)
    bundle, digest = _command_bundle(tmp_path / "bundle")

    completed = run_owned_command(
        bundle,
        ("commands/proceed",),
        expected_hash=digest,
        input_data={"answer": "yes"},
    )

    assert completed.returncode == 0
    seen = json.loads(completed.stdout.decode("utf-8"))
    assert seen["SASE_PROC_REQUEST_PATH"] is None
    assert seen["SASE_PROC_RESULT_PATH"] is None
    assert seen["SASE_PROC_OPERATION"] is None
    assert seen["SASE_PROC_ID"] == "proc-1"
    assert seen["SASE_PROC_LOG_PATH"] == str(tmp_path / "proc.log")
    assert seen["SASE_PROC_SESSION_ID"] == "session-1"
    assert seen[GATE_COMMAND_ENV] == "1"


def test_streamed_owned_command_scrubs_proc_sidecar_env(
    monkeypatch, tmp_path: Path
) -> None:
    """The streaming path drops only the sidecar trio too."""
    _seed_proc_env(monkeypatch, tmp_path)
    bundle, digest = _command_bundle(tmp_path / "bundle")
    lines: list[tuple[str, str]] = []

    completed = run_owned_command(
        bundle,
        ("commands/proceed",),
        expected_hash=digest,
        input_data={"answer": "yes"},
        on_output_line=lambda stream, line: lines.append((stream, line)),
    )

    assert completed.returncode == 0
    assert len(lines) == 1
    seen = json.loads(lines[0][1])
    assert lines[0][0] == "stdout"
    assert seen["SASE_PROC_REQUEST_PATH"] is None
    assert seen["SASE_PROC_RESULT_PATH"] is None
    assert seen["SASE_PROC_OPERATION"] is None
    assert seen["SASE_PROC_ID"] == "proc-1"
    assert seen["SASE_PROC_LOG_PATH"] == str(tmp_path / "proc.log")
    assert seen["SASE_PROC_SESSION_ID"] == "session-1"
    assert seen[GATE_COMMAND_ENV] == "1"
