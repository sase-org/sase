"""Owned gate commands carry the history-ingress marker in their environment."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sase.notification_gates.command_runner import (
    GATE_COMMAND_ENV,
    run_owned_command,
)

_MARKS_STDIN = (
    "#!/usr/bin/env python3\n"
    "import os\n"
    f'print(os.environ.get("{GATE_COMMAND_ENV}", ""))\n'
)


def _command_bundle(root: Path) -> tuple[Path, str]:
    """Write one marker-echoing gate command and return its bundle and hash."""
    commands = root / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    command = commands / "proceed"
    command.write_text(_MARKS_STDIN, encoding="utf-8")
    command.chmod(0o700)
    return root, hashlib.sha256(command.read_bytes()).hexdigest()


def test_owned_command_exports_gate_marker(tmp_path: Path) -> None:
    """The ``subprocess.run`` path marks its command as gate automation."""
    bundle, digest = _command_bundle(tmp_path / "bundle")

    completed = run_owned_command(
        bundle,
        ("commands/proceed",),
        expected_hash=digest,
        input_data={"answer": "yes"},
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == b"1"


def test_streamed_owned_command_exports_gate_marker(tmp_path: Path) -> None:
    """The streaming path marks its command as gate automation too."""
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
    assert lines == [("stdout", "1")]
