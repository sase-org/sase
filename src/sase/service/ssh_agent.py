"""SSH agent readiness reporting for the captured service environment."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping

_PROBE_TIMEOUT_SECONDS = 2
_PROBE_ENV_NAMES = ("PATH", "SSH_AUTH_SOCK", "SSH_AGENT_PID")


def ssh_agent_readiness_warnings(env: Mapping[str, str]) -> list[str]:
    """Warn when the captured SSH agent cannot authenticate git remotes.

    ``ssh-add -l`` exits ``0`` with identities, ``1`` when the agent is
    reachable but empty, and ``2`` when it cannot be reached. This probe must
    never raise: readiness reporting is advisory.
    """
    sock = env.get("SSH_AUTH_SOCK")
    if not sock:
        return [
            "captured service environment carries no SSH agent (SSH_AUTH_SOCK); "
            "plan archival, stitch pushes, and any other host-owned git work "
            "against an SSH remote will fail with `Permission denied (publickey)`; "
            "run `sase service init` from a shell whose agent holds the key"
        ]
    try:
        # A missing ssh-add is not a SASE problem, so skip the probe silently.
        ssh_add = shutil.which("ssh-add", path=env.get("PATH"))
        if ssh_add is None:
            return []
        result = subprocess.run(
            [ssh_add, "-l"],
            env={name: env[name] for name in _PROBE_ENV_NAMES if name in env},
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception as exc:
        return [f"SSH agent readiness could not be checked: {exc}"]
    if result.returncode == 1:
        return [
            f"SSH agent at {sock} is reachable but holds no identities, so git "
            "operations against SSH remotes will fail with "
            "`Permission denied (publickey)`; load the key with `ssh-add` and "
            "re-run `sase service init`"
        ]
    if result.returncode == 2:
        return [
            f"SSH agent at {sock} is unreachable, so git operations against SSH "
            "remotes will fail with `Permission denied (publickey)`; re-run "
            "`sase service init` from a shell with a live agent"
        ]
    return []


__all__ = ["ssh_agent_readiness_warnings"]
