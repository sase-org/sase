"""Shared git plumbing for the attachment store (private).

Public helpers live here because both :mod:`store` and :mod:`plumbing`
need them: bounded :func:`run_git`, :func:`git_env`, and the timeout and
chunk-size constants. Import only public names from this module.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

LOCAL_GIT_TIMEOUT_SECONDS = 30.0
CHUNK_SIZE = 1 << 20


def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a noninteractive git environment plus *extra* overrides."""

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    ssh_command = env.get("GIT_SSH_COMMAND", "ssh")
    if "BatchMode=" not in ssh_command:
        ssh_command = f"{ssh_command} -o BatchMode=yes"
    env["GIT_SSH_COMMAND"] = ssh_command
    if extra:
        env.update(extra)
    return env


def run_git(
    args: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one bounded git command, capturing output as text."""

    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        timeout=timeout,
        check=False,
        capture_output=True,
        text=True,
        env=git_env(env),
    )
