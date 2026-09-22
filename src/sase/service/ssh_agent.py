"""Git remote authentication probing and readiness reporting for the service host."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

_PROBE_TIMEOUT_SECONDS = 2
_REMOTE_PROBE_TIMEOUT_SECONDS = 5
_PROBE_ENV_NAMES = ("PATH", "SSH_AUTH_SOCK", "SSH_AGENT_PID")
_GIT_REMOTE_LOGIN = "git@github.com"
# GitHub greets a deploy key as ``Hi <owner>/<repo>!`` and a user key as
# ``Hi <login>!``; matched against lowercased output.
_DEPLOY_KEY_GREETING = re.compile(r"\bhi [\w.-]+/[\w.-]+!")

SshAgentState = Literal["ready", "empty", "unreachable"]
SshAgentScope = Literal["captured", "effective"]
GitRemoteReadiness = Literal["ready", "denied", "unknown"]


def is_live_ssh_agent_socket(sock: str | None) -> bool:
    """Return True when ``sock`` names a live agent socket.

    Shared by capture and host-start loading so both agree on what "live"
    means. A missing or empty path is not live.
    """
    if not sock:
        return False
    try:
        return Path(sock).is_socket()
    except OSError:
        return False


def _probe_ssh_agent(env: Mapping[str, str]) -> SshAgentState | None:
    """Ask the agent named by ``env`` whether it can authenticate anything.

    ``ssh-add -l`` exits ``0`` with identities, ``1`` when the agent is
    reachable but empty, and ``2`` when it cannot be reached. Returns ``None``
    when ``ssh-add`` cannot be found, because a missing ssh-add is not a SASE
    problem. Raises when the probe itself fails to run (for example a timeout);
    callers that only advise must catch that.

    This describes the agent, not the credential: a host can authenticate by
    ``IdentityFile`` while its agent is empty. Use it to explain a failure,
    never to decide readiness; :func:`probe_git_remote_auth` decides that.
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


def probe_git_remote_auth(env: Mapping[str, str]) -> GitRemoteReadiness:
    """Ask the git remote whether ``env`` can authenticate to it.

    Runs ``ssh -T`` against the remote the way git would, so it sees whatever
    credential really applies: an agent identity, an ``IdentityFile``, or
    neither. GitHub answers a successful login with ``successfully
    authenticated`` (and exit status ``1``, since it grants no shell) and a
    rejected one with ``Permission denied (publickey)``. A login greeted as
    ``Hi <owner>/<repo>!`` used a deploy key and is ``denied`` too: ssh
    presents the first key the remote accepts (agent keys go before any
    ``IdentityFile`` unless ``IdentitiesOnly`` is set), and GitHub scopes a
    deploy key to its one repository, so every other repo, sidecars included,
    fails with ``Permission to <repo> denied to deploy key``. Anything else
    (timeout, DNS failure, no route, a missing ``ssh``) is ``unknown``, never
    ``denied``: an offline host is not a credential failure. This never raises.
    """
    try:
        ssh = shutil.which("ssh", path=env.get("PATH"))
        if ssh is None:
            return "unknown"
        result = subprocess.run(
            [
                ssh,
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-T",
                _GIT_REMOTE_LOGIN,
            ],
            env={name: env[name] for name in _PROBE_ENV_NAMES if name in env},
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=_REMOTE_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception:
        return "unknown"
    output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    if "successfully authenticated" in output:
        return "denied" if _DEPLOY_KEY_GREETING.search(output) else "ready"
    if "permission denied (publickey" in output:
        return "denied"
    return "unknown"


def ssh_agent_readiness_warnings(
    env: Mapping[str, str],
    *,
    scope: SshAgentScope = "captured",
    ignored_stale_sock: str | None = None,
) -> list[str]:
    """Warn when ``env`` cannot authenticate to the git remote.

    Readiness is the remote's answer (:func:`probe_git_remote_auth`): only
    ``denied`` warns, and ``ready`` and ``unknown`` stay silent. The agent's
    contents only word the warning. ``scope="captured"`` reports on the
    environment ``sase service init`` is about to capture. ``scope="effective"``
    reports on the environment a (re)started service host would really see,
    where the platform manager's inherited agent is what applies whenever
    nothing is captured. This must never raise: readiness reporting is advisory.
    """
    if probe_git_remote_auth(env) != "denied":
        return []
    detail = _agent_detail(env, scope, ignored_stale_sock)
    if scope == "effective":
        return [
            "the service host's effective environment is refused by the git "
            f"remote: {detail}; git operations against SSH remotes will fail "
            "with `Permission denied (publickey)`; see docs/init.md for "
            "remediation options"
        ]
    return [
        f"captured service environment is refused by the git remote: {detail}; "
        "plan archival, stitch pushes, and any other host-owned git work "
        "against an SSH remote will fail with `Permission denied (publickey)`; "
        "see docs/init.md to give the host an unattended credential"
    ]


def _agent_detail(
    env: Mapping[str, str],
    scope: SshAgentScope,
    ignored_stale_sock: str | None = None,
) -> str:
    """Describe the agent in ``env`` for a refused credential; advisory only."""
    sock = env.get("SSH_AUTH_SOCK")
    if not sock:
        if scope == "effective":
            base = (
                "neither the captured environment nor the platform manager "
                "provides an SSH agent (SSH_AUTH_SOCK) and no configured "
                "IdentityFile was accepted"
            )
        else:
            base = (
                "no SSH agent (SSH_AUTH_SOCK) is captured and no configured "
                "IdentityFile was accepted"
            )
    else:
        try:
            state = _probe_ssh_agent(env)
        except Exception:
            state = None
        if state == "empty":
            base = (
                f"the SSH agent at {sock} is reachable but holds no identities, "
                "and no configured IdentityFile was accepted"
            )
        elif state == "unreachable":
            base = (
                f"the SSH agent at {sock} is unreachable, and no configured "
                "IdentityFile was accepted"
            )
        elif state == "ready":
            base = (
                f"the SSH agent at {sock} holds identities, "
                "but the remote accepted none"
            )
        else:
            base = f"the SSH agent at {sock} could not be inspected"
    if scope == "effective" and ignored_stale_sock:
        if sock:
            prefix = (
                f"the captured SSH agent at {ignored_stale_sock} no longer "
                "exists, so the host uses the platform manager's agent at "
                f"{sock}; "
            )
        else:
            prefix = (
                f"the captured SSH agent at {ignored_stale_sock} no longer "
                "exists, so the host ignores it and the platform manager "
                "provides no agent; "
            )
        return prefix + base
    return base


__all__ = [
    "GitRemoteReadiness",
    "SshAgentScope",
    "SshAgentState",
    "is_live_ssh_agent_socket",
    "probe_git_remote_auth",
    "ssh_agent_readiness_warnings",
]
