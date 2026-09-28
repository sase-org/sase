"""Shell lifecycle of the Admin Center Tools pane (sase-1bt.10).

Owns construction, composition, mount polling, focus entry points, and the
active-view switch. Data loading, list rendering, key handling, and tool
actions live in the sibling ``tool_runs_pane_*`` modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Label, OptionList, Static

from sase.ace.tui.keymaps import (
    ToolRunsPaneKeymaps,
    build_tool_runs_bindings,
    load_keymap_registry,
)
from sase.ace.tui.widgets.panel_tab_strip import PanelTab, PanelTabStrip

from ._tool_runs_pane_shared import VIEWS, store_token
from .config_center_session import ToolRunsSessionState
from .tool_runs_pane_data import ToolRunFocusTarget

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object

_POLL_INTERVAL_SECONDS = 2.0
_VIEW_TABS: tuple[PanelTab, ...] = (
    PanelTab("runs", "Runs", "#87D7FF"),
    PanelTab("failures", "Failures", "#FF5F5F"),
    PanelTab("catalog", "Catalog", "#FFAF5F"),
)


def _resolve_scope_project(modal_project: str | None) -> str | None:
    """Return the default Runs scope project, if one is known."""

    if modal_project:
        return modal_project
    try:
        from sase.current_project import resolve_current_project
    except Exception:
        return None
    try:
        current = resolve_current_project()
    except Exception:
        return None
    if current is None:
        return None
    return getattr(current, "project_key", None)


class ToolRunsPaneShellMixin(_MixinBase):
    """Construct and compose the Tools pane; switch its active view."""

    if TYPE_CHECKING:
        _all_projects: bool
        _bindings: BindingsMap
        _detail_cache: dict[str, Any]
        _failure_groups: list[dict[str, Any]]
        _catalog_entries: list[Any]
        _catalog_project: str
        _catalog_summaries: dict[str, dict[str, Any]]
        _keymaps: ToolRunsPaneKeymaps
        _last_token: tuple[object, ...]
        _loaded_once: bool
        _loading: bool
        _modal_project: str | None
        _pending_run_id: str | None
        _poll_timer: Any | None
        _query: str
        _reload_pending: bool
        _run_briefs: list[Any]
        _run_rows: list[tuple[str, Any]]
        _scope_project: str | None
        _selected_run_id: str | None
        _session_state: ToolRunsSessionState
        _tab_active: bool
        _view: str

        def _on_poll_tick(self) -> None: ...

        def _rebuild_list(self) -> None: ...

        def _render_detail(self) -> None: ...

        def _request_reload(self, *, force: bool = False) -> None: ...

        def _select_run(self, run_id: str) -> bool: ...

    def __init__(
        self,
        *,
        project: str | None = None,
        session_state: ToolRunsSessionState | None = None,
        keymaps: ToolRunsPaneKeymaps | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._modal_project = project
        self._session_state = session_state or ToolRunsSessionState()
        self._keymaps = keymaps or load_keymap_registry({}).tool_runs
        self._bindings = BindingsMap(build_tool_runs_bindings(self._keymaps))
        self._view = (
            self._session_state.active_view
            if self._session_state.active_view in VIEWS
            else "runs"
        )
        self._scope_project = _resolve_scope_project(project)
        self._all_projects = self._session_state.all_projects
        self._query = self._session_state.query or ""
        self._run_rows = []
        self._run_briefs = []
        self._failure_groups = []
        self._catalog_entries = []
        self._catalog_project = ""
        self._catalog_summaries = {}
        self._detail_cache = {}
        self._selected_run_id = self._session_state.run.identity
        self._pending_run_id = self._session_state.pending_run_id
        self._loaded_once = False
        self._loading = False
        self._reload_pending = False
        self._poll_timer = None
        self._last_token = ()
        self._tab_active = False

    def compose(self) -> ComposeResult:
        yield Label(self._title_text(), id="tools-pane-title")
        yield PanelTabStrip(
            _VIEW_TABS, self._view, id="tools-view-tabs", show_numbers=False
        )
        yield Input(
            value=self._query,
            placeholder="tool: state: agent: verdict: text",
            id="tools-filter",
        )
        with Horizontal(id="tools-panels"):
            with Vertical(id="tools-list-panel"):
                yield OptionList(id="tools-list")
            with Vertical(id="tools-detail-panel"):
                with VerticalScroll(id="tools-detail-scroll"):
                    yield Static("", id="tools-detail", markup=False)
        yield Static(self._hints(), id="tools-hints", markup=False)

    def on_mount(self) -> None:
        self._last_token = store_token()
        self._request_reload()
        self._poll_timer = self.set_interval(_POLL_INTERVAL_SECONDS, self._on_poll_tick)

    def on_unmount(self) -> None:
        if self._poll_timer is not None:
            try:
                self._poll_timer.stop()
            except Exception:
                pass
            self._poll_timer = None

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """Pause polling while the Tools tab is hidden."""

        self._tab_active = bool(active)
        if active:
            self._request_reload()

    def focus_default(self) -> None:
        """Focus the Tools list and refresh on activation."""

        self._request_reload()
        try:
            self.query_one("#tools-list", OptionList).focus()
        except Exception:
            pass

    def focus_tool_run(self, target: ToolRunFocusTarget | str) -> bool:
        """Switch to Runs, then select (loaded) or hold pending (not loaded)."""

        run_id = target.run_id if isinstance(target, ToolRunFocusTarget) else target
        if not run_id:
            return False
        if self._view != "runs":
            self._set_view("runs")
        self._pending_run_id = run_id
        self._session_state.pending_run_id = run_id
        if self._loaded_once:
            if self._select_run(run_id):
                return True
            return True
        return True

    def _is_active_tab(self) -> bool:
        try:
            return getattr(self.screen, "_active_tab", None) == self.id
        except Exception:
            return False

    def _title_text(self) -> str:
        scope = (
            "all projects"
            if self._all_projects
            else (self._scope_project or "current project")
        )
        return f"⚒ Tools   Runs │ Failures │ Catalog      +{scope} · A all projects"

    def _hints(self) -> str:
        return (
            "j/k: move  enter: detail  a: agent  s: stop  r: run"
            "  v: log  y: copy id  /: filter  [ ]: view  A: all  R: reload"
            "  Esc: close"
        )

    def _set_view(self, view: str) -> None:
        if view not in VIEWS:
            return
        self._view = view
        self._session_state.active_view = view
        try:
            self.query_one("#tools-view-tabs", PanelTabStrip).set_active_tab(view)
        except Exception:
            pass
        self._rebuild_list()
        self._render_detail()


__all__ = ["ToolRunsPaneShellMixin"]
