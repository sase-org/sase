"""SASE Admin Center modal: a tabbed home for config, logs, projects, plugins, xprompts.

SASE Admin Center is a full-screen ``ModalScreen`` that hosts five internal
tabs over a :class:`ContentSwitcher`:

- **Config** (leftmost, default focus on open) — the schema-driven config
  editor skeleton (:class:`ConfigPane`); filled in by later phases.
- **Logs** — the canonical SASE log browser (:class:`LogsPane`), replacing
  the standalone ``,L`` modal. Sits immediately to the right of Config.
- **Projects** — the migrated project lifecycle manager
  (:class:`ProjectsPane`), replacing the standalone ``,p`` modal.
- **Plugins** — the read-only plugin catalog browser
  (:class:`PluginsBrowserPane`), mirroring ``sase plugin list``.
- **XPrompts** — the migrated XPrompt Browser (:class:`XPromptBrowserPane`).

``#`` opens the modal on the **Config** tab. ``[`` / ``]`` cycle the
tabs with modulo wrapping, mirroring the notification panel's sub-tab
navigation. The clickable tab strip mirrors the app's :class:`TabBar`.
"""

from __future__ import annotations

from typing import Any, Literal

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.events import Click, Key
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Label, Static

from .config_pane import ConfigPane
from .logs_pane import LogsPane
from .plugins_browser_pane import PluginsBrowserPane
from .projects_pane import ProjectsPane
from .xprompt_browser_pane import XPromptBrowserPane

CenterTab = Literal["config", "logs", "projects", "plugins", "xprompts"]

_TAB_ORDER: tuple[CenterTab, ...] = (
    "config",
    "logs",
    "projects",
    "plugins",
    "xprompts",
)
_TAB_LABELS: list[tuple[CenterTab, str]] = [
    ("config", "Config"),
    ("logs", "Logs"),
    ("projects", "Projects"),
    ("plugins", "Plugins"),
    ("xprompts", "XPrompts"),
]
_TAB_COLORS: dict[CenterTab, str] = {
    "config": "#00D7AF",
    "logs": "#FFD700",
    "projects": "#FFAF5F",
    "plugins": "#AF87FF",
    "xprompts": "#87D7FF",
}
_TITLE_TEXT = "SASE Admin Center"
_HEADER_DIVIDER_RULE = "─"
_TITLE_UNDERLINE = _HEADER_DIVIDER_RULE * len(_TITLE_TEXT)


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
            style = f"bold {_TAB_COLORS[tab]}" if is_active else "#888888"
            start = len(text.plain)
            text.append(f" {label} ", style=style)
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
        ("left_square_bracket", "prev_center_tab", "Prev Tab"),
        ("right_square_bracket", "next_center_tab", "Next Tab"),
    ]

    def __init__(
        self,
        project: str | None = None,
        *,
        initial_tab: CenterTab = "config",
    ) -> None:
        super().__init__()
        self._project = project
        self._active_tab: CenterTab = (
            initial_tab if initial_tab in _TAB_ORDER else "config"
        )

    def compose(self) -> ComposeResult:
        with Container(id="config-center-container"):
            yield Label(_TITLE_TEXT, id="config-center-title")
            yield Static(_TITLE_UNDERLINE, id="config-center-title-underline")
            yield _ConfigCenterTabStrip(self._active_tab, id="config-center-tabs")
            yield _ConfigCenterHeaderDivider(id="config-center-divider")
            with ContentSwitcher(initial=self._active_tab, id="config-center-switcher"):
                yield ConfigPane(id="config")
                yield LogsPane(id="logs")
                yield ProjectsPane(id="projects")
                yield PluginsBrowserPane(id="plugins")
                yield XPromptBrowserPane(self._project, id="xprompts")

    def on_mount(self) -> None:
        self._focus_active_pane()

    def on_key(self, event: Key) -> None:
        """Forward Logs-tab detail scroll keys when the source list has focus."""
        if self._active_tab != "logs":
            return
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
        self._focus_active_pane()

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

    @on(_ConfigCenterTabStrip.TabClicked)
    def _on_tab_clicked(self, event: _ConfigCenterTabStrip.TabClicked) -> None:
        """Handle mouse selection of a tab."""
        event.stop()
        self._switch_to(event.tab)
