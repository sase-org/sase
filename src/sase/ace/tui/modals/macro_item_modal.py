"""Sub-form modal for editing one ``macros`` item in the Frontmatter Panel (Phase 4).

A small sub-form for a single local macro: its ``_``-prefixed ``name``,
``content``, optional ``inputs`` (authored as a compact ``name:type[=default]``
list), and optional ``description``.  The name is validated against the same
underscore-scoping rule the launch path enforces (:class:`LocalMacroNameError`),
and each input spec is coerced through the real runtime parser, so a helper saved
here behaves identically to one hand-authored in raw YAML or a macro ``.md``.

The modal dismisses with ``(name, Macro)`` on save, or ``None`` on cancel.  Save
is refused (with an inline message) while any field is invalid.
"""

from __future__ import annotations

import re

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, Static, TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.macro.loader_parsing import (
    LocalMacroNameError,
    parse_input_type,
    parse_local_macro_entries,
)
from sase.macro.models import (
    UNSET,
    InputArg,
    Macro,
    MacroValidationError,
)
from sase.macro.prompt_frontmatter import LOCAL_MACRO_SOURCE

from .input_item_modal import default_to_text

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _known_type_names() -> set[str]:
    """All accepted input-type spellings (canonical names + aliases)."""
    from sase.macro.frontmatter_schema import input_type_schema

    names: set[str] = set()
    for descriptor in input_type_schema():
        names.add(descriptor.name)
        names.update(descriptor.aliases)
    return names


def _parse_compact_input_specs(text: str) -> list[InputArg]:
    """Parse a ``name:type[=default], ...`` compact spec into input args.

    Each comma-separated entry is ``name``, ``name:type``, ``name=default``, or
    ``name:type=default`` (type defaults to ``line``).  A non-blank default is
    coerced through :meth:`InputArg.validate_and_convert` so it matches the value
    the launch path accepts.

    Raises:
        ValueError: If a name is not a valid identifier, a type is unknown, or a
            default fails to convert — the message is suitable for inline display.
    """
    known_types = _known_type_names()
    specs: list[InputArg] = []
    seen: set[str] = set()
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name_part, sep, default_part = chunk.partition("=")
        name_token, _, type_token = name_part.partition(":")
        name = name_token.strip()
        type_text = type_token.strip().lower() or "line"
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f"invalid input name '{name}'")
        if name in seen:
            raise ValueError(f"duplicate input '{name}'")
        if type_text not in known_types:
            raise ValueError(f"unknown input type '{type_text}'")
        try:
            resolved = parse_input_type(type_text, name=name)
        except MacroValidationError as exc:
            raise ValueError(str(exc)) from None
        if resolved.base.value == "enum" and resolved.named_type is None:
            raise ValueError(
                f"input '{name}' needs choices: add it with the input editor, "
                "not the compact list"
            )
        try:
            input_arg = InputArg(
                name=name,
                type=resolved.base,
                choices=resolved.choices,
                named_type=resolved.named_type,
                value_role=resolved.value_role,
            )
        except MacroValidationError as exc:
            raise ValueError(str(exc)) from None
        if sep:
            default_text = default_part.strip()
            try:
                default = input_arg.validate_and_convert(default_text)
            except MacroValidationError as exc:
                raise ValueError(str(exc)) from None
        else:
            default = UNSET
        seen.add(name)
        input_arg.default = default
        specs.append(input_arg)
    return specs


def _format_compact_input_specs(inputs: list[InputArg]) -> str:
    """Render input args back to their compact ``name:type[=default]`` form."""
    parts: list[str] = []
    for arg in inputs:
        type_text = arg.named_type or arg.type.value
        spec = f"{arg.name}:{type_text}"
        if arg.default is not UNSET:
            spec += f"={default_to_text(arg.default)}"
        parts.append(spec)
    return ", ".join(parts)


def _validate_local_macro_name(name: str) -> str:
    """Return a validation error for a local macro *name*, or ``""`` if valid.

    Reuses the launch path's underscore-scoping rule (via
    :func:`parse_local_macro_entries`) so the panel never drifts from how a
    local macro name is actually validated.
    """
    if not name:
        return "name is required"
    try:
        parse_local_macro_entries({name: ""}, source_path=LOCAL_MACRO_SOURCE)
    except LocalMacroNameError as exc:
        return str(exc)
    if not _NAME_RE.fullmatch(name):
        return "name must be a valid identifier"
    return ""


class _ModalInput(SingleLineVimTextArea):
    """Single-line vim editor for compact macro fields."""


class MacroItemModal(ModalScreen["tuple[str, Macro] | None"]):
    """Add or edit a local macro; dismiss with ``(name, Macro)`` or ``None``."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        *,
        existing: tuple[str, Macro] | None = None,
        used_names: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._existing = existing
        self._used_names = set(used_names or ())

    def compose(self) -> ComposeResult:
        """Compose the name / content / inputs / description sub-form."""
        existing = self._existing
        title = "Edit macro" if existing else "Add macro"
        name = existing[0] if existing else "_"
        macro = existing[1] if existing else None
        with Container(id="macro-item-modal-container"):
            yield Label(title, id="modal-title")
            yield Label("name  (must start with _)", classes="input-item-field-label")
            yield _ModalInput(value=name, placeholder="_rules", id="macro-item-name")
            yield Label("content", classes="input-item-field-label")
            yield VimTextArea(
                macro.content if macro else "",
                id="macro-item-content",
                show_line_numbers=False,
                soft_wrap=True,
            )
            yield Label(
                "inputs  (name:type[=default], …)", classes="input-item-field-label"
            )
            yield _ModalInput(
                value=_format_compact_input_specs(macro.inputs) if macro else "",
                placeholder="target:word, dry_run:bool=false",
                id="macro-item-inputs",
            )
            yield Label("description", classes="input-item-field-label")
            yield _ModalInput(
                value=(macro.description or "") if macro else "",
                placeholder="(optional)",
                id="macro-item-description",
            )
            yield Static("", id="macro-item-error")
            yield Static("ctrl+s save · esc esc cancel", id="macro-item-footer")

    def on_mount(self) -> None:
        """Focus the name field and prime validation."""
        name = self.query_one("#macro-item-name", _ModalInput)
        name.focus()
        name.cursor_position = len(name.text)
        name._update_vim_mode_display()
        self._refresh_error()

    # -- live feedback --------------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Re-validate on any single-line field edit."""
        self._refresh_error()

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        """Enter on a single-line field saves when valid."""
        self.action_save()

    def _refresh_error(self) -> None:
        _, error = self._build()
        self.query_one("#macro-item-error", Static).update(
            f"[red]✗ {error}[/]" if error else ""
        )

    # -- actions --------------------------------------------------------------

    def action_save(self) -> None:
        """Validate and dismiss with ``(name, Macro)``, or surface an error."""
        result, error = self._build()
        if result is None:
            self.query_one("#macro-item-error", Static).update(f"[red]✗ {error}[/]")
            return
        self.dismiss(result)

    def action_cancel(self) -> None:
        """Dismiss without changes."""
        self.dismiss(None)

    # -- validation -----------------------------------------------------------

    def _current_name(self) -> str:
        return self.query_one("#macro-item-name", _ModalInput).text.strip()

    def _build(self) -> tuple[tuple[str, Macro] | None, str]:
        """Return ``(name, Macro)`` or a validation error string."""
        name = self._current_name()
        name_error = _validate_local_macro_name(name)
        if name_error:
            return None, name_error
        if name in self._used_names:
            return None, f"macro '{name}' already exists"

        content = self.query_one("#macro-item-content", TextArea).text.strip()
        if not content:
            return None, "content is required"

        inputs_text = self.query_one("#macro-item-inputs", _ModalInput).text
        existing_macro = self._existing[1] if self._existing else None
        # The compact grammar cannot represent enum choices, labels, or
        # descriptions. When the text is untouched, reuse the original rich
        # inputs so richer declarations are never overwritten by the compact
        # round-trip.
        if existing_macro is not None and inputs_text == _format_compact_input_specs(
            existing_macro.inputs
        ):
            inputs = list(existing_macro.inputs)
        else:
            try:
                inputs = _parse_compact_input_specs(inputs_text)
            except ValueError as exc:
                return None, str(exc)

        description = (
            self.query_one("#macro-item-description", _ModalInput).text.strip() or None
        )
        macro = Macro(
            name=name,
            content=content,
            inputs=inputs,
            source_path=LOCAL_MACRO_SOURCE,
            description=description,
        )
        return (name, macro), ""


__all__ = ["MacroItemModal"]
