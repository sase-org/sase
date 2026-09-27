"""Minimal agent-tab picker for the Agents tab (``pick_agents_tab``).

A labels-only option list over the catalog view; selecting a row switches
to that tab. The later ``tab-strip`` phase replaces this with the
searchable picker.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from sase.ace.tui.models.agent_tab_index import AgentTabCatalogEntry
from sase.core.agent_tab import AgentTabKey


class AgentTabPickerModal(ModalScreen[AgentTabKey | None]):
    """Pick which agent tab the Agents tab shows."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        entries: tuple[AgentTabCatalogEntry, ...],
        active: AgentTabKey,
    ) -> None:
        super().__init__()
        self._entries = tuple(entries)
        self._keys = [entry.key for entry in entries]
        try:
            self._selected = self._keys.index(active)
        except ValueError:
            self._selected = 0

    def compose(self) -> ComposeResult:
        """Yield the heading plus one option per catalog label."""
        yield Label("Agents: go to tab…", id="agent-tab-picker-heading")
        options = [
            Option(f"{entry.label} ({entry.root_count})", id=f"tab-{pos}")
            for pos, entry in enumerate(self._entries)
        ]
        yield OptionList(*options, id="agent-tab-picker-list")

    def on_mount(self) -> None:
        """Preselect the active tab's row."""
        try:
            self.query_one(
                "#agent-tab-picker-list", OptionList
            ).highlighted = self._selected
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Dismiss with the chosen tab key."""
        try:
            index = event.option_index
        except Exception:
            index = self._selected
        if 0 <= index < len(self._keys):
            self.dismiss(self._keys[index])
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Dismiss without switching tabs."""
        self.dismiss(None)


__all__ = ["AgentTabPickerModal"]
