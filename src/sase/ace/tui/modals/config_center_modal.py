"""SASE Admin Center modal: a tabbed home for config, logs, projects, tasks, updates, xprompts.

SASE Admin Center is a full-screen ``ModalScreen`` that hosts six internal
alphabetical tabs over a :class:`ContentSwitcher`:

- **Config** (tab 1, default focus on first open) — the schema-driven config
  editor skeleton (:class:`ConfigPane`); filled in by later phases.
- **Logs** (tab 2) — the canonical SASE log browser (:class:`LogsPane`), replacing
  the standalone ``,L`` modal.
- **Projects** (tab 3) — the migrated project lifecycle manager
  (:class:`ProjectsPane`), replacing the standalone ``,p`` modal.
- **Tasks** (tab 4) — the canonical background-task monitor (:class:`TasksPane`),
  replacing the standalone ``,t`` modal.
- **Updates** (tab 5) — SASE core + plugin updates
  (:class:`PluginsBrowserPane`), mirroring ``sase update`` and
  ``sase plugin list``.
- **XPrompts** (tab 6) — the migrated XPrompt Browser (:class:`XPromptBrowserPane`).

``#`` opens the modal on the last Admin Center tab used in the current app
session (Config on a fresh session). ``1``-``6`` jump directly to the matching
tab, and ``Tab`` / ``Shift+Tab`` cycle the main tabs with modulo wrapping.
Pane-local sub-tabs use ``]`` / ``[`` (currently the Projects state filters).
The clickable tab strip mirrors the app's :class:`TabBar`. A centered caption
below the tab strip describes the active tab using that tab's accent color.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Label, Static

from .config_pane import ConfigPane
from .logs_pane import LogsPane
from .plugins_browser_pane import PluginsBrowserPane
from .projects_pane import ProjectsPane
from .tasks_pane import TasksPane
from .xprompt_browser_pane import XPromptBrowserPane
from ..widgets.panel_tab_strip import PanelTab, PanelTabStrip

CenterTab = Literal["config", "logs", "projects", "tasks", "updates", "xprompts"]

_TAB_ORDER: tuple[CenterTab, ...] = (
    "config",
    "logs",
    "projects",
    "tasks",
    "updates",
    "xprompts",
)
_TAB_LABELS: list[tuple[CenterTab, str]] = [
    ("config", "Config"),
    ("logs", "Logs"),
    ("projects", "Projects"),
    ("tasks", "Tasks"),
    ("updates", "Updates"),
    ("xprompts", "XPrompts"),
]
_TAB_COLORS: dict[CenterTab, str] = {
    "config": "#00D7AF",
    "logs": "#FFD700",
    "projects": "#FFAF5F",
    "tasks": "#5FD75F",
    "updates": "#AF87FF",
    "xprompts": "#87D7FF",
}
_PANEL_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(tab, label, _TAB_COLORS[tab]) for tab, label in _TAB_LABELS
)
_TAB_DESCRIPTIONS: dict[CenterTab, str] = {
    "config": "Edit layered SASE settings with live preview",
    "logs": "Browse SASE logs and launch failures",
    "projects": "Manage project lifecycle states and claims",
    "tasks": "Monitor background tasks and live output",
    "updates": "Update SASE core and plugins with incoming commit previews",
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


def center_tab_accent(tab: str) -> str | None:
    """Return the accent color for an Admin Center tab, if it exists."""
    for candidate, color in _TAB_COLORS.items():
        if candidate == tab:
            return color
    return None


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
        Binding("tab", "next_center_tab", "Next Tab", priority=True),
        Binding("shift+tab", "prev_center_tab", "Prev Tab", priority=True),
    ]

    def __init__(
        self,
        project: str | None = None,
        *,
        initial_tab: CenterTab = "config",
        auto_update: bool = False,
    ) -> None:
        super().__init__()
        self._project = project
        self._auto_update = auto_update
        self._active_tab: CenterTab = (
            initial_tab if initial_tab in _TAB_ORDER else "config"
        )

    def compose(self) -> ComposeResult:
        with Container(id="config-center-container"):
            yield Label(
                _gradient_text(_TITLE_TEXT, bold=True), id="config-center-title"
            )
            yield Static(
                _gradient_text(_TITLE_UNDERLINE, bold=False),
                id="config-center-title-underline",
            )
            yield PanelTabStrip(
                _PANEL_TABS,
                self._active_tab,
                show_numbers=True,
                id="config-center-tabs",
            )
            yield Static(
                _tab_description_text(self._active_tab),
                id="config-center-tab-description",
            )
            yield _ConfigCenterHeaderDivider(id="config-center-divider")
            with ContentSwitcher(initial=self._active_tab, id="config-center-switcher"):
                yield ConfigPane(id="config")
                yield LogsPane(id="logs")
                yield ProjectsPane(id="projects")
                yield TasksPane(id="tasks")
                yield PluginsBrowserPane(
                    id="updates", auto_update_on_load=self._auto_update
                )
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
        """Remember the active Admin Center tab for later reopens.

        Updates the long-lived in-memory app field synchronously (so a plain
        ``#`` in this session reopens here) and delegates disk persistence off
        the Textual event loop so a fresh TUI also reopens on this tab.
        """
        try:
            self.app._admin_center_tab = self._active_tab  # type: ignore[attr-defined]
        except Exception:
            pass
        persist = getattr(self.app, "_persist_admin_center_tab", None)
        if callable(persist):
            try:
                persist(self._active_tab)
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
            strip = self.query_one("#config-center-tabs", PanelTabStrip)
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

    @on(PanelTabStrip.TabClicked)
    def _on_tab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        """Handle mouse selection of a tab."""
        event.stop()
        if event.tab_id in _TAB_ORDER:
            self._switch_to(cast(CenterTab, event.tab_id))
