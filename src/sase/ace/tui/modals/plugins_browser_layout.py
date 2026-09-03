"""Layout and scope navigation for the Config Center Updates pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static
from textual.widgets.option_list import Option

from .plugins_browser_constants import _DETAIL_PLACEHOLDER
from .plugins_browser_rows import (
    SCOPE_LABELS,
    SCOPE_ORDER,
    UpdateScope,
    scope_counts,
)
from ..widgets.panel_tab_strip import PanelTab, PanelTabStrip

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from rich.console import RenderableType

    from sase.ace.tui.util.debounce import DetailPanelDebouncer

    from .config_center_session import UpdatesSessionState
    from .plugins_browser_rows import UpdateRow
else:
    _MixinBase = object


_ROW_NAV_ACTIONS = {
    "next_option",
    "prev_option",
    "jump_to_entry",
    "toggle_mark",
    "scroll_detail_down",
    "scroll_detail_up",
    "scroll_to_top",
    "scroll_to_bottom",
}


class PluginsBrowserLayoutMixin(_MixinBase):
    """Compose the pane and coordinate its scope strip and master/detail list."""

    if TYPE_CHECKING:
        _agent_cli_plan_worker: object | None
        _auto_load: bool
        _detail_debouncer: DetailPanelDebouncer | None
        _grouped: list[tuple[str, str, list[UpdateRow]]]
        _loading: bool
        _rows: tuple[UpdateRow, ...]
        _scope: UpdateScope
        _session_state: UpdatesSessionState
        app: Any

        def _can_mark_highlighted(self) -> bool: ...

        def _can_switch_mode(self) -> bool: ...

        def _can_update_sase(self) -> bool: ...

        def _create_options(
            self, reuse: dict[str, Option] | None = None
        ) -> list[Option]: ...

        def _header_renderable(self) -> RenderableType: ...

        def _highlighted_row(self) -> UpdateRow | None: ...

        def _hints(self) -> str: ...

        def _rebuild_groups(self) -> None: ...

        def _rebuild_options(self, *, reuse_options: bool = False) -> None: ...

        def _render_detail_now(self, *, force: bool = False) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

        def _status_message(self) -> str: ...

        def _sync_header(self) -> None: ...

        def _sync_state_visibility(self) -> None: ...

        def focus_default(self) -> None: ...

        def reset_jump_state(self, *, repaint: bool = False) -> None: ...

    def compose(self) -> ComposeResult:
        # Resolve the historical widget aliases lazily so the pane module
        # remains the stable compatibility/monkeypatch surface after the split.
        from . import plugins_browser_pane as pane_module

        yield Static(self._header_renderable(), id="updates-header", markup=False)
        yield PanelTabStrip(
            self._scope_tabs(),
            self._scope,
            uppercase_active=True,
            id="updates-scopes",
        )
        yield pane_module._PluginsFilterInput(
            placeholder="/ filter components, plugins, agent CLIs…",
            id="updates-filter-input",
        )
        with Horizontal(id="updates-panels"):
            with Vertical(id="updates-list-panel"):
                yield Static(self._status_message(), id="updates-status", markup=False)
                yield pane_module._PluginList(
                    *self._create_options(), id="updates-list"
                )
            with Vertical(id="updates-detail-panel"):
                with VerticalScroll(id="updates-detail-scroll"):
                    yield Static(_DETAIL_PLACEHOLDER, id="updates-detail", markup=False)
                    yield Static("", id="updates-history", markup=False)
        yield Static(self._hints(), id="updates-hints", markup=False)

    def on_mount(self) -> None:
        from sase.ace.tui.util.debounce import DetailPanelDebouncer

        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._sync_state_visibility()
        self._sync_header()
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
        if action == "switch_mode":
            return self._can_switch_mode()
        if action == "toggle_install_mark":
            return self._can_mark_highlighted()
        row_capability = {
            "install": "install",
            "uninstall": "uninstall",
            "update": "update",
            "toggle_history_scope": "history",
        }
        if action in row_capability:
            row = self._highlighted_row()
            return row is not None and row_capability[action] in row.capabilities
        if action in _ROW_NAV_ACTIONS:
            return self._has_item_rows()
        return super().check_action(action, parameters)

    def _scope_tabs(self) -> tuple[PanelTab, ...]:
        counts = scope_counts(self._rows)
        return tuple(
            PanelTab(scope, f"{SCOPE_LABELS[scope]} {counts[scope]}", "#AF87FF")
            for scope in SCOPE_ORDER
        )

    def _refresh_scope_strip(self) -> None:
        try:
            self.query_one("#updates-scopes", PanelTabStrip).set_tabs(
                self._scope_tabs(), active_tab=self._scope
            )
        except Exception:
            return

    def _has_item_rows(self) -> bool:
        return any(rows for _, _, rows in self._grouped)

    @on(PanelTabStrip.TabClicked)
    def _on_scope_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        event.stop()
        if event.tab_id in SCOPE_ORDER:
            self._set_scope(cast(UpdateScope, event.tab_id))

    def _set_scope(self, scope: UpdateScope) -> None:
        if scope == self._scope:
            return
        self.reset_jump_state(repaint=True)
        self._scope = scope
        self._session_state.scope = scope
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        self._refresh_scope_strip()
        self._rebuild_groups()
        self._rebuild_options(reuse_options=True)
        self._sync_state_visibility()
        self._render_detail_now(force=True)
        self.focus_default()

    def _cycle_scope(self, step: int) -> None:
        index = SCOPE_ORDER.index(self._scope)
        self._set_scope(SCOPE_ORDER[(index + step) % len(SCOPE_ORDER)])

    def action_cycle_scope(self) -> None:
        self._cycle_scope(1)

    def action_cycle_scope_reverse(self) -> None:
        self._cycle_scope(-1)

    def action_sync_agents(self) -> None:
        """Delegate ``a`` to ACE's shared tracked full-sync action."""
        action = getattr(self.app, "action_sync_agents", None)
        if callable(action):
            action()
