"""Shared constants and validation helpers for mobile agent integration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MOBILE_AGENT_SCHEMA_VERSION = 1

_PROMPT_SNIPPET_LIMIT = 200
_SAFE_DIRECTIVE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_DEVICE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_SAFE_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_CONTEXT_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_.:-]+")
_MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
_IMAGE_TYPES: dict[str, tuple[str, bytes | tuple[bytes, ...]]] = {
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".webp": ("image/webp", b"RIFF"),
    ".gif": ("image/gif", (b"GIF87a", b"GIF89a")),
}


class MobileAgentBridgeError(RuntimeError):
    """Deterministic bridge error for JSON command failures."""


class MobileAgentInvalidUploadError(MobileAgentBridgeError):
    """Deterministic bridge error for rejected mobile image uploads."""


class MobileAgentNotFoundError(MobileAgentBridgeError):
    """Deterministic bridge error for missing mobile agent lifecycle targets."""


class MobileAgentNotRunningError(MobileAgentBridgeError):
    """Deterministic bridge error for non-running mobile lifecycle targets."""


class MobileAgentPermissionDeniedError(MobileAgentBridgeError):
    """Deterministic bridge error for denied host lifecycle mutations."""


@dataclass(frozen=True)
class MobileAgentListRequest:
    include_recent: bool = False
    status: str | None = None
    project: str | None = None
    device_id: str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class MobileProjectContext:
    context_id: str
    mode: str
    project: str | None = None
    project_file: str | None = None
    workflow: str | None = None
    ref: str | None = None


def required_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MobileAgentInvalidUploadError(f"{field} must be a non-empty string")
    return value.strip()


def required_bridge_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MobileAgentBridgeError(f"{field} must be a non-empty string")
    return value.strip()


def required_byte_length(value: Any) -> int:
    try:
        byte_length = int(value)
    except (TypeError, ValueError) as exc:
        raise MobileAgentInvalidUploadError("byte_length must be an integer") from exc
    if byte_length < 0:
        raise MobileAgentInvalidUploadError("byte_length must be non-negative")
    return byte_length


def safe_device_id(device_id: str | None) -> str:
    if not device_id:
        return "unknown_device"
    safe = _SAFE_DEVICE_ID_RE.sub("-", device_id).strip(".-")
    return safe or "unknown_device"


def safe_context_id(value: str) -> str:
    safe = _SAFE_CONTEXT_COMPONENT_RE.sub("-", value).strip(".:-")
    return safe or "current"


def mobile_model_directive_value(
    model: str | None,
    provider: str | None,
    runtime: str | None,
) -> str | None:
    if model is None:
        return None
    prefix = provider or runtime
    if prefix and "/" not in model:
        return f"{prefix}/{model}"
    return model


def safe_error_message(exc: BaseException) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def optional_uint(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def directive_name(name: str) -> str:
    if _SAFE_DIRECTIVE_NAME_RE.fullmatch(name):
        return name
    return f"`{name.replace('`', '')}`"


def option_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "agent"
