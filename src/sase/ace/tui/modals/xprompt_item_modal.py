"""Sub-form modal for editing one ``xprompts`` item in the Frontmatter Panel (Phase 4).

A small sub-form for a single local xprompt: its ``_``-prefixed ``name``,
``content``, optional ``inputs`` (authored as a compact ``name:type[=default]``
list), and optional ``description``.  The name is validated against the same
underscore-scoping rule the launch path enforces (:class:`LocalXPromptNameError`),
and each input spec is coerced through the real runtime parser, so a helper saved
here behaves identically to one hand-authored in raw YAML or an xprompt ``.md``.

The modal dismisses with ``(name, XPrompt)`` on save, or ``None`` on cancel.  Save
is refused (with an inline message) while any field is invalid.
"""

from __future__ import annotations

import re

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static, TextArea

from sase.xprompt.loader_parsing import (
    LocalXPromptNameError,
    parse_input_type,
    parse_local_xprompt_entries,
)
from sase.xprompt.models import (
    UNSET,
    InputArg,
    XPrompt,
    XPromptValidationError,
)
from sase.xprompt.prompt_frontmatter import LOCAL_XPROMPT_SOURCE

from .input_item_modal import default_to_text

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _known_type_names() -> set[str]:
    """All accepted input-type spellings (canonical names + aliases)."""
    from sase.xprompt.frontmatter_schema import input_type_schema

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
        input_type = parse_input_type(type_text)
        if sep:
            default_text = default_part.strip()
            try:
                default = InputArg(name=name, type=input_type).validate_and_convert(
                    default_text
                )
            except XPromptValidationError as exc:
                raise ValueError(str(exc)) from None
        else:
            default = UNSET
        seen.add(name)
        specs.append(InputArg(name=name, type=input_type, default=default))
    return specs


def _format_compact_input_specs(inputs: list[InputArg]) -> str:
    """Render input args back to their compact ``name:type[=default]`` form."""
    parts: list[str] = []
    for arg in inputs:
        spec = f"{arg.name}:{arg.type.value}"
        if arg.default is not UNSET:
            spec += f"={default_to_text(arg.default)}"
        parts.append(spec)
    return ", ".join(parts)


def _validate_local_xprompt_name(name: str) -> str:
    """Return a validation error for a local xprompt *name*, or ``""`` if valid.

    Reuses the launch path's underscore-scoping rule (via
    :func:`parse_local_xprompt_entries`) so the panel never drifts from how a
    local xprompt name is actually validated.
    """
    if not name:
        return "name is required"
    try:
        parse_local_xprompt_entries({name: ""}, source_path=LOCAL_XPROMPT_SOURCE)
    except LocalXPromptNameError as exc:
        return str(exc)
    if not _NAME_RE.fullmatch(name):
        return "name must be a valid identifier"
    return ""


class _ModalInput(Input):
    """Input with readline-style cursor bindings, matching the other modals."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
    ]


class XPromptItemModal(ModalScreen["tuple[str, XPrompt] | None"]):
    """Add or edit a local xprompt; dismiss with ``(name, XPrompt)`` or ``None``."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        *,
        existing: tuple[str, XPrompt] | None = None,
        used_names: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._existing = existing
        self._used_names = set(used_names or ())

    def compose(self) -> ComposeResult:
        """Compose the name / content / inputs / description sub-form."""
        existing = self._existing
        title = "Edit xprompt" if existing else "Add xprompt"
        name = existing[0] if existing else "_"
        xprompt = existing[1] if existing else None
        with Container(id="xprompt-item-modal-container"):
            yield Label(title, id="modal-title")
            yield Label("name  (must start with _)", classes="input-item-field-label")
            yield _ModalInput(value=name, placeholder="_rules", id="xprompt-item-name")
            yield Label("content", classes="input-item-field-label")
            yield TextArea(
                xprompt.content if xprompt else "",
                id="xprompt-item-content",
                show_line_numbers=False,
                soft_wrap=True,
            )
            yield Label(
                "inputs  (name:type[=default], …)", classes="input-item-field-label"
            )
            yield _ModalInput(
                value=_format_compact_input_specs(xprompt.inputs) if xprompt else "",
                placeholder="target:word, dry_run:bool=false",
                id="xprompt-item-inputs",
            )
            yield Label("description", classes="input-item-field-label")
            yield _ModalInput(
                value=(xprompt.description or "") if xprompt else "",
                placeholder="(optional)",
                id="xprompt-item-description",
            )
            yield Static("", id="xprompt-item-error")
            yield Static("ctrl+s save · esc cancel", id="xprompt-item-footer")

    def on_mount(self) -> None:
        """Focus the name field and prime validation."""
        name = self.query_one("#xprompt-item-name", _ModalInput)
        name.focus()
        name.cursor_position = len(name.value)
        self._refresh_error()

    # -- live feedback --------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        """Re-validate on any single-line field edit."""
        self._refresh_error()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Re-validate on a content edit."""
        self._refresh_error()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter on a single-line field saves when valid."""
        self.action_save()

    def _refresh_error(self) -> None:
        _, error = self._build()
        self.query_one("#xprompt-item-error", Static).update(
            f"[red]✗ {error}[/]" if error else ""
        )

    # -- actions --------------------------------------------------------------

    def action_save(self) -> None:
        """Validate and dismiss with ``(name, XPrompt)``, or surface an error."""
        result, error = self._build()
        if result is None:
            self.query_one("#xprompt-item-error", Static).update(f"[red]✗ {error}[/]")
            return
        self.dismiss(result)

    def action_cancel(self) -> None:
        """Dismiss without changes."""
        self.dismiss(None)

    # -- validation -----------------------------------------------------------

    def _current_name(self) -> str:
        return self.query_one("#xprompt-item-name", _ModalInput).value.strip()

    def _build(self) -> tuple[tuple[str, XPrompt] | None, str]:
        """Return ``(name, XPrompt)`` or a validation error string."""
        name = self._current_name()
        name_error = _validate_local_xprompt_name(name)
        if name_error:
            return None, name_error
        if name in self._used_names:
            return None, f"xprompt '{name}' already exists"

        content = self.query_one("#xprompt-item-content", TextArea).text.strip()
        if not content:
            return None, "content is required"

        inputs_text = self.query_one("#xprompt-item-inputs", _ModalInput).value
        try:
            inputs = _parse_compact_input_specs(inputs_text)
        except ValueError as exc:
            return None, str(exc)

        description = (
            self.query_one("#xprompt-item-description", _ModalInput).value.strip()
            or None
        )
        xprompt = XPrompt(
            name=name,
            content=content,
            inputs=inputs,
            source_path=LOCAL_XPROMPT_SOURCE,
            description=description,
        )
        return (name, xprompt), ""


__all__ = ["XPromptItemModal"]
