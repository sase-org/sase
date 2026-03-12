"""Tab bar widget for switching between views."""

from typing import Any, Literal

from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

TabName = Literal["changespecs", "agents", "axe"]


class TabBar(Static):
    """Horizontal tab bar showing available tabs with selection indicator."""

    class TabClicked(Message):
        """Message sent when a tab is clicked."""

        def __init__(self, tab: TabName) -> None:
            super().__init__()
            self.tab = tab

    def __init__(self, **kwargs: Any) -> None:
        self._current_tab: TabName = "changespecs"
        self._cls_main_count: int = 0
        self._cls_hidden_count: int = 0
        self._cls_show_hidden: bool = False
        self._agents_manual_count: int = 0
        self._agents_hidden_count: int = 0
        self._agents_show_hidden: bool = False
        self._axe_main_count: int = 0
        self._axe_hidden_count: int = 0
        self._axe_show_hidden: bool = False
        # Store positions for click detection
        self._cl_tab_range: tuple[int, int] = (0, 0)
        self._agents_tab_range: tuple[int, int] = (0, 0)
        self._axe_tab_range: tuple[int, int] = (0, 0)
        # Initialize with content so tabline shows immediately
        super().__init__(self._build_content(), **kwargs)

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
    ) -> None:
        """Update the ChangeSpec counts shown on the CLs tab label.

        Args:
            main_count: Number of non-reverted ChangeSpecs matching query.
            hidden_count: Number of reverted/archived ChangeSpecs matching query.
            show_hidden: Whether reverted/archived are currently visible.
        """
        if (
            self._cls_main_count != main_count
            or self._cls_hidden_count != hidden_count
            or self._cls_show_hidden != show_hidden
        ):
            self._cls_main_count = main_count
            self._cls_hidden_count = hidden_count
            self._cls_show_hidden = show_hidden
            self._refresh_content()

    def update_agents_count(
        self,
        manual_count: int,
        hidden_count: int,
        *,
        show_hidden: bool,
    ) -> None:
        """Update the running agent counts shown on the Agents tab label.

        Args:
            manual_count: Number of running manual (always-visible) agents.
            hidden_count: Number of running hidden agents.
            show_hidden: Whether hidden agents are currently visible.
        """
        if (
            self._agents_manual_count != manual_count
            or self._agents_hidden_count != hidden_count
            or self._agents_show_hidden != show_hidden
        ):
            self._agents_manual_count = manual_count
            self._agents_hidden_count = hidden_count
            self._agents_show_hidden = show_hidden
            self._refresh_content()

    def update_axe_count(
        self,
        main_count: int,
        hidden_count: int,
        *,
        show_hidden: bool,
    ) -> None:
        """Update the counts shown on the AXE tab label.

        Args:
            main_count: Number of running axe lumberjacks.
            hidden_count: Number of active background commands.
            show_hidden: Whether background commands are currently visible.
        """
        if (
            self._axe_main_count != main_count
            or self._axe_hidden_count != hidden_count
            or self._axe_show_hidden != show_hidden
        ):
            self._axe_main_count = main_count
            self._axe_hidden_count = hidden_count
            self._axe_show_hidden = show_hidden
            self._refresh_content()

    def _build_content(self) -> Text:
        """Build the tab bar content."""
        text = Text()

        # CLs tab
        cl_start = 0
        m = str(self._cls_main_count) if self._cls_main_count > 0 else ""
        if self._cls_show_hidden:
            h = str(self._cls_hidden_count) if self._cls_hidden_count > 0 else ""
            cl_label = f" CLs ({m}+{h}) "
        elif self._cls_main_count > 0:
            cl_label = f" CLs ({m}) "
        else:
            cl_label = " CLs "
        cl_base = (
            "bold reverse #00D7AF" if self._current_tab == "changespecs" else "dim"
        )
        text.append(cl_label, style=cl_base)
        cl_end = len(text.plain)
        self._cl_tab_range = (cl_start, cl_end)

        text.append(" | ", style="dim #808080")

        # Agents tab
        agents_start = len(text.plain)
        m = str(self._agents_manual_count) if self._agents_manual_count > 0 else ""
        if self._agents_show_hidden:
            h = str(self._agents_hidden_count) if self._agents_hidden_count > 0 else ""
            agents_label = f" Agents ({m}+{h}) "
        elif self._agents_manual_count > 0:
            agents_label = f" Agents ({m}) "
        else:
            agents_label = " Agents "
        if self._current_tab == "agents":
            text.append(agents_label, style="bold reverse #87D7FF")
        else:
            text.append(agents_label, style="dim")
        agents_end = len(text.plain)
        self._agents_tab_range = (agents_start, agents_end)

        text.append(" | ", style="dim #808080")

        # Axe tab
        axe_start = len(text.plain)
        m = str(self._axe_main_count) if self._axe_main_count > 0 else ""
        if self._axe_show_hidden:
            h = str(self._axe_hidden_count) if self._axe_hidden_count > 0 else ""
            axe_label = f" AXE ({m}+{h}) "
        elif self._axe_main_count > 0:
            axe_label = f" AXE ({m}) "
        else:
            axe_label = " AXE "
        if self._current_tab == "axe":
            text.append(axe_label, style="bold reverse #FF5F5F")
        else:
            text.append(axe_label, style="dim")
        axe_end = len(text.plain)
        self._axe_tab_range = (axe_start, axe_end)

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
