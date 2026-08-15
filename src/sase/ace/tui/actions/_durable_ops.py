"""Small helpers for ACE durable-operation submissions."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any


def durable_fingerprint(operation: str, *identifiers: object) -> str:
    """Hash only stable identifiers into a durable request fingerprint."""
    parts = [operation, *(str(item) for item in identifiers)]
    encoded = "\0".join(parts).encode("utf-8", errors="surrogateescape")
    return f"sha256:{sha256(encoded).hexdigest()}"


def durable_request_payload(**payload: Any) -> Mapping[str, Any]:
    """Return a JSON-shaped payload while keeping call sites readable."""
    return dict(payload)


def sase_argv(*parts: object) -> list[str]:
    """Build a SASE CLI argv with stringified non-empty parts."""
    return ["sase", *(str(part) for part in parts if part is not None)]


__all__ = ["durable_fingerprint", "durable_request_payload", "sase_argv"]
