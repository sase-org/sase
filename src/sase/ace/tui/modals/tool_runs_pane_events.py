"""Key and cursor handling for the Admin Center Tools pane (sase-1bt.10)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.widgets import Input, OptionList
from textual.containers import VerticalScroll

from ._tool_runs_pane_shared import VIEWS

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from sase.ace.tui.keymaps import ToolRunsPaneKeymaps

    from .config_center_session import ToolRunsSessionState
else:
    _MixinBase = object


class ToolRunsPaneEventsMixin(_MixinBase):
    """Refilter, cursor, and view-local keys for the Tools pane."""

    if TYPE_CHECKING:
        _all_projects: bool
        _keymaps: ToolRunsPaneKeymaps
        _query: str
        _scope_project: str | None
        _selected_run_id: str | None
        _session_state: ToolRunsSessionState
        _view: str

        def _load_runs(self, project: str | None) -> None: ...

        def _selected_identity(self) -> str | None: ...

        def _rebuild_list(self) -> None: ...

        def _render_detail(self) -> None: ...

        def _request_reload(self, *, force: bool = False) -> None: ...

        def _set_view(self, view: str) -> None: ...

    def on_option_list_option_highlighted(
        self, _event: OptionList.OptionHighlighted
    ) -> None:
        """Repaint detail as the cursor moves; record the selection."""

        identity = self._selected_identity()
        if self._view == "runs" and identity:
            self._selected_run_id = identity
            self._session_state.run.record(identity, None)
        self._render_detail()

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        """Focus detail on enter; failures enter is a no-op detail refresh."""

        self._render_detail()
        try:
            self.query_one("#tools-detail-scroll", VerticalScroll).focus()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refilter runs as the ``/`` query changes."""

        if getattr(event.input, "id", "") != "tools-filter":
            return
        self._query = event.value or ""
        self._session_state.query = self._query
        self._load_runs(None if self._all_projects else self._scope_project)
        self._rebuild_list()
        self._render_detail()

    def on_key(self, event: events.Key) -> None:
        """Handle view-local keys before the modal's numbered tab keys."""

        from sase.ace.tui.keymaps import split_key_alternatives

        keys = self._keymaps
        key = event.key or ""
        if key in split_key_alternatives(keys.cycle_subtab):
            event.prevent_default()
            event.stop()
            self.action_cycle_subtab()
        elif key in split_key_alternatives(keys.cycle_subtab_reverse):
            event.prevent_default()
            event.stop()
            self.action_cycle_subtab_reverse()
        elif key in split_key_alternatives(keys.toggle_scope):
            event.prevent_default()
            event.stop()
            self.action_toggle_scope()
        elif key in split_key_alternatives(keys.reload):
            event.prevent_default()
            event.stop()
            self.action_reload_tool_runs()

    def action_next_option(self) -> None:
        """Move the list cursor down."""

        try:
            self.query_one("#tools-list", OptionList).action_cursor_down()
        except Exception:
            pass

    def action_prev_option(self) -> None:
        """Move the list cursor up."""

        try:
            self.query_one("#tools-list", OptionList).action_cursor_up()
        except Exception:
            pass

    def action_focus_filter(self) -> None:
        """Focus the ``/`` filter input."""

        try:
            self.query_one("#tools-filter", Input).focus()
        except Exception:
            pass

    def action_cycle_subtab(self) -> None:
        """Switch to the next Tools view."""

        self._set_view(VIEWS[(VIEWS.index(self._view) + 1) % len(VIEWS)])

    def action_cycle_subtab_reverse(self) -> None:
        """Switch to the previous Tools view."""

        self._set_view(VIEWS[(VIEWS.index(self._view) - 1) % len(VIEWS)])

    def action_toggle_scope(self) -> None:
        """Toggle current-project filtering (``A`` toggles all projects)."""

        self._all_projects = not self._all_projects
        self._session_state.all_projects = self._all_projects
        self._request_reload(force=True)

    def action_reload_tool_runs(self) -> None:
        """Reload all three Tools views."""

        self._request_reload(force=True)

    def action_focus_detail(self) -> None:
        """Focus the detail region."""

        try:
            self.query_one("#tools-detail-scroll", VerticalScroll).focus()
        except Exception:
            pass


__all__ = ["ToolRunsPaneEventsMixin"]
