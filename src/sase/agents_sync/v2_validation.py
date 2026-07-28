"""Shared limits and strict validation helpers for v2 sidecar payloads."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_models import V2ProjectIdentity, V2_SCHEMA_VERSION
from sase.core.agent_identity_facade import AgentOwnerIdentity, validate_agent_owner

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_RUNS = 4_096
MAX_CONTAINERS = 2_048
MAX_RELATIONSHIPS = 16_384
MAX_FILES = 32_768
MAX_PAYLOAD_BYTES = 128 * 1024 * 1024
MAX_OUTPUT_VARIABLES = 256
MAX_OUTPUT_VARIABLE_VALUE_BYTES = 8_192

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OUTPUT_VARIABLE_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

V2_METADATA_FIELDS = frozenset(
    {
        "agent_clan",
        "agent_clan_generation",
        "agent_family",
        "agent_family_role",
        "approve",
        "bead_id",
        "changespec_name",
        "cl_name",
        "clan_summary",
        "clan_tribe",
        "epic_bead_id",
        "hidden",
        "llm_provider",
        "model",
        "output_variables",
        "phase_bead_id",
        "plan",
        "reasoning_effort",
        "role_suffix",
        "tribe",
        "vcs_provider",
        "workflow_name",
    }
)


def validate_component(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AgentsSyncFormatError(f"{label} must be a non-empty string")
    if value in {".", ".."} or value.startswith("."):
        raise AgentsSyncFormatError(f"unsafe {label}: {value!r}")
    if len(value.encode("utf-8")) > 255:
        raise AgentsSyncFormatError(f"{label} is too long")
    if "\x00" in value or "/" in value or "\\" in value:
        raise AgentsSyncFormatError(f"unsafe {label}: {value!r}")
    if Path(value).name != value:
        raise AgentsSyncFormatError(f"unsafe {label}: {value!r}")
    return value


def validate_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AgentsSyncFormatError("publication path must be a non-empty string")
    if "\\" in value or "\x00" in value or "//" in value:
        raise AgentsSyncFormatError(f"unsafe publication path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AgentsSyncFormatError(f"unsafe publication path: {value!r}")
    for part in path.parts:
        if part != ".gitkeep":
            validate_component(part, label="publication path component")
    return value


def is_valid_output_variable_key(value: object) -> bool:
    """Return whether a value is a portable output-variable key."""

    return (
        isinstance(value, str) and _OUTPUT_VARIABLE_KEY_RE.fullmatch(value) is not None
    )


def validate_output_variables(metadata: Mapping[str, Any], *, label: str) -> None:
    """Validate the strict output-variable shape in portable metadata."""

    if "output_variables" not in metadata:
        return
    raw = metadata["output_variables"]
    if not isinstance(raw, dict):
        raise AgentsSyncFormatError(f"{label} output_variables must be a JSON object")
    if len(raw) > MAX_OUTPUT_VARIABLES:
        raise AgentsSyncFormatError(
            f"{label} output_variables exceeds the {MAX_OUTPUT_VARIABLES} entry limit"
        )
    for key, value in raw.items():
        if not is_valid_output_variable_key(key):
            raise AgentsSyncFormatError(
                f"{label} output_variables has an invalid key: {key!r}"
            )
        if not isinstance(value, str):
            raise AgentsSyncFormatError(
                f"{label} output_variables value for {key!r} must be a string"
            )
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise AgentsSyncFormatError(
                f"{label} output_variables value for {key!r} is not valid UTF-8"
            ) from exc
        if size > MAX_OUTPUT_VARIABLE_VALUE_BYTES:
            raise AgentsSyncFormatError(
                f"{label} output_variables value for {key!r} exceeds "
                f"{MAX_OUTPUT_VARIABLE_VALUE_BYTES} UTF-8 bytes"
            )


def read_json(path: Path, label: str) -> object:
    try:
        size = path.stat().st_size
        if size > MAX_JSON_BYTES:
            raise AgentsSyncFormatError(f"{label} exceeds the byte limit")
        return json.loads(path.read_text(encoding="utf-8"))
    except AgentsSyncFormatError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read {label} at {path}: {exc}") from exc


def json_from_bytes(payload: bytes, label: str) -> object:
    if len(payload) > MAX_JSON_BYTES:
        raise AgentsSyncFormatError(f"{label} exceeds the byte limit")
    try:
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not decode {label}: {exc}") from exc


def decode_owner_identity(value: object, label: str) -> AgentOwnerIdentity:
    row = exact_object(value, label, {"username", "machine_name"})
    owner = AgentOwnerIdentity(
        validate_component(row["username"], label="username"),
        validate_component(row["machine_name"], label="machine"),
    )
    try:
        validate_agent_owner(owner)
    except (ValueError, RuntimeError) as exc:
        raise AgentsSyncFormatError(f"invalid {label}: {exc}") from exc
    return owner


def decode_project_identity(value: object) -> V2ProjectIdentity:
    row = exact_object(value, "project identity", {"key", "name"})
    key = validate_component(row["key"], label="project key")
    name = row["name"]
    if not isinstance(name, str) or not name or "\x00" in name:
        raise AgentsSyncFormatError("project name must be a non-empty string")
    return V2ProjectIdentity(key, name)


def validate_schema(data: Mapping[str, Any], label: str) -> None:
    if data.get("schema_version") != V2_SCHEMA_VERSION:
        raise AgentsSyncFormatError(
            f"unsupported {label} schema_version "
            f"{data.get('schema_version')!r}; expected {V2_SCHEMA_VERSION}"
        )


def exact_object(value: object, label: str, keys: set[str]) -> dict[str, Any]:
    row = json_object(value, label)
    if set(row) != keys:
        raise AgentsSyncFormatError(f"{label} has an invalid shape")
    return row


def json_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AgentsSyncFormatError(f"{label} must be a JSON object")
    return value


def json_list(value: object, label: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise AgentsSyncFormatError(f"{label} must be a list")
    if len(value) > maximum:
        raise AgentsSyncFormatError(f"{label} exceeds the count limit")
    return value


def string_list(value: object, label: str, maximum: int) -> tuple[str, ...]:
    rows = json_list(value, label, maximum)
    if not all(isinstance(item, str) and item for item in rows):
        raise AgentsSyncFormatError(f"{label} must contain non-empty strings")
    return tuple(rows)


def validate_run_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _RUN_ID_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"{label} is invalid")
    return value


def validate_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"{label} is invalid")
    return value


def nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise AgentsSyncFormatError(f"{label} must be a non-negative integer")
    return value


def optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\x00" in value:
        raise AgentsSyncFormatError(f"{label} must be null or a non-empty string")
    return value


def validate_json_value(value: object, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AgentsSyncFormatError(f"{label} contains a non-JSON value") from exc
