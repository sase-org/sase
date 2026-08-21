"""Home-first SASE Admin Center with lazily mounted working panes.

The first unqualified ``#`` action opens a lightweight landing page. Repeating
the configured opener resumes the last section used in this or a previous ACE
process. Working tabs are otherwise created only when the user explicitly
enters one with numbered keys, ``Tab`` / ``Shift+Tab``, or the clickable tab
strip. Mounted panes are cached for the lifetime of the modal, so returning
to a tab preserves its selection and other pane-local state.

The Config section hosts the nested Glossary, Launch, Memory, Misc, Snippets,
and XPrompts catalog. Direct-entry actions may still pass ``initial_tab`` to
open exactly one pane. Pane-local sub-tabs continue to use ``]`` / ``[`` where
provided.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingsMap
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Label, Static

from ..keymaps import is_valid_key
from ..widgets.panel_tab_strip import PanelTabStrip
from .config_center_catalog import (
    _PANEL_TABS as _PANEL_TABS,
    _TAB_BY_ID as _TAB_BY_ID,
    _TAB_BY_NUMBER as _TAB_BY_NUMBER,
    _TAB_COLORS as _TAB_COLORS,
    _TAB_DESCRIPTIONS as _TAB_DESCRIPTIONS,
    _TAB_LABELS as _TAB_LABELS,
    _TAB_ORDER as _TAB_ORDER,
    _TAB_SPECS as _TAB_SPECS,
    CenterTab as CenterTab,
    CenterTabSpec,
    PaneFactory as PaneFactory,
    center_tab_accent as center_tab_accent,
    validated_center_tab as validated_center_tab,
)
from .config_hub_session import ConfigHubEntry
from .config_center_footer import AdminCenterFooter
from .config_center_history import (
    AdminCenterTabHistory,
    validated_admin_center_tab_history,
)
from .config_center_session import AdminCenterSessionState
from .config_center_home import (
    _HOME_ID as _HOME_ID,
    _HOME_LEAD as _HOME_LEAD,
    _HOME_ORIENTATION as _HOME_ORIENTATION,
    _TITLE_LABEL as _TITLE_LABEL,
    _TITLE_TEXT as _TITLE_TEXT,
    _TITLE_UNDERLINE as _TITLE_UNDERLINE,
    AdminCenterLanding,
    AdminCenterLandingRow,
    ConfigCenterHeaderDivider,
    gradient_text,
    home_hint_text,
    home_orientation_text,
    tab_description_text,
)

if TYPE_CHECKING:
    from sase.logs import RegisteredError

# Compatibility aliases for callers that imported these implementation details
# before the Admin Center was split into focused modules.
_AdminCenterLanding = AdminCenterLanding
_AdminCenterLandingRow = AdminCenterLandingRow
_CenterTabSpec = CenterTabSpec
_ConfigCenterHeaderDivider = ConfigCenterHeaderDivider
_gradient_text = gradient_text
_home_hint_text = home_hint_text
_home_orientation_text = home_orientation_text
_tab_description_text = tab_description_text

log = logging.getLogger(__name__)


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
        alternate_tab: CenterTab | None = None,
        opener_binding: str = "number_sign",
        log_error_target: RegisteredError | None = None,
        session_state: AdminCenterSessionState | None = None,
        on_tab_activated: Callable[[CenterTab], None] | None = None,
        config_entry: ConfigHubEntry | None = None,
    ) -> None:
        super().__init__()
        self._project = project
        self._log_error_target = log_error_target
        self._session_state = session_state or AdminCenterSessionState()
        self._tab_specs = _TAB_SPECS
        self._tab_by_id = _TAB_BY_ID
        self._tab_by_number = _TAB_BY_NUMBER
        self._tab_order = _TAB_ORDER
        self._panel_tabs = _PANEL_TABS
        self._config_entry = config_entry
        requested_tab = "config" if config_entry is not None else initial_tab
        self._initial_tab = validated_center_tab(requested_tab)
        self._resume_tab = validated_center_tab(resume_tab)
        self._history: AdminCenterTabHistory = validated_admin_center_tab_history(
            self._resume_tab,
            validated_center_tab(alternate_tab),
        )
        self._on_tab_activated = on_tab_activated
        self._opener_binding = (
            opener_binding
            if isinstance(opener_binding, str) and is_valid_key(opener_binding)
            else "number_sign"
        )
        # Put the modal-local opener first so a custom binding that overlaps
        # another modal key (for example Tab or q) still means "resume" while
        # home is visible.  ``check_action`` disables it on working panes.
        # The alternate-jump binding on the same key is appended *after*
        # ``*self.BINDINGS`` instead: on a colliding custom opener, "resume"
        # wins on home, but a working tab's own ``q``/``Tab`` meaning still
        # wins over the alternate jump (see ``check_action``).
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
                Binding(
                    self._opener_binding,
                    "alternate_center_tab",
                    "Back to alternate section",
                    show=False,
                    priority=False,
                ),
            ]
        )
        self._active_tab: CenterTab | None = None
        self._panes: dict[CenterTab, Widget] = {}
        self._navigation_lock = asyncio.Lock()
        self._initial_navigation_pending = self._initial_tab is not None

    def compose(self) -> ComposeResult:
        with Container(id="config-center-container"):
            yield Label(gradient_text(_TITLE_TEXT, bold=True), id="config-center-title")
            yield Static(
                gradient_text(_TITLE_UNDERLINE, bold=False),
                id="config-center-title-underline",
            )
            yield PanelTabStrip(
                self._panel_tabs,
                None,
                show_numbers=True,
                compact_below=95,
                id="config-center-tabs",
            )
            yield Static(
                home_orientation_text(),
                id="config-center-tab-description",
            )
            yield ConfigCenterHeaderDivider(id="config-center-divider")
            with ContentSwitcher(initial=_HOME_ID, id="config-center-switcher"):
                yield AdminCenterLanding(
                    self._resume_tab,
                    self._opener_binding,
                    self._schedule_switch,
                    tab_specs=self._tab_specs,
                    id=_HOME_ID,
                )
            footer = AdminCenterFooter(self._schedule_switch, id="config-center-footer")
            footer.display = False
            yield footer

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
        """Give the opener a home-only and a working-tab-only meaning."""
        if action == "resume_last_tab":
            return self._active_tab is None and not self._initial_navigation_pending
        if action == "alternate_center_tab":
            return (
                self._active_tab is not None
                and not self._initial_navigation_pending
                and self._history.alternate is not None
            )
        if action in ("next_center_tab", "prev_center_tab"):
            if self._child_owns_tab_keys():
                return False
        return super().check_action(action, parameters)

    def _child_owns_tab_keys(self) -> bool:
        """Let Glossary/Memory/Snippets keep Tab for relationship travel."""
        if self._active_tab != "config":
            return False
        pane = self._active_pane()
        owns = getattr(pane, "child_owns_tab_keys", None)
        return bool(callable(owns) and owns())

    def _active_pane(self) -> Widget | None:
        """Return the stable, currently visible working pane."""
        if self._active_tab is None:
            return None
        return self._panes.get(self._active_tab)

    def _create_pane(self, tab: CenterTab) -> Widget:
        """Construct one requested pane through the immutable tab catalog."""
        return self._tab_by_id[tab].factory(self)

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

    def _sync_chrome(self, tab: CenterTab | None) -> None:
        """Keep the tab strip, description caption, and footer in lockstep."""
        strip = self.query_one("#config-center-tabs", PanelTabStrip)
        strip.set_active_tab(tab)
        description = self.query_one("#config-center-tab-description", Static)
        description.update(
            home_orientation_text()
            if tab is None
            else tab_description_text(tab, specs=self._tab_by_id)
        )
        footer = self.query_one("#config-center-footer", AdminCenterFooter)
        footer.display = tab is not None
        footer.update_state(
            self._history.alternate if tab is not None else None,
            self._opener_binding,
        )

    async def _switch_to(self, tab: CenterTab) -> bool:
        """Mount and select ``tab`` once, preserving a stable view on failure."""
        async with self._navigation_lock:
            if tab == self._active_tab and tab in self._panes:
                self._focus_active_pane()
                return True
            if not self._active_pane_can_deactivate():
                return False

            try:
                pane = await self._ensure_pane(tab)
            except Exception as exc:
                spec = self._tab_by_id[tab]
                self.notify(
                    f"Could not open {spec.label}: {exc}",
                    severity="error",
                )
                return False

            previous_tab = self._active_tab
            previous_pane = self._active_pane()
            previous_history = self._history
            self._set_pane_active(previous_pane, False)
            try:
                switcher = self.query_one("#config-center-switcher", ContentSwitcher)
                self._active_tab = tab
                switcher.current = tab
                self._history = self._history.remember(tab)
                self._sync_chrome(tab)
            except Exception as exc:
                self._active_tab = previous_tab
                self._history = previous_history
                try:
                    switcher.current = previous_tab or _HOME_ID
                    self._sync_chrome(previous_tab)
                except Exception:
                    pass
                self._set_pane_active(previous_pane, True)
                self.notify(
                    f"Could not open {self._tab_by_id[tab].label}: {exc}",
                    severity="error",
                )
                return False

            self._set_pane_active(pane, True)
            self._focus_active_pane()
            if self._on_tab_activated is not None:
                try:
                    self._on_tab_activated(tab)
                except Exception:
                    log.exception("Admin Center tab-activation callback failed")
            return True

    def _active_pane_can_deactivate(self) -> bool:
        pane = self._active_pane()
        can_deactivate = getattr(pane, "can_deactivate", None)
        return not callable(can_deactivate) or bool(can_deactivate())

    def _active_pane_can_close(self) -> bool:
        pane = self._active_pane()
        can_close = getattr(pane, "can_close", None)
        return not callable(can_close) or bool(can_close())

    def action_close(self) -> None:
        """Close SASE Admin Center."""
        if not self._active_pane_can_close():
            return
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

    def action_alternate_center_tab(self) -> None:
        """Toggle to the other section of the current two-slot pair."""
        alternate = self._history.alternate
        if (
            self._active_tab is not None
            and not self._initial_navigation_pending
            and alternate is not None
        ):
            self._schedule_switch(alternate)

    def action_prev_center_tab(self) -> None:
        """Enter the last working tab from home or select the previous tab."""
        if self._active_tab is None:
            tab = self._tab_order[-1]
        else:
            index = self._tab_order.index(self._active_tab)
            tab = self._tab_order[(index - 1) % len(self._tab_order)]
        self._schedule_switch(tab)

    def action_next_center_tab(self) -> None:
        """Enter Config from home or select the next working tab."""
        if self._active_tab is None:
            tab = self._tab_order[0]
        else:
            index = self._tab_order.index(self._active_tab)
            tab = self._tab_order[(index + 1) % len(self._tab_order)]
        self._schedule_switch(tab)

    def action_focus_center_tab(self, number: int) -> None:
        """Switch to a numbered tab; out-of-range digits remain swallowed."""
        spec = self._tab_by_number.get(number)
        if spec is not None:
            self._schedule_switch(spec.id)

    @on(PanelTabStrip.TabClicked)
    def _on_tab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        """Handle mouse selection of a working tab."""
        event.stop()
        if event.tab_id in self._tab_order:
            self._schedule_switch(cast(CenterTab, event.tab_id))
