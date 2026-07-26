"""Single-page Prompt Inputs panel for placeholders and declared inputs.

Raw ``<placeholder>`` fields appear first, with source context and a
``<ctrl+l>`` escape hatch that preserves the tag literally. Declared
frontmatter ``input:`` arguments follow with their existing typed validation
and optional-input reveal behavior.

The modal returns :class:`~sase.agent.prompt_placeholder_inputs.PromptInputValues`
on confirm, or ``None`` on cancel. Substitution and typed-input rendering remain
pure logic in :mod:`sase.agent.prompt_placeholder_inputs`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.xprompt.raw_placeholders import RawPlaceholderField
from sase.xprompt.models import UNSET, InputArg, InputType, XPromptValidationError

if TYPE_CHECKING:
    from sase.agent.prompt_placeholder_inputs import PromptInputPlan, PromptInputValues


class _InputCollectionInput(SingleLineVimTextArea):
    """Single-line vim editor for prompt input values."""


class _LiteralPlaceholderLine(Label):
    """Focusable replacement for an editor whose placeholder stays literal."""

    can_focus = True


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


class InputCollectionModal(ModalScreen["PromptInputValues | None"]):
    """Collect raw-placeholder and declared-input values on one page.

    Placeholder values are keyed by their exact inner text. Literal-marked
    placeholders are omitted, as are empty optional declared inputs.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+l", "toggle_literal", "Keep literal"),
        ("enter", "next_field", "Next field"),
    ]

    def __init__(self, plan: PromptInputPlan, *, agent_count: int = 1) -> None:
        """Initialize the modal.

        Args:
            plan: The unified raw-placeholder and declared-input collection
                plan.
            agent_count: How many agents the prompt will launch (for the confirm
                button label).
        """
        super().__init__()
        from sase.agent.prompt_placeholder_inputs import PromptInputPlan

        assert isinstance(plan, PromptInputPlan)
        self._placeholders = list(plan.placeholders)
        request = plan.declared
        self._required: list[InputArg] = request.required if request else []
        self._optional: list[InputArg] = request.optional if request else []
        # One flat index space: placeholders, required inputs, optional inputs.
        self._declared_fields: list[InputArg] = self._required + self._optional
        self._field_count = len(self._placeholders) + len(self._declared_fields)
        self._literal_indices: set[int] = set()
        self._agent_count = max(1, agent_count)
        self._optional_revealed = False
        self._type_rule_by_name = _load_type_rules()

    # -- composition ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="input-collection-container"):
            yield Label("Fill in this prompt", id="modal-title")
            yield Label(self._subtitle(), id="modal-subtitle")
            with VerticalScroll(id="input-fields"):
                show_sections = bool(self._placeholders and self._declared_fields)
                if show_sections:
                    yield Label("PLACEHOLDERS", classes="input-section-header")
                for idx, field in enumerate(self._placeholders):
                    yield self._build_placeholder_block(idx, field)
                if show_sections:
                    yield Label("INPUTS", classes="input-section-header")
                declared_offset = len(self._placeholders)
                for offset, arg in enumerate(self._required):
                    idx = declared_offset + offset
                    yield self._build_field_block(idx, arg, required=True, hidden=False)
                if self._optional:
                    yield Button(
                        self._optional_toggle_label(),
                        id="toggle-optional",
                        variant="default",
                    )
                    for offset, arg in enumerate(self._optional):
                        idx = declared_offset + len(self._required) + offset
                        yield self._build_field_block(
                            idx, arg, required=False, hidden=True
                        )
            yield Label("", id="filled-status")
            yield Label(
                self._footer_hint(),
                id="input-collection-hint",
            )
            with Horizontal(id="button-row"):
                yield Button(self._confirm_label(), id="confirm", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    def _build_placeholder_block(
        self, idx: int, field: RawPlaceholderField
    ) -> Vertical:
        heading_children: list[Label] = [
            Label(
                self._styled_tag(field.text),
                classes="placeholder-header",
            )
        ]
        if field.occurrences > 1:
            heading_children.append(
                Label(f"×{field.occurrences}", classes="placeholder-occurrences")
            )
        literal = _LiteralPlaceholderLine(
            self._literal_line(field.text),
            id=f"field-literal-{idx}",
            classes="placeholder-literal",
        )
        literal.display = False
        return Vertical(
            Horizontal(*heading_children, classes="placeholder-heading"),
            Label(
                self._styled_context(field),
                classes="placeholder-context",
            ),
            _InputCollectionInput(id=f"field-input-{idx}"),
            literal,
            id=f"field-block-{idx}",
            classes="input-field-block placeholder-field-block",
        )

    def _build_field_block(
        self, idx: int, arg: InputArg, *, required: bool, hidden: bool
    ) -> Vertical:
        children: list[object] = [
            Label(self._field_header(arg, required=required), classes="field-header")
        ]
        guidance = self._field_guidance(arg)
        if guidance:
            children.append(Label(guidance, classes="field-desc"))
        children.append(self._build_input(idx, arg))
        error = Label("", id=f"field-error-{idx}", classes="field-error")
        error.display = False
        children.append(error)
        block = Vertical(
            *children,  # type: ignore[arg-type]
            id=f"field-block-{idx}",
            classes="input-field-block",
        )
        block.display = not hidden
        return block

    def _build_input(self, idx: int, arg: InputArg) -> SingleLineVimTextArea:
        placeholder = ""
        if arg.default is not UNSET and arg.default is not None:
            placeholder = f"default: {arg.default}"
        field_id = f"field-input-{idx}"
        if arg.type is InputType.PATH:
            return _PathField(id=field_id, placeholder=placeholder)
        return _InputCollectionInput(id=field_id, placeholder=placeholder)

    # -- labels ---------------------------------------------------------------

    def _subtitle(self) -> str:
        parts: list[str] = []
        if self._placeholders:
            parts.append(
                _counted(len(self._placeholders), "placeholder", "placeholders")
            )
        if self._declared_fields:
            parts.append(_counted(len(self._declared_fields), "input", "inputs"))
        return " · ".join(parts)

    def _footer_hint(self) -> str:
        if self._placeholders:
            return "<enter> next field · ^l keep literal · <esc> cancel"
        return "<enter> next field · <esc> cancel"

    def _styled_tag(self, inner: str) -> Text:
        theme = self.app.current_theme
        result = Text()
        result.append("<", Style(color=theme.accent, dim=True))
        result.append(inner, Style(color=theme.secondary, bold=True))
        result.append(">", Style(color=theme.accent, dim=True))
        return result

    def _styled_context(self, field: RawPlaceholderField) -> Text:
        result = Text(field.context, style="dim")
        tag = f"<{field.text}>"
        start = field.context.find(tag)
        if start < 0:
            return result
        theme = self.app.current_theme
        result.stylize(
            Style(color=theme.accent, dim=True),
            start,
            start + 1,
        )
        result.stylize(
            Style(color=theme.secondary, bold=True, dim=True),
            start + 1,
            start + len(tag) - 1,
        )
        result.stylize(
            Style(color=theme.accent, dim=True),
            start + len(tag) - 1,
            start + len(tag),
        )
        return result

    def _literal_line(self, inner: str) -> Text:
        result = Text("literal · will stay as ", style="dim")
        result.append_text(self._styled_tag(inner))
        return result

    def _field_header(self, arg: InputArg, *, required: bool) -> str:
        tag = "required" if required else "optional"
        return f"{arg.name}    ({arg.type.value} · {tag})"

    def _field_guidance(self, arg: InputArg) -> str:
        parts: list[str] = []
        if arg.description:
            parts.append(arg.description)
        rule = self._type_rule_by_name.get(arg.type.value)
        if rule:
            parts.append(rule)
        return "  ·  ".join(parts)

    def _optional_toggle_label(self) -> str:
        marker = "▼" if self._optional_revealed else "►"
        count = len(self._optional)
        noun = "input" if count == 1 else "inputs"
        return f"{marker} {count} optional {noun}"

    def _confirm_label(self) -> str:
        noun = "agent" if self._agent_count == 1 else "agents"
        return f"Launch {self._agent_count} {noun}"

    # -- lifecycle ------------------------------------------------------------

    def on_mount(self) -> None:
        self._refresh_confirm_enabled()
        try:
            editor = self.query_one("#field-input-0", SingleLineVimTextArea)
            editor.focus()
            editor._update_vim_mode_display()
        except Exception:
            pass

    # -- validation -----------------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        idx = self._index_of(event.text_area)
        if idx is not None:
            self._validate_field(idx)
        self._refresh_confirm_enabled()

    def _index_of(self, widget: object) -> int | None:
        widget_id = getattr(widget, "id", "") or ""
        for prefix in ("field-input-", "field-literal-"):
            if widget_id.startswith(prefix):
                try:
                    return int(widget_id[len(prefix) :])
                except ValueError:
                    return None
        return None

    def _field_value(self, idx: int) -> str:
        return self.query_one(f"#field-input-{idx}", SingleLineVimTextArea).text

    def _declared_index(self, idx: int) -> int:
        return idx - len(self._placeholders)

    def _is_required_declared(self, idx: int) -> bool:
        declared_idx = self._declared_index(idx)
        return 0 <= declared_idx < len(self._required)

    def _field_valid(self, idx: int) -> bool:
        value = self._field_value(idx)
        if idx < len(self._placeholders):
            return idx in self._literal_indices or value != ""
        declared_idx = self._declared_index(idx)
        if value == "":
            # Empty required input is incomplete (invalid); empty optional input
            # falls back to its declared default (valid).
            return not self._is_required_declared(idx)
        try:
            self._declared_fields[declared_idx].validate_and_convert(value)
        except XPromptValidationError:
            return False
        return True

    def _validate_field(self, idx: int) -> None:
        """Update the inline error message for field *idx*."""
        if idx < len(self._placeholders):
            return
        try:
            error_label = self.query_one(f"#field-error-{idx}", Label)
        except Exception:
            return
        value = self._field_value(idx)
        arg = self._declared_fields[self._declared_index(idx)]
        if value == "":
            error_label.update("")
            error_label.display = False
            return
        try:
            arg.validate_and_convert(value)
        except XPromptValidationError as exc:
            guidance = self._type_rule_by_name.get(arg.type.value) or str(exc)
            error_label.update(f"× {guidance}")
            error_label.display = True
            return
        error_label.update("")
        error_label.display = False

    def _all_valid(self) -> bool:
        return all(self._field_valid(idx) for idx in range(self._field_count))

    def _filled_count(self) -> tuple[int, int]:
        required_declared_end = len(self._placeholders) + len(self._required)
        indices = range(required_declared_end)
        return sum(self._field_valid(idx) for idx in indices), required_declared_end

    def _filled_status(self) -> str:
        filled, total = self._filled_count()
        if filled == total:
            return "all filled"
        return f"{filled} of {total} filled"

    def _refresh_confirm_enabled(self) -> None:
        try:
            self.query_one("#filled-status", Label).update(self._filled_status())
        except Exception:
            pass
        try:
            confirm = self.query_one("#confirm", Button)
        except Exception:
            return
        confirm.disabled = not self._all_valid()

    # -- actions --------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self._try_confirm()
        elif event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "toggle-optional":
            self._toggle_optional()

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        idx = self._index_of(event.text_area)
        if idx is not None and self._focus_next_field(idx):
            return
        self._try_confirm()

    def _focus_next_field(self, idx: int) -> bool:
        """Focus the next visible input after *idx*; return whether one existed."""
        for next_idx in range(idx + 1, self._field_count):
            block = self.query_one(f"#field-block-{next_idx}", Vertical)
            if block.display:
                self._focus_field(next_idx)
                return True
        return False

    def _focus_field(self, idx: int) -> None:
        if idx in self._literal_indices:
            self.query_one(f"#field-literal-{idx}", _LiteralPlaceholderLine).focus()
            return
        editor = self.query_one(f"#field-input-{idx}", SingleLineVimTextArea)
        editor.focus()
        editor._update_vim_mode_display()

    def _toggle_optional(self) -> None:
        self._optional_revealed = not self._optional_revealed
        for offset in range(len(self._optional)):
            idx = len(self._placeholders) + len(self._required) + offset
            block = self.query_one(f"#field-block-{idx}", Vertical)
            block.display = self._optional_revealed
        self.query_one("#toggle-optional", Button).label = self._optional_toggle_label()
        if self._optional_revealed and self._optional:
            self._focus_field(len(self._placeholders) + len(self._required))

    def action_toggle_literal(self) -> None:
        """Toggle the focused placeholder, or mark every empty one literal."""
        idx = self._index_of(self.focused)
        if idx is not None:
            if idx < len(self._placeholders):
                self._set_literal(idx, idx not in self._literal_indices)
            return
        for placeholder_idx in range(len(self._placeholders)):
            if self._field_value(placeholder_idx) == "":
                self._set_literal(placeholder_idx, True, focus=False)
        self._refresh_confirm_enabled()

    def _set_literal(self, idx: int, literal: bool, *, focus: bool = True) -> None:
        editor = self.query_one(f"#field-input-{idx}", SingleLineVimTextArea)
        line = self.query_one(f"#field-literal-{idx}", _LiteralPlaceholderLine)
        block = self.query_one(f"#field-block-{idx}", Vertical)
        if literal:
            self._literal_indices.add(idx)
        else:
            self._literal_indices.discard(idx)
        editor.display = not literal
        line.display = literal
        block.set_class(literal, "literal")
        if focus:
            self._focus_field(idx)
        self._refresh_confirm_enabled()

    def action_next_field(self) -> None:
        """Advance from a literal line; editors handle their own submit event."""
        idx = self._index_of(self.focused)
        if idx is None or not isinstance(self.focused, _LiteralPlaceholderLine):
            return
        if not self._focus_next_field(idx):
            self._try_confirm()

    def _try_confirm(self) -> None:
        if not self._all_valid():
            self.notify("Fix the highlighted inputs before launching", severity="error")
            return
        from sase.agent.prompt_placeholder_inputs import PromptInputValues

        placeholder_values = {
            field.text: self._field_value(idx)
            for idx, field in enumerate(self._placeholders)
            if idx not in self._literal_indices
        }
        declared_values: dict[str, str] = {}
        declared_offset = len(self._placeholders)
        for declared_idx, arg in enumerate(self._declared_fields):
            idx = declared_offset + declared_idx
            value = self._field_value(idx)
            if value == "" and not self._is_required_declared(idx):
                # Empty optional input: omit so its declared default applies.
                continue
            declared_values[arg.name] = value
        self.dismiss(
            PromptInputValues(
                placeholders=placeholder_values,
                declared=declared_values,
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


def _load_type_rules() -> dict[str, str]:
    """Map each input type name/alias to its per-type guidance rule (Phase 1).

    Falls back to an empty map if the ``sase-core`` binding is unavailable so the
    modal still renders (without guidance text) rather than failing to open.
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


def _counted(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"
