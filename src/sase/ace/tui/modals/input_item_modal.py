"""Sub-form modal for editing one ``input`` item in the Frontmatter Panel (Phase 4).

A small typed sub-form for a single declared input: its ``name``, ``type``,
optional ``default`` (blank means required), and optional ``description``.  The
type field is validated against — and guided by — the ``sase-core`` input-type
catalog (the same engine that backs the xprompt LSP), and a non-blank default is
coerced through the real runtime validator (:meth:`InputArg.validate_and_convert`)
so the saved value is exactly what the launch path will accept.

The modal dismisses with the constructed :class:`InputArg` on save, or ``None`` on
cancel.  Save is refused (with an inline message) while any field is invalid.
"""

from __future__ import annotations

import re
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from sase.xprompt.frontmatter_schema import input_type_schema
from sase.xprompt.loader_parsing import parse_input_type
from sase.xprompt.models import (
    UNSET,
    InputArg,
    InputType,
    XPromptValidationError,
)

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _input_type_names() -> dict[str, InputType]:
    """Map every canonical type name and alias to its :class:`InputType`."""
    mapping: dict[str, InputType] = {}
    for descriptor in input_type_schema():
        resolved = parse_input_type(descriptor.name)
        mapping[descriptor.name] = resolved
        for alias in descriptor.aliases:
            mapping[alias] = resolved
    return mapping


def _input_type_rules() -> dict[str, str]:
    """Map every canonical type name and alias to its one-line guidance rule."""
    rules: dict[str, str] = {}
    for descriptor in input_type_schema():
        rules[descriptor.name] = descriptor.rule
        for alias in descriptor.aliases:
            rules[alias] = descriptor.rule
    return rules


def default_to_text(default: Any) -> str:
    """Render an :class:`InputArg` default back to its editable text form."""
    if default is UNSET:
        return ""
    if isinstance(default, bool):
        return "true" if default else "false"
    return str(default)


class _ModalInput(Input):
    """Input with readline-style cursor bindings, matching the other modals."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
    ]


class InputItemModal(ModalScreen[InputArg | None]):
    """Add or edit a single ``input`` declaration; dismiss with the ``InputArg``."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        *,
        existing: InputArg | None = None,
        used_names: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._existing = existing
        self._used_names = set(used_names or ())
        self._types = _input_type_names()
        self._rules = _input_type_rules()

    def compose(self) -> ComposeResult:
        """Compose the four-field sub-form plus the live guidance / error lines."""
        existing = self._existing
        title = "Edit input" if existing else "Add input"
        with Container(id="input-item-modal-container"):
            yield Label(title, id="modal-title")
            yield Label("name", classes="input-item-field-label")
            yield _ModalInput(
                value=existing.name if existing else "",
                placeholder="service",
                id="input-item-name",
            )
            yield Label("type", classes="input-item-field-label")
            yield _ModalInput(
                value=existing.type.value if existing else InputType.LINE.value,
                placeholder="word · line · text · path · int · float · bool",
                id="input-item-type",
            )
            yield Static("", id="input-item-type-rule")
            yield Label("default  (blank = required)", classes="input-item-field-label")
            yield _ModalInput(
                value=default_to_text(existing.default) if existing else "",
                placeholder="(required)",
                id="input-item-default",
            )
            yield Label("description", classes="input-item-field-label")
            yield _ModalInput(
                value=existing.description or "" if existing else "",
                placeholder="(optional)",
                id="input-item-description",
            )
            yield Static("", id="input-item-error")
            yield Static("⏎ save · esc cancel", id="input-item-footer")

    def on_mount(self) -> None:
        """Focus the name field and prime the live guidance / validation."""
        name = self.query_one("#input-item-name", _ModalInput)
        name.focus()
        name.cursor_position = len(name.value)
        self._refresh_feedback()

    # -- live feedback --------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        """Re-validate and refresh the type rule / error line on any edit."""
        self._refresh_feedback()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter saves when valid (otherwise the inline error stays visible)."""
        self.action_save()

    def _refresh_feedback(self) -> None:
        """Update the per-type rule hint and the validation error message."""
        type_text = self._field("input-item-type").strip().lower()
        rule = self._rules.get(type_text, "")
        self.query_one("#input-item-type-rule", Static).update(
            f"[dim]{rule}[/]" if rule else "[red]unknown type[/]"
        )
        _, error = self._build()
        self.query_one("#input-item-error", Static).update(
            f"[red]✗ {error}[/]" if error else ""
        )

    # -- actions --------------------------------------------------------------

    def action_save(self) -> None:
        """Validate and dismiss with the constructed input, or surface an error."""
        arg, error = self._build()
        if arg is None:
            self.query_one("#input-item-error", Static).update(f"[red]✗ {error}[/]")
            return
        self.dismiss(arg)

    def action_cancel(self) -> None:
        """Dismiss without changes."""
        self.dismiss(None)

    # -- validation -----------------------------------------------------------

    def _field(self, widget_id: str) -> str:
        return self.query_one(f"#{widget_id}", _ModalInput).value

    def _build(self) -> tuple[InputArg | None, str]:
        """Return the constructed :class:`InputArg` or a validation error string."""
        name = self._field("input-item-name").strip()
        if not name:
            return None, "name is required"
        if not _NAME_RE.fullmatch(name):
            return None, "name must be a valid identifier"
        if name in self._used_names:
            return None, f"input '{name}' already exists"

        type_text = self._field("input-item-type").strip().lower()
        input_type = self._types.get(type_text)
        if input_type is None:
            return None, f"unknown type '{type_text}'"

        description = self._field("input-item-description").strip() or None

        default_text = self._field("input-item-default").strip()
        if not default_text:
            return (
                InputArg(
                    name=name,
                    type=input_type,
                    default=UNSET,
                    description=description,
                ),
                "",
            )
        try:
            default = InputArg(name=name, type=input_type).validate_and_convert(
                default_text
            )
        except XPromptValidationError as exc:
            return None, str(exc)
        return (
            InputArg(
                name=name,
                type=input_type,
                default=default,
                description=description,
            ),
            "",
        )
