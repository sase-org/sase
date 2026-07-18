"""Prompt search command-line panel for ``PromptInputBar``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets._vim_search import SearchDirection
from sase.ace.tui.widgets.search_command_line import render_search_command_line

if TYPE_CHECKING:
    from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


class PromptInputBarSearchMixin(_MixinBase):
    """Transient Vim-style search command line for the prompt body."""

    if TYPE_CHECKING:
        _completion_line_count: int
        _completion_panel_kind: str | None
        _completion_visible: bool
        _search_command_line_count: int
        _search_command_visible: bool

        def _frontmatter_panel(self) -> FrontmatterPanel | None: ...
        def _schedule_height_update(self) -> None: ...
        def hide_soft_completion(self) -> None: ...
        def hide_g_prefix_hints(self) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._prompt_search_register: tuple[str, SearchDirection] | None = None
        super().__init__(*args, **kwargs)

    def record_prompt_search(
        self,
        query: str,
        direction: SearchDirection,
    ) -> None:
        """Record the last successful search shared by this bar's panes."""
        self._prompt_search_register = (query, direction)

    def prompt_search_register(self) -> tuple[str, SearchDirection] | None:
        """Return the last successful search shared by this bar's panes."""
        return self._prompt_search_register

    def prepare_search_command_line(self) -> None:
        """Hide other transient prompt panels before search opens."""
        self._hide_completion_panel_for_search()
        try:
            self.hide_g_prefix_hints()
        except Exception:
            pass
        frontmatter = None
        try:
            frontmatter = self._frontmatter_panel()
        except Exception:
            pass
        if frontmatter is not None and not frontmatter.has_class("hidden"):
            frontmatter.add_class("hidden")
            self._schedule_height_update()

    def _hide_completion_panel_for_search(self) -> None:
        """Hide completion/Jinja panels without restoring diagnostics."""
        try:
            self.hide_soft_completion()
        except Exception:
            pass
        try:
            panel = self.query_one("#prompt-completion", Static)
        except Exception:
            return
        panel.update("")
        panel.border_title = ""
        panel.border_subtitle = ""
        panel.remove_class("jinja-diagnostics")
        panel.remove_class("jinja-error")
        panel.remove_class("jinja-warning")
        panel.add_class("hidden")
        self._completion_visible = False
        self._completion_panel_kind = None
        self._completion_line_count = 0
        self._schedule_height_update()

    def show_search_command_line(
        self,
        *,
        direction: SearchDirection,
        query: str,
        current_index: int | None,
        total: int,
    ) -> None:
        """Render and reveal the search command line."""
        try:
            panel = self.query_one("#prompt-search-command", Static)
        except Exception:
            return

        panel.border_title = "search"
        panel.border_subtitle = "[enter] accept  [esc/^c] cancel"
        panel.update(
            self._render_search_command_line(
                direction=direction,
                query=query,
                current_index=current_index,
                total=total,
            )
        )
        panel.remove_class("hidden")

        was_visible = self._search_command_visible
        old_line_count = self._search_command_line_count
        self._search_command_visible = True
        self._search_command_line_count = 4
        if not was_visible or old_line_count != self._search_command_line_count:
            self._schedule_height_update()

    def hide_search_command_line(self) -> None:
        """Hide the search command line."""
        if not self._search_command_visible:
            return
        try:
            panel = self.query_one("#prompt-search-command", Static)
        except Exception:
            return

        panel.update("")
        panel.border_title = ""
        panel.border_subtitle = ""
        panel.add_class("hidden")
        self._search_command_visible = False
        self._search_command_line_count = 0
        self._schedule_height_update()

    def _render_search_command_line(
        self,
        *,
        direction: SearchDirection,
        query: str,
        current_index: int | None,
        total: int,
    ) -> Text:
        width = max(0, int(getattr(self.size, "width", 0)) - 4)
        return render_search_command_line(
            direction=direction,
            query=query,
            current_index=current_index,
            total=total,
            width=width,
        )
