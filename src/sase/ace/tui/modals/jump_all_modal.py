"""Cross-tab jump-to-entry modal for the ace TUI.

Opens a modal showing all entries across CLs, Agents, and AXE tabs.
Each entry has a single-keypress hint character; pressing a hint
immediately switches to the target tab, focuses that entry, and
dismisses the modal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from ..actions.navigation.jump_hints import JUMP_HINT_CHARS
from ..widgets.bgcmd_list import AxeParentItem, BgCmdItem, LumberjackItem

if TYPE_CHECKING:
    from ...changespec import ChangeSpec
    from ..models import Agent
    from ..widgets.bgcmd_list import AxeItem

TabName = Literal["changespecs", "agents", "axe"]
PanelFocus = Literal["main", "pinned"]

# ── Visual constants ──────────────────────────────────────────────
_NAME_MAX = 50
_STATUS_MAX = 18
_SECTION_RULE_WIDTH = 76

# Per-tab section header colours
_TAB_STYLES: dict[TabName, tuple[str, str]] = {
    "changespecs": ("CLs", "#00D7AF"),
    "agents": ("Agents", "#87D7FF"),
    "axe": ("AXE", "#FFD700"),
}

# Status colours (ChangeSpec)
_CS_STATUS_STYLES: dict[str, str] = {
    "WIP": "#FFD700",
    "Draft": "#87D7FF",
    "Ready": "#00D7AF",
    "Mailed": "#AF87FF",
    "Submitted": "dim",
    "Archived": "dim",
    "Reverted": "dim",
}

# Status colours (Agent)
_AGENT_STATUS_STYLES: dict[str, str] = {
    "RUNNING": "#00D7AF",
    "DONE": "dim #87D7FF",
    "FAILED": "#FF5F5F",
    "KILLED": "#FF8C00",
    "WAITING": "#FFD700",
    "WORKFLOW": "#AF87FF",
}


@dataclass(frozen=True)
class JumpAllResult:
    """Result returned when the user selects an entry."""

    tab: TabName
    index: int
    pinned_panel_focused: PanelFocus | None


@dataclass(frozen=True)
class _Entry:
    """Internal entry representation for display."""

    tab: TabName
    index: int
    name: str
    status: str
    status_style: str
    name_style: str = ""
    panel_focus: PanelFocus | None = None
    indent: int = 0
    is_pinned: bool = False


class JumpAllModal(ModalScreen[JumpAllResult | None]):
    """Modal showing all entries across tabs with single-keypress hints."""

    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    def __init__(
        self,
        changespecs: list[ChangeSpec],
        agents: list[Agent],
        main_panel_indices: list[int],
        pinned_panel_indices: list[int],
        pinned_panel_idx_map: dict[int, int],
        axe_items: list[AxeItem],
    ) -> None:
        super().__init__()
        self._entries: list[_Entry] = []
        self._hint_to_entry: dict[str, _Entry] = {}
        self._build_entries(
            changespecs,
            agents,
            main_panel_indices,
            pinned_panel_indices,
            pinned_panel_idx_map,
            axe_items,
        )

    def _build_entries(
        self,
        changespecs: list[ChangeSpec],
        agents: list[Agent],
        main_panel_indices: list[int],
        pinned_panel_indices: list[int],
        pinned_panel_idx_map: dict[int, int],
        axe_items: list[AxeItem],
    ) -> None:
        """Collect all entries and assign hint characters."""
        entries: list[_Entry] = []

        # CLs
        _, cl_color = _TAB_STYLES["changespecs"]
        for i, cs in enumerate(changespecs):
            style = _CS_STATUS_STYLES.get(cs.status, "")
            entries.append(
                _Entry("changespecs", i, cs.name, cs.status, style, name_style=cl_color)
            )

        # Agents (main then pinned — matching existing jump order)
        _, ag_color = _TAB_STYLES["agents"]
        for idx in [*main_panel_indices, *pinned_panel_indices]:
            if idx >= len(agents):
                continue
            ag = agents[idx]
            panel: PanelFocus = "pinned" if idx in pinned_panel_idx_map else "main"
            style = _AGENT_STATUS_STYLES.get(ag.status, "")
            name = ag.cl_name
            if ag.raw_suffix:
                name = f"{name}/{ag.raw_suffix}"
            pinned = idx in pinned_panel_idx_map
            entries.append(
                _Entry(
                    "agents",
                    idx,
                    name,
                    ag.status,
                    style,
                    name_style=ag_color,
                    panel_focus=panel,
                    is_pinned=pinned,
                )
            )

        # AXE
        _, axe_color = _TAB_STYLES["axe"]
        for i, item in enumerate(axe_items):
            if isinstance(item, AxeParentItem):
                entries.append(
                    _Entry("axe", i, "sase axe", "", "", name_style=axe_color, indent=0)
                )
            elif isinstance(item, LumberjackItem):
                entries.append(
                    _Entry("axe", i, item.name, "", "", name_style=axe_color, indent=1)
                )
            elif isinstance(item, BgCmdItem):
                entries.append(
                    _Entry(
                        "axe",
                        i,
                        f"bgcmd #{item.slot}",
                        "",
                        "",
                        name_style=axe_color,
                        indent=0,
                    )
                )

        self._entries = entries

        # Assign hints
        for hint, entry in zip(JUMP_HINT_CHARS, entries, strict=False):
            self._hint_to_entry[hint] = entry

    def compose(self) -> ComposeResult:
        with Container(id="jump-all-container"):
            yield Static(self._build_title(), id="jump-all-title")
            with VerticalScroll(id="jump-all-scroll"):
                yield Static(self._build_display(), id="jump-all-content")
            yield Static(
                "press key to jump · esc cancel",
                id="jump-all-footer",
            )

    def _build_title(self) -> Text:
        text = Text(justify="center")
        text.append("\n")
        text.append("───", style="dim")
        text.append(" ✦ ", style="bold #FFD700")
        text.append("Jump to Entry", style="bold white")
        text.append(" ✦ ", style="bold #FFD700")
        text.append("───", style="dim")
        text.append("\n")
        return text

    def _build_display(self) -> Text:
        """Build the Rich Text content with tabbed sections and hint chars."""
        text = Text()
        hint_idx = 0
        hints = list(JUMP_HINT_CHARS)

        current_tab: TabName | None = None
        for entry in self._entries:
            # Section header when tab changes
            if entry.tab != current_tab:
                current_tab = entry.tab
                label, color = _TAB_STYLES[current_tab]
                count = sum(1 for e in self._entries if e.tab == current_tab)
                if text.plain:
                    text.append("\n")
                header = f"  ── {label} ({count}) "
                fill_width = max(0, _SECTION_RULE_WIDTH - len(header))
                text.append(header, style=f"bold {color}")
                text.append("─" * fill_width, style=f"dim {color}")
                text.append("\n\n")

            # Hint character
            if hint_idx < len(hints):
                hint = hints[hint_idx]
                hint_idx += 1
            else:
                hint = " "

            # Build entry line
            indent = "  " * entry.indent
            prefix = f"    {indent}"

            text.append(prefix)
            text.append("[", style="dim")
            text.append(hint, style="bold #FFFF00")
            text.append("] ", style="dim")

            # Name (truncated, tab-colored)
            avail = _NAME_MAX - len(indent)
            name = entry.name[:avail] if len(entry.name) > avail else entry.name
            text.append(f"{name:<{avail}}", style=entry.name_style or "#00D7AF")

            # Status (right-aligned)
            if entry.status:
                text.append("  ")
                text.append(
                    f"{entry.status:>{_STATUS_MAX}}",
                    style=entry.status_style or "",
                )

            # Pinned indicator
            if entry.is_pinned:
                text.append("  pin", style="dim")

            text.append("\n")

        if not self._entries:
            text.append("\n    No entries\n", style="dim")

        text.append("\n")
        return text

    def on_key(self, event: Key) -> None:
        """Intercept hint keypresses for immediate jump."""
        key = event.key
        if key == "escape":
            event.prevent_default()
            self.dismiss(None)
            return

        entry = self._hint_to_entry.get(key)
        if entry is not None:
            event.prevent_default()
            self.dismiss(
                JumpAllResult(
                    tab=entry.tab,
                    index=entry.index,
                    pinned_panel_focused=entry.panel_focus,
                )
            )
            return

        # Any other key dismisses without action
        event.prevent_default()
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
