"""Standalone modal adapter for the Memory catalog pane.

:class:`MemoryPane` owns composition, bindings, loads, and mutations. This
screen only dismisses itself on close, forwards focus and visibility to the
pane, and keeps the current prompt-opened route unchanged.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen

from sase.ace.tui.keymaps import MemoryPanelKeymaps

from .catalog_pane_host import CatalogPane
from .memory_pane import MemoryPane as MemoryPane
from .memory_pane import MemoryPaneSession as MemoryPaneSession


class MemoryPanel(ModalScreen[None]):
    """Standalone modal host around :class:`MemoryPane`."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(
        self,
        *,
        keymaps: MemoryPanelKeymaps | None = None,
        launch_workspace: str | None = None,
        initial_scope_key: str | None = None,
        initial_note: str | None = None,
        session: MemoryPaneSession | None = None,
    ) -> None:
        super().__init__()
        self.pane = MemoryPane(
            host=self,
            keymaps=keymaps,
            launch_workspace=launch_workspace,
            initial_scope_key=initial_scope_key,
            initial_note=initial_note,
            session=session,
        )

    def compose(self) -> ComposeResult:
        yield self.pane

    def _catalog_pane(self) -> CatalogPane:
        return self.pane

    def close_catalog_pane(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.close_catalog_pane()

    def focus_default(self) -> None:
        self._catalog_pane().focus_default()

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        self._catalog_pane().on_center_tab_visibility_changed(active)

    @property
    def _loading(self) -> bool:
        return self.pane._loading

    @property
    def _current_note(self) -> str | None:
        return self.pane._current_note

    @property
    def _trail(self) -> list[str]:
        return self.pane._trail

    @property
    def _initial_note(self) -> str | None:
        return self.pane._initial_note

    @property
    def _launch_workspace(self) -> str | None:
        return self.pane._launch_workspace


__all__ = ["MemoryPanel", "MemoryPane", "MemoryPaneSession"]
