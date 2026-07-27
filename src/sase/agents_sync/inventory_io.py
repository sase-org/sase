"""Bounded parsing and normalization helpers for agent inventory."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from sase.agents_sync.inventory_models import InventoryRelationship
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_io import (
    MAX_JSON_BYTES,
    MAX_OUTPUT_VARIABLES,
    MAX_OUTPUT_VARIABLE_VALUE_BYTES,
    MAX_TEXT_BYTES,
    V2_METADATA_FIELDS,
    is_valid_output_variable_key,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
)


def portable_metadata(raw: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    metadata = {
        key: raw[key]
        for key in V2_METADATA_FIELDS
        if key != "output_variables" and key in raw and raw[key] is not None
    }
    try:
        json.dumps(metadata, allow_nan=False)
    except (TypeError, ValueError):
        metadata = {
            key: value
            for key, value in metadata.items()
            if isinstance(value, (str, int, float, bool, list, dict))
        }
    output_variables = _portable_output_variables(raw.get("output_variables"))
    if output_variables:
        metadata["output_variables"] = output_variables
    return tuple(sorted(metadata.items()))


def _portable_output_variables(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in sorted(value.items(), key=lambda row: str(row[0])):
        if (
            len(result) >= MAX_OUTPUT_VARIABLES
            or not is_valid_output_variable_key(key)
            or not isinstance(item, str)
        ):
            continue
        try:
            size = len(item.encode("utf-8"))
        except UnicodeEncodeError:
            continue
        if size <= MAX_OUTPUT_VARIABLE_VALUE_BYTES:
            result[key] = item
    return result


def read_json_object(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise AgentsSyncFormatError(f"{path.name} exceeds the byte limit")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise AgentsSyncFormatError(f"missing {path.name}") from None
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise AgentsSyncFormatError(f"{path.name} must be a JSON object")
    return value


def read_text_bytes(path: Path) -> bytes | None:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_TEXT_BYTES:
            raise AgentsSyncFormatError(f"{path.name} exceeds the byte limit")
        payload = path.read_bytes()
        payload.decode("utf-8")
        return payload
    except AgentsSyncFormatError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read {path.name}: {exc}") from exc


def embedded_workflows_payload(path: Path) -> bytes | None:
    """Return bounded canonical embedded-workflow restart metadata."""

    value = _read_json_value(path)
    if value is None:
        return None
    if not isinstance(value, list):
        raise AgentsSyncFormatError("embedded_workflows.json must contain a JSON list")
    portable: list[dict[str, object]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise AgentsSyncFormatError(
                f"embedded_workflows.json entry {index} must be an object"
            )
        name = raw.get("name")
        args = raw.get("args")
        tags = raw.get("tags")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(args, dict)
            or not isinstance(tags, list)
            or not all(isinstance(tag, str) for tag in tags)
        ):
            raise AgentsSyncFormatError(
                f"embedded_workflows.json entry {index} has an invalid shape"
            )
        portable.append({"name": name, "args": args, "tags": tags})
    payload = (
        json.dumps(
            portable,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    if len(payload) > MAX_JSON_BYTES:
        raise AgentsSyncFormatError("embedded_workflows.json exceeds the byte limit")
    return payload


def _read_json_value(path: Path) -> object | None:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_JSON_BYTES:
            raise AgentsSyncFormatError(f"{path.name} exceeds the byte limit")
        return json.loads(path.read_text(encoding="utf-8"))
    except AgentsSyncFormatError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read {path.name}: {exc}") from exc


def prompt_steps_payload(artifact: Path) -> bytes | None:
    """Archive restart-relevant prompt-step markers without host paths."""

    rows: list[dict[str, object]] = []
    for path in sorted(artifact.glob("prompt_step_*.json"), key=lambda item: item.name):
        value = read_json_object(path)
        assert value is not None
        portable = {
            key: value[key]
            for key in (
                "status",
                "workflow_name",
                "step_name",
                "step_type",
                "step_source",
                "output",
                "step_index",
                "total_steps",
                "parent_step_index",
                "parent_total_steps",
                "hidden",
                "embedded_workflow_name",
                "is_pre_prompt_step",
            )
            if key in value
        }
        rows.append({"file_name": path.name, "marker": portable})
    if not rows:
        return None
    payload = (
        json.dumps(
            rows,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    if len(payload) > MAX_JSON_BYTES:
        raise AgentsSyncFormatError(
            "prompt-step restart payload exceeds the byte limit"
        )
    return payload


def read_referenced_text(*values: object) -> bytes | None:
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        payload = read_text_bytes(Path(value).expanduser())
        if payload is not None:
            return payload
    return None


def inline_text(raw: dict[str, Any], keys: tuple[str, ...]) -> bytes | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value:
            payload = value.encode("utf-8")
            if len(payload) > MAX_TEXT_BYTES:
                raise AgentsSyncFormatError(f"{key} exceeds the byte limit")
            return payload
    return None


def canonical_local_name(name: str, identity: AgentIdentitySnapshot) -> str:
    normalized = normalize_owned_agent_name(name, identity)
    normalized = normalize_agent_archive_name(normalized)
    if (
        not normalized
        or "/" in normalized
        or "\\" in normalized
        or "\x00" in normalized
    ):
        raise AgentsSyncFormatError(f"unsafe local agent name: {name!r}")
    return normalized


def canonical_optional_name(
    value: object, identity: AgentIdentitySnapshot
) -> str | None:
    name = text(value)
    return canonical_local_name(name, identity) if name else None


def source_run_id(project: str, workflow: str, durable: str) -> str:
    digest = hashlib.sha256(
        "\x00".join((project, workflow, durable)).encode("utf-8")
    ).hexdigest()
    return f"run-{digest[:32]}"


def time_text(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    return None


def is_imported(meta: dict[str, Any], done: dict[str, Any] | None) -> bool:
    values = (meta, done or {})
    return any(
        any(
            row.get(key) is not None
            for key in (
                "imported_from_machine",
                "imported_digest",
                "imported_source_owner",
                "imported_snapshot_digest",
                "imported_transaction_key",
                "source_owner",
            )
        )
        for row in values
    )


def dedupe_relationships(
    rows: list[InventoryRelationship],
) -> tuple[InventoryRelationship, ...]:
    return tuple(
        sorted(
            set(rows),
            key=lambda item: (item.kind, item.target_kind, item.target),
        )
    )


def require_owner(identity: AgentIdentitySnapshot) -> AgentOwnerIdentity:
    if identity.owner is None:
        raise AgentsSyncFormatError("owner identity is not configured")
    return identity.owner


def text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
