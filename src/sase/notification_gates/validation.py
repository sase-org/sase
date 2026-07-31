"""Cross-field ownership and validation for notification gates."""

from __future__ import annotations

import json
from collections.abc import Mapping

from sase.notification_gates.adapters import GateAdapter
from sase.notification_gates.kind_validation import (
    validate_launch_spec,
    validate_plan_spec,
    validate_question_spec,
    validate_task_triage_spec,
)
from sase.notification_gates.models import (
    GATE_REQUEST_SCHEMA_VERSION,
    GateError,
    GateSpec,
    validate_icon,
)


def validate_gate_spec(spec: GateSpec, adapter: GateAdapter) -> None:
    """Validate cross-field ownership and adapter invariants."""
    if spec.schema_version != GATE_REQUEST_SCHEMA_VERSION:
        raise GateError(
            "unsupported_schema",
            "schema_version",
            f"new gate requests require schema_version {GATE_REQUEST_SCHEMA_VERSION}",
        )
    resource_paths = [resource.path for resource in spec.resources]
    _reject_duplicates(resource_paths, "resources", "resource path")
    reserved_roots = {
        ".creation.json",
        ".creation_result.json",
        ".response.lock",
        "cancellation.json",
        "request.json",
        "response.json",
    }
    for path in resource_paths:
        if path.split("/", 1)[0] in reserved_roots:
            raise GateError(
                "reserved_resource_path",
                path,
                f"resource path is reserved by the gate service: {path}",
            )
    resources = {resource.path: resource for resource in spec.resources}

    option_ids = [option.id for option in spec.options]
    _reject_duplicates(option_ids, "options", "option id")
    operation_ids = [operation.id for operation in spec.operations]
    _reject_duplicates(operation_ids, "operations", "operation id")
    overlap = set(option_ids) & set(operation_ids)
    if overlap:
        raise GateError(
            "duplicate_identifier",
            "operations",
            f"option and operation ids overlap: {', '.join(sorted(overlap))}",
        )

    for option in spec.options:
        command_path = option.command.argv[0]
        resource = resources.get(command_path)
        if resource is None or resource.role != "command" or not resource.executable:
            raise GateError(
                "unowned_command",
                f"options.{option.id}.command",
                f"command must reference an executable command resource: {command_path}",
            )
    for operation in spec.operations:
        resource = resources.get(operation.target)
        if resource is None or resource.role != "editable":
            raise GateError(
                "unowned_edit_target",
                f"operations.{operation.id}.target",
                f"edit target must reference an editable resource: {operation.target}",
            )

    presentation = spec.presentation
    declared_action = presentation.get("action")
    if declared_action is not None and declared_action != adapter.action:
        raise GateError(
            "action_kind_mismatch",
            "presentation.action",
            f"{adapter.kind} gates project as {adapter.action}",
        )
    sender = presentation.get("sender", adapter.sender)
    if not isinstance(sender, str) or not sender.strip():
        raise GateError(
            "invalid_presentation",
            "presentation.sender",
            "notification sender must be a non-empty string",
        )
    validate_icon(presentation.get("icon"), "presentation.icon")
    _validate_string_or_list(presentation.get("notes", []), "presentation.notes")
    _validate_string_or_list(presentation.get("tags", []), "presentation.tags")
    files = _validate_string_or_list(
        presentation.get("files", []), "presentation.files"
    )
    for path in files:
        if path not in resources:
            raise GateError(
                "unowned_attachment",
                "presentation.files",
                f"notification attachment is not a bundle resource: {path}",
            )
    preview = presentation.get("preview")
    if preview is not None:
        if not isinstance(preview, str) or preview not in resources:
            raise GateError(
                "unowned_preview",
                "presentation.preview",
                "preview must reference a bundle resource",
            )
        if resources[preview].role != "preview":
            raise GateError(
                "invalid_preview",
                "presentation.preview",
                "preview must reference a preview resource",
            )
    action_data = presentation.get("action_data", {})
    if not isinstance(action_data, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in action_data.items()
    ):
        raise GateError(
            "invalid_presentation",
            "presentation.action_data",
            "action_data must be an object of string values",
        )
    protected = {
        "bundle_path",
        "request_id",
        "request_kind",
        "request_path",
        "response_path",
        adapter.legacy_directory_key,
    }
    overwritten = protected & set(action_data)
    if overwritten:
        raise GateError(
            "reserved_action_data",
            "presentation.action_data",
            f"reserved action_data key(s): {', '.join(sorted(overwritten))}",
        )

    silent = presentation.get("silent", False)
    if not isinstance(silent, bool):
        raise GateError(
            "invalid_presentation",
            "presentation.silent",
            "silent must be a boolean",
        )
    try:
        json.dumps(spec.payload, allow_nan=False)
        json.dumps(spec.producer, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise GateError(
            "invalid_request",
            "payload",
            "payload and producer must contain JSON values",
        ) from exc
    if adapter.kind == "launch":
        validate_launch_spec(spec)
    if adapter.kind == "question":
        validate_question_spec(spec)
    if adapter.kind == "task_triage":
        validate_task_triage_spec(spec)
    if adapter.kind in {"plan", "epic_plan"}:
        validate_plan_spec(spec, adapter)
    expected_primary = {
        "plan": ("approve", "commit"),
        "epic_plan": ("approve",),
        "question": ("submit",),
        "launch": ("approve",),
        "hitl": ("accept",),
        "task_triage": ("launch",),
    }.get(adapter.kind)
    if expected_primary is not None and spec.primary_branch != expected_primary:
        raise GateError(
            "invalid_primary_branch",
            "primary_branch",
            f"{adapter.kind} gates require primary branch: "
            + ", ".join(expected_primary),
        )
    if spec.auto.enabled:
        adapter.resolve_auto_selection(spec, spec.auto.argument)
        adapter.automatic_input(spec)


def _reject_duplicates(values: list[str], target: str, label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise GateError(
            "duplicate_identifier",
            target,
            f"duplicate {label}(s): {', '.join(sorted(duplicates))}",
        )


def _validate_string_or_list(value: object, target: str) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise GateError(
        "invalid_presentation", target, f"{target} must be a string or string array"
    )
