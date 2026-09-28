"""Shared types and helpers for `%dispatch` launches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FLEET_SCHEMA_VERSION = 1


class RemoteDispatchLaunchError(RuntimeError):
    """Raised when a `%dispatch` launch cannot be safely submitted."""


@dataclass(frozen=True)
class RemoteDispatchLaunchPreview:
    """Source-side dispatch validation result before network submission."""

    target: str
    prompt: str
    source: str
    target_installation_id: str
    target_status: str
    target_detail: str
    portable_context: dict[str, Any]
    intent: dict[str, Any]
    operation_key: dict[str, str | int]
    payload_fingerprint: dict[str, Any]
    request: dict[str, Any]
    provisional_locator: dict[str, object]


def optional_string(value: object) -> str | None:
    """Return *value* stripped, or None when it is not a non-empty string."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


__all__ = [
    "FLEET_SCHEMA_VERSION",
    "RemoteDispatchLaunchError",
    "RemoteDispatchLaunchPreview",
    "optional_string",
]
