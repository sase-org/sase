"""Navigation, input, and small widget helpers for the Updates plugin browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from rich.console import RenderableType
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static

from .plugins_browser_constants import _HEADER_PREFIX
from .plugins_browser_input import PluginsFilterInput

if TYPE_CHECKING:
    from textual.app import App


class PluginsBrowserControlsMixin:
    """User-input actions and widget lookup helpers for PluginsBrowserPane."""

    if TYPE_CHECKING:
        _filter_text: str
        _active_subtab: str
        _loading: bool
        _offline: bool
        _verbose: bool
        app: App[object]

        def _hints(self) -> str: ...

        def _rebuild_groups(self) -> None: ...

        def _rebuild_options(self) -> None: ...

        def _render_detail_now(self, *, force: bool = False) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

        def _sync_state_visibility(self) -> None: ...

    def focus_default(self) -> None:
        """Focus the active browser list, or the pane itself for Core."""
        option_list = self._active_option_list()
        if option_list is not None:
            option_list.focus()
        else:
            cast(Widget, self).focus()

    def action_next_option(self) -> None:
        """Move to the next non-header option."""
        option_list = self._active_option_list()
        if option_list is None:
            return
        current = option_list.highlighted
        start = 0 if current is None else current + 1
        for index in range(start, option_list.option_count):
            if self._is_item(option_list, index):
                option_list.highlighted = index
                return

    def action_prev_option(self) -> None:
        """Move to the previous non-header option."""
        option_list = self._active_option_list()
        if option_list is None or option_list.highlighted is None:
            return
        for index in range(option_list.highlighted - 1, -1, -1):
            if self._is_item(option_list, index):
                option_list.highlighted = index
                return

    def action_focus_filter(self) -> None:
        try:
            self.query_one("#plugins-filter-input", PluginsFilterInput).focus()  # type: ignore[attr-defined]
        except Exception:
            pass

    def action_refresh(self) -> None:
        """Refetch the catalog and latest versions (the ``-r/--refresh`` analog)."""
        if self._loading:
            return
        self._start_load(force=True)

    def action_toggle_offline(self) -> None:
        """Toggle offline (cache-only) mode and reload (the ``-o`` analog)."""
        if self._loading:
            return
        self._offline = not self._offline
        self._start_load(force=False)

    def action_toggle_verbose(self) -> None:
        """Toggle the list rows' verbose columns (stars / updated)."""
        self._verbose = not self._verbose
        self._rebuild_options()
        self._update_static("#plugins-hints", self._hints())
        self._render_detail_now(force=True)

    def action_scroll_detail_down(self) -> None:
        """Scroll the plugin detail pane down by half a page."""
        scroll = self._detail_scroll()
        if scroll is None:
            return
        height = scroll.scrollable_content_region.height
        self._force_scroll_detail_to(scroll.scroll_y + height // 2, scroll=scroll)

    def action_scroll_detail_up(self) -> None:
        """Scroll the plugin detail pane up by half a page."""
        scroll = self._detail_scroll()
        if scroll is None:
            return
        height = scroll.scrollable_content_region.height
        self._force_scroll_detail_to(scroll.scroll_y - height // 2, scroll=scroll)

    def action_scroll_to_top(self) -> None:
        """Scroll the plugin detail pane to the top (highlight unchanged)."""
        scroll = self._detail_scroll()
        if scroll is not None:
            self._force_scroll_detail_to(0, scroll=scroll)

    def action_scroll_to_bottom(self) -> None:
        """Scroll the plugin detail pane to the bottom (highlight unchanged)."""
        scroll = self._detail_scroll()
        if scroll is not None:
            self._force_scroll_detail_to(scroll.max_scroll_y, scroll=scroll)

    def _detail_scroll(self) -> VerticalScroll | None:
        try:
            selector = (
                "#agent-clis-detail-scroll"
                if self._active_subtab == "agent-clis"
                else "#plugins-detail-scroll"
            )
            return self.query_one(selector, VerticalScroll)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _force_scroll_detail_to(
        self, y: float, *, scroll: VerticalScroll | None = None
    ) -> None:
        scroll = scroll or self._detail_scroll()
        if scroll is None:
            return
        target = max(0, min(int(y), int(scroll.max_scroll_y)))
        scroll._scroll_to(y=target, animate=False, force=True)  # noqa: SLF001

    def _notify(
        self,
        message: str,
        *,
        severity: Literal["information", "warning", "error"] = "information",
    ) -> None:
        """Toast *message*, tolerating an already-unmounted pane/app."""
        try:
            self.app.notify(message, severity=severity)
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "plugins-filter-input":
            return
        self._filter_text = event.value
        self._rebuild_groups()
        self._rebuild_options()
        self._sync_state_visibility()
        self._render_detail_now(force=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "plugins-filter-input":
            # Keep the filter applied; hand control back to the list.
            self.focus_default()

    def cancel_input(self) -> None:
        """Drop any in-progress filter and return focus to the list."""
        if self._filter_text:
            self._filter_text = ""
            self._set_filter_value("")
            self._rebuild_groups()
            self._rebuild_options()
            self._sync_state_visibility()
            self._render_detail_now(force=True)
        self.focus_default()

    def _option_list(self) -> OptionList | None:
        try:
            return self.query_one("#plugins-list", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _active_option_list(self) -> OptionList | None:
        if self._active_subtab == "agent-clis":
            try:
                return self.query_one("#agent-clis-list", OptionList)  # type: ignore[attr-defined]
            except Exception:
                return None
        if self._active_subtab == "plugins":
            return self._option_list()
        return None

    def _detail_widget(self) -> Static | None:
        try:
            return self.query_one("#plugins-detail", Static)  # type: ignore[attr-defined]
        except Exception:
            return None

    @staticmethod
    def _is_item(option_list: OptionList, index: int) -> bool:
        try:
            opt = option_list.get_option_at_index(index)
        except Exception:
            return False
        return bool(opt.id) and not str(opt.id).startswith(_HEADER_PREFIX)

    def _set_filter_value(self, value: str) -> None:
        try:
            self.query_one("#plugins-filter-input", PluginsFilterInput).value = value  # type: ignore[attr-defined]
        except Exception:
            pass

    def _update_static(self, selector: str, content: RenderableType) -> None:
        try:
            self.query_one(selector, Static).update(content)  # type: ignore[attr-defined]
        except Exception:
            pass
