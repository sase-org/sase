"""Input Collection Modal for prompt frontmatter ``input:`` declarations.

Phase 5 of the prompt-frontmatter-panel epic. When a submitted prompt declares
``input:`` arguments without defaults, this modal collects a typed, validated
value for each required input (optional inputs stay collapsed behind a reveal
toggle, showing their defaults) before the agents fan out. Each field validates
live via :meth:`InputArg.validate_and_convert`; the confirm button stays disabled
until every required input is valid. Per-type guidance text comes from the shared
``sase-core`` engine (:func:`input_type_schema`, Phase 1) so it never drifts from
the xprompt LSP.

The modal returns a mapping of input name to the raw (unconverted) string value
on confirm, or ``None`` on cancel. Conversion + default-filling + Jinja
substitution into each segment happens in
:func:`sase.agent.prompt_inputs.render_prompt_with_inputs`.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from sase.xprompt.models import UNSET, InputArg, InputType, XPromptValidationError


class _InputCollectionInput(Input):
    """Single-line input with readline-style cursor bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
    ]


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


class InputCollectionModal(ModalScreen["dict[str, str] | None"]):
    """Collect typed values for a prompt's declared frontmatter inputs.

    Returns a mapping of input name to raw string value on confirm, or ``None``
    on cancel. Only inputs the user supplied are returned (empty optional inputs
    are omitted so their declared defaults apply downstream).
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, request: object, *, agent_count: int = 1) -> None:
        """Initialize the modal.

        Args:
            request: The :class:`~sase.agent.prompt_inputs.PromptInputRequest`
                describing the declared inputs.
            agent_count: How many agents the prompt will launch (for the confirm
                button label).
        """
        super().__init__()
        from sase.agent.prompt_inputs import PromptInputRequest

        assert isinstance(request, PromptInputRequest)
        self._required: list[InputArg] = request.required
        self._optional: list[InputArg] = request.optional
        # Required inputs first, then optional — index into this list is the
        # field id suffix used throughout (``field-input-<idx>``).
        self._fields: list[InputArg] = self._required + self._optional
        self._agent_count = max(1, agent_count)
        self._optional_revealed = False
        self._type_rule_by_name = _load_type_rules()

    # -- composition ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="input-collection-container"):
            yield Label("Inputs for this prompt", id="modal-title")
            with VerticalScroll(id="input-fields"):
                for idx, arg in enumerate(self._required):
                    yield self._build_field_block(idx, arg, required=True, hidden=False)
                if self._optional:
                    yield Button(
                        self._optional_toggle_label(),
                        id="toggle-optional",
                        variant="default",
                    )
                    for offset, arg in enumerate(self._optional):
                        idx = len(self._required) + offset
                        yield self._build_field_block(
                            idx, arg, required=False, hidden=True
                        )
            with Horizontal(id="button-row"):
                yield Button(self._confirm_label(), id="confirm", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

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

    def _build_input(self, idx: int, arg: InputArg) -> Input:
        placeholder = ""
        if arg.default is not UNSET and arg.default is not None:
            placeholder = f"default: {arg.default}"
        field_id = f"field-input-{idx}"
        if arg.type is InputType.PATH:
            return _PathField(id=field_id, placeholder=placeholder)
        return _InputCollectionInput(id=field_id, placeholder=placeholder)

    # -- labels ---------------------------------------------------------------

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
            self.query_one("#field-input-0", Input).focus()
        except Exception:
            pass

    # -- validation -----------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        idx = self._index_of(event.input)
        if idx is not None:
            self._validate_field(idx)
        self._refresh_confirm_enabled()

    def _index_of(self, widget: Input) -> int | None:
        widget_id = widget.id or ""
        prefix = "field-input-"
        if not widget_id.startswith(prefix):
            return None
        try:
            return int(widget_id[len(prefix) :])
        except ValueError:
            return None

    def _field_value(self, idx: int) -> str:
        return self.query_one(f"#field-input-{idx}", Input).value

    def _is_required(self, idx: int) -> bool:
        return idx < len(self._required)

    def _field_valid(self, idx: int) -> bool:
        value = self._field_value(idx)
        if value == "":
            # Empty required input is incomplete (invalid); empty optional input
            # falls back to its declared default (valid).
            return not self._is_required(idx)
        try:
            self._fields[idx].validate_and_convert(value)
        except XPromptValidationError:
            return False
        return True

    def _validate_field(self, idx: int) -> None:
        """Update the inline error message for field *idx*."""
        try:
            error_label = self.query_one(f"#field-error-{idx}", Label)
        except Exception:
            return
        value = self._field_value(idx)
        arg = self._fields[idx]
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
        return all(self._field_valid(idx) for idx in range(len(self._fields)))

    def _refresh_confirm_enabled(self) -> None:
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        idx = self._index_of(event.input)
        if idx is not None and self._focus_next_field(idx):
            return
        self._try_confirm()

    def _focus_next_field(self, idx: int) -> bool:
        """Focus the next visible input after *idx*; return whether one existed."""
        for next_idx in range(idx + 1, len(self._fields)):
            block = self.query_one(f"#field-block-{next_idx}", Vertical)
            if block.display:
                self.query_one(f"#field-input-{next_idx}", Input).focus()
                return True
        return False

    def _toggle_optional(self) -> None:
        self._optional_revealed = not self._optional_revealed
        for offset in range(len(self._optional)):
            idx = len(self._required) + offset
            block = self.query_one(f"#field-block-{idx}", Vertical)
            block.display = self._optional_revealed
        self.query_one("#toggle-optional", Button).label = self._optional_toggle_label()
        if self._optional_revealed and self._optional:
            self.query_one(f"#field-input-{len(self._required)}", Input).focus()

    def _try_confirm(self) -> None:
        if not self._all_valid():
            self.notify("Fix the highlighted inputs before launching", severity="error")
            return
        values: dict[str, str] = {}
        for idx, arg in enumerate(self._fields):
            value = self._field_value(idx)
            if value == "" and not self._is_required(idx):
                # Empty optional input: omit so its declared default applies.
                continue
            values[arg.name] = value
        self.dismiss(values)

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
