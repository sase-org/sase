"""Searchable agent-tab picker for the Agents tab (``pick_agents_tab``).

Lists every catalog tab with its glyph, accent label, count, attention,
and machine information; typing filters rows by label. Selecting a row
switches to that tab. The ``(entries, active)`` constructor and the
palette / ``pick_agents_tab`` entry points are unchanged.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from sase.ace.tui.models.agent_tab_index import AgentTabCatalogEntry
from sase.core.agent_tab import AgentTabKey

try:
    from sase.ace.tui.widgets.agent_tab_strip import (
        AgentTabDescriptor,
        agent_tab_label_style,
    )
except Exception:  # noqa: BLE001 - picker degrades to labels-only rows.
    AgentTabDescriptor = None  # type: ignore[assignment,misc]

    def agent_tab_label_style(descriptor: object) -> str:  # type: ignore[misc]
        return "#AFAFAF"


def _picker_row_text(
    entry: AgentTabCatalogEntry,
    descriptor: AgentTabDescriptor | None = None,
) -> Text:
    """Return the rich row for *entry* with glyph, count, and attention."""
    text = Text()
    accent = "#AFAFAF"
    glyph = ""
    count = entry.root_count
    stopped = failed = unread = 0
    machine = ""
    is_local = False
    label_text = entry.label or "tab"
    if descriptor is not None:
        try:
            accent = agent_tab_label_style(descriptor)
            glyph = descriptor.glyph or ""
            count = descriptor.count
            stopped, failed, unread = (
                descriptor.stopped,
                descriptor.failed,
                descriptor.unread,
            )
            machine = descriptor.machine_alias or ""
            is_local = bool(getattr(descriptor, "is_local_machine", False))
            # Descriptors carry the bare label; the catalog label already
            # includes the glyph, so prefer the bare form to render it once.
            if descriptor.label:
                label_text = descriptor.label
        except Exception:  # noqa: BLE001 - degrade to the catalog row.
            pass
    if glyph:
        text.append(f"{glyph} ", style=accent)
    text.append(label_text, style=accent)
    text.append(f"  {count}", style="#AFAFAF")
    if stopped:
        text.append(f"  S{stopped}", style="bold #FFAF00")
    if failed:
        text.append(f"  F{failed}", style="bold #FF5F5F")
    if unread:
        text.append(f"  U{unread}", style="bold #1a1a1a on #FFD700")
    if is_local:
        text.append("  this machine", style="dim")
    elif machine and machine.casefold() != label_text.casefold():
        text.append(f"  ⌨ {machine}", style="#5FD7FF")
    elif (
        entry.kind in ("machine", "unresolved_machine")
        and not glyph
        and "⌨" not in label_text
        and "⌂" not in label_text
    ):
        text.append("  ⌨", style="#5FD7FF")
    return text


def _filter_picker_entries(
    entries: tuple[AgentTabCatalogEntry, ...],
    query: str,
) -> tuple[int, ...]:
    """Return entry positions whose label matches *query* (pure).

    Empty queries match everything; matching is case-insensitive
    substring over the catalog label.
    """
    needle = (query or "").casefold().strip()
    if not needle:
        return tuple(range(len(entries)))
    return tuple(
        pos
        for pos, entry in enumerate(entries)
        if needle in (entry.label or "").casefold()
    )


class AgentTabPickerModal(ModalScreen[AgentTabKey | None]):
    """Pick which agent tab the Agents tab shows."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        entries: tuple[AgentTabCatalogEntry, ...],
        active: AgentTabKey,
        descriptors: tuple[AgentTabDescriptor, ...] | None = None,
    ) -> None:
        super().__init__()
        self._entries = tuple(entries)
        self._keys = [entry.key for entry in entries]
        by_key = {}
        for descriptor in descriptors or ():
            try:
                by_key[descriptor.key] = descriptor
            except Exception:  # noqa: BLE001
                continue
        self._descriptors_by_key = by_key
        try:
            self._selected = self._keys.index(active)
        except ValueError:
            self._selected = 0
        self._visible_positions: tuple[int, ...] = tuple(range(len(self._entries)))

    def compose(self) -> ComposeResult:
        """Yield the heading, search input, and one option per catalog tab."""
        yield Label("Agents: go to tab…", id="agent-tab-picker-heading")
        yield Input(placeholder="Search tabs…", id="agent-tab-picker-search")
        options = [
            Option(
                _picker_row_text(entry, self._descriptors_by_key.get(entry.key)),
                id=f"tab-{pos}",
            )
            for pos, entry in enumerate(self._entries)
        ]
        yield OptionList(*options, id="agent-tab-picker-list")

    def on_mount(self) -> None:
        """Preselect the active tab's row and focus the search input."""
        try:
            self.query_one(
                "#agent-tab-picker-list", OptionList
            ).highlighted = self._selected
        except Exception:
            pass
        try:
            self.query_one("#agent-tab-picker-search", Input).focus()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter rows to the search text, keeping selection reachable."""
        try:
            if event.input.id != "agent-tab-picker-search":
                return
            query = event.value
        except Exception:
            return
        self._visible_positions = _filter_picker_entries(self._entries, query)
        try:
            option_list = self.query_one("#agent-tab-picker-list", OptionList)
        except Exception:
            return
        try:
            option_list.clear_options()
            for pos in self._visible_positions:
                entry = self._entries[pos]
                option_list.add_option(
                    Option(
                        _picker_row_text(
                            entry, self._descriptors_by_key.get(entry.key)
                        ),
                        id=f"tab-{pos}",
                    )
                )
            if self._selected in self._visible_positions:
                option_list.highlighted = self._visible_positions.index(self._selected)
            elif self._visible_positions:
                option_list.highlighted = 0
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Dismiss with the chosen tab key."""
        try:
            highlighted = self.query_one(
                "#agent-tab-picker-list", OptionList
            ).highlighted
        except Exception:
            highlighted = None
        positions = self._visible_positions
        if highlighted is not None and 0 <= highlighted < len(positions):
            self.dismiss(self._keys[positions[highlighted]])
            return
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


__all__ = [
    "AgentTabPickerModal",
]
