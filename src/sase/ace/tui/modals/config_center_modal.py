"""SASE Admin Center modal: a tabbed home for config, operations, projects, updates, xprompts.

SASE Admin Center is a full-screen ``ModalScreen`` that hosts five internal
alphabetical tabs over a :class:`ContentSwitcher`:

- **Config** (tab 1, default focus on first open) — the schema-driven config
  editor skeleton (:class:`ConfigPane`); filled in by later phases.
- **Operations** (tab 2) — operational surfaces with nested Tasks and Logs
  sub-tabs (:class:`OperationsPane`), replacing standalone ``,t`` / ``,L``
  modals.
- **Projects** (tab 3) — the migrated project lifecycle manager
  (:class:`ProjectsPane`), replacing the standalone ``,p`` modal.
- **Updates** (tab 4) — SASE core + plugin updates
  (:class:`PluginsBrowserPane`), mirroring ``sase update`` and
  ``sase plugin list``.
- **XPrompts** (tab 5) — the migrated XPrompt Browser (:class:`XPromptBrowserPane`).

``#`` opens the modal on the last Admin Center tab used in the current app
session (Config on a fresh session). ``1``-``5`` jump directly to the matching
tab, and ``[`` / ``]`` cycle the tabs with modulo wrapping. The clickable tab
strip mirrors the app's :class:`TabBar`. A centered caption below the tab strip
describes the active tab using that tab's accent color.
"""

from __future__ import annotations

from typing import Any, Literal

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.events import Click, Key
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Label, Static

from .config_pane import ConfigPane
from .operations_pane import OperationsPane, OperationsSubTab
from .plugins_browser_pane import PluginsBrowserPane
from .projects_pane import ProjectsPane
from .xprompt_browser_pane import XPromptBrowserPane

CenterTab = Literal["config", "operations", "projects", "updates", "xprompts"]

_TAB_ORDER: tuple[CenterTab, ...] = (
    "config",
    "operations",
    "projects",
    "updates",
    "xprompts",
)
_TAB_LABELS: list[tuple[CenterTab, str]] = [
    ("config", "Config"),
    ("operations", "Operations"),
    ("projects", "Projects"),
    ("updates", "Updates"),
    ("xprompts", "XPrompts"),
]
_TAB_COLORS: dict[CenterTab, str] = {
    "config": "#00D7AF",
    "operations": "#5FD75F",
    "projects": "#FFAF5F",
    "updates": "#AF87FF",
    "xprompts": "#87D7FF",
}
_TAB_DESCRIPTIONS: dict[CenterTab, str] = {
    "config": "Edit layered SASE settings with live preview",
    "operations": "Monitor background tasks and browse SASE logs",
    "projects": "Manage project lifecycle states and claims",
    "updates": "Update SASE core and installed plugins",
    "xprompts": "Browse and preview xprompt definitions",
}
_TITLE_LABEL = "SASE Admin Center"
_TITLE_TEXT = _TITLE_LABEL
_HEADER_DIVIDER_RULE = "─"
_TITLE_RULE_CHAR = "━"
_TITLE_UNDERLINE = _TITLE_RULE_CHAR * len(_TITLE_TEXT)
# Aurora accent gradient (aqua -> cyan -> sky -> indigo -> violet) swept
# across the Admin Center header title and its rule. Vivid on the dark surface
# and a deliberate tie-in to the colorful tab palette directly below it. The
# first stop doubles as the panel border color (see ``ConfigCenterModal >
# Container`` in styles.tcss).
_TITLE_GRADIENT: tuple[str, ...] = (
    "#2BE7C7",
    "#36CFEC",
    "#4FB6FF",
    "#7E8BFF",
    "#B98CFF",
)


def _gradient_color(stops: tuple[str, ...], position: float) -> str:
    """Sample a left-to-right gradient of hex ``stops`` at ``position`` in [0, 1]."""
    if position <= 0.0:
        return stops[0]
    if position >= 1.0:
        return stops[-1]
    span = position * (len(stops) - 1)
    index = int(span)
    local = span - index
    start, end = stops[index], stops[index + 1]
    channels = (
        round(
            int(start[i : i + 2], 16)
            + (int(end[i : i + 2], 16) - int(start[i : i + 2], 16)) * local
        )
        for i in (1, 3, 5)
    )
    return "#" + "".join(f"{value:02X}" for value in channels)


def _gradient_text(content: str, *, bold: bool) -> Text:
    """Render ``content`` with a per-character sweep of :data:`_TITLE_GRADIENT`."""
    text = Text()
    divisor = max(1, len(content) - 1)
    for index, char in enumerate(content):
        color = _gradient_color(_TITLE_GRADIENT, index / divisor)
        text.append(char, style=f"bold {color}" if bold else color)
    return text


def _tab_description_text(tab: CenterTab) -> Text:
    """Render the Admin Center caption for ``tab`` in its accent color."""
    return Text(f"› {_TAB_DESCRIPTIONS[tab]}", style=_TAB_COLORS[tab])


class _ConfigCenterTabStrip(Static):
    """Clickable one-line tab strip for the SASE Admin Center modal."""

    class TabClicked(Message):
        """Message emitted when a tab is clicked."""

        def __init__(self, tab: CenterTab) -> None:
            super().__init__()
            self.tab: CenterTab = tab

    def __init__(self, active_tab: CenterTab, **kwargs: Any) -> None:
        self._active_tab: CenterTab = active_tab
        self._tab_ranges: dict[CenterTab, tuple[int, int]] = {}
        self._line_width = 0
        super().__init__(self._build_content(), **kwargs)

    def set_active_tab(self, active_tab: CenterTab) -> None:
        """Refresh the active tab indicator."""
        self._active_tab = active_tab
        self.update(self._build_content())

    def _build_content(self) -> Text:
        text = Text()
        self._tab_ranges.clear()
        for index, (tab, label) in enumerate(_TAB_LABELS):
            if index > 0:
                text.append(" │ ", style="#444444")
            is_active = tab == self._active_tab
            number_style = _TAB_COLORS[tab] if is_active else "#666666"
            label_style = f"bold {_TAB_COLORS[tab]}" if is_active else "#888888"
            start = len(text.plain)
            text.append(f" {index + 1} ", style=number_style)
            text.append(f"{label} ", style=label_style)
            self._tab_ranges[tab] = (start, len(text.plain))
        self._line_width = len(text.plain)
        return text

    def on_click(self, event: Click) -> None:
        content_width = max(0, int(self.size.width))
        center_pad = max(0, (content_width - self._line_width) // 2)
        x = event.x - center_pad
        for tab, (start, end) in self._tab_ranges.items():
            if start <= x < end:
                if tab != self._active_tab:
                    self.post_message(self.TabClicked(tab))
                return


class _ConfigCenterHeaderDivider(Static):
    """Width-aware divider between the SASE Admin Center header and content."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)

    def render(self) -> Text:
        width = max(0, int(self.size.width))
        return Text(_HEADER_DIVIDER_RULE * width, style="#444444")


class ConfigCenterModal(ModalScreen[None]):
    """Full-screen modal hosting the Admin Center tabs."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        Binding("1", "focus_center_tab(1)", "Tab 1", show=False),
        Binding("2", "focus_center_tab(2)", "Tab 2", show=False),
        Binding("3", "focus_center_tab(3)", "Tab 3", show=False),
        Binding("4", "focus_center_tab(4)", "Tab 4", show=False),
        Binding("5", "focus_center_tab(5)", "Tab 5", show=False),
        Binding("6", "focus_center_tab(6)", "Tab 6", show=False),
        Binding("7", "focus_center_tab(7)", "Tab 7", show=False),
        Binding("8", "focus_center_tab(8)", "Tab 8", show=False),
        Binding("9", "focus_center_tab(9)", "Tab 9", show=False),
        Binding("0", "focus_center_tab(0)", "Tab 0", show=False),
        ("left_square_bracket", "prev_center_tab", "Prev Tab"),
        ("right_square_bracket", "next_center_tab", "Next Tab"),
    ]

    def __init__(
        self,
        project: str | None = None,
        *,
        initial_tab: CenterTab = "config",
        initial_operations_subtab: OperationsSubTab | None = None,
    ) -> None:
        super().__init__()
        self._project = project
        self._active_tab: CenterTab = (
            initial_tab if initial_tab in _TAB_ORDER else "config"
        )
        self._initial_operations_subtab = initial_operations_subtab

    def compose(self) -> ComposeResult:
        with Container(id="config-center-container"):
            yield Label(
                _gradient_text(_TITLE_TEXT, bold=True), id="config-center-title"
            )
            yield Static(
                _gradient_text(_TITLE_UNDERLINE, bold=False),
                id="config-center-title-underline",
            )
            yield _ConfigCenterTabStrip(self._active_tab, id="config-center-tabs")
            yield Static(
                _tab_description_text(self._active_tab),
                id="config-center-tab-description",
            )
            yield _ConfigCenterHeaderDivider(id="config-center-divider")
            with ContentSwitcher(initial=self._active_tab, id="config-center-switcher"):
                yield ConfigPane(id="config")
                yield OperationsPane(
                    initial_subtab=self._initial_operations_subtab,
                    id="operations",
                )
                yield ProjectsPane(id="projects")
                yield PluginsBrowserPane(id="updates")
                yield XPromptBrowserPane(self._project, id="xprompts")

    def on_mount(self) -> None:
        self._remember_active_tab()
        self._focus_active_pane()

    def on_key(self, event: Key) -> None:
        """Forward active-pane detail scroll keys when a source list has focus."""
        character = getattr(event, "character", None)
        pane = self._active_pane()
        if event.key in ("G", "shift+g") or character == "G":
            scroll_to_bottom = getattr(pane, "action_scroll_to_bottom", None)
            if callable(scroll_to_bottom):
                event.prevent_default()
                event.stop()
                scroll_to_bottom()
        elif event.key == "g":
            scroll_to_top = getattr(pane, "action_scroll_to_top", None)
            if callable(scroll_to_top):
                event.prevent_default()
                event.stop()
                scroll_to_top()

    def _active_pane(self) -> Widget | None:
        """Return the currently visible pane widget."""
        try:
            return self.query_one(f"#{self._active_tab}", Widget)
        except Exception:
            return None

    def _focus_active_pane(self) -> None:
        pane = self._active_pane()
        focus_default = getattr(pane, "focus_default", None)
        if callable(focus_default):
            focus_default()

    def _remember_active_tab(self) -> None:
        """Persist the active Admin Center tab on the long-lived app."""
        try:
            self.app._admin_center_tab = self._active_tab  # type: ignore[attr-defined]
        except Exception:
            pass

    def _switch_to(self, tab: CenterTab) -> None:
        if tab == self._active_tab:
            return
        self._active_tab = tab
        try:
            switcher = self.query_one("#config-center-switcher", ContentSwitcher)
            switcher.current = tab
        except Exception:
            return
        try:
            strip = self.query_one("#config-center-tabs", _ConfigCenterTabStrip)
            strip.set_active_tab(tab)
        except Exception:
            pass
        try:
            description = self.query_one("#config-center-tab-description", Static)
            description.update(_tab_description_text(tab))
        except Exception:
            pass
        self._focus_active_pane()
        self._remember_active_tab()

    def action_close(self) -> None:
        """Close SASE Admin Center."""
        self.dismiss(None)

    def action_prev_center_tab(self) -> None:
        """Switch to the previous tab (wrapping)."""
        if len(_TAB_ORDER) <= 1:
            return
        index = _TAB_ORDER.index(self._active_tab)
        self._switch_to(_TAB_ORDER[(index - 1) % len(_TAB_ORDER)])

    def action_next_center_tab(self) -> None:
        """Switch to the next tab (wrapping)."""
        if len(_TAB_ORDER) <= 1:
            return
        index = _TAB_ORDER.index(self._active_tab)
        self._switch_to(_TAB_ORDER[(index + 1) % len(_TAB_ORDER)])

    def action_focus_center_tab(self, number: int) -> None:
        """Switch directly to the numbered tab; out-of-range digits are ignored."""
        if not 1 <= number <= len(_TAB_ORDER):
            return
        self._switch_to(_TAB_ORDER[number - 1])

    @on(_ConfigCenterTabStrip.TabClicked)
    def _on_tab_clicked(self, event: _ConfigCenterTabStrip.TabClicked) -> None:
        """Handle mouse selection of a tab."""
        event.stop()
        self._switch_to(event.tab)
