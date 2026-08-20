"""Standalone modal adapter for the reusable Glossary content pane.

Call sites that open :class:`GlossaryPanel` keep the same constructor and
dismiss contract. Browse/edit behavior lives on :class:`GlossaryPane`.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen

from sase.ace.tui.keymaps import GlossaryPanelKeymaps

from .base import CopyModeForwardingMixin
from .catalog_pane_contract import CatalogPaneSession
from .glossary_pane import GlossaryPane


class GlossaryPanel(CopyModeForwardingMixin, ModalScreen[None]):
    """Modal host that mounts :class:`GlossaryPane` and dismisses on close."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(
        self,
        *,
        keymaps: GlossaryPanelKeymaps | None = None,
        launch_workspace: str | None = None,
        initial_project_key: str | None = None,
        initial_term: str | None = None,
        session: CatalogPaneSession | None = None,
    ) -> None:
        super().__init__()
        self._pane = GlossaryPane(
            keymaps=keymaps,
            launch_workspace=launch_workspace,
            initial_project_key=initial_project_key,
            initial_term=initial_term,
            host=self,
            session=session,
        )

    def compose(self) -> ComposeResult:
        yield self._pane

    def on_mount(self) -> None:
        self._pane.on_center_tab_visibility_changed(True)
        self._pane.focus_default()

    @property
    def pane(self) -> GlossaryPane:
        """The reusable content widget this adapter hosts."""
        return self._pane

    def request_close(self) -> None:
        """Dismiss this standalone modal."""
        self.dismiss(None)

    def action_close(self) -> None:
        self.request_close()

    def focus_default(self) -> None:
        self._pane.focus_default()

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        self._pane.on_center_tab_visibility_changed(active)

    @property
    def _loading(self) -> bool:
        return self._pane._loading

    @property
    def _current_term(self) -> str | None:
        return self._pane._current_term

    @property
    def _trail(self) -> list[str]:
        return self._pane._trail

    @property
    def _initial_term(self) -> str | None:
        return self._pane._initial_term

    @property
    def _launch_workspace(self) -> str | None:
        return self._pane._launch_workspace


__all__ = ["GlossaryPanel", "GlossaryPane"]
