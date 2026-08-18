"""Single-page Prompt Inputs panel for placeholders and declared inputs.

Raw ``<placeholder>`` fields appear first, with source context and a
``<ctrl+l>`` escape hatch that preserves the tag literally. Declared
frontmatter ``input:`` arguments follow, rendered by the shared
:class:`~sase.ace.tui.widgets.typed_input_form.TypedInputForm` with its
existing typed validation and optional-input reveal behavior.

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
from textual.geometry import Region
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.typed_input_form import TypedFormField, TypedInputForm
from sase.xprompt.raw_placeholders import RawPlaceholderField
from sase.xprompt.models import InputArg

if TYPE_CHECKING:
    from sase.agent.prompt_placeholder_inputs import PromptInputPlan, PromptInputValues


class _LiteralPlaceholderLine(Label):
    """Focusable replacement for an editor whose placeholder stays literal."""

    can_focus = True


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
        self._literal_indices: set[int] = set()
        self._agent_count = max(1, agent_count)
        self._form = TypedInputForm(
            [TypedFormField(arg=arg) for arg in self._declared_fields],
            id_prefix="field",
            index_offset=len(self._placeholders),
        )

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
                yield self._form
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
            SingleLineVimTextArea(id=f"field-input-{idx}", soft_wrap=True),
            literal,
            id=f"field-block-{idx}",
            classes="input-field-block placeholder-field-block",
        )

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

    def _confirm_label(self) -> str:
        noun = "agent" if self._agent_count == 1 else "agents"
        return f"Launch {self._agent_count} {noun}"

    # -- lifecycle ------------------------------------------------------------

    def on_mount(self) -> None:
        self._refresh_confirm_enabled()
        try:
            editor = self.query_one("#field-input-0")
            editor.focus()
            update_display = getattr(editor, "_update_vim_mode_display", None)
            if callable(update_display):
                update_display()
        except Exception:
            pass

    # -- validation -----------------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._refresh_confirm_enabled()
        if event.text_area.has_focus:
            self._scroll_editor_cursor_visible(event.text_area)
            self.call_after_refresh(
                self._scroll_editor_cursor_visible,
                event.text_area,
            )

    def on_typed_input_form_changed(self, event: TypedInputForm.Changed) -> None:
        self._refresh_confirm_enabled()

    def on_typed_input_form_submitted(self, event: TypedInputForm.Submitted) -> None:
        self._try_confirm()

    def _scroll_editor_cursor_visible(self, editor: TextArea) -> None:
        """Reveal *editor*'s cursor row inside the fields scroll container."""
        try:
            fields = self.query_one("#input-fields", VerticalScroll)
            window = fields.scrollable_content_region
            target_y = editor.cursor_screen_offset.y - window.y + fields.scroll_offset.y
            fields.scroll_to_region(
                # Keep one row of breathing room below the cursor. When the
                # parent scrollbar first appears it narrows the editor and can
                # add one final wrapped row during the same layout pass.
                Region(0, target_y, 1, 2),
                animate=False,
                immediate=True,
            )
        except Exception:
            pass

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

    def _field_valid(self, idx: int) -> bool:
        value = self._field_value(idx)
        return idx in self._literal_indices or value != ""

    def _all_valid(self) -> bool:
        placeholders_ok = all(
            self._field_valid(idx) for idx in range(len(self._placeholders))
        )
        return placeholders_ok and self._form.is_valid()

    def _filled_count(self) -> tuple[int, int]:
        placeholder_total = len(self._placeholders)
        placeholder_filled = sum(
            self._field_valid(idx) for idx in range(placeholder_total)
        )
        form_filled, form_total = self._form.required_progress()
        return placeholder_filled + form_filled, placeholder_total + form_total

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

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        idx = self._index_of(event.text_area)
        if idx is not None and self._focus_next_field(idx):
            return
        self._try_confirm()

    def _focus_next_field(self, idx: int) -> bool:
        """Focus the next visible placeholder after *idx*, or hand off to the form."""
        for next_idx in range(idx + 1, len(self._placeholders)):
            block = self.query_one(f"#field-block-{next_idx}", Vertical)
            if block.display:
                self._focus_field(next_idx)
                return True
        if self._declared_fields:
            return self._form.focus_first()
        return False

    def _focus_field(self, idx: int) -> None:
        if idx in self._literal_indices:
            self.query_one(f"#field-literal-{idx}", _LiteralPlaceholderLine).focus()
            return
        editor = self.query_one(f"#field-input-{idx}", SingleLineVimTextArea)
        editor.focus()
        editor._update_vim_mode_display()
        self.call_after_refresh(self._scroll_editor_cursor_visible, editor)

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
        self.dismiss(
            PromptInputValues(
                placeholders=placeholder_values,
                declared=self._form.values(),
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


def _counted(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"
