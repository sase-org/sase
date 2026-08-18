"""Pure per-option input request model for the gate input panel.

Which fields a selection collects, how text becomes a typed JSON value, and
which option gets which value stay in
:mod:`sase.notification_gates.input_collection`. This module only decides
ownership, conflict, emptiness, and the reviewer-facing collect error.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.notification_gates.input_collection import (
    collected_input_fields,
    option_inputs_from_values,
)
from sase.notification_gates.model_inputs import GateInputField
from sase.notification_gates.model_validation import GateError
from sase.notification_gates.models import GateFeedbackMode, GateOption
from sase.xprompt.models import InputType

#: Properties a raw-schema editor never renders because a sibling control on
#: the modal already collects them (and the executor injects/merges them).
DEFAULT_HOST_COLLECTED_PROPERTIES = frozenset({"feedback"})


class GateBranchInputError(Exception):
    """Inputs could not be collected; the message is reviewer-facing."""


@dataclass(frozen=True)
class GateInputDraft:
    """In-progress panel values, restored when the same selection reopens."""

    values: Mapping[str, str] = field(default_factory=dict)
    raw_text: Mapping[str, str] = field(default_factory=dict)
    feedback: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(self, "raw_text", MappingProxyType(dict(self.raw_text)))


@dataclass(frozen=True)
class GateInputSectionSpec:
    """One selected option's fields and raw-schema editor, in render order."""

    option_id: str
    label: str
    icon: str | None
    fields: tuple[GateInputField, ...]
    shared_with: Mapping[str, tuple[str, ...]]
    raw_properties: tuple[str, ...]
    raw_seed_text: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "shared_with", MappingProxyType(dict(self.shared_with))
        )


@dataclass(frozen=True)
class GateInputRequest:
    """Everything the panel needs to collect one branch selection's inputs."""

    branch_index: int
    branch_label: str
    selected_option_ids: tuple[str, ...]
    options: tuple[GateOption, ...]
    sections: tuple[GateInputSectionSpec, ...]
    feedback_mode: GateFeedbackMode
    feedback_field_owner: str | None
    conflict: str | None
    draft: GateInputDraft

    @property
    def requires_panel(self) -> bool:
        """Whether confirming this selection must open the panel first."""
        if any(section.fields or section.raw_properties for section in self.sections):
            return True
        return self.feedback_mode == "required"

    @property
    def is_empty(self) -> bool:
        """Whether this selection has nothing the panel could collect."""
        return not self.sections and self.feedback_mode == "disabled"


def _schema_extra_properties(
    schema: Mapping[str, Any], host_collected_properties: frozenset[str]
) -> tuple[str, ...]:
    """Schema property names not already collected by a sibling host control."""
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    return tuple(name for name in properties if name not in host_collected_properties)


def _raw_properties(
    option: GateOption, host_collected_properties: frozenset[str]
) -> tuple[str, ...]:
    if option.inputs:
        return ()
    return _schema_extra_properties(option.input_schema, host_collected_properties)


def _seeded_raw_text(
    option: GateOption, host_collected_properties: frozenset[str]
) -> str:
    properties = option.input_schema.get("properties")
    if not isinstance(properties, Mapping):
        return ""
    seeded: dict[str, Any] = {}
    for name, property_schema in properties.items():
        if name in host_collected_properties:
            continue
        if isinstance(property_schema, Mapping) and "default" in property_schema:
            seeded[name] = property_schema["default"]
    if not seeded:
        return ""
    return str(yaml.safe_dump(seeded, sort_keys=False))


def _assign_fields(
    selected: Sequence[GateOption], collected: tuple[GateInputField, ...]
) -> tuple[dict[str, list[GateInputField]], dict[str, dict[str, tuple[str, ...]]]]:
    fields_by_owner: dict[str, list[GateInputField]] = {
        option.id: [] for option in selected
    }
    shared_by_owner: dict[str, dict[str, tuple[str, ...]]] = {
        option.id: {} for option in selected
    }
    for gate_input_field in collected:
        owners = [
            option
            for option in selected
            if any(declared.id == gate_input_field.id for declared in option.inputs)
        ]
        if not owners:
            continue
        first = owners[0]
        fields_by_owner[first.id].append(gate_input_field)
        others = tuple(option.label for option in owners[1:])
        if others:
            shared_by_owner[first.id][gate_input_field.id] = others
    return fields_by_owner, shared_by_owner


def gate_declares_inputs(
    options: Sequence[GateOption], host_collected_properties: frozenset[str]
) -> tuple[bool, bool]:
    """Whether *options* render an Inputs section, and whether any is ``path``.

    Used by the gate modals to decide whether their footer needs an inputs
    hint, without duplicating the panel's own per-selection bookkeeping.
    """
    has_any = False
    has_path = False
    for option in options:
        if option.inputs:
            has_any = True
            if any(field.type is InputType.PATH for field in option.inputs):
                has_path = True
            continue
        if _schema_extra_properties(option.input_schema, host_collected_properties):
            has_any = True
    return has_any, has_path


def build_gate_input_request(
    options: Sequence[GateOption],
    selected_option_ids: Sequence[str],
    *,
    branch_index: int,
    branch_label: str,
    feedback_mode: GateFeedbackMode = "disabled",
    host_collected_properties: Collection[str] = DEFAULT_HOST_COLLECTED_PROPERTIES,
    draft: GateInputDraft | None = None,
) -> GateInputRequest:
    """Build the panel request for one branch's selected options."""
    host = frozenset(host_collected_properties)
    selected_set = set(selected_option_ids)
    selected = tuple(option for option in options if option.id in selected_set)
    conflict: str | None
    try:
        collected = collected_input_fields(selected)
        conflict = None
    except GateError as exc:
        collected = ()
        conflict = str(exc)

    fields_by_owner, shared_by_owner = _assign_fields(selected, collected)
    sections: list[GateInputSectionSpec] = []
    if conflict is None:
        for option in selected:
            raw_properties = _raw_properties(option, host)
            owned = tuple(fields_by_owner.get(option.id, ()))
            if not owned and not raw_properties:
                continue
            sections.append(
                GateInputSectionSpec(
                    option_id=option.id,
                    label=option.label,
                    icon=option.icon,
                    fields=owned,
                    shared_with=shared_by_owner.get(option.id, {}),
                    raw_properties=raw_properties,
                    raw_seed_text=_seeded_raw_text(option, host),
                )
            )

    feedback_field_owner = next(
        (
            option.id
            for option in selected
            if any(field.id == "feedback" for field in option.inputs)
        ),
        None,
    )
    return GateInputRequest(
        branch_index=branch_index,
        branch_label=branch_label,
        selected_option_ids=tuple(option.id for option in selected),
        options=selected,
        sections=tuple(sections),
        feedback_mode=feedback_mode,
        feedback_field_owner=feedback_field_owner,
        conflict=conflict,
        draft=draft if draft is not None else GateInputDraft(),
    )


def collect_option_inputs(
    request: GateInputRequest,
    values: Mapping[str, Any],
    raw_values: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Distribute typed and raw-schema answers to each selected option.

    Raises:
        GateBranchInputError: If a raw editor's YAML cannot be parsed. The
            message is written for the reviewer, who is told which control
            to fix.
    """
    if request.conflict is not None:
        raise GateBranchInputError(request.conflict)
    result: dict[str, dict[str, Any]] = option_inputs_from_values(
        request.options, values
    )
    raw_option_ids = {
        section.option_id for section in request.sections if section.raw_properties
    }
    options_by_id = {option.id: option for option in request.options}
    for option_id in raw_option_ids:
        option = options_by_id[option_id]
        text = raw_values.get(option_id, "")
        try:
            parsed = yaml.safe_load(text) if text.strip() else {}
        except yaml.YAMLError as exc:
            raise GateBranchInputError(
                f"Fix the input for {option.label}: {exc}"
            ) from exc
        result[option_id] = {} if parsed is None else parsed
    return result


__all__ = [
    "DEFAULT_HOST_COLLECTED_PROPERTIES",
    "GateBranchInputError",
    "GateInputDraft",
    "GateInputRequest",
    "GateInputSectionSpec",
    "build_gate_input_request",
    "collect_option_inputs",
    "gate_declares_inputs",
]
