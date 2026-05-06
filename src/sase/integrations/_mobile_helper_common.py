"""Shared mobile helper bridge validation and wire helpers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, TextIO

GATEWAY_WIRE_SCHEMA_VERSION = 1
_SAFE_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class MobileHelperBridgeError(RuntimeError):
    """Deterministic bridge error for invalid mobile helper requests."""


class MobileUpdateAlreadyRunning(RuntimeError):
    """Bridge sentinel mapped to update_already_running by the gateway."""


class MobileUpdateJobNotFound(RuntimeError):
    """Bridge sentinel mapped to update_job_not_found by the gateway."""


class MobileHelperNotFoundError(MobileHelperBridgeError):
    """Deterministic bridge error for missing helper records."""


def read_request(stdin: TextIO) -> dict[str, Any]:
    raw = stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MobileHelperBridgeError(f"invalid JSON request: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise MobileHelperBridgeError("request JSON must be an object")
    return payload


def optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MobileHelperBridgeError(f"{field} must be a string")
    value = value.strip()
    return value or None


def optional_limit(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise MobileHelperBridgeError("limit must be an integer")
    if value < 0:
        raise MobileHelperBridgeError("limit must be non-negative")
    return value


def optional_bool(value: object, field: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise MobileHelperBridgeError(f"{field} must be a boolean")
    return value


def required_string(value: object, field: str) -> str:
    parsed = optional_string(value, field)
    if parsed is None:
        raise MobileHelperBridgeError(f"{field} is required")
    return parsed


def reject_unexpected_fields(request: dict[str, Any], allowed: set[str]) -> None:
    unexpected = sorted(set(request) - allowed)
    if unexpected:
        fields = ", ".join(unexpected)
        raise MobileHelperBridgeError(f"unexpected request field(s): {fields}")


def optional_project(value: object) -> str | None:
    project = optional_string(value, "project")
    if project is None:
        return None
    if (
        "/" in project
        or "\\" in project
        or project in {".", ".."}
        or not _SAFE_PROJECT_NAME_RE.fullmatch(project)
    ):
        raise MobileHelperBridgeError(
            "project must be a known SASE project name, not a path"
        )
    return project


def helper_result(status: str, message: str) -> dict[str, object]:
    return {
        "status": status,
        "message": message,
        "warnings": [],
        "skipped": [],
        "partial_failure_count": None,
    }


def skip_record(target: str | None, reason: str) -> dict[str, str | None]:
    return {"target": target, "reason": reason}


def path_display(path: object) -> str | None:
    if path is None:
        return None
    return str(path)


def sase_home() -> Path:
    return Path(os.environ.get("SASE_HOME") or Path.home() / ".sase").expanduser()
