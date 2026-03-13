"""Background command list widget for the ace TUI.

Shows a list of running commands (axe + background commands) when
background commands are present.
"""

from dataclasses import dataclass
from typing import Any, Literal

from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..bgcmd import BackgroundCommandInfo, is_slot_running

# Item type: "axe" or slot number (1-9)
ItemType = Literal["axe"] | int


# --- AXE side-panel item types ---


@dataclass(frozen=True)
class AxeParentItem:
    """The main 'sase axe' parent entry."""


@dataclass(frozen=True)
class LumberjackItem:
    """A lumberjack child entry."""

    name: str


@dataclass(frozen=True)
class BgCmdItem:
    """A background command entry."""

    slot: int


AxeItem = AxeParentItem | LumberjackItem | BgCmdItem


class BgCmdList(OptionList):
    """Left sidebar showing list of AXE tab items (axe parent, lumberjacks, bgcmds)."""

    class SelectionChanged(Message):
        """Message sent when selection changes."""

        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the background command list."""
        super().__init__(**kwargs)
        self._item_count: int = 0
        self._programmatic_update: bool = False

    def update_list(
        self,
        items: list[AxeItem],
        current_idx: int,
        axe_running: bool,
        lumberjack_names: list[str],
        bgcmd_infos: dict[int, BackgroundCommandInfo],
    ) -> None:
        """Update the list with current AXE items.

        Args:
            items: Flat list of AxeItem entries to display.
            current_idx: Index of currently selected item.
            axe_running: Whether axe daemon is running.
            lumberjack_names: Lumberjack names for status lookup.
            bgcmd_infos: Mapping of slot -> info for bgcmds.
        """
        from sase.axe.state import read_lumberjack_status

        self._programmatic_update = True
        self._item_count = len(items)

        self.clear_options()

        # Count lumberjack children for the parent label
        lj_count = sum(1 for item in items if isinstance(item, LumberjackItem))

        for idx, item in enumerate(items):
            is_selected = idx == current_idx
            match item:
                case AxeParentItem():
                    option = self._format_axe_parent_option(
                        is_running=axe_running,
                        is_selected=is_selected,
                        child_count=lj_count,
                        is_expanded=lj_count > 0,
                    )
                case LumberjackItem(name=name):
                    lj_status = read_lumberjack_status(name)
                    option = self._format_lumberjack_option(
                        name=name,
                        status=lj_status,
                        is_selected=is_selected,
                    )
                case BgCmdItem(slot=slot):
                    info = bgcmd_infos.get(slot)
                    option = self._format_bgcmd_option(
                        slot=slot,
                        info=info,
                        is_selected=is_selected,
                        is_running=is_slot_running(slot),
                    )
            self.add_option(option)

        # Highlight the current item
        if 0 <= current_idx < len(items):
            self.highlighted = current_idx
        else:
            self.highlighted = 0

        # Clear flag after event loop processes pending events
        self.call_later(self._clear_programmatic_flag)

    def _clear_programmatic_flag(self) -> None:
        """Clear programmatic update flag after event processing."""
        self._programmatic_update = False

    def _format_axe_parent_option(
        self,
        is_running: bool,
        is_selected: bool,
        child_count: int,
        is_expanded: bool,
    ) -> Option:
        """Format the axe parent option for display."""
        text = Text()

        # Status indicator
        if is_running:
            text.append("[", style="dim")
            text.append("*", style="bold green")
            text.append("] ", style="dim")
        else:
            text.append("[ ] ", style="dim")

        # Label
        label_style = "bold #FFD700" if is_selected else "#FFD700"
        text.append("sase axe", style=label_style)

        # Fold annotation
        if child_count > 0 or not is_expanded:
            from sase.axe.config import load_axe_config

            config = load_axe_config()
            total_lj = len(config.lumberjacks)
            if total_lj > 0:
                fold_label = f" ({total_lj} steps)" if not is_expanded else ""
                if fold_label:
                    text.append(fold_label, style="dim")

        return Option(text, id="axe")

    def _format_lumberjack_option(
        self,
        name: str,
        status: Any,
        is_selected: bool,
    ) -> Option:
        """Format a lumberjack child option for display."""
        text = Text()

        # Indentation + tree connector
        text.append("  \u2514\u2500 ", style="dim")

        # Status indicator
        if status and status.status == "running":
            text.append("[", style="dim")
            text.append("*", style="bold green")
            text.append("] ", style="dim")
        elif status and status.status == "error":
            text.append("[", style="dim")
            text.append("!", style="bold red")
            text.append("] ", style="dim")
        else:
            text.append("[", style="dim")
            text.append("\u00b7", style="dim")
            text.append("] ", style="dim")

        # Name
        label_style = "bold #FFD700" if is_selected else "#FFD700"
        text.append(name, style=label_style)

        return Option(text, id=f"lj-{name}")

    def _format_bgcmd_option(
        self,
        slot: int,
        info: BackgroundCommandInfo | None,
        is_selected: bool,
        is_running: bool,
    ) -> Option:
        """Format a background command option for display."""
        text = Text()

        # Hideable indicator
        text.append("\u25cc ", style="bold #FF5F87")

        # Status indicator: running (*) vs done (✓)
        text.append("[", style="dim")
        if is_running:
            text.append("*", style="bold #00D7AF")
        else:
            text.append("\u2713", style="bold #FFD700")
        text.append("] ", style="dim")

        # Command (truncated)
        cmd_display = info.command if info else f"slot {slot}"
        if len(cmd_display) > 25:
            cmd_display = cmd_display[:22] + "..."
        if is_running:
            label_style = "bold #00D7AF" if is_selected else "#00D7AF"
        else:
            label_style = "bold #FFD700" if is_selected else "#FFD700"
        text.append(cmd_display, style=label_style)

        return Option(text, id=str(slot))

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Handle option highlight (keyboard navigation)."""
        if self._programmatic_update:
            return
        if (
            event.option_index is not None
            and 0 <= event.option_index < self._item_count
        ):
            self.post_message(self.SelectionChanged(event.option_index))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (mouse click or Enter)."""
        if (
            event.option_index is not None
            and 0 <= event.option_index < self._item_count
        ):
            self.post_message(self.SelectionChanged(event.option_index))
