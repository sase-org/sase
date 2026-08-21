"""Lazy nested Config catalog hosted by the Admin Center Config tab."""

from __future__ import annotations

import asyncio
from typing import cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Input

from ..widgets.panel_tab_strip import PanelTabStrip
from .config_center_session import AdminCenterSessionState
from .config_hub_catalog import (
    RELATION_SUBTABS,
    config_panel_tabs,
    config_subtab_by_id,
)
from .config_hub_session import (
    ConfigHubEntry,
    ConfigSubTab,
    config_subtab_order,
    validated_config_subtab,
)

_EMPTY_ID = "config-hub-empty"


class ConfigHubPane(Vertical):
    """Lazy, cached host for the Config catalog children."""

    can_focus = False
    BINDINGS = [
        ("right_square_bracket", "cycle_subtab", "Next Sub-tab"),
        ("left_square_bracket", "cycle_subtab_reverse", "Previous Sub-tab"),
    ]

    def __init__(
        self,
        *,
        project: str | None = None,
        session_state: AdminCenterSessionState | None = None,
        entry: ConfigHubEntry | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._project = project
        self._session_state = session_state or AdminCenterSessionState()
        self._entry = entry
        self._subtab_order = config_subtab_order()
        self._subtab_by_id = config_subtab_by_id()
        self._panel_tabs = config_panel_tabs()
        requested = None if entry is None else validated_config_subtab(entry.subtab)
        remembered = validated_config_subtab(
            self._session_state.config_hub.active_subtab
        )
        self._active_subtab: ConfigSubTab = requested or remembered or "xprompts"
        self._session_state.config_hub.active_subtab = self._active_subtab
        self._panes: dict[ConfigSubTab, Widget] = {}
        self._navigation_lock = asyncio.Lock()
        self._host_visible = True
        self._initial_navigation_pending = True

    def compose(self) -> ComposeResult:
        yield PanelTabStrip(
            self._panel_tabs,
            self._active_subtab,
            uppercase_active=True,
            compact_below=72,
            compact_separator=" │ ",
            micro_below=48,
            micro_separator="│",
            id="config-hub-tabs",
        )
        with ContentSwitcher(initial=_EMPTY_ID, id="config-hub-switcher"):
            yield Vertical(id=_EMPTY_ID)

    def on_mount(self) -> None:
        self.run_worker(
            self._open_initial_subtab(self._active_subtab),
            name=f"config-hub-open-{self._active_subtab}",
            group="config-hub-navigation",
        )

    def on_unmount(self) -> None:
        self._set_pane_active(self._active_child(), False)

    def request_close(self) -> None:
        """Dismiss the enclosing Admin Center (Glossary host contract)."""
        self._close_admin_center()

    def close_catalog_pane(self) -> None:
        """Dismiss the enclosing Admin Center (Memory host contract)."""
        self._close_admin_center()

    def close_snippets_pane(self) -> None:
        """Dismiss the enclosing Admin Center (Snippets host contract)."""
        self._close_admin_center()

    def request_launch_close(self, result: object) -> None:
        """Dismiss the enclosing Admin Center (Launch host contract)."""
        self.on_launch_changed(result)
        self._close_admin_center()

    def on_launch_changed(self, result: object) -> None:
        """Refresh app-level launch indicators after embedded Launch writes."""
        changed = bool(getattr(result, "changed", False))
        if not changed:
            return
        refresh = getattr(self.app, "_refresh_launch_indicators", None)
        if callable(refresh):
            refresh(
                provider_routing_changed=bool(
                    getattr(result, "provider_routing_changed", False)
                )
            )

    def can_deactivate(self) -> bool:
        """Return whether the active Config child can be hidden."""
        child = self._active_child()
        can_deactivate = getattr(child, "can_deactivate", None)
        return not callable(can_deactivate) or bool(can_deactivate())

    def can_close(self) -> bool:
        """Return whether the active Config child can close with the hub."""
        child = self._active_child()
        can_close = getattr(child, "can_close", None)
        return not callable(can_close) or bool(can_close())

    def _close_admin_center(self) -> None:
        close = getattr(self.screen, "action_close", None)
        if callable(close):
            close()

    def focus_default(self) -> None:
        """Focus the active child when Config becomes the working tab."""
        child = self._active_child()
        focus_default = getattr(child, "focus_default", None)
        if callable(focus_default):
            focus_default()

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """Forward Admin Center visibility to the active Config child."""
        self._host_visible = active
        self._set_pane_active(self._active_child(), active)

    def child_owns_tab_keys(self) -> bool:
        """True when Tab/Shift+Tab belong to relationship navigation."""
        if self._filter_has_focus():
            return False
        return self._active_subtab in RELATION_SUBTABS

    def _filter_has_focus(self) -> bool:
        focused = getattr(self.app, "focused", None)
        return isinstance(focused, Input)

    def _active_child(self) -> Widget | None:
        return self._panes.get(self._active_subtab)

    def _create_pane(self, subtab: ConfigSubTab) -> Widget:
        return self._subtab_by_id[subtab].factory(self)

    @staticmethod
    def _set_pane_active(pane: Widget | None, active: bool) -> None:
        visibility_changed = getattr(pane, "on_center_tab_visibility_changed", None)
        if callable(visibility_changed):
            visibility_changed(active)

    def _schedule_switch(self, subtab: ConfigSubTab) -> None:
        self.run_worker(
            self._switch_to(subtab),
            name=f"config-hub-open-{subtab}",
            group="config-hub-navigation",
        )

    async def _open_initial_subtab(self, subtab: ConfigSubTab) -> None:
        try:
            await self._switch_to(subtab)
        finally:
            self._initial_navigation_pending = False

    async def _remove_failed_pane(self, pane: Widget) -> None:
        try:
            if pane.parent is not None:
                await pane.remove()
        except Exception:
            pass

    async def _ensure_pane(self, subtab: ConfigSubTab) -> Widget:
        cached = self._panes.get(subtab)
        if cached is not None:
            return cached
        pane = self._create_pane(subtab)
        try:
            switcher = self.query_one("#config-hub-switcher", ContentSwitcher)
            await switcher.add_content(pane)
        except Exception:
            await self._remove_failed_pane(pane)
            raise
        self._panes[subtab] = pane
        return pane

    def _sync_strip(self, subtab: ConfigSubTab) -> None:
        strip = self.query_one("#config-hub-tabs", PanelTabStrip)
        strip.set_active_tab(subtab)

    async def _switch_to(self, subtab: ConfigSubTab) -> bool:
        async with self._navigation_lock:
            if subtab == self._active_subtab and subtab in self._panes:
                if self._host_visible:
                    self.focus_default()
                return True
            if not self.can_deactivate():
                return False
            try:
                pane = await self._ensure_pane(subtab)
            except Exception as exc:
                spec = self._subtab_by_id[subtab]
                self.notify(
                    f"Could not open {spec.label}: {exc}",
                    severity="error",
                )
                return False

            previous_subtab = self._active_subtab
            previous_pane = self._active_child()
            self._set_pane_active(previous_pane, False)
            try:
                switcher = self.query_one("#config-hub-switcher", ContentSwitcher)
                self._active_subtab = subtab
                self._session_state.config_hub.active_subtab = subtab
                switcher.current = subtab
                self._sync_strip(subtab)
            except Exception as exc:
                self._active_subtab = previous_subtab
                self._session_state.config_hub.active_subtab = previous_subtab
                try:
                    switcher.current = (
                        previous_subtab if previous_subtab in self._panes else _EMPTY_ID
                    )
                    self._sync_strip(previous_subtab)
                except Exception:
                    pass
                self._set_pane_active(previous_pane, True)
                self.notify(
                    f"Could not open {self._subtab_by_id[subtab].label}: {exc}",
                    severity="error",
                )
                return False

            if self._host_visible:
                self._set_pane_active(pane, True)
                self.focus_default()
            return True

    def _cycle_subtab(self, step: int) -> None:
        index = self._subtab_order.index(self._active_subtab)
        self._schedule_switch(
            self._subtab_order[(index + step) % len(self._subtab_order)]
        )

    def action_cycle_subtab(self) -> None:
        """Select the next Config catalog child."""
        self._cycle_subtab(1)

    def action_cycle_subtab_reverse(self) -> None:
        """Select the previous Config catalog child."""
        self._cycle_subtab(-1)

    def action_scroll_to_top(self) -> None:
        child = self._active_child()
        scroll = getattr(child, "action_scroll_to_top", None)
        if callable(scroll):
            scroll()

    def action_scroll_to_bottom(self) -> None:
        child = self._active_child()
        scroll = getattr(child, "action_scroll_to_bottom", None)
        if callable(scroll):
            scroll()

    @on(PanelTabStrip.TabClicked)
    def _on_subtab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        event.stop()
        subtab = validated_config_subtab(event.tab_id)
        if subtab is not None:
            self._schedule_switch(cast(ConfigSubTab, subtab))


__all__ = ["ConfigHubPane"]
