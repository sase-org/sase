"""The environment a service host would really see, as opposed to a capture.

``sase service init`` captures the *calling shell's* environment. The host that
actually runs sees that capture overlaid on whatever its platform manager hands
every unit, and the two disagree exactly when it matters: a credential that works in
your interactive shell says nothing about the one the manager supplies.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from sase.service.env import read_service_environment
from sase.service.ssh_agent import (
    is_live_ssh_agent_socket,
    ssh_agent_readiness_warnings,
)

_SSH_AUTH_SOCK_ENV = "SSH_AUTH_SOCK"
_SSH_AGENT_PID_ENV = "SSH_AGENT_PID"


class _CommandOutput(Protocol):
    """The slice of a command result the environment lookup reads."""

    @property
    def returncode(self) -> int: ...

    @property
    def stdout(self) -> str: ...


def _effective_service_environment(
    *,
    platform_kind: str,
    env_path: Path,
    runner: Callable[[Sequence[str]], _CommandOutput],
) -> dict[str, str]:
    """Return the captured environment overlaid on the manager's inherited one.

    Mirrors how the host boots: it loads ``env_path`` over ``os.environ`` with
    ``override_existing=True``, and ``os.environ`` starts as the platform
    manager's environment. A missing or malformed file contributes nothing.
    A persisted agent socket that is no longer live is ignored, so the
    manager's agent applies.
    """
    values = _inherited_environment(platform_kind, runner)
    try:
        persisted = read_service_environment(path=env_path)
    except (OSError, ValueError):
        return values
    if not is_live_ssh_agent_socket(persisted.get(_SSH_AUTH_SOCK_ENV)):
        persisted = {
            name: value
            for name, value in persisted.items()
            if name not in (_SSH_AUTH_SOCK_ENV, _SSH_AGENT_PID_ENV)
        }
    values.update(persisted)
    return values


def effective_service_environment(
    *,
    platform_kind: str,
    env_path: Path,
    runner: Callable[[Sequence[str]], _CommandOutput],
) -> dict[str, str]:
    """Public wrapper for the host's effective environment."""
    return _effective_service_environment(
        platform_kind=platform_kind, env_path=env_path, runner=runner
    )


def inherited_environment(
    *,
    platform_kind: str,
    runner: Callable[[Sequence[str]], _CommandOutput],
) -> dict[str, str]:
    """Public wrapper for the manager's inherited environment."""
    return _inherited_environment(platform_kind, runner)


def effective_ssh_agent_warnings(
    *,
    platform_kind: str,
    env_path: Path,
    desired_env: Mapping[str, str],
    runner: Callable[[Sequence[str]], _CommandOutput],
) -> list[str]:
    """Warn when the environment the service host would really see is refused.

    ``desired_env`` is what ``sase service init`` is about to capture and is
    reported on separately. When both name the same agent that report already
    covers it, so this stays quiet rather than saying the same thing twice (and
    skips a second round trip to the git remote).
    """
    effective = _effective_service_environment(
        platform_kind=platform_kind, env_path=env_path, runner=runner
    )
    if effective.get(_SSH_AUTH_SOCK_ENV) == desired_env.get(_SSH_AUTH_SOCK_ENV):
        return []
    try:
        persisted = read_service_environment(path=env_path)
    except (OSError, ValueError):
        persisted = {}
    ignored: str | None = None
    stale = persisted.get(_SSH_AUTH_SOCK_ENV)
    if stale and not is_live_ssh_agent_socket(stale):
        ignored = stale
    return ssh_agent_readiness_warnings(
        effective, scope="effective", ignored_stale_sock=ignored
    )


def _inherited_environment(
    platform_kind: str,
    runner: Callable[[Sequence[str]], _CommandOutput],
) -> dict[str, str]:
    """Best-effort read of the environment the platform manager gives units."""
    try:
        if platform_kind == "linux":
            result = runner(["systemctl", "--user", "show-environment"])
            return (
                _parse_show_environment(result.stdout) if result.returncode == 0 else {}
            )
        if platform_kind == "darwin":
            result = runner(["launchctl", "getenv", _SSH_AUTH_SOCK_ENV])
            sock = result.stdout.strip()
            if result.returncode == 0 and sock:
                return {_SSH_AUTH_SOCK_ENV: sock}
    except Exception:
        pass
    return {}


def _parse_show_environment(text: str) -> dict[str, str]:
    """Parse ``systemctl show-environment`` ``NAME=value`` lines.

    systemd shell-quotes values containing special characters as ``$'...'``;
    those are left undecoded. Every value this module consumes (``PATH`` and
    ``SSH_AUTH_SOCK``) is a plain path, and an undecodable one only degrades the
    probe to "could not check".
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        name, separator, value = line.partition("=")
        if separator and name:
            values[name] = value
    return values


__all__ = [
    "effective_service_environment",
    "effective_ssh_agent_warnings",
    "inherited_environment",
]
