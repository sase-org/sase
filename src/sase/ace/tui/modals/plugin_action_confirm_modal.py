"""Reusable confirm-with-preview modal for plugin install / update mutations.

Every ``uv tool`` mutation surfaced in the TUI Updates tab runs through this
modal first: it shows the **exact** ``uv`` argv that would run and the resolved
scope, then asks for confirmation. The confirmation *is* the CLI's ``--dry-run``
— both safer and more discoverable than a hidden mode (epic decision *D5*).

The modal is purely presentational and reusable. A caller passes one or more
:class:`PluginActionVariant` previews (built off-thread from
:func:`sase.plugins.operations.plan_install` / ``plan_update``); with more than
one variant a toggle (``g``) cycles between them — used by the install action to
offer "from index" vs. "from git" without any further I/O. On confirm the modal
dismisses with the :class:`PluginActionConfirmResult` for the active variant; on
cancel it dismisses ``None``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


@dataclass(frozen=True)
class PluginActionVariant:
    """One selectable preview of a mutation (e.g. install-from-index vs -git).

    *key* is the stable identifier returned on confirm so the caller can map the
    accepted variant back to its planned ``*Ready`` outcome; *label* names the
    variant in the toggle; *argv* is the exact ``uv`` command shown verbatim;
    *summary* describes the resolved plugin set / source.
    """

    key: str
    label: str
    argv: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class PluginActionConfirmResult:
    """The confirmed choice: which variant the user accepted."""

    variant_key: str


class PluginActionConfirmModal(ModalScreen[PluginActionConfirmResult | None]):
    """Confirm a plugin mutation after previewing its exact ``uv`` command."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("n", "cancel", "Cancel"),
        ("y", "confirm", "Confirm"),
        ("g", "toggle_source", "Toggle source"),
    ]

    def __init__(
        self,
        *,
        title: str,
        intro: str,
        variants: Sequence[PluginActionVariant],
        panel_title: str = "Confirm",
    ) -> None:
        super().__init__()
        if not variants:
            raise ValueError("PluginActionConfirmModal requires at least one variant")
        self._title = title
        self._intro = intro
        self._variants = tuple(variants)
        self._panel_title = panel_title
        self._index = 0

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(self._title, id="plugin-action-title")
            yield Static(self._preview_renderable(), id="plugin-action-preview")
            with Horizontal(id="plugin-action-buttons"):
                yield Button(
                    "Confirm (y)", id="plugin-action-confirm", variant="success"
                )
                if len(self._variants) > 1:
                    yield Button(
                        self._toggle_label(),
                        id="plugin-action-toggle",
                        variant="primary",
                    )
                yield Button("Cancel (n)", id="plugin-action-cancel", variant="error")

    # -- rendering --

    def _preview_renderable(self) -> RenderableType:
        variant = self._variants[self._index]
        parts: list[RenderableType] = []
        if self._intro:
            parts.append(Text(self._intro, style="dim"))
            parts.append(Text(""))

        command = Text()
        command.append("Would run  ", style="dim")
        command.append(" ".join(variant.argv), style="cyan")
        parts.append(command)

        parts.append(Text(""))
        parts.append(Text(variant.summary, style="bold"))

        if len(self._variants) > 1:
            parts.append(Text(""))
            parts.append(self._source_line())

        return Panel(Group(*parts), title=self._panel_title, border_style="cyan")

    def _source_line(self) -> Text:
        line = Text()
        line.append("Source  ", style="dim")
        for index, variant in enumerate(self._variants):
            if index > 0:
                line.append("  /  ", style="dim")
            active = index == self._index
            line.append(variant.label, style="bold cyan" if active else "dim")
        line.append("   (g to switch)", style="dim")
        return line

    def _toggle_label(self) -> str:
        nxt = self._variants[(self._index + 1) % len(self._variants)]
        return f"Source: {nxt.label} (g)"

    # -- actions --

    def action_toggle_source(self) -> None:
        """Cycle to the next preview variant (e.g. index ↔ git)."""
        if len(self._variants) <= 1:
            return
        self._index = (self._index + 1) % len(self._variants)
        try:
            self.query_one("#plugin-action-preview", Static).update(
                self._preview_renderable()
            )
        except Exception:
            pass
        try:
            self.query_one("#plugin-action-toggle", Button).label = self._toggle_label()
        except Exception:
            pass

    def action_confirm(self) -> None:
        self.dismiss(PluginActionConfirmResult(self._variants[self._index].key))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "plugin-action-confirm":
            self.action_confirm()
        elif event.button.id == "plugin-action-toggle":
            self.action_toggle_source()
        else:
            self.action_cancel()
