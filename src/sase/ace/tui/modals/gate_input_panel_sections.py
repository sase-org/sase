"""One option's fields and raw-schema editor inside :class:`GateInputPanel`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import yaml  # type: ignore[import-untyped]
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.typed_input_form import TypedFormField, TypedInputForm
from sase.ace.tui.widgets.vim_mode_routing import VimModeRoutingMixin
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.notification_gates.input_collection import input_arg_for_field
from sase.notification_gates.model_inputs import GateInputField
from sase.notification_gates.model_validation import first_schema_error
from sase.notification_gates.models import GateOption

from .gate_input_panel_model import GateInputSectionSpec


class _RawYamlEditor(VimModeRoutingMixin, VimTextArea):
    """YAML editor for an option that declared a raw ``input_schema``."""

    def __init__(self, text: str = "", **kwargs: object) -> None:
        kwargs.setdefault("language", "yaml")
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        kwargs.setdefault("tab_behavior", "focus")
        super().__init__(text, **kwargs)  # type: ignore[arg-type]
        self.show_line_numbers = False


class GateInputSection(Vertical):
    """Declared fields and optional raw-schema editor for one option."""

    def __init__(
        self,
        spec: GateInputSectionSpec,
        option: GateOption,
        *,
        draft_values: Mapping[str, str] | None = None,
        draft_raw_text: str | None = None,
    ) -> None:
        super().__init__(
            id=f"gate-input-section-{spec.option_id}",
            classes="gate-input-section",
        )
        self.spec = spec
        self._option = option
        self._draft_values = dict(draft_values or {})
        self._initial_raw = (
            draft_raw_text if draft_raw_text is not None else spec.raw_seed_text
        )
        self._form: TypedInputForm | None = None
        self._raw_valid = True

    def compose(self) -> ComposeResult:
        yield Static(self._title_text(), classes="gate-input-section-title")
        if self.spec.fields:
            form = TypedInputForm(
                [
                    _form_field(field, self.spec.shared_with.get(field.id, ()))
                    for field in self.spec.fields
                ],
                id_prefix=f"gate-input-{self.spec.option_id}",
                optional_toggle=False,
                soft_wrap=False,
                id=f"gate-input-form-{self.spec.option_id}",
            )
            self._form = form
            yield form
        if self.spec.raw_properties:
            yield from self._compose_raw_editor()

    def _compose_raw_editor(self) -> ComposeResult:
        widget_id = self._raw_editor_id()
        with Vertical(id=f"{widget_id}-block", classes="input-field-block"):
            yield Static(f"{self.spec.label}    (yaml)", classes="field-header")
            yield _RawYamlEditor(self._initial_raw, id=widget_id)
            error_label = Static("", id=f"{widget_id}-error", classes="field-error")
            error_label.display = False
            yield error_label

    def on_mount(self) -> None:
        if self._form is not None and self._draft_values:
            self._form.set_raw_values(self._draft_values)
        if self.spec.raw_properties:
            self._apply_raw_error(self._initial_raw)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != self._raw_editor_id():
            return
        self._apply_raw_error(event.text_area.text)

    def owns_form(self, form: object) -> bool:
        """Whether *form* is this section's declared-field collection widget."""
        return self._form is form

    def control_ids(self) -> list[str]:
        """This section's focusable control ids, in render order."""
        ids: list[str] = []
        if self._form is not None:
            ids.extend(self._form.visible_control_ids())
        if self.spec.raw_properties:
            ids.append(self._raw_editor_id())
        return ids

    def is_valid(self) -> bool:
        """Whether every control in this section holds a submittable value."""
        if self._form is not None and not self._form.is_valid():
            return False
        return self._raw_valid

    def focus_first_invalid(self) -> bool:
        """Focus the first invalid input/editor in render order."""
        if self._form is not None and self._form.focus_first_invalid():
            return True
        if self.spec.raw_properties and not self._raw_valid:
            self.query_one(f"#{self._raw_editor_id()}", VimTextArea).focus()
            return True
        return False

    def focus_first(self) -> bool:
        """Focus the first control in this section."""
        if self._form is not None and self._form.focus_first():
            return True
        if self.spec.raw_properties:
            self.query_one(f"#{self._raw_editor_id()}", VimTextArea).focus()
            return True
        return False

    def values(self) -> dict[str, str]:
        """Raw text per declared field id."""
        if self._form is None:
            return {}
        return self._form.values()

    def typed_values(self) -> dict[str, object]:
        """Converted values per declared field id."""
        if self._form is None:
            return {}
        return self._form.typed_values()

    def raw_text(self) -> str:
        """Current YAML text, or empty when this option has no raw editor."""
        if not self.spec.raw_properties:
            return ""
        try:
            return self.query_one(f"#{self._raw_editor_id()}", VimTextArea).text
        except Exception:
            return self._initial_raw

    def required_progress(self) -> tuple[int, int]:
        """``(filled, total)`` among this section's required declared fields."""
        if self._form is None:
            return 0, 0
        return self._form.required_progress()

    def _title_text(self) -> str:
        icon = f"{self.spec.icon} " if self.spec.icon else ""
        field_count = len(self.spec.fields) + (1 if self.spec.raw_properties else 0)
        required = sum(1 for field in self.spec.fields if field.required)
        noun = "input" if field_count == 1 else "inputs"
        right = f"{field_count} {noun}"
        if required:
            right = f"{right} · {required} required"
        return f"{icon}{self.spec.label}    {right}"

    def _raw_editor_id(self) -> str:
        return f"gate-input-{self.spec.option_id}-raw"

    def _apply_raw_error(self, text: str) -> None:
        error = _raw_editor_error(self._option, text)
        self._raw_valid = error is None
        try:
            error_label = self.query_one(f"#{self._raw_editor_id()}-error", Static)
        except Exception:
            return
        error_label.update(f"× {error}" if error else "")
        error_label.display = error is not None


def _form_field(field: GateInputField, shared_with: tuple[str, ...]) -> TypedFormField:
    arg = input_arg_for_field(field)
    if shared_with:
        annotation = "also sent to " + ", ".join(shared_with)
        description = arg.description
        merged = f"{description}  ·  {annotation}" if description else annotation
        arg = replace(arg, description=merged)
    return TypedFormField(
        arg=arg,
        label=field.label,
        placeholder=field.placeholder,
        secret=field.secret,
    )


def _raw_editor_error(option: GateOption, text: str) -> str | None:
    try:
        parsed = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as exc:
        return f"invalid YAML: {exc}"
    if parsed is None:
        parsed = {}
    error = first_schema_error(parsed, option.input_schema)
    return None if error is None else str(error.message)


__all__ = ["GateInputSection"]
