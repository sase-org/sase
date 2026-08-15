"""Typed errors for durable operation request and result sidecars."""

from __future__ import annotations


class OperationIOError(ValueError):
    """A durable operation sidecar could not be read or validated."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class DurableSubmitError(ValueError):
    """ACE rejected a durable submission at the argv/request boundary."""


__all__ = ["DurableSubmitError", "OperationIOError"]
