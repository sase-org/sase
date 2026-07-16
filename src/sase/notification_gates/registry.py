"""Registered typed projections and validation for notification gates."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.notification_gates.models import GateChoice, GateError, GateSpec


@dataclass(frozen=True)
class GateAdapter:
    """The stable typed transport and legacy-file shape for one gate kind."""

    kind: str
    action: str
    pending_action_kind: str
    sender: str
    request_filename: str
    response_filename: str
    legacy_directory_key: str
    auto_policy: str

    def resolve_auto_choice(
        self, choices: tuple[GateChoice, ...], argument: str | None
    ) -> GateChoice:
        """Interpret the common opaque auto argument for this kind."""
        by_id = {choice.id: choice for choice in choices}
        if self.auto_policy == "forbidden":
            raise GateError(
                "auto_not_supported",
                "auto",
                f"automatic resolution is not supported for {self.kind} gates",
            )
        if self.auto_policy == "first":
            if argument not in (None, "", "first"):
                raise GateError(
                    "invalid_auto_argument",
                    "auto.argument",
                    f"unsupported {self.kind} auto argument: {argument}",
                )
            return choices[0]

        allowed = {
            "plan": {None, "", "plan", "tale"},
            "epic_plan": {None, "", "epic", "epic_plan"},
        }[self.kind]
        if argument not in allowed:
            raise GateError(
                "invalid_auto_argument",
                "auto.argument",
                f"unsupported {self.kind} auto argument: {argument}",
            )
        preferred = (
            ("tale", "plan", "approve")
            if self.kind == "plan"
            else ("epic", "epic_plan", "approve")
        )
        for choice_id in preferred:
            if choice_id in by_id:
                return by_id[choice_id]
        raise GateError(
            "invalid_auto_choice",
            "choices",
            f"{self.kind} auto resolution requires an approval choice",
        )

    def apply_side_effects(
        self, *, bundle_path: Path, response: Mapping[str, Any]
    ) -> None:
        """Apply adapter-declared host effects after terminal persistence."""
        del bundle_path, response

    def validate_edited_resource(self, *, path: Path) -> None:
        """Validate an editable target before advancing its review revision."""
        del path

    def regenerate_previews(self, *, bundle_path: Path) -> None:
        """Regenerate adapter-owned previews after an edit."""
        del bundle_path


_ADAPTERS = (
    GateAdapter(
        kind="plan",
        action="PlanApproval",
        pending_action_kind="plan_approval",
        sender="plan",
        request_filename="plan_request.json",
        response_filename="plan_response.json",
        legacy_directory_key="response_dir",
        auto_policy="approval",
    ),
    GateAdapter(
        kind="epic_plan",
        action="EpicApproval",
        pending_action_kind="epic_approval",
        sender="epic",
        request_filename="plan_request.json",
        response_filename="plan_response.json",
        legacy_directory_key="response_dir",
        auto_policy="approval",
    ),
    GateAdapter(
        kind="question",
        action="UserQuestion",
        pending_action_kind="user_question",
        sender="question",
        request_filename="question_request.json",
        response_filename="question_response.json",
        legacy_directory_key="response_dir",
        auto_policy="first",
    ),
    GateAdapter(
        kind="launch",
        action="LaunchApproval",
        pending_action_kind="launch_approval",
        sender="launch",
        request_filename="launch_request.json",
        response_filename="launch_response.json",
        legacy_directory_key="response_dir",
        auto_policy="forbidden",
    ),
    GateAdapter(
        kind="hitl",
        action="HITL",
        pending_action_kind="hitl",
        sender="hitl",
        request_filename="hitl_request.json",
        response_filename="hitl_response.json",
        legacy_directory_key="artifacts_dir",
        auto_policy="forbidden",
    ),
)

_BY_KIND = {adapter.kind: adapter for adapter in _ADAPTERS}
_BY_ACTION = {adapter.action: adapter for adapter in _ADAPTERS}
_KIND_ALIASES = {
    "plan_approval": "plan",
    "epic": "epic_plan",
    "epic_approval": "epic_plan",
    "user_question": "question",
    "launch_approval": "launch",
}

PRIVILEGED_GATE_ACTIONS = frozenset(_BY_ACTION)


def adapter_for_kind(kind: str) -> GateAdapter:
    """Return the registered adapter for *kind*."""
    canonical = _KIND_ALIASES.get(kind, kind)
    try:
        return _BY_KIND[canonical]
    except KeyError as exc:
        raise GateError(
            "unknown_gate_kind", "kind", f"unregistered gate kind: {kind}"
        ) from exc


def adapter_for_action(action: str | None) -> GateAdapter | None:
    """Return the registered adapter projected by a notification action."""
    if action is None:
        return None
    return _BY_ACTION.get(action)


def registered_gate_kinds() -> tuple[str, ...]:
    """Return canonical registered kind identifiers."""
    return tuple(adapter.kind for adapter in _ADAPTERS)


def validate_gate_spec(spec: GateSpec, adapter: GateAdapter) -> None:
    """Validate cross-field ownership and adapter invariants."""
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

    choice_ids = [choice.id for choice in spec.choices]
    _reject_duplicates(choice_ids, "choices", "choice id")
    operation_ids = [operation.id for operation in spec.operations]
    _reject_duplicates(operation_ids, "operations", "operation id")
    overlap = set(choice_ids) & set(operation_ids)
    if overlap:
        raise GateError(
            "duplicate_identifier",
            "operations",
            f"choice and operation ids overlap: {', '.join(sorted(overlap))}",
        )

    for choice in spec.choices:
        command_path = choice.command.argv[0]
        resource = resources.get(command_path)
        if resource is None or resource.role != "command" or not resource.executable:
            raise GateError(
                "unowned_command",
                f"choices.{choice.id}.command",
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
    if spec.auto.enabled:
        adapter.resolve_auto_choice(spec.choices, spec.auto.argument)


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


__all__ = [
    "PRIVILEGED_GATE_ACTIONS",
    "GateAdapter",
    "adapter_for_action",
    "adapter_for_kind",
    "registered_gate_kinds",
    "validate_gate_spec",
]
