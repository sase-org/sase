"""Tab bar widget for switching between views."""

from typing import Any, Literal

from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from ..keymaps import KeymapRegistry, key_display_name, load_keymap_registry

TabName = Literal["changespecs", "agents", "axe"]


class TabBar(Static):
    """Horizontal tab bar showing available tabs with selection indicator."""

    class TabClicked(Message):
        """Message sent when a tab is clicked."""

        def __init__(self, tab: TabName) -> None:
            super().__init__()
            self.tab = tab

    def __init__(self, **kwargs: Any) -> None:
        self._registry = load_keymap_registry({})
        self._current_tab: TabName = "changespecs"
        self._cls_main_count: int = 0
        self._cls_hidden_count: int = 0
        self._cls_show_hidden: bool = False
        self._cls_submitted_count: int = 0
        self._cls_show_submitted: bool = False
        self._agents_manual_count: int = 0
        self._agents_hidden_count: int = 0
        self._agents_done_count: int = 0
        self._agents_show_hidden: bool = False
        self._axe_main_count: int = 0
        self._axe_hidden_count: int = 0
        self._axe_done_count: int = 0
        self._axe_show_hidden: bool = False
        # Store positions for click detection
        self._cl_tab_range: tuple[int, int] = (0, 0)
        self._agents_tab_range: tuple[int, int] = (0, 0)
        self._axe_tab_range: tuple[int, int] = (0, 0)
        # Initialize with content so tabline shows immediately
        super().__init__(self._build_content(), **kwargs)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Override the keymap registry and refresh display."""
        self._registry = registry
        self._refresh_content()

    def update_tab(self, tab: TabName) -> None:
        """Update the displayed active tab.

        Args:
            tab: The tab to mark as active.
        """
        self._current_tab = tab
        self._refresh_content()

    def update_cls_count(
        self,
        main_count: int,
        hidden_count: int,
        *,
        show_hidden: bool,
        submitted_count: int = 0,
        show_submitted: bool = False,
    ) -> None:
        """Update the ChangeSpec counts shown on the CLs tab label.

        Args:
            main_count: Number of non-reverted/non-submitted ChangeSpecs matching query.
            hidden_count: Number of reverted/archived ChangeSpecs matching query.
            show_hidden: Whether reverted/archived are currently visible.
            submitted_count: Number of submitted ChangeSpecs matching query.
            show_submitted: Whether submitted are currently visible.
        """
        if (
            self._cls_main_count != main_count
            or self._cls_hidden_count != hidden_count
            or self._cls_show_hidden != show_hidden
            or self._cls_submitted_count != submitted_count
            or self._cls_show_submitted != show_submitted
        ):
            self._cls_main_count = main_count
            self._cls_hidden_count = hidden_count
            self._cls_show_hidden = show_hidden
            self._cls_submitted_count = submitted_count
            self._cls_show_submitted = show_submitted
            self._refresh_content()

    def update_agents_count(
        self,
        manual_count: int,
        hidden_count: int,
        *,
        show_hidden: bool,
        done_count: int = 0,
    ) -> None:
        """Update the running agent counts shown on the Agents tab label.

        Args:
            manual_count: Number of running manual (always-visible) agents.
            hidden_count: Number of running hidden agents.
            show_hidden: Whether hidden agents are currently visible.
            done_count: Number of done agents not yet dismissed.
        """
        if (
            self._agents_manual_count != manual_count
            or self._agents_hidden_count != hidden_count
            or self._agents_done_count != done_count
            or self._agents_show_hidden != show_hidden
        ):
            self._agents_manual_count = manual_count
            self._agents_hidden_count = hidden_count
            self._agents_done_count = done_count
            self._agents_show_hidden = show_hidden
            self._refresh_content()

    def update_axe_count(
        self,
        main_count: int,
        hidden_count: int,
        *,
        show_hidden: bool,
        done_count: int = 0,
    ) -> None:
        """Update the counts shown on the AXE tab label.

        Args:
            main_count: Number of running axe lumberjacks.
            hidden_count: Number of active background commands.
            show_hidden: Whether background commands are currently visible.
            done_count: Number of completed background commands.
        """
        if (
            self._axe_main_count != main_count
            or self._axe_hidden_count != hidden_count
            or self._axe_done_count != done_count
            or self._axe_show_hidden != show_hidden
        ):
            self._axe_main_count = main_count
            self._axe_hidden_count = hidden_count
            self._axe_done_count = done_count
            self._axe_show_hidden = show_hidden
            self._refresh_content()

    def _append_tab_with_suffix(
        self,
        text: Text,
        name: str,
        main_count: int,
        key_counts: list[tuple[str, int]],
        active_color: str,
        is_active: bool,
    ) -> tuple[int, int]:
        """Append a styled tab label with suffix counts.

        Active tabs use bold colored text; inactive tabs are muted gray.
        Key hint characters use a dimmer shade to distinguish them from
        count digits (e.g. ``5 D2 .1`` reads as "5 items, D-dismiss 2,
        .-toggle 1").

        Returns:
            (start, end) character positions for click detection.
        """
        start = len(text.plain)
        key_counts = [(k, c) for k, c in key_counts if c > 0]
        has_suffix = main_count > 0 or len(key_counts) > 0

        if is_active:
            name_style = f"bold {active_color}"
            count_style = active_color
            hint_style = f"dim {active_color}"
        else:
            name_style = "#888888"
            count_style = "#707070"
            hint_style = "#505050"

        text.append(f" {name}", style=name_style)

        if has_suffix:
            text.append(" (", style=hint_style)
            if main_count > 0:
                text.append(str(main_count), style=count_style)
            for i, (key, count) in enumerate(key_counts):
                if main_count > 0 or i > 0:
                    text.append(" ", style="")
                text.append(key, style=hint_style)
                text.append(str(count), style=count_style)
            text.append(")", style=hint_style)

        text.append(" ", style="")
        end = len(text.plain)
        return (start, end)

    def _build_content(self) -> Text:
        """Build the tab bar content."""
        text = Text()
        dismiss_key = key_display_name(self._registry.app.kill_agent)
        hide_key = key_display_name(self._registry.app.toggle_hide_reverted)
        submitted_key = key_display_name(self._registry.app.toggle_hide_submitted)

        # CLs tab
        cls_key_counts: list[tuple[str, int]] = []
        if self._cls_show_submitted:
            cls_key_counts.append((submitted_key, self._cls_submitted_count))
        if self._cls_show_hidden:
            cls_key_counts.append((hide_key, self._cls_hidden_count))
        self._cl_tab_range = self._append_tab_with_suffix(
            text,
            "CLs",
            self._cls_main_count,
            cls_key_counts,
            "#00D7AF",
            self._current_tab == "changespecs",
        )

        text.append(" │ ", style="#444444")

        # Agents tab
        agents_key_counts: list[tuple[str, int]] = [
            (dismiss_key, self._agents_done_count),
        ]
        if self._agents_show_hidden:
            agents_key_counts.append((hide_key, self._agents_hidden_count))
        self._agents_tab_range = self._append_tab_with_suffix(
            text,
            "Agents",
            self._agents_manual_count,
            agents_key_counts,
            "#87D7FF",
            self._current_tab == "agents",
        )

        text.append(" │ ", style="#444444")

        # AXE tab
        axe_key_counts: list[tuple[str, int]] = [
            (dismiss_key, self._axe_done_count),
        ]
        if self._axe_show_hidden:
            axe_key_counts.append((hide_key, self._axe_hidden_count))
        self._axe_tab_range = self._append_tab_with_suffix(
            text,
            "AXE",
            self._axe_main_count,
            axe_key_counts,
            "#FF5F5F",
            self._current_tab == "axe",
        )

        return text

    def _refresh_content(self) -> None:
        """Refresh the tab bar display."""
        # Only update if mounted (avoid errors in unit tests)
        if self.is_mounted:
            self.update(self._build_content())

    def on_click(self, event: Click) -> None:
        """Handle click events to switch tabs."""
        # Get the x coordinate of the click
        x = event.x

        if self._cl_tab_range[0] <= x < self._cl_tab_range[1]:
            if self._current_tab != "changespecs":
                self.post_message(self.TabClicked("changespecs"))
        elif self._agents_tab_range[0] <= x < self._agents_tab_range[1]:
            if self._current_tab != "agents":
                self.post_message(self.TabClicked("agents"))
        elif self._axe_tab_range[0] <= x < self._axe_tab_range[1]:
            if self._current_tab != "axe":
                self.post_message(self.TabClicked("axe"))
