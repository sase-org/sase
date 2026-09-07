"""Exception types raised by the federation facade and worker supervisor."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FederationConfigError(RuntimeError):
    """Raised when configured federation hosts cannot be projected safely."""


class FederationWorkerUnavailable(RuntimeError):
    """Raised when the local federation worker cannot be reached or started."""


class FederationWorkerResponseError(RuntimeError):
    """Raised when the worker returns an IPC-level error response."""

    def __init__(self, error: Mapping[str, Any]) -> None:
        self.error = dict(error)
        message = str(self.error.get("message") or "federation worker request failed")
        super().__init__(message)
