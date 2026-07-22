"""Focused keyboard-first modals for adding AXE lumberjacks and chops."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.axe.chop_inventory import ChopInventory

from .property_picker_modal import PropertyPickerItem, PropertyPickerModal


AxeAddKind = Literal["lumberjack", "chop"]


@dataclass(frozen=True)
class AxeScriptChoice:
    """One installed executable choice, or the explicit custom path."""

    name: str
    executable: str | None
    source: str
    configured: bool = False
    custom: bool = False


@dataclass(frozen=True)
class AxeNewEntryDraft:
    """Validated immutable identity values returned before schema editing."""

    kind: AxeAddKind
    lumberjack: str
    name: str
    script: str | None = None


def stable_chop_name(script: str) -> str:
    """Derive a deterministic editable chop identity from an executable."""
    name = script.rsplit("/", 1)[-1]
    return name.removeprefix("sase_chop_") or name


def validate_axe_new_entry_identity(
    *,
    kind: AxeAddKind,
    lumberjack: str,
    name: str,
    script: str = "",
    lumberjack_names: Iterable[str] = (),
    base_chop_identities: Iterable[tuple[str, str]] = (),
) -> str | None:
    """Validate only immutable base identities, preserving exact key text."""
    if not name:
        return "identity cannot be empty"
    if kind == "lumberjack":
        if name in frozenset(lumberjack_names):
            return f"lumberjack {name!r} already exists"
        return None
    if (lumberjack, name) in frozenset(base_chop_identities):
        return f"base chop {name!r} already exists under {lumberjack!r}"
    if not script:
        return "executable cannot be empty"
    return None


class AxeAddChooserModal(PropertyPickerModal):
    """Choose between a contextual chop and a new lumberjack."""

    def __init__(self, contextual_lumberjack: str | None) -> None:
        self.contextual_lumberjack = contextual_lumberjack
        if contextual_lumberjack:
            properties = (
                PropertyPickerItem(
                    "chop",
                    f"Create a chop under {contextual_lumberjack}.",
                    "AXE entry",
                ),
                PropertyPickerItem(
                    "lumberjack", "Create a new scheduled lane.", "AXE entry"
                ),
            )
        else:
            properties = (
                PropertyPickerItem(
                    "lumberjack", "Create a new scheduled lane.", "AXE entry"
                ),
                PropertyPickerItem(
                    "chop", "Pick a parent, then attach a chop.", "AXE entry"
                ),
            )
        super().__init__(
            properties,
            title="Add to AXE",
            guidance="Choose an entry type. Names remain editable before preview.",
            dom_prefix="axe-add",
        )


class AxeLumberjackPickerModal(PropertyPickerModal):
    """Pick a cached lumberjack parent without loading configuration."""

    def __init__(self, names: Iterable[str]) -> None:
        properties = [
            PropertyPickerItem(name, "Attach the new chop here.", "lumberjack")
            for name in names
        ]
        super().__init__(
            properties,
            title="Choose lumberjack",
            guidance="The selected lumberjack becomes the chop's immutable parent.",
            empty_message="No lumberjacks are configured yet.",
            dom_prefix="axe-parent",
        )


class AxeScriptPickerModal(PropertyPickerModal):
    """Present installed chop scripts with source and resolution metadata."""

    def __init__(self, inventory: ChopInventory) -> None:
        self.script_choices = tuple(
            AxeScriptChoice(
                name=record.name,
                executable=record.executable,
                source=record.source,
                configured=record.configured,
            )
            for record in inventory.available_scripts
        ) + (
            AxeScriptChoice(
                name="Custom script",
                executable=None,
                source="custom",
                custom=True,
            ),
        )
        properties = [
            PropertyPickerItem(
                choice.name,
                (
                    "Enter an executable name manually."
                    if choice.custom
                    else "Resolved executable"
                    + (" · already configured" if choice.configured else "")
                ),
                choice.source,
                example=choice.executable or "sase_chop_example",
                allowed_values=("configured" if choice.configured else "available"),
            )
            for choice in self.script_choices
        ]
        super().__init__(
            properties,
            title="Choose chop script",
            guidance="Installed scripts are discovered off-thread; Custom accepts any executable.",
            dom_prefix="axe-script",
        )

    def _select_index(self, index: int) -> None:
        self.dismiss(self.script_choices[index])  # type: ignore[arg-type]


class AxeNewEntryIdentityModal(ModalScreen[AxeNewEntryDraft | None]):
    """Edit a new entry's mapping key and, for chops, executable name."""

    AUTO_FOCUS = None
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "confirm", "Continue"),
    ]

    def __init__(
        self,
        *,
        kind: AxeAddKind,
        lumberjack: str = "",
        initial_name: str = "",
        initial_script: str = "",
        lumberjack_names: Iterable[str] = (),
        base_chop_identities: Iterable[tuple[str, str]] = (),
    ) -> None:
        super().__init__()
        self.kind = kind
        self.lumberjack = lumberjack
        self.initial_name = initial_name
        self.initial_script = initial_script
        self._lumberjack_names = frozenset(lumberjack_names)
        self._base_chop_identities = frozenset(base_chop_identities)

    def compose(self) -> ComposeResult:
        with Container(id="axe-identity-container"):
            yield Static(
                "New AXE lumberjack" if self.kind == "lumberjack" else "New AXE chop",
                id="axe-identity-title",
            )
            if self.kind == "chop":
                yield Static(f"Parent  {self.lumberjack}", id="axe-identity-context")
            with Vertical(id="axe-identity-fields"):
                yield Static("Identity", classes="axe-identity-label")
                yield SingleLineVimTextArea(
                    self.initial_name,
                    id="axe-identity-name",
                )
                if self.kind == "chop":
                    yield Static("Executable", classes="axe-identity-label")
                    yield SingleLineVimTextArea(
                        self.initial_script,
                        id="axe-identity-script",
                    )
            yield Static("", id="axe-identity-validation")
            yield Static(
                "Tab: field  Enter/Ctrl+S: continue  Esc: cancel",
                id="axe-identity-hints",
            )

    def on_mount(self) -> None:
        editor = self.query_one("#axe-identity-name", SingleLineVimTextArea)
        editor.focus()
        editor.select_all()
        editor._update_vim_mode_display()
        self._render_validation()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_confirm(self) -> None:
        message = self.validation_message
        if message is not None:
            self._render_validation()
            return
        name = self.query_one("#axe-identity-name", SingleLineVimTextArea).text
        script = None
        if self.kind == "chop":
            script = self.query_one("#axe-identity-script", SingleLineVimTextArea).text
        self.dismiss(
            AxeNewEntryDraft(
                kind=self.kind,
                lumberjack=self.lumberjack or name,
                name=name,
                script=script,
            )
        )

    @property
    def validation_message(self) -> str | None:
        name = self.query_one("#axe-identity-name", SingleLineVimTextArea).text
        script = ""
        if self.kind == "chop":
            script = self.query_one("#axe-identity-script", SingleLineVimTextArea).text
        return validate_axe_new_entry_identity(
            kind=self.kind,
            lumberjack=self.lumberjack,
            name=name,
            script=script,
            lumberjack_names=self._lumberjack_names,
            base_chop_identities=self._base_chop_identities,
        )

    def _render_validation(self) -> None:
        if not self.is_mounted:
            return
        message = self.validation_message
        widget = self.query_one("#axe-identity-validation", Static)
        widget.update(f"✗ {message}" if message else "✓ identity is available")
        widget.set_class(message is not None, "error")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id in {"axe-identity-name", "axe-identity-script"}:
            self._render_validation()

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        if event.text_area.id == "axe-identity-name" and self.kind == "chop":
            script = self.query_one("#axe-identity-script", SingleLineVimTextArea)
            script.focus()
            script.select_all()
            script._update_vim_mode_display()
            return
        self.action_confirm()


__all__ = [
    "AxeAddChooserModal",
    "AxeAddKind",
    "AxeLumberjackPickerModal",
    "AxeNewEntryDraft",
    "AxeNewEntryIdentityModal",
    "AxeScriptChoice",
    "AxeScriptPickerModal",
    "stable_chop_name",
    "validate_axe_new_entry_identity",
]
