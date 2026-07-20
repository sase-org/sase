"""Home-first SASE Admin Center with lazily mounted working panes.

The first unqualified ``#`` action opens a lightweight landing page. Repeating
the configured opener resumes the last section used in this ACE process. The
seven alphabetical working tabs are otherwise created only when the user
explicitly enters one with ``1``-``7``, ``Tab`` / ``Shift+Tab``, or the
clickable tab strip. Mounted panes are cached for the lifetime of the modal,
so returning to a tab preserves its selection and other pane-local state.

Direct-entry actions may still pass ``initial_tab`` to open exactly one pane.
Pane-local sub-tabs continue to use ``]`` / ``[`` where provided.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingsMap
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Click, Key, Resize
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Label, Static

from ..keymaps import is_valid_key, key_display_name
from ..widgets.panel_tab_strip import PanelTab, PanelTabStrip

CenterTab = Literal[
    "config", "logs", "projects", "statistics", "tasks", "updates", "xprompts"
]
PaneFactory = Callable[["ConfigCenterModal"], Widget]


@dataclass(frozen=True)
class _CenterTabSpec:
    """Immutable navigation and construction metadata for one working tab."""

    id: CenterTab
    number: int
    label: str
    accent: str
    description: str
    pane_identity: str
    factory: PaneFactory


def _config_pane_factory(modal: ConfigCenterModal) -> Widget:
    from .config_pane import ConfigPane

    return ConfigPane(project=modal._project, id="config")


def _logs_pane_factory(_modal: ConfigCenterModal) -> Widget:
    from .logs_pane import LogsPane

    return LogsPane(id="logs")


def _projects_pane_factory(_modal: ConfigCenterModal) -> Widget:
    from .projects_pane import ProjectsPane

    return ProjectsPane(id="projects")


def _statistics_pane_factory(modal: ConfigCenterModal) -> Widget:
    from .statistics_pane import StatisticsPane

    registry = getattr(modal.app, "_keymap_registry", None)
    keymaps = getattr(registry, "statistics", None)
    return StatisticsPane(id="statistics", keymaps=keymaps)


def _tasks_pane_factory(_modal: ConfigCenterModal) -> Widget:
    from .tasks_pane import TasksPane

    return TasksPane(id="tasks")


def _updates_pane_factory(modal: ConfigCenterModal) -> Widget:
    from .plugins_browser_pane import PluginsBrowserPane

    return PluginsBrowserPane(
        id="updates",
        auto_update_on_load=modal._auto_update,
        comprehensive_provider_names=modal._comprehensive_provider_names,
    )


def _xprompts_pane_factory(modal: ConfigCenterModal) -> Widget:
    from .xprompt_browser_pane import XPromptBrowserPane

    return XPromptBrowserPane(modal._project, id="xprompts")


_TAB_SPECS: tuple[_CenterTabSpec, ...] = (
    _CenterTabSpec(
        "config",
        1,
        "Config",
        "#00D7AF",
        "Review and edit layered SASE settings with provenance and live previews.",
        "ConfigPane",
        _config_pane_factory,
    ),
    _CenterTabSpec(
        "logs",
        2,
        "Logs",
        "#FFD700",
        "Inspect TUI activity, launch failures, and notification history.",
        "LogsPane",
        _logs_pane_factory,
    ),
    _CenterTabSpec(
        "projects",
        3,
        "Projects",
        "#FFAF5F",
        "Manage projects and inspect their repositories and workspaces.",
        "ProjectsPane",
        _projects_pane_factory,
    ),
    _CenterTabSpec(
        "statistics",
        4,
        "Statistics",
        "#FF87D7",
        "Explore agent activity, runtime, outcomes, and trends over time.",
        "StatisticsPane",
        _statistics_pane_factory,
    ),
    _CenterTabSpec(
        "tasks",
        5,
        "Tasks",
        "#5FD75F",
        "Follow background work, inspect live output, and manage running jobs.",
        "TasksPane",
        _tasks_pane_factory,
    ),
    _CenterTabSpec(
        "updates",
        6,
        "Updates",
        "#AF87FF",
        "Update SASE, plugins, and supported agent CLIs from one place.",
        "PluginsBrowserPane",
        _updates_pane_factory,
    ),
    _CenterTabSpec(
        "xprompts",
        7,
        "XPrompts",
        "#87D7FF",
        "Find, preview, and load reusable prompts and workflows.",
        "XPromptBrowserPane",
        _xprompts_pane_factory,
    ),
)
_TAB_BY_ID: dict[CenterTab, _CenterTabSpec] = {spec.id: spec for spec in _TAB_SPECS}
_TAB_BY_NUMBER: dict[int, _CenterTabSpec] = {spec.number: spec for spec in _TAB_SPECS}
_TAB_ORDER: tuple[CenterTab, ...] = tuple(spec.id for spec in _TAB_SPECS)
_TAB_LABELS: list[tuple[CenterTab, str]] = [
    (spec.id, spec.label) for spec in _TAB_SPECS
]
_TAB_COLORS: dict[CenterTab, str] = {spec.id: spec.accent for spec in _TAB_SPECS}
_TAB_DESCRIPTIONS: dict[CenterTab, str] = {
    spec.id: spec.description for spec in _TAB_SPECS
}
_PANEL_TABS: tuple[PanelTab, ...] = tuple(
    PanelTab(spec.id, spec.label, spec.accent) for spec in _TAB_SPECS
)

_HOME_ID = "admin-center-home"
_HOME_LEAD = "Choose a section"
_HOME_ORIENTATION = "Configure, observe, and maintain SASE from one place."
_HOME_HINT_NAV = "1-7 or click a section · Tab/Shift+Tab cycle · q/Esc close"
_HOME_HINT_NAV_COMPACT = "1-7/click · Tab cycle · q/Esc close"
_HOME_LABEL_WIDTH = max(len(spec.label) for spec in _TAB_SPECS)
_HOME_DESCRIPTION_WIDTH = max(len(spec.description) for spec in _TAB_SPECS)
_HOME_ROOMY_ROW_WIDTH = 3 + 2 + _HOME_LABEL_WIDTH + 1 + _HOME_DESCRIPTION_WIDTH
_HOME_COMPACT_ROW_WIDTH = 1 + 2 + _HOME_LABEL_WIDTH + 1 + _HOME_DESCRIPTION_WIDTH
_HOME_COMPACT_BELOW_WIDTH = 96
_HOME_COMPACT_BELOW_HEIGHT = 14
_TITLE_LABEL = "SASE Admin Center"
_TITLE_TEXT = _TITLE_LABEL
_HEADER_DIVIDER_RULE = "─"
_TITLE_RULE_CHAR = "━"
_TITLE_UNDERLINE = _TITLE_RULE_CHAR * len(_TITLE_TEXT)
# Aurora accent gradient (aqua -> cyan -> sky -> indigo -> violet) swept
# across the Admin Center header title and its rule. The first stop doubles as
# the panel border color in styles.tcss.
_TITLE_GRADIENT: tuple[str, ...] = (
    "#2BE7C7",
    "#36CFEC",
    "#4FB6FF",
    "#7E8BFF",
    "#B98CFF",
)


def _gradient_color(stops: tuple[str, ...], position: float) -> str:
    """Sample a left-to-right gradient of hex ``stops`` at ``position``."""
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
    """Render ``content`` with a per-character aurora sweep."""
    text = Text()
    divisor = max(1, len(content) - 1)
    for index, char in enumerate(content):
        color = _gradient_color(_TITLE_GRADIENT, index / divisor)
        text.append(char, style=f"bold {color}" if bold else color)
    return text


def _tab_description_text(tab: CenterTab) -> Text:
    """Render the active-tab caption in its accent color."""
    spec = _TAB_BY_ID[tab]
    return Text(f"› {spec.description}", style=spec.accent)


def _home_lead_text() -> Text:
    """Render the landing-page lead with the Admin Center aurora sweep."""
    return _gradient_text(_HOME_LEAD, bold=True)


def _home_orientation_text() -> Text:
    """Render the muted orientation caption shown while home is active."""
    return Text(_HOME_ORIENTATION, style="#888888")


def _landing_key_text(spec: _CenterTabSpec, *, compact: bool) -> Text:
    """Render one roomy or compact reversed numeric key chip."""
    key = str(spec.number) if compact else f" {spec.number} "
    return Text(key, style=f"bold reverse {spec.accent}")


def _landing_label_text(spec: _CenterTabSpec) -> Text:
    """Render one catalog label padded to the shared landing column."""
    return Text(
        f"{spec.label:<{_HOME_LABEL_WIDTH}}",
        style=f"bold {spec.accent}",
    )


def center_tab_accent(tab: str) -> str | None:
    """Return the accent color for an Admin Center tab, if it exists."""
    spec = _TAB_BY_ID.get(cast(Any, tab))
    return spec.accent if spec is not None else None


def validated_center_tab(value: object) -> CenterTab | None:
    """Return a catalog-backed Admin Center tab identity, if valid."""
    if isinstance(value, str) and value in _TAB_BY_ID:
        return cast(CenterTab, value)
    return None


def _home_hint_text(
    resume_tab: CenterTab | None,
    opener_binding: str,
    *,
    compact: bool,
) -> Text:
    """Render the landing's one-row, catalog-derived resume affordance."""
    spec = _TAB_BY_ID.get(resume_tab) if resume_tab is not None else None
    accent = spec.accent if spec is not None else _TITLE_GRADIENT[0]
    navigation = _HOME_HINT_NAV_COMPACT if compact or spec is None else _HOME_HINT_NAV

    text = Text()
    text.append(f" {key_display_name(opener_binding)} ", style=f"bold reverse {accent}")
    if spec is None:
        resume_copy = (
            " resumes after first visit"
            if compact
            else " resumes after your first section visit"
        )
        text.append(resume_copy, style="#A0A0A0")
    else:
        text.append(f" resume {spec.label}", style=f"bold {spec.accent}")
    text.append(f" · {navigation}", style="#777777")
    return text


class _ConfigCenterHeaderDivider(Static):
    """Width-aware divider between the SASE Admin Center header and content."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)

    def render(self) -> Text:
        width = max(0, int(self.size.width))
        return Text(_HEADER_DIVIDER_RULE * width, style="#444444")


class _AdminCenterLandingRow(Horizontal):
    """Catalog-derived, mouse-clickable, keyboard-transparent home row."""

    can_focus = False

    def __init__(self, spec: _CenterTabSpec) -> None:
        super().__init__(
            id=f"admin-center-home-row-{spec.id}",
            classes="admin-center-home-row",
        )
        self._spec = spec
        self._compact = False
        self.styles.width = _HOME_ROOMY_ROW_WIDTH

    def compose(self) -> ComposeResult:
        yield Static(
            _landing_key_text(self._spec, compact=self._compact),
            classes="admin-center-home-row-key",
            markup=False,
        )
        yield Static(
            _landing_label_text(self._spec),
            classes="admin-center-home-row-label",
            markup=False,
        )
        yield Static(
            self._spec.description,
            classes="admin-center-home-row-description",
        )

    def set_compact(self, compact: bool) -> None:
        """Repaint the key chip after the landing's synchronous reflow."""
        if compact == self._compact:
            return
        self._compact = compact
        self.styles.width = (
            _HOME_COMPACT_ROW_WIDTH if compact else _HOME_ROOMY_ROW_WIDTH
        )
        key = self.query_one(".admin-center-home-row-key", Static)
        key.update(_landing_key_text(self._spec, compact=compact))

    def on_click(self, event: Click) -> None:
        """Open this row through the modal's shared navigation path."""
        event.stop()
        modal = self.screen
        if isinstance(modal, ConfigCenterModal):
            modal._schedule_switch(self._spec.id)


class _AdminCenterLanding(VerticalScroll):
    """Pure, bounded presentation-only home view."""

    can_focus = False

    def __init__(
        self,
        resume_tab: CenterTab | None,
        opener_binding: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._resume_tab = resume_tab
        self._opener_binding = opener_binding
        self._compact: bool | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="admin-center-home-hero"):
            yield Static(
                _home_lead_text(),
                id="admin-center-home-lead",
                markup=False,
            )
            with Vertical(id="admin-center-home-card"):
                for spec in _TAB_SPECS:
                    yield _AdminCenterLandingRow(spec)
            yield Static(
                _home_hint_text(
                    self._resume_tab,
                    self._opener_binding,
                    compact=False,
                ),
                id="admin-center-home-hint",
                markup=False,
            )

    def on_resize(self, event: Resize) -> None:
        """Toggle compact home chrome with bounded synchronous work."""
        compact = (
            event.size.width < _HOME_COMPACT_BELOW_WIDTH
            or event.size.height < _HOME_COMPACT_BELOW_HEIGHT
        )
        if compact == self._compact:
            return
        self._compact = compact
        self.set_class(compact, "-compact")
        for row in self.query(_AdminCenterLandingRow):
            row.set_compact(compact)
        self.query_one("#admin-center-home-hint", Static).update(
            _home_hint_text(
                self._resume_tab,
                self._opener_binding,
                compact=compact,
            )
        )


class ConfigCenterModal(ModalScreen[CenterTab | None]):
    """Full-screen Admin Center home and lazy working-pane host."""

    _blocks_global_config_center_open = True

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
        initial_tab: CenterTab | None = None,
        resume_tab: CenterTab | None = None,
        opener_binding: str = "number_sign",
        auto_update: bool = False,
        comprehensive_provider_names: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__()
        self._project = project
        self._auto_update = auto_update
        self._comprehensive_provider_names = comprehensive_provider_names
        self._initial_tab = validated_center_tab(initial_tab)
        self._resume_tab = validated_center_tab(resume_tab)
        self._opener_binding = (
            opener_binding
            if isinstance(opener_binding, str) and is_valid_key(opener_binding)
            else "number_sign"
        )
        # Put the modal-local opener first so a custom binding that overlaps
        # another modal key (for example Tab or q) still means "resume" while
        # home is visible.  ``check_action`` disables it on working panes.
        self._bindings = BindingsMap(
            [
                Binding(
                    self._opener_binding,
                    "resume_last_tab",
                    "Resume last section",
                    show=False,
                    priority=True,
                ),
                *self.BINDINGS,
            ]
        )
        self._active_tab: CenterTab | None = None
        self._panes: dict[CenterTab, Widget] = {}
        self._navigation_lock = asyncio.Lock()
        self._initial_navigation_pending = self._initial_tab is not None

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
                None,
                show_numbers=True,
                compact_below=95,
                id="config-center-tabs",
            )
            yield Static(
                _home_orientation_text(),
                id="config-center-tab-description",
            )
            yield _ConfigCenterHeaderDivider(id="config-center-divider")
            with ContentSwitcher(initial=_HOME_ID, id="config-center-switcher"):
                yield _AdminCenterLanding(
                    self._resume_tab,
                    self._opener_binding,
                    id=_HOME_ID,
                )

    def on_mount(self) -> None:
        if self._initial_tab is not None:
            self.run_worker(
                self._open_initial_tab(self._initial_tab),
                name=f"admin-center-open-{self._initial_tab}",
                group="admin-center-navigation",
            )

    def on_unmount(self) -> None:
        self._set_pane_active(self._active_pane(), False)

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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Make the configured opener a home-only modal action."""
        if action == "resume_last_tab":
            return self._active_tab is None and not self._initial_navigation_pending
        return super().check_action(action, parameters)

    def _active_pane(self) -> Widget | None:
        """Return the stable, currently visible working pane."""
        if self._active_tab is None:
            return None
        return self._panes.get(self._active_tab)

    def _create_pane(self, tab: CenterTab) -> Widget:
        """Construct one requested pane through the immutable tab catalog."""
        return _TAB_BY_ID[tab].factory(self)

    def _focus_active_pane(self) -> None:
        pane = self._active_pane()
        focus_default = getattr(pane, "focus_default", None)
        if callable(focus_default):
            focus_default()

    @staticmethod
    def _set_pane_active(pane: Widget | None, active: bool) -> None:
        visibility_changed = getattr(pane, "on_center_tab_visibility_changed", None)
        if callable(visibility_changed):
            visibility_changed(active)

    def _schedule_switch(self, tab: CenterTab) -> None:
        """Run navigation outside Textual's serial message-pump callback."""
        self.run_worker(
            self._switch_to(tab),
            name=f"admin-center-open-{tab}",
            group="admin-center-navigation",
        )

    async def _open_initial_tab(self, tab: CenterTab) -> None:
        """Finish direct entry before enabling the home resume binding."""
        try:
            await self._switch_to(tab)
        finally:
            self._initial_navigation_pending = False

    async def _remove_failed_pane(self, pane: Widget) -> None:
        """Best-effort cleanup after a failed mount so a retry can reuse the ID."""
        try:
            if pane.parent is not None:
                await pane.remove()
        except Exception:
            pass

    async def _ensure_pane(self, tab: CenterTab) -> Widget:
        cached = self._panes.get(tab)
        if cached is not None:
            return cached

        pane = self._create_pane(tab)
        try:
            switcher = self.query_one("#config-center-switcher", ContentSwitcher)
            await switcher.add_content(pane)
        except Exception:
            await self._remove_failed_pane(pane)
            raise
        self._panes[tab] = pane
        return pane

    def _sync_header(self, tab: CenterTab | None) -> None:
        strip = self.query_one("#config-center-tabs", PanelTabStrip)
        strip.set_active_tab(tab)
        description = self.query_one("#config-center-tab-description", Static)
        description.update(
            _home_orientation_text() if tab is None else _tab_description_text(tab)
        )

    async def _switch_to(self, tab: CenterTab) -> bool:
        """Mount and select ``tab`` once, preserving a stable view on failure."""
        async with self._navigation_lock:
            if tab == self._active_tab and tab in self._panes:
                self._focus_active_pane()
                return True

            try:
                pane = await self._ensure_pane(tab)
            except Exception as exc:
                spec = _TAB_BY_ID[tab]
                self.notify(
                    f"Could not open {spec.label}: {exc}",
                    severity="error",
                )
                return False

            previous_tab = self._active_tab
            previous_pane = self._active_pane()
            self._set_pane_active(previous_pane, False)
            try:
                switcher = self.query_one("#config-center-switcher", ContentSwitcher)
                self._active_tab = tab
                switcher.current = tab
                self._sync_header(tab)
            except Exception as exc:
                self._active_tab = previous_tab
                try:
                    switcher.current = previous_tab or _HOME_ID
                    self._sync_header(previous_tab)
                except Exception:
                    pass
                self._set_pane_active(previous_pane, True)
                self.notify(
                    f"Could not open {_TAB_BY_ID[tab].label}: {exc}",
                    severity="error",
                )
                return False

            self._set_pane_active(pane, True)
            self._focus_active_pane()
            return True

    def action_close(self) -> None:
        """Close SASE Admin Center."""
        self._set_pane_active(self._active_pane(), False)
        self.dismiss(self._active_tab)

    def action_resume_last_tab(self) -> None:
        """Resume the session's last active section from home, when known."""
        if (
            self._active_tab is None
            and not self._initial_navigation_pending
            and self._resume_tab is not None
        ):
            self._schedule_switch(self._resume_tab)

    def action_prev_center_tab(self) -> None:
        """Enter XPrompts from home or select the previous working tab."""
        if self._active_tab is None:
            tab = _TAB_ORDER[-1]
        else:
            index = _TAB_ORDER.index(self._active_tab)
            tab = _TAB_ORDER[(index - 1) % len(_TAB_ORDER)]
        self._schedule_switch(tab)

    def action_next_center_tab(self) -> None:
        """Enter Config from home or select the next working tab."""
        if self._active_tab is None:
            tab = _TAB_ORDER[0]
        else:
            index = _TAB_ORDER.index(self._active_tab)
            tab = _TAB_ORDER[(index + 1) % len(_TAB_ORDER)]
        self._schedule_switch(tab)

    def action_focus_center_tab(self, number: int) -> None:
        """Switch to a numbered tab; out-of-range digits remain swallowed."""
        spec = _TAB_BY_NUMBER.get(number)
        if spec is not None:
            self._schedule_switch(spec.id)

    @on(PanelTabStrip.TabClicked)
    def _on_tab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        """Handle mouse selection of a working tab."""
        event.stop()
        if event.tab_id in _TAB_ORDER:
            self._schedule_switch(cast(CenterTab, event.tab_id))
