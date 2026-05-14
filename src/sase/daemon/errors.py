"""Typed errors raised by the local SASE daemon client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class LocalDaemonError(RuntimeError):
    """Base class for local daemon client failures."""


@dataclass(frozen=True)
class LocalDaemonTransportError(LocalDaemonError):
    """Transport-level failure with daemon fallback metadata."""

    message: str
    code: str = "daemon_unavailable"
    fallback_reason: str | None = "daemon_not_running"
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


class LocalDaemonUnavailableError(LocalDaemonTransportError):
    """Typed failure for unavailable local daemon transport."""


@dataclass(frozen=True)
class LocalDaemonRpcError(LocalDaemonError):
    """Typed error returned by the local daemon RPC protocol."""

    code: str
    message: str
    retryable: bool
    target: str | None
    details: dict[str, Any] | None
    fallback_reason: str | None
    fallback_message: str | None

    def __str__(self) -> str:
        return self.message
