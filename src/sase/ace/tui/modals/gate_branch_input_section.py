"""The per-branch **Inputs** section of the gate branch controls.

A branch's declared fields, its field-conflict message, and its raw-schema
YAML editors are one unit: they render together, validate together, and
produce one option→inputs mapping. Owning them in a widget of their own lets
:class:`~sase.ace.tui.modals.gate_branch_controls.GateBranchControls` deal in
whole branches instead of in per-branch field bookkeeping.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

import yaml  # type: ignore[import-untyped]
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.typed_input_form import TypedFormField, TypedInputForm
from sase.notification_gates.input_collection import (
    collected_input_fields,
    input_arg_for_field,
    option_inputs_from_values,
)
from sase.notification_gates.model_inputs import GateInputField
from sase.notification_gates.model_validation import GateError, first_schema_error
from sase.notification_gates.models import GateOption
from sase.xprompt.models import XPromptValidationError

from .gate_input_panel_model import (
    DEFAULT_HOST_COLLECTED_PROPERTIES,
    GateBranchInputError,
    gate_declares_inputs,
)


def _schema_extra_properties(
    schema: Mapping[str, Any], host_collected_properties: frozenset[str]
) -> tuple[str, ...]:
    """Schema property names not already collected by a sibling host control."""
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    return tuple(name for name in properties if name not in host_collected_properties)


class GateBranchInputSection(Vertical):
    """Declared fields and raw-schema editors for one branch's options."""

    class Validated(Message):
        """A raw editor's validity changed, so its branch's submit may too."""

        def __init__(self, branch_index: int) -> None:
            super().__init__()
            self.branch_index = branch_index

    def __init__(
        self,
        branch_index: int,
        options: Sequence[GateOption],
        *,
        host_collected_properties: frozenset[str],
    ) -> None:
        super().__init__(id=f"gate-inputs-{branch_index}", classes="gate-branch-inputs")
        self.branch_index = branch_index
        self.conflict: str | None = None
        self._options = tuple(options)
        self._host_collected_properties = host_collected_properties
        self._form: TypedInputForm | None = None
        try:
            self._fields: tuple[GateInputField, ...] = collected_input_fields(
                self._options
            )
        except GateError as exc:
            self.conflict = str(exc)
            self._fields = ()
        self._raw_options = tuple(
            option
            for option in self._options
            if not option.inputs and self._raw_editor_properties(option)
        )
        self._raw_valid = {
            option.id: self._raw_editor_error(option, self._seeded_raw_text(option))
            is None
            for option in self._raw_options
        }
        self._visible_option_ids = frozenset(option.id for option in self._options)

    @property
    def is_empty(self) -> bool:
        """Whether this branch renders nothing at all.

        A gate written before declared inputs existed renders exactly as it
        did: no container, not merely a hidden one.
        """
        return not self._fields and not self._raw_options and self.conflict is None

    def compose(self) -> ComposeResult:
        yield Static("Inputs", classes="gate-review-section-title")
        if self.conflict is not None:
            yield Static(self.conflict, classes="gate-input-conflict")
            return
        if self._fields:
            form = TypedInputForm(
                [_typed_form_field(field) for field in self._fields],
                id_prefix=f"gate-branch-{self.branch_index}-field",
                optional_toggle=False,
                id=f"gate-inputs-form-{self.branch_index}",
            )
            self._form = form
            yield form
        for option in self._raw_options:
            yield from self._compose_raw_editor(option)

    def _compose_raw_editor(self, option: GateOption) -> ComposeResult:
        widget_id = self._raw_editor_id(option.id)
        with Vertical(id=f"{widget_id}-block", classes="input-field-block"):
            yield Static(f"{option.label}    (yaml)", classes="field-header")
            yield TextArea(self._seeded_raw_text(option), id=widget_id, language="yaml")
            error_label = Static("", id=f"{widget_id}-error", classes="field-error")
            error_label.display = False
            yield error_label

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        widget_id = event.text_area.id or ""
        for option in self._raw_options:
            if widget_id != self._raw_editor_id(option.id):
                continue
            error = self._raw_editor_error(option, event.text_area.text)
            self._raw_valid[option.id] = error is None
            try:
                error_label = self.query_one(f"#{widget_id}-error", Static)
            except Exception:
                error_label = None
            if error_label is not None:
                error_label.update(f"× {error}" if error else "")
                error_label.display = error is not None
            self.post_message(self.Validated(self.branch_index))
            return

    # -- host-facing state ----------------------------------------------------

    def set_visible_options(self, option_ids: Collection[str]) -> None:
        """Reveal only *option_ids*' fields and editors, for an AND branch."""
        self._visible_option_ids = frozenset(option_ids)
        if self._form is not None:
            selected = [
                option
                for option in self._options
                if option.id in self._visible_option_ids
            ]
            try:
                visible_field_ids = {
                    field.id for field in collected_input_fields(selected)
                }
            except GateError:
                visible_field_ids = set()
            for field in self._fields:
                self._form.set_field_visible(field.id, field.id in visible_field_ids)
        if self.is_mounted:
            for option in self._raw_options:
                block = self.query_one(
                    f"#{self._raw_editor_id(option.id)}-block", Vertical
                )
                block.display = option.id in self._visible_option_ids

    def is_valid(self) -> bool:
        """Whether every visible control holds a submittable value."""
        if self.conflict is not None:
            return False
        if self._form is not None and not self._form.is_valid():
            return False
        return all(
            self._raw_valid.get(option.id, True)
            for option in self._raw_options
            if option.id in self._visible_option_ids
        )

    def focus_first_invalid(self) -> bool:
        """Focus the first visible invalid input/editor in render order."""
        if self.conflict is not None:
            return False
        if self._form is not None and self._form.focus_first_invalid():
            return True
        for option in self._raw_options:
            if option.id not in self._visible_option_ids:
                continue
            if self._raw_valid.get(option.id, True):
                continue
            self.query_one(f"#{self._raw_editor_id(option.id)}", TextArea).focus()
            return True
        return False

    def control_ids(self) -> list[str]:
        """This section's focusable control ids, in render order."""
        ids: list[str] = []
        if self._form is not None:
            ids.extend(self._form.visible_control_ids())
        ids.extend(
            self._raw_editor_id(option.id)
            for option in self._raw_options
            if option.id in self._visible_option_ids
        )
        return ids

    def collect(
        self, selected_option_ids: Collection[str]
    ) -> dict[str, dict[str, Any]]:
        """Per-option inputs for *selected_option_ids*.

        Raises:
            GateBranchInputError: If a value is missing or unparseable. The
                message is written for the reviewer, who is told which control
                to fix.
        """
        selected = [
            option for option in self._options if option.id in set(selected_option_ids)
        ]
        result: dict[str, dict[str, Any]] = {}
        if self._form is not None:
            try:
                values = self._form.typed_values()
            except XPromptValidationError as exc:
                raise GateBranchInputError(
                    f"Fix the highlighted inputs before submitting: {exc}"
                ) from exc
            result = option_inputs_from_values(selected, values)
        raw_option_ids = {option.id for option in self._raw_options}
        for option in selected:
            if option.id not in raw_option_ids:
                continue
            try:
                result[option.id] = self._raw_editor_value(option.id)
            except yaml.YAMLError as exc:
                raise GateBranchInputError(
                    f"Fix the input for {option.label}: {exc}"
                ) from exc
        return result

    # -- raw-schema editors ---------------------------------------------------

    def _raw_editor_id(self, option_id: str) -> str:
        return f"gate-branch-{self.branch_index}-raw-{option_id}"

    def _raw_editor_properties(self, option: GateOption) -> tuple[str, ...]:
        return _schema_extra_properties(
            option.input_schema, self._host_collected_properties
        )

    def _seeded_raw_value(self, option: GateOption) -> dict[str, Any]:
        properties = option.input_schema.get("properties")
        if not isinstance(properties, Mapping):
            return {}
        seeded: dict[str, Any] = {}
        for name, property_schema in properties.items():
            if name in self._host_collected_properties:
                continue
            if isinstance(property_schema, Mapping) and "default" in property_schema:
                seeded[name] = property_schema["default"]
        return seeded

    def _seeded_raw_text(self, option: GateOption) -> str:
        seeded = self._seeded_raw_value(option)
        if not seeded:
            return ""
        return str(yaml.safe_dump(seeded, sort_keys=False))

    @staticmethod
    def _raw_editor_error(option: GateOption, text: str) -> str | None:
        try:
            parsed = yaml.safe_load(text) if text.strip() else {}
        except yaml.YAMLError as exc:
            return f"invalid YAML: {exc}"
        if parsed is None:
            parsed = {}
        error = first_schema_error(parsed, option.input_schema)
        return None if error is None else str(error.message)

    def _raw_editor_value(self, option_id: str) -> Any:
        text = self.query_one(f"#{self._raw_editor_id(option_id)}", TextArea).text
        return yaml.safe_load(text) if text.strip() else {}


def _typed_form_field(field: GateInputField) -> TypedFormField:
    return TypedFormField(
        arg=input_arg_for_field(field),
        label=field.label,
        placeholder=field.placeholder,
        secret=field.secret,
    )


__all__ = [
    "DEFAULT_HOST_COLLECTED_PROPERTIES",
    "GateBranchInputError",
    "GateBranchInputSection",
    "gate_declares_inputs",
]
