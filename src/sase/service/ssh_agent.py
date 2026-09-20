"""SSH agent probing and readiness reporting for the service environment."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from typing import Literal

_PROBE_TIMEOUT_SECONDS = 2
_PROBE_ENV_NAMES = ("PATH", "SSH_AUTH_SOCK", "SSH_AGENT_PID")

SshAgentState = Literal["ready", "empty", "unreachable"]
SshAgentScope = Literal["captured", "effective"]


def probe_ssh_agent(env: Mapping[str, str]) -> SshAgentState | None:
    """Ask the agent named by ``env`` whether it can authenticate anything.

    ``ssh-add -l`` exits ``0`` with identities, ``1`` when the agent is
    reachable but empty, and ``2`` when it cannot be reached. Returns ``None``
    when ``ssh-add`` cannot be found, because a missing ssh-add is not a SASE
    problem. Raises when the probe itself fails to run (for example a timeout);
    callers that only advise must catch that.
    """
    ssh_add = shutil.which("ssh-add", path=env.get("PATH"))
    if ssh_add is None:
        return None
    result = subprocess.run(
        [ssh_add, "-l"],
        env={name: env[name] for name in _PROBE_ENV_NAMES if name in env},
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=_PROBE_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode == 1:
        return "empty"
    if result.returncode == 2:
        return "unreachable"
    return "ready"


def ssh_agent_readiness_warnings(
    env: Mapping[str, str],
    *,
    scope: SshAgentScope = "captured",
) -> list[str]:
    """Warn when the SSH agent in ``env`` cannot authenticate git remotes.

    ``scope="captured"`` reports on the environment ``sase service init`` is
    about to capture. ``scope="effective"`` reports on the environment a
    (re)started service host would really see, where the platform manager's
    inherited agent is what applies whenever nothing is captured. This probe
    must never raise: readiness reporting is advisory.
    """
    sock = env.get("SSH_AUTH_SOCK")
    if not sock:
        if scope == "effective":
            return [
                "the service host's effective environment carries no SSH agent "
                "(SSH_AUTH_SOCK) from either the captured environment or the "
                "platform manager; host-owned git work against an SSH remote "
                "will fail with `Permission denied (publickey)`; see "
                "docs/init.md for remediation options"
            ]
        return [
            "captured service environment carries no SSH agent (SSH_AUTH_SOCK); "
            "plan archival, stitch pushes, and any other host-owned git work "
            "against an SSH remote will fail with `Permission denied (publickey)`; "
            "run `sase service init` from a shell whose agent holds the key"
        ]
    try:
        state = probe_ssh_agent(env)
    except Exception as exc:
        return [f"SSH agent readiness could not be checked: {exc}"]
    if state == "empty":
        if scope == "effective":
            return [
                f"the service host's effective SSH agent at {sock} is reachable "
                "but holds no identities, so git operations against SSH remotes "
                "will fail with `Permission denied (publickey)`; see "
                "docs/init.md for remediation options"
            ]
        return [
            f"SSH agent at {sock} is reachable but holds no identities, so git "
            "operations against SSH remotes will fail with "
            "`Permission denied (publickey)`; load the key with `ssh-add` and "
            "re-run `sase service init`"
        ]
    if state == "unreachable":
        if scope == "effective":
            return [
                f"the service host's effective SSH agent at {sock} is "
                "unreachable, so git operations against SSH remotes will fail "
                "with `Permission denied (publickey)`; see docs/init.md for "
                "remediation options"
            ]
        return [
            f"SSH agent at {sock} is unreachable, so git operations against SSH "
            "remotes will fail with `Permission denied (publickey)`; re-run "
            "`sase service init` from a shell with a live agent"
        ]
    return []


__all__ = [
    "SshAgentScope",
    "SshAgentState",
    "probe_ssh_agent",
    "ssh_agent_readiness_warnings",
]
