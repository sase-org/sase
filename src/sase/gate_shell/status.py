"""Status-label helpers for gate shell members."""

from __future__ import annotations

from typing import cast

from sase.notification_gates.model_shell import (
    DEFAULT_GATE_SHELL_PENDING_STATUS,
    DEFAULT_GATE_SHELL_SETTLED_STATUS,
    GATE_SHELL_STATUS_ELLIPSIS,
    GATE_SHELL_STATUS_MAX_CHARS,
)
from sase.shells.status import ShellStatusPair, shell_status_pair


class _GateStatusPair(ShellStatusPair):
    """Ordered ``(pending, settled)`` label pair for one gate shell."""


def gate_status_pair(start: str | None, stop: str | None) -> ShellStatusPair:
    """Clamp both gate-shell status labels, filling omitted halves."""
    return cast(
        ShellStatusPair,
        shell_status_pair(
            start,
            stop,
            default_start=DEFAULT_GATE_SHELL_PENDING_STATUS,
            default_stop=DEFAULT_GATE_SHELL_SETTLED_STATUS,
            max_chars=GATE_SHELL_STATUS_MAX_CHARS,
            ellipsis=GATE_SHELL_STATUS_ELLIPSIS,
            pair_type=_GateStatusPair,
            noun="gate shell status",
        ),
    )


__all__ = [
    "DEFAULT_GATE_SHELL_PENDING_STATUS",
    "DEFAULT_GATE_SHELL_SETTLED_STATUS",
    "gate_status_pair",
]
