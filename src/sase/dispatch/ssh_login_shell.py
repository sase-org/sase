"""Encode a remote argv so SSH runs it through the account login shell."""

from __future__ import annotations

import shlex
from collections.abc import Sequence

LOGIN_SHELL_ARGV0 = "sase-login-shell"
_LOGIN_SHELL_BOOTSTRAP = 'shell="${SHELL:-/bin/sh}"; exec "$shell" -lc "$1"'


def remote_login_shell_argv(command: Sequence[str]) -> list[str]:
    """Return argv that runs *command* via the remote account's login shell.

    The wrapper preserves argv boundaries with shell quoting, honors the remote
    ``SHELL`` value, and falls back to ``/bin/sh``. It does not allocate a TTY
    and does not apply screenshot- or sudo-specific policy.
    """
    if not command:
        raise ValueError("remote login-shell command must not be empty")
    return [
        "sh",
        "-c",
        _LOGIN_SHELL_BOOTSTRAP,
        LOGIN_SHELL_ARGV0,
        "exec " + shlex.join(command),
    ]


def remote_login_shell_command(command: Sequence[str]) -> str:
    """Return one SSH remote-command string for a login-shell *command*."""
    return shlex.join(remote_login_shell_argv(command))


__all__ = [
    "LOGIN_SHELL_ARGV0",
    "remote_login_shell_argv",
    "remote_login_shell_command",
]
