"""Repeatable non-terminal gate actions.

A gate action is a control a reviewer may run **as many times as they need**
and that **never answers the gate**. It exists so a reviewer can iterate
toward a decision — edit the plan until it validates, read a diff, run a dry
run — instead of being forced to answer or cancel.

Two kinds are declared:

``edit_file``
    Open an editable resource in an editor. ``edit_target: "origin"`` opens
    the durable file the resource was copied from instead of the bundle copy.

``run_command``
    Run an owned bundle command and show the reviewer its output. The command
    may rewrite only the editable resources it declares under ``targets``.

The array is still named ``operations`` on the wire, which is what keeps this
additive within ``schema_version: 3``; surfaces present them as **Actions**.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.notification_gates.action_keys import validate_gate_action_key
from sase.notification_gates.model_options import GateCommand
from sase.notification_gates.model_validation import (
    GateError,
    check_json_schema,
    check_schema_bounds,
    json_object,
    reject_unknown_fields,
    stamp_schema_dialect,
    string_list,
    validate_icon,
    validate_identifier,
    validate_label,
    validate_relative_path,
)

GATE_ACTION_KINDS = ("edit_file", "run_command")
GATE_ACTION_DISPLAYS = ("markdown", "text", "json", "none")
GATE_ACTION_EDIT_TARGETS = ("resource", "origin")

_MAX_ACTION_DESCRIPTION_LENGTH = 400
_COMMON_FIELDS = {"id", "kind", "label", "icon", "key", "description"}
_EDIT_FILE_FIELDS = {"target", "edit_target"}
_RUN_COMMAND_FIELDS = {
    "command",
    "display",
    "input_schema",
    "result_schema",
    "targets",
}


@dataclass(frozen=True)
class GateOperation:
    """One repeatable action a local gate surface renders and runs."""

    id: str
    kind: str
    label: str
    icon: str | None = None
    key: str | None = None
    description: str | None = None
    target: str | None = None
    edit_target: str = "resource"
    command: GateCommand | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    result_schema: dict[str, Any] = field(default_factory=dict)
    targets: tuple[str, ...] = ()
    display: str = "text"

    @classmethod
    def from_mapping(cls, value: object, index: int) -> GateOperation:
        target_field = f"operations[{index}]"
        data = json_object(value, target_field)
        kind = data.get("kind")
        if kind not in GATE_ACTION_KINDS:
            raise GateError(
                "invalid_operation",
                f"{target_field}.kind",
                "operation kind must be one of: " + ", ".join(GATE_ACTION_KINDS),
            )
        reject_unknown_fields(
            data,
            _COMMON_FIELDS
            | (_EDIT_FILE_FIELDS if kind == "edit_file" else _RUN_COMMAND_FIELDS),
            target_field,
        )
        operation_id = validate_identifier(data.get("id"), f"{target_field}.id")
        common = {
            "id": operation_id,
            "kind": kind,
            "label": _operation_label(data.get("label"), operation_id, target_field),
            "icon": validate_icon(data.get("icon"), f"{target_field}.icon"),
            "key": validate_gate_action_key(data.get("key"), f"{target_field}.key"),
            "description": _operation_description(
                data.get("description"), target_field
            ),
        }
        if kind == "edit_file":
            return cls(
                **common,
                target=validate_relative_path(
                    data.get("target"), f"{target_field}.target"
                ),
                edit_target=_edit_target(data.get("edit_target"), target_field),
            )
        declared_input_schema = json_object(
            data.get("input_schema", {}), f"{target_field}.input_schema"
        )
        declared_result_schema = json_object(
            data.get("result_schema", {}), f"{target_field}.result_schema"
        )
        check_json_schema(declared_input_schema, f"{target_field}.input_schema")
        check_json_schema(declared_result_schema, f"{target_field}.result_schema")
        input_schema = stamp_schema_dialect(declared_input_schema)
        result_schema = stamp_schema_dialect(declared_result_schema)
        check_schema_bounds(input_schema, f"{target_field}.input_schema")
        return cls(
            **common,
            command=GateCommand.from_value(
                data.get("command"), f"{target_field}.command"
            ),
            input_schema=input_schema,
            result_schema=result_schema,
            targets=_action_targets(data.get("targets", []), target_field),
            display=_display_format(data.get("display"), target_field),
        )

    def to_dict(self) -> dict[str, Any]:
        common: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "icon": self.icon,
            "key": self.key,
            "description": self.description,
        }
        if self.kind == "edit_file":
            return {**common, "target": self.target, "edit_target": self.edit_target}
        assert self.command is not None
        return {
            **common,
            "command": self.command.to_dict(),
            "input_schema": self.input_schema,
            "result_schema": self.result_schema,
            "targets": list(self.targets),
            "display": self.display,
        }


@dataclass(frozen=True)
class GateActionDisplay:
    """The closed display record a surface reads out of an action's result.

    Everything else the command returns stays in the result and the journal;
    a renderer never has to understand an action's own result schema.
    """

    summary: str | None = None
    body: str | None = None
    refresh: bool = False

    @classmethod
    def from_result(cls, value: object) -> GateActionDisplay:
        """Project the display record, ignoring every other result field."""
        if not isinstance(value, Mapping):
            return cls()
        raw_summary = value.get("summary")
        raw_body = value.get("body")
        summary = raw_summary.strip() if isinstance(raw_summary, str) else None
        body = raw_body if isinstance(raw_body, str) and raw_body else None
        return cls(
            summary=summary or None, body=body, refresh=value.get("refresh") is True
        )


def gate_operation_from_envelope(
    envelope: Mapping[str, Any], operation_id: str, *, kind: str | None = None
) -> GateOperation:
    """Return one declared action from an envelope.

    ``kind`` restricts the lookup to one action kind, which is what an
    execution path wants: running an ``edit_file`` action as a command would
    be a category error. A dispatcher that has yet to learn the kind -- the
    headless ``sase gate act`` -- passes ``None`` and branches on the result.
    """
    raw_operations = envelope.get("operations")
    if not isinstance(raw_operations, list):
        raise GateError("invalid_request", "operations", "operations are missing")
    for index, raw in enumerate(raw_operations):
        if not isinstance(raw, Mapping) or raw.get("id") != operation_id:
            continue
        operation = GateOperation.from_mapping(raw, index)
        if kind is not None and operation.kind != kind:
            raise GateError(
                "invalid_operation",
                operation_id,
                f"action {operation_id} is not a {kind} action",
            )
        return operation
    raise GateError(
        "unknown_operation", operation_id, f"gate declares no action: {operation_id}"
    )


def _operation_label(value: object, operation_id: str, target_field: str) -> str:
    if value is None:
        readable = operation_id.replace("_", " ").replace("-", " ")
        return readable[:1].upper() + readable[1:]
    return validate_label(value, f"{target_field}.label")


def _operation_description(value: object, target_field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GateError(
            "invalid_operation",
            f"{target_field}.description",
            f"{target_field}.description must be a non-empty string",
        )
    normalized = value.strip()
    if len(normalized) > _MAX_ACTION_DESCRIPTION_LENGTH:
        raise GateError(
            "invalid_operation",
            f"{target_field}.description",
            f"{target_field}.description must be at most "
            f"{_MAX_ACTION_DESCRIPTION_LENGTH} characters",
        )
    return normalized


def _edit_target(value: object, target_field: str) -> str:
    if value is None:
        return "resource"
    if value not in GATE_ACTION_EDIT_TARGETS:
        raise GateError(
            "invalid_operation",
            f"{target_field}.edit_target",
            "edit_target must be one of: " + ", ".join(GATE_ACTION_EDIT_TARGETS),
        )
    return str(value)


def _display_format(value: object, target_field: str) -> str:
    if value is None:
        return "text"
    if value not in GATE_ACTION_DISPLAYS:
        raise GateError(
            "invalid_operation",
            f"{target_field}.display",
            "display must be one of: " + ", ".join(GATE_ACTION_DISPLAYS),
        )
    return str(value)


def _action_targets(value: object, target_field: str) -> tuple[str, ...]:
    raw = string_list(value, f"{target_field}.targets")
    targets = tuple(
        validate_relative_path(item, f"{target_field}.targets[{index}]")
        for index, item in enumerate(raw)
    )
    if len(set(targets)) != len(targets):
        raise GateError(
            "invalid_operation",
            f"{target_field}.targets",
            "action targets must be unique",
        )
    return targets


__all__ = [
    "GATE_ACTION_DISPLAYS",
    "GATE_ACTION_EDIT_TARGETS",
    "GATE_ACTION_KINDS",
    "GateActionDisplay",
    "GateOperation",
    "gate_operation_from_envelope",
]
