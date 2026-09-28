"""Bounded, noninteractive git execution shared by sync and status."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import subprocess
from typing import Protocol

from sase.git_lock_retry import run_with_git_lock_retry
from sase.sdd._git import network_git_timeout, run_sdd_git, run_sdd_network_git


class GitRunner(Protocol):
    """Injectable git command boundary used by deterministic tests."""

    def __call__(
        self,
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "agents_sync.git",
    ) -> subprocess.CompletedProcess[str]: ...


def _noninteractive_git_env(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a git environment that cannot prompt for credentials."""

    env = dict(os.environ if base is None else base)
    env["GIT_TERMINAL_PROMPT"] = "0"
    ssh_command = env.get("GIT_SSH_COMMAND", "ssh")
    if "BatchMode=" not in ssh_command:
        ssh_command = f"{ssh_command} -o BatchMode=yes"
    env["GIT_SSH_COMMAND"] = ssh_command
    return env


def run_git(
    cwd: Path,
    args: list[str],
    *,
    network: bool = False,
    op: str = "agents_sync.git",
) -> subprocess.CompletedProcess[str]:
    """Run one bounded git command with network prompt hardening.

    Local (non-network) commands retry around a contended ``index.lock``: git
    performs no work when it cannot create the lock, so re-running add,
    commit, reset, checkout, clean, ls-files, or ``rebase --abort`` is safe.
    Network commands (pull --rebase, push) are left unwrapped; rebase
    failures already go through ``abort_agents_rebase``.
    """

    if network:
        result = run_sdd_network_git(
            args,
            cwd=cwd,
            op=op,
            timeout=network_git_timeout(),
            check=False,
            capture_output=True,
            text=True,
            env=_noninteractive_git_env(),
        )
    else:
        result, _outcome = run_with_git_lock_retry(
            lambda: run_sdd_git(
                args,
                cwd=cwd,
                op=op,
                timeout=None,
                check=False,
                capture_output=True,
                text=True,
                env=_noninteractive_git_env(),
            ),
            cwd=cwd,
        )
    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        str(result.stdout or ""),
        str(result.stderr or ""),
    )


__all__ = ["GitRunner", "run_git"]
