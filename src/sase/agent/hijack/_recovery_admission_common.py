"""Shared admission constants and helpers for keep-work recovery.

This private module owns every helper needed by more than one recovery
admission submodule. Helpers carry public names so sibling submodules can
import them without touching a ``_``-prefixed name across files.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack.recovery_successor import RecoveryLineage

RECOVERY_ADMISSION_SOURCE_SURFACE = "agent_hijack_recovery"
RECOVERY_ADMISSION_METADATA_KEY = "hijack_recovery_descriptor"
RECOVERY_ADMISSION_SCHEMA_VERSION = 1
RECOVERY_REQUESTS_SUBDIR = "hijack_recovery_requests"
TYPED_LAUNCHES_SUBDIR = "typed_launches"
LOGICAL_ID = "hijack-recovery"
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z")

__all__ = [
    "LOGICAL_ID",
    "RECOVERY_ADMISSION_METADATA_KEY",
    "RECOVERY_ADMISSION_SCHEMA_VERSION",
    "RECOVERY_ADMISSION_SOURCE_SURFACE",
    "RECOVERY_REQUESTS_SUBDIR",
    "TYPED_LAUNCHES_SUBDIR",
    "bundle_dir_for_request",
    "canonical_json",
    "descriptor_digest",
    "descriptor_from_data",
    "is_hijack_recovery_typed_request",
    "positive_int",
    "read_prepared_recovery_descriptor",
    "record_owns_descriptor",
    "required_string",
    "split_model_effort",
    "string_or_none",
    "validate_descriptor_fields",
    "validate_request_id",
]


def is_hijack_recovery_typed_request(data: Mapping[str, Any]) -> bool:
    return str(data.get("source_surface") or "") == RECOVERY_ADMISSION_SOURCE_SURFACE


def required_string(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"recovery admission descriptor requires {key}")
    return result.strip()


def string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def validate_request_id(request_id: str) -> None:
    if not _REQUEST_ID_PATTERN.fullmatch(request_id):
        raise ValueError("recovery admission request id is not a safe path component")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def descriptor_digest(descriptor: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in descriptor.items()
        if key
        not in {
            "descriptor_digest",
            "dispatch_fingerprint",
            "logical_id",
            "plan_digest",
            "typed_plan",
        }
    }
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def split_model_effort(target: str) -> tuple[str, str | None]:
    from sase.macro.effort import split_model_effort

    model, effort = split_model_effort(target)
    return str(model), str(effort) if effort is not None else None


def validate_descriptor_fields(descriptor: Mapping[str, Any]) -> None:
    if descriptor.get("schema_version") != RECOVERY_ADMISSION_SCHEMA_VERSION:
        raise ValueError("unsupported recovery admission descriptor schema")
    for field in (
        "hijack_id",
        "action",
        "target",
        "prompt",
        "reserved_successor_name",
        "session_base",
        "project_name",
        "workspace_dir",
        "launch_identity",
        "admission_request_id",
        "launch_submitted_at",
    ):
        required_string(descriptor, field)
    validate_request_id(required_string(descriptor, "admission_request_id"))
    workspace_num = descriptor.get("workspace_num")
    if (
        not isinstance(workspace_num, int)
        or isinstance(workspace_num, bool)
        or workspace_num <= 0
    ):
        raise ValueError("recovery admission requires a positive fixed workspace")
    if positive_int(descriptor.get("resolver_pid")) is None:
        raise ValueError("recovery admission requires a positive resolver pid")
    attempt_revision = descriptor.get("attempt_revision")
    if (
        not isinstance(attempt_revision, int)
        or isinstance(attempt_revision, bool)
        or attempt_revision <= 0
    ):
        raise ValueError("recovery admission requires a positive attempt revision")
    lineage = descriptor.get("lineage")
    if not isinstance(lineage, Mapping):
        raise ValueError("recovery admission descriptor has no lineage")
    RecoveryLineage(**dict(lineage))


def descriptor_from_data(data: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = data.get("unit_dispatch_metadata")
    if not isinstance(metadata, Mapping):
        return None
    descriptor = metadata.get(RECOVERY_ADMISSION_METADATA_KEY)
    if not isinstance(descriptor, Mapping):
        return None
    return dict(descriptor)


def record_owns_descriptor(
    record: Mapping[str, Any], descriptor: Mapping[str, Any]
) -> bool:
    expected = {
        "state": "resolving",
        "hijack_id": descriptor.get("hijack_id"),
        "resolution_action": descriptor.get("action"),
        "reserved_successor_name": descriptor.get("reserved_successor_name"),
        "concrete_target_model": descriptor.get("target"),
        "launch_identity": descriptor.get("launch_identity"),
        "admission_request_id": descriptor.get("admission_request_id"),
        "admission_identity": descriptor.get("dispatch_fingerprint"),
        "workspace_num": descriptor.get("workspace_num"),
        "workspace_dir": descriptor.get("workspace_dir"),
        "project_file": descriptor.get("project_file"),
        "expected_claim_owner_pid": descriptor.get("expected_claim_owner_pid"),
        "resolver_pid": descriptor.get("resolver_pid"),
        "resolver_process_identity_token": descriptor.get(
            "resolver_process_identity_token"
        ),
    }
    return all(record.get(key) == value for key, value in expected.items())


def bundle_dir_for_request(request_id: str) -> Path:
    from sase.core.paths import sase_subdir

    validate_request_id(request_id)
    return sase_subdir(TYPED_LAUNCHES_SUBDIR) / request_id


def read_prepared_recovery_descriptor(request_id: str) -> dict[str, Any] | None:
    """Read one inert or submitted recovery descriptor by its durable id."""
    from sase.agent.launch_admission_store import read_json
    from sase.core.paths import sase_subdir

    validate_request_id(request_id)
    path = sase_subdir(RECOVERY_REQUESTS_SUBDIR) / f"{request_id}.json"
    payload = read_json(path)
    if payload is None:
        return None
    return payload
