"""Reusable typed, validated single-page field collection.

Driven entirely by the shared xprompt :class:`~sase.xprompt.models.InputArg`
rules, so both the prompt-launch :class:`InputCollectionModal` and the ACE
gate modals collect typed input through one widget with no per-host
branching. See ``sase/repos/plans/202608/gate_inputs_ace_1.md`` for the
extraction this widget grew out of.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Label, TextArea

from sase.xprompt.models import UNSET, InputArg, InputType, XPromptValidationError

from .single_line_vim_text_area import SingleLineVimTextArea

__all__ = ["TypedFormField", "TypedInputForm"]

_ENUM_SENTINEL = "— select —"


@dataclass(frozen=True)
class TypedFormField:
    """One field a :class:`TypedInputForm` renders, with its presentation."""

    arg: InputArg
    label: str = ""
    placeholder: str | None = None
    secret: bool = False

    def __post_init__(self) -> None:
        if not self.label:
            object.__setattr__(self, "label", self.arg.name)

    @property
    def required(self) -> bool:
        return self.arg.default is UNSET


class _InputCollectionInput(SingleLineVimTextArea):
    """Single-line vim editor for typed input values."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("soft_wrap", True)
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]


class _PathField(_InputCollectionInput):
    """Path input that reuses ``<ctrl+t>`` file completion from the prompt bar.

    Pressing ``<ctrl+t>`` cycles through filesystem completions for the current
    value using the same pure completion engine the prompt panes use, so a
    ``path``-typed input gets the familiar tab-completion behavior.
    """

    BINDINGS = [
        ("ctrl+t", "complete_path", "Complete path"),
    ]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._cycle_origin: str | None = None
        self._cycle_index = -1
        self._cycle_last_set: str | None = None

    def action_complete_path(self) -> None:
        """Cycle the value through file completions for the current token."""
        from sase.ace.tui.widgets.file_completion import build_completion_candidates

        # Restart cycling whenever the user has typed since the last completion.
        if self.value != self._cycle_last_set:
            self._cycle_origin = self.value
            self._cycle_index = -1
        origin = self._cycle_origin or ""
        # The completion engine expects a path-like token (one containing ``/``).
        # The whole field value is a path, so a bare filename is completed against
        # the current directory by looking it up as ``./<name>``.
        added_dot_slash = "/" not in origin
        lookup = f"./{origin}" if added_dot_slash else origin
        try:
            candidates, _ = build_completion_candidates(lookup)
        except (OSError, ValueError):
            return
        if not candidates:
            return
        self._cycle_index = (self._cycle_index + 1) % len(candidates)
        chosen = candidates[self._cycle_index].insertion
        if added_dot_slash and chosen.startswith("./"):
            chosen = chosen[2:]
        self.value = chosen
        self.cursor_position = len(chosen)
        self._cycle_last_set = chosen


class _EnumField(Button):
    """Button cycling one ``InputType.ENUM`` field's declared choices.

    A required field with no default starts on a non-submittable sentinel;
    cycling never returns to it once a real choice has been made.
    """

    def __init__(self, arg: InputArg, *, id: str) -> None:
        self._values = [choice.value for choice in arg.choices]
        self._labels = [choice.label or choice.value for choice in arg.choices]
        default = arg.default
        self._index = (
            self._values.index(default)
            if isinstance(default, str) and default in self._values
            else -1
        )
        super().__init__(self._current_label(), id=id, variant="default")

    @property
    def value(self) -> str:
        return "" if self._index < 0 else self._values[self._index]

    def _current_label(self) -> str:
        return _ENUM_SENTINEL if self._index < 0 else self._labels[self._index]

    def cycle(self) -> None:
        self._index = (self._index + 1) % len(self._values)
        self.label = self._current_label()


class TypedInputForm(Vertical):
    """Typed, validated single-page field collection driven by ``InputArg`` rules."""

    class Changed(Message):
        """A field's text changed; the host should refresh its submit state."""

    class Submitted(Message):
        """``<enter>`` was pressed past this form's last visible field."""

    def __init__(
        self,
        fields: Sequence[TypedFormField],
        *,
        id_prefix: str = "field",
        index_offset: int = 0,
        optional_toggle: bool = True,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._fields = list(fields)
        self._id_prefix = id_prefix
        self._index_offset = index_offset
        self._optional_toggle = optional_toggle
        self._optional_revealed = False
        self._visible = [
            not optional_toggle or field.required for field in self._fields
        ]
        self._type_rule_by_name = _load_type_rules()

    # -- ids --------------------------------------------------------------

    @property
    def _toggle_optional_id(self) -> str:
        return (
            "toggle-optional"
            if self._id_prefix == "field"
            else f"{self._id_prefix}-toggle-optional"
        )

    def _input_id(self, index: int) -> str:
        return f"{self._id_prefix}-input-{self._index_offset + index}"

    def _block_id(self, index: int) -> str:
        return f"{self._id_prefix}-block-{self._index_offset + index}"

    def _error_id(self, index: int) -> str:
        return f"{self._id_prefix}-error-{self._index_offset + index}"

    # -- composition --------------------------------------------------------

    def compose(self) -> ComposeResult:
        optional_fields = [field for field in self._fields if not field.required]
        toggle_inserted = False
        for index, field in enumerate(self._fields):
            if (
                self._optional_toggle
                and optional_fields
                and not toggle_inserted
                and not field.required
            ):
                yield Button(
                    self._optional_toggle_label(),
                    id=self._toggle_optional_id,
                    variant="default",
                )
                toggle_inserted = True
            hidden = self._optional_toggle and not field.required
            yield self._build_field_block(index, field, hidden=hidden)

    def _build_field_block(
        self, index: int, field: TypedFormField, *, hidden: bool
    ) -> Vertical:
        children: list[object] = [
            Label(self._field_header(field), classes="field-header")
        ]
        guidance = self._field_guidance(field)
        if guidance:
            children.append(Label(guidance, classes="field-desc"))
        children.append(self._build_editor(index, field))
        error = Label("", id=self._error_id(index), classes="field-error")
        error.display = False
        children.append(error)
        block = Vertical(
            *children,  # type: ignore[arg-type]
            id=self._block_id(index),
            classes="input-field-block",
        )
        block.display = not hidden
        return block

    def _build_editor(self, index: int, field: TypedFormField) -> Widget:
        field_id = self._input_id(index)
        arg = field.arg
        if arg.type is InputType.ENUM:
            return _EnumField(arg, id=field_id)
        placeholder = self._placeholder_text(field)
        if field.secret:
            return Input(id=field_id, password=True, placeholder=placeholder)
        if arg.type is InputType.PATH:
            return _PathField(id=field_id, placeholder=placeholder)
        return _InputCollectionInput(id=field_id, placeholder=placeholder)

    # -- labels ---------------------------------------------------------------

    def _placeholder_text(self, field: TypedFormField) -> str:
        if field.placeholder is not None:
            return field.placeholder
        arg = field.arg
        if arg.default is not UNSET and arg.default is not None:
            return f"default: {arg.default}"
        return ""

    def _field_header(self, field: TypedFormField) -> str:
        tag = "required" if field.required else "optional"
        return f"{field.label}    ({field.arg.type.value} · {tag})"

    def _field_guidance(self, field: TypedFormField) -> str:
        parts: list[str] = []
        if field.arg.description:
            parts.append(field.arg.description)
        rule = self._type_rule_by_name.get(field.arg.type.value)
        if rule:
            parts.append(rule)
        return "  ·  ".join(parts)

    def _optional_toggle_label(self) -> str:
        marker = "▼" if self._optional_revealed else "►"
        count = sum(1 for field in self._fields if not field.required)
        noun = "input" if count == 1 else "inputs"
        return f"{marker} {count} optional {noun}"

    # -- values ---------------------------------------------------------------

    def _raw_value(self, index: int) -> str:
        widget = self.query_one(f"#{self._input_id(index)}")
        return widget.value  # type: ignore[attr-defined,no-any-return]

    def _convert(self, field: TypedFormField, raw: str) -> Any:
        arg = field.arg
        if arg.repeatable:
            lines = [line for line in raw.split("\n") if line.strip()]
            return [arg.validate_and_convert(line) for line in lines]
        return arg.validate_and_convert(raw)

    def values(self) -> dict[str, str]:
        """Raw text per field name, omitting hidden and empty optional fields."""
        result: dict[str, str] = {}
        for index, field in enumerate(self._fields):
            if not self._visible[index]:
                continue
            raw = self._raw_value(index)
            if raw == "" and not field.required:
                continue
            result[field.arg.name] = raw
        return result

    def typed_values(self) -> dict[str, Any]:
        """Converted values per field name, omitting hidden and empty optional fields.

        Raises:
            XPromptValidationError: If a visible required field is empty or a
                visible field's text does not convert. Callers should block
                submission with :meth:`is_valid` before this can happen.
        """
        result: dict[str, Any] = {}
        for index, field in enumerate(self._fields):
            if not self._visible[index]:
                continue
            raw = self._raw_value(index)
            if raw == "":
                if field.required:
                    raise XPromptValidationError(
                        f"Argument '{field.arg.name}' is required"
                    )
                continue
            result[field.arg.name] = self._convert(field, raw)
        return result

    def is_valid(self) -> bool:
        """Whether every visible field is empty-and-optional or converts cleanly."""
        return all(
            self._field_ok(index)
            for index in range(len(self._fields))
            if self._visible[index]
        )

    def _field_ok(self, index: int) -> bool:
        field = self._fields[index]
        raw = self._raw_value(index)
        if raw == "":
            return not field.required
        try:
            self._convert(field, raw)
        except XPromptValidationError:
            return False
        return True

    def required_progress(self) -> tuple[int, int]:
        """(filled, total) counts among required fields, for a status label."""
        total = sum(1 for field in self._fields if field.required)
        filled = sum(
            1
            for index, field in enumerate(self._fields)
            if field.required and self._field_ok(index)
        )
        return filled, total

    # -- visibility -------------------------------------------------------

    def set_field_visible(self, field_name: str, visible: bool) -> None:
        for index, field in enumerate(self._fields):
            if field.arg.name != field_name:
                continue
            self._visible[index] = visible
            if self.is_mounted:
                self.query_one(f"#{self._block_id(index)}", Vertical).display = visible
            self.post_message(self.Changed())
            return

    def visible_field_names(self) -> list[str]:
        return [
            field.arg.name
            for index, field in enumerate(self._fields)
            if self._visible[index]
        ]

    def visible_control_ids(self) -> list[str]:
        """Focusable ids in render order, for a host's focus ring."""
        return [
            self._input_id(index)
            for index in range(len(self._fields))
            if self._visible[index]
        ]

    # -- focus --------------------------------------------------------------

    def focus_first(self) -> bool:
        for index in range(len(self._fields)):
            if self._visible[index]:
                self.focus_field(index)
                return True
        return False

    def focus_first_invalid(self) -> bool:
        """Focus the first visible invalid field that can be corrected."""
        for index, field in enumerate(self._fields):
            if self._visible[index] and field.required and not self._field_ok(index):
                self.focus_field(index)
                return True
        for index, field in enumerate(self._fields):
            if (
                self._visible[index]
                and not field.required
                and not self._field_ok(index)
            ):
                self.focus_field(index)
                return True
        return False

    def focus_field(self, index: int) -> None:
        widget = self.query_one(f"#{self._input_id(index)}")
        widget.focus()
        update_display = getattr(widget, "_update_vim_mode_display", None)
        if callable(update_display):
            update_display()

    def focus_next_after(self, index: int) -> bool:
        for next_index in range(index + 1, len(self._fields)):
            if self._visible[next_index]:
                self.focus_field(next_index)
                return True
        return False

    def _index_of_widget(self, widget: object) -> int | None:
        widget_id = getattr(widget, "id", "") or ""
        prefix = f"{self._id_prefix}-input-"
        if not widget_id.startswith(prefix):
            return None
        try:
            idx = int(widget_id[len(prefix) :])
        except ValueError:
            return None
        index = idx - self._index_offset
        return index if 0 <= index < len(self._fields) else None

    # -- validation ---------------------------------------------------------

    def _validate_field(self, index: int) -> None:
        field = self._fields[index]
        try:
            error_label = self.query_one(f"#{self._error_id(index)}", Label)
        except Exception:
            return
        raw = self._raw_value(index)
        if raw == "":
            error_label.update("")
            error_label.display = False
            return
        try:
            self._convert(field, raw)
        except XPromptValidationError as exc:
            guidance = self._type_rule_by_name.get(field.arg.type.value) or str(exc)
            error_label.update(f"× {guidance}")
            error_label.display = True
            return
        error_label.update("")
        error_label.display = False

    # -- events ---------------------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        index = self._index_of_widget(event.text_area)
        if index is not None:
            self._validate_field(index)
        self.post_message(self.Changed())

    def on_input_changed(self, event: Input.Changed) -> None:
        index = self._index_of_widget(event.input)
        if index is not None:
            self._validate_field(index)
        self.post_message(self.Changed())

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        event.stop()
        self._advance_from(self._index_of_widget(event.text_area))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._advance_from(self._index_of_widget(event.input))

    def _advance_from(self, index: int | None) -> None:
        if index is not None and self.focus_next_after(index):
            return
        self.post_message(self.Submitted())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button
        if button.id == self._toggle_optional_id:
            event.stop()
            self._toggle_optional()
            return
        if isinstance(button, _EnumField):
            event.stop()
            button.cycle()
            index = self._index_of_widget(button)
            if index is not None:
                self.post_message(self.Changed())

    def _toggle_optional(self) -> None:
        self._optional_revealed = not self._optional_revealed
        first_optional: int | None = None
        for index, field in enumerate(self._fields):
            if field.required:
                continue
            if first_optional is None:
                first_optional = index
            self._visible[index] = self._optional_revealed
            if self.is_mounted:
                block = self.query_one(f"#{self._block_id(index)}", Vertical)
                block.display = self._optional_revealed
        if self.is_mounted:
            self.query_one(
                f"#{self._toggle_optional_id}", Button
            ).label = self._optional_toggle_label()
        if self._optional_revealed and first_optional is not None:
            self.focus_field(first_optional)
        self.post_message(self.Changed())


def _load_type_rules() -> dict[str, str]:
    """Map each input type name/alias to its per-type guidance rule (Phase 1).

    Falls back to an empty map if the ``sase-core`` binding is unavailable so the
    form still renders (without guidance text) rather than failing to open.
    """
    try:
        from sase.xprompt.frontmatter_schema import input_type_schema

        rules: dict[str, str] = {}
        for type_schema in input_type_schema():
            rules[type_schema.name] = type_schema.rule
            for alias in type_schema.aliases:
                rules[alias] = type_schema.rule
        return rules
    except Exception:
        return {}
