"""Coverage for the shared SSH login-shell encoder."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sase.dispatch.ssh_login_shell import (
    LOGIN_SHELL_ARGV0,
    remote_login_shell_argv,
    remote_login_shell_command,
)

_BOOTSTRAP = 'shell="${SHELL:-/bin/sh}"; exec "$shell" -lc "$1"'


def test_remote_login_shell_argv_quotes_spaces() -> None:
    argv = remote_login_shell_argv(
        ["sase", "sudo", "exec", "--manifest", "/tmp/remote cwd/manifest.json"]
    )
    assert argv == [
        "sh",
        "-c",
        _BOOTSTRAP,
        LOGIN_SHELL_ARGV0,
        "exec sase sudo exec --manifest '/tmp/remote cwd/manifest.json'",
    ]


def test_remote_login_shell_command_is_one_ssh_argument() -> None:
    command = remote_login_shell_command(["sase", "screenshot", "--contract"])
    assert command == (
        'sh -c \'shell="${SHELL:-/bin/sh}"; exec "$shell" -lc "$1"\' '
        "sase-login-shell 'exec sase screenshot --contract'"
    )


def test_remote_login_shell_argv_rejects_empty_command() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        remote_login_shell_argv(())


def test_remote_login_shell_preserves_spaces_quotes_and_dollars(tmp_path: Path) -> None:
    recorder = tmp_path / "record.py"
    output = tmp_path / "argv.json"
    login_shell = tmp_path / "fake-login-shell"
    recorder.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    login_shell.write_text(
        "#!/usr/bin/env python3\n"
        "import subprocess, sys\n"
        "if sys.argv[1:2] != ['-lc'] or len(sys.argv) != 3:\n"
        "    raise SystemExit(64)\n"
        "raise SystemExit(subprocess.run(['/bin/sh', '-c', sys.argv[2]]).returncode)\n",
        encoding="utf-8",
    )
    login_shell.chmod(0o755)
    payload = [
        sys.executable,
        str(recorder),
        str(output),
        "a b",
        "x'y",
        'say "hi"',
        "$HOME",
        "a;b|c",
        "`id`",
        "$(uname)",
    ]
    completed = subprocess.run(
        ["/bin/sh", "-c", remote_login_shell_command(payload)],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
        env={**os.environ, "SHELL": str(login_shell)},
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == payload[3:]
