"""Layout and sub-tab navigation for the Config Center Updates pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from rich.panel import Panel
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import ContentSwitcher, Static
from textual.widgets.option_list import Option

from .config_center_session import UpdatesSubTab
from .plugins_browser_constants import _DETAIL_PLACEHOLDER, _SUBTAB_NAV_HINT
from ..widgets.panel_tab_strip import PanelTab, PanelTabStrip

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from sase.ace.tui.util.debounce import DetailPanelDebouncer

    from .config_center_session import UpdatesSessionState
    from .plugins_browser_rows import UpdateRow
else:
    _MixinBase = object


_SUBTAB_ORDER: tuple[UpdatesSubTab, ...] = ("core", "plugins", "agent-clis")
_SUBTAB_WIDGET_IDS: dict[UpdatesSubTab, str] = {
    "core": "updates-subtab-core",
    "plugins": "updates-subtab-plugins",
    "agent-clis": "updates-subtab-agent-clis",
}
_SUBTABS: tuple[PanelTab, ...] = (
    PanelTab("core", "Core", "#AF87FF"),
    PanelTab("plugins", "Plugins", "#AF87FF"),
    PanelTab("agent-clis", "Agent CLIs", "#AF87FF"),
)


class PluginsBrowserLayoutMixin(_MixinBase):
    """Compose the pane and coordinate its three update sub-tabs."""

    if TYPE_CHECKING:
        _active_subtab: UpdatesSubTab
        _agent_cli_plan_worker: object | None
        _auto_load: bool
        _detail_debouncer: DetailPanelDebouncer | None
        _loading: bool
        _offline: bool
        _session_state: UpdatesSessionState
        app: Any

        def _agent_cli_hints(self) -> str: ...

        def _agent_cli_status_message(self) -> str: ...

        def _agent_cli_summary(self) -> Text: ...

        def _all_current_banner(self) -> Panel: ...

        def _can_update_sase(self) -> bool: ...

        def _core_versions_panel(self) -> Panel: ...

        def _create_options(self) -> list[Option]: ...

        def _hints(self) -> str: ...

        def _start_load(self, *, force: bool) -> None: ...

        def _highlighted_row(self) -> UpdateRow | None: ...

        def reset_jump_state(self, *, repaint: bool = False) -> None: ...

        def _status_message(self) -> str: ...

        def _summary_text(self) -> Text: ...

        def _sync_current_banner(self) -> None: ...

        def _sync_state_visibility(self) -> None: ...

        def focus_default(self) -> None: ...

    def compose(self) -> ComposeResult:
        # Resolve the historical widget aliases lazily so the pane module
        # remains the stable compatibility/monkeypatch surface after the split.
        from . import plugins_browser_pane as pane_module

        yield PanelTabStrip(
            _SUBTABS,
            self._active_subtab,
            uppercase_active=True,
            id="updates-subtabs",
        )
        with ContentSwitcher(
            initial=_SUBTAB_WIDGET_IDS[self._active_subtab],
            id="updates-subtab-switcher",
        ):
            with Vertical(id=_SUBTAB_WIDGET_IDS["core"]):
                banner = Static(self._all_current_banner(), id="updates-current-banner")
                banner.display = False
                yield banner
                yield Static(self._core_versions_panel(), id="sase-core-versions")
                yield Static(self._core_hints(), id="updates-core-hints", markup=False)
            with Vertical(id=_SUBTAB_WIDGET_IDS["plugins"]):
                yield Static(self._summary_text(), id="plugins-summary", markup=False)
                yield pane_module._PluginsFilterInput(
                    placeholder="/ filter plugins…", id="plugins-filter-input"
                )
                with Horizontal(id="plugins-panels"):
                    with Vertical(id="plugins-list-panel"):
                        yield Static(
                            self._status_message(), id="plugins-status", markup=False
                        )
                        yield pane_module._PluginList(
                            *self._create_options(), id="plugins-list"
                        )
                    with Vertical(id="plugins-detail-panel"):
                        with VerticalScroll(id="plugins-detail-scroll"):
                            yield Static(
                                _DETAIL_PLACEHOLDER,
                                id="plugins-detail",
                                markup=False,
                            )
                yield Static(self._hints(), id="plugins-hints", markup=False)
            with Vertical(id=_SUBTAB_WIDGET_IDS["agent-clis"]):
                yield Static(
                    self._agent_cli_summary(), id="agent-clis-summary", markup=False
                )
                with Horizontal(id="agent-clis-panels"):
                    with Vertical(id="agent-clis-list-panel"):
                        yield Static(
                            self._agent_cli_status_message(),
                            id="agent-clis-status",
                            markup=False,
                        )
                        yield pane_module._PluginList(id="agent-clis-list")
                    with Vertical(id="agent-clis-detail-panel"):
                        with VerticalScroll(id="agent-clis-detail-scroll"):
                            yield Static(
                                "Select an agent CLI to view its update details.",
                                id="agent-clis-detail",
                                markup=False,
                            )
                            yield Static("", id="agent-clis-history", markup=False)
                yield Static(
                    self._agent_cli_hints(), id="agent-clis-hints", markup=False
                )

    def on_mount(self) -> None:
        from sase.ace.tui.util.debounce import DetailPanelDebouncer

        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._sync_state_visibility()
        self._sync_current_banner()
        if self._auto_load:
            self._start_load(force=False)

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "update_sase":
            return self._can_update_sase()
        if action == "update_agent_clis":
            return not self._loading and self._agent_cli_plan_worker is None
        if action == "sync_agents":
            return callable(getattr(self.app, "action_sync_agents", None))
        plugin_row_capability = {
            "install": "install",
            "toggle_install_mark": "install",
            "uninstall": "uninstall",
            "update": "update",
        }
        if action in plugin_row_capability:
            if self._active_subtab != "plugins":
                return False
            row = self._highlighted_row()
            return row is not None and plugin_row_capability[action] in row.capabilities
        if action == "toggle_history_scope":
            if self._active_subtab != "agent-clis":
                return False
            row = self._highlighted_row()
            return row is not None and "history" in row.capabilities
        plugin_only = {
            "switch_mode",
            "toggle_verbose",
            "focus_filter",
        }
        if action in plugin_only and self._active_subtab != "plugins":
            return False
        browse_only = {
            "next_option",
            "prev_option",
            "jump_to_entry",
            "toggle_mark",
            "scroll_detail_down",
            "scroll_detail_up",
            "scroll_to_top",
            "scroll_to_bottom",
        }
        if action in browse_only and self._active_subtab == "core":
            return False
        return super().check_action(action, parameters)

    @on(PanelTabStrip.TabClicked)
    def _on_subtab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        event.stop()
        if event.tab_id in _SUBTAB_ORDER:
            self._switch_to_subtab(cast(UpdatesSubTab, event.tab_id))

    def _switch_to_subtab(self, subtab: UpdatesSubTab) -> None:
        # Each sub-tab owns its own row list, so hints painted on the outgoing
        # one are repainted away and the back stack's indices are dropped.
        self.reset_jump_state(repaint=True)
        self._active_subtab = subtab
        self._session_state.active_subtab = subtab
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        try:
            self.query_one(
                "#updates-subtab-switcher", ContentSwitcher
            ).current = _SUBTAB_WIDGET_IDS[subtab]
            self.query_one("#updates-subtabs", PanelTabStrip).set_active_tab(subtab)
        except Exception:
            return
        self.focus_default()

    def _cycle_subtab(self, step: int) -> None:
        index = _SUBTAB_ORDER.index(self._active_subtab)
        self._switch_to_subtab(_SUBTAB_ORDER[(index + step) % len(_SUBTAB_ORDER)])

    def action_cycle_subtab(self) -> None:
        self._cycle_subtab(1)

    def action_cycle_subtab_reverse(self) -> None:
        self._cycle_subtab(-1)

    def _core_hints(self) -> str:
        offline = " (on)" if self._offline else " off"
        return " · ".join(
            (
                "u core+plugins",
                "A agent CLIs",
                "a sync agents",
                "r reload",
                f"o{offline}",
                _SUBTAB_NAV_HINT,
                "esc",
            )
        )

    def action_sync_agents(self) -> None:
        """Delegate ``a`` to ACE's shared tracked full-sync action."""
        action = getattr(self.app, "action_sync_agents", None)
        if callable(action):
            action()
