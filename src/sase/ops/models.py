"""Versioned durable-operation request and result models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

OPERATION_SCHEMA_VERSION = 1
SUPPORTED_OPERATION_SCHEMA_VERSIONS = frozenset({OPERATION_SCHEMA_VERSION})

REQUEST_ENV = "SASE_PROC_REQUEST_PATH"
RESULT_ENV = "SASE_PROC_RESULT_PATH"
OPERATION_ENV = "SASE_PROC_OPERATION"
PROC_ID_ENV = "SASE_PROC_ID"


@dataclass(frozen=True, slots=True)
class DurableOperationRequest:
    """Versioned operation request: identity plus JSON-shaped domain data."""

    operation: str
    payload: Mapping[str, Any]
    schema_version: int = OPERATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "payload": dict(self.payload),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class DurableOperationResult:
    """Versioned typed completion envelope for one durable operation."""

    operation: str
    proc_id: str
    success: bool
    message: str
    error: str | None = None
    payload: Mapping[str, Any] | None = None
    schema_version: int = OPERATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.error,
            "message": self.message,
            "operation": self.operation,
            "payload": None if self.payload is None else dict(self.payload),
            "proc_id": self.proc_id,
            "schema_version": self.schema_version,
            "success": self.success,
        }


__all__ = [
    "OPERATION_ENV",
    "OPERATION_SCHEMA_VERSION",
    "PROC_ID_ENV",
    "REQUEST_ENV",
    "RESULT_ENV",
    "SUPPORTED_OPERATION_SCHEMA_VERSIONS",
    "DurableOperationRequest",
    "DurableOperationResult",
]
