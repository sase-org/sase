"""Cross-tab jump-to-entry modal for the ace TUI.

Opens a modal showing all entries across Artifacts, Agents, and AXE tabs.
Each entry has an adaptive one- or two-character hint; completing a hint
switches to the target tab, focuses that entry, and dismisses the modal.
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

from sase.project_display_names import humanize_cl_name

from ..actions.navigation.jump_hints import (
    JumpHintMatchOutcome,
    build_jump_hint_maps,
    match_jump_hint,
    normalize_jump_key,
)
from ..bgcmd import get_slot_info
from ..models.agent_status import STOPPED_COLOR, STOPPED_STATUS
from ..widgets.bgcmd_list import BgCmdItem, ChopItem, LumberjackItem

if TYPE_CHECKING:
    from ...changespec import ChangeSpec
    from ..models import Agent
    from ..widgets.bgcmd_list import AxeItem

TabName = Literal["changespecs", "agents", "axe"]

# ── Visual constants ──────────────────────────────────────────────
_NAME_MAX = 50
_STATUS_MAX = 18
_SECTION_RULE_WIDTH = 76

# Per-tab section header colours
_TAB_STYLES: dict[TabName, tuple[str, str]] = {
    "changespecs": ("Artifacts", "#00D7AF"),
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
    STOPPED_STATUS: STOPPED_COLOR,
    "QUEUED": "#5F87FF",
    "WAITING": "#AF87FF",
    "WORKFLOW": "#AF87FF",
}


@dataclass(frozen=True)
class JumpAllResult:
    """Result returned when the user selects an entry."""

    tab: TabName
    index: int


@dataclass(frozen=True)
class _Entry:
    """Internal entry representation for display."""

    tab: TabName
    index: int
    name: str
    status: str
    status_style: str
    name_style: str = ""
    indent: int = 0


class JumpAllModal(ModalScreen[JumpAllResult | None]):
    """Modal showing all entries across tabs with adaptive jump hints."""

    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    def __init__(
        self,
        changespecs: list[ChangeSpec],
        agents: list[Agent],
        axe_items: list[AxeItem],
        last_position: JumpAllResult | None = None,
    ) -> None:
        super().__init__()
        self._entries: list[_Entry] = []
        self._hint_to_entry: dict[str, _Entry] = {}
        self._entry_to_hint: dict[_Entry, str] = {}
        self._pending_hint_prefix = ""
        self._last_position = last_position
        self._build_entries(changespecs, agents, axe_items)

    def _build_entries(
        self,
        changespecs: list[ChangeSpec],
        agents: list[Agent],
        axe_items: list[AxeItem],
    ) -> None:
        """Collect all entries and assign hint characters."""
        entries: list[_Entry] = []

        # ChangeSpecs
        _, cl_color = _TAB_STYLES["changespecs"]
        for i, cs in enumerate(changespecs):
            style = _CS_STATUS_STYLES.get(cs.status, "")
            entries.append(
                _Entry(
                    "changespecs",
                    i,
                    humanize_cl_name(cs.name),
                    cs.status,
                    style,
                    name_style=cl_color,
                )
            )

        # Agents
        _, ag_color = _TAB_STYLES["agents"]
        for idx, ag in enumerate(agents):
            style = _AGENT_STATUS_STYLES.get(ag.status, "")
            name = ag.display_name or humanize_cl_name(ag.cl_name)
            if ag.raw_suffix:
                name = f"{name}/{ag.raw_suffix}"
            entries.append(
                _Entry(
                    "agents",
                    idx,
                    name,
                    ag.status,
                    style,
                    name_style=ag_color,
                )
            )

        # AXE
        _, axe_color = _TAB_STYLES["axe"]
        for i, item in enumerate(axe_items):
            if isinstance(item, LumberjackItem):
                entries.append(
                    _Entry("axe", i, item.name, "", "", name_style=axe_color, indent=0)
                )
            elif isinstance(item, ChopItem):
                label = f"{item.lumberjack_name} / {item.chop_name}"
                entries.append(
                    _Entry("axe", i, label, "", "", name_style=axe_color, indent=1)
                )
            elif isinstance(item, BgCmdItem):
                info = get_slot_info(item.slot)
                if info is not None:
                    label = f"bgcmd #{item.slot}: {info.command}"
                else:
                    label = f"bgcmd #{item.slot}"
                entries.append(
                    _Entry(
                        "axe",
                        i,
                        label,
                        "",
                        "",
                        name_style=axe_color,
                        indent=0,
                    )
                )

        self._entries = entries

        self._hint_to_entry, self._entry_to_hint = build_jump_hint_maps(entries)

    def compose(self) -> ComposeResult:
        with Container(id="jump-all-container"):
            yield Static(self._build_title(), id="jump-all-title")
            with VerticalScroll(id="jump-all-scroll"):
                yield Static(self._build_display(), id="jump-all-content")
            yield Static(
                "press key to jump · ` back · esc cancel"
                if self._last_position
                else "press key to jump · esc cancel",
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
        """Build the Rich Text content with tabbed sections and allocated hints."""
        text = Text()
        hint_width = len(next(iter(self._hint_to_entry), "0"))

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

            hint = self._entry_to_hint.get(entry, " " * hint_width)

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

            text.append("\n")

        if not self._entries:
            text.append("\n    No entries\n", style="dim")

        text.append("\n")
        return text

    def on_key(self, event: Key) -> None:
        """Intercept hint keypresses for immediate jump."""
        key = normalize_jump_key(event.key, event.character)
        if key == "escape":
            event.prevent_default()
            event.stop()
            self._pending_hint_prefix = ""
            self.dismiss(None)
            return

        # Hidden backtick hint: jump back to previous position.
        if key == "grave_accent" and self._last_position is not None:
            event.prevent_default()
            event.stop()
            self._pending_hint_prefix = ""
            self.dismiss(self._last_position)
            return

        if key in ("ctrl+d", "ctrl+u"):
            event.prevent_default()
            event.stop()
            self._scroll_entries(direction=1 if key == "ctrl+d" else -1)
            return

        match = match_jump_hint(
            self._hint_to_entry,
            self._pending_hint_prefix,
            key,
        )
        if match.outcome is JumpHintMatchOutcome.PENDING:
            event.prevent_default()
            event.stop()
            self._pending_hint_prefix = match.prefix
            return
        if match.outcome is JumpHintMatchOutcome.COMPLETE and match.target is not None:
            entry = match.target
            event.prevent_default()
            event.stop()
            self._pending_hint_prefix = ""
            self.dismiss(JumpAllResult(tab=entry.tab, index=entry.index))
            return

        # Any other key dismisses without action
        event.prevent_default()
        event.stop()
        self._pending_hint_prefix = ""
        self.dismiss(None)

    def _scroll_entries(self, *, direction: int) -> None:
        """Scroll the entry list by half a page."""
        scroll = self.query_one("#jump-all-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=direction * (height // 2), animate=False)

    def action_close(self) -> None:
        self._pending_hint_prefix = ""
        self.dismiss(None)
