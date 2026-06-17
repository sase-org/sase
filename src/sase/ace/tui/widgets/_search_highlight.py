"""Search highlight overlay for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from rich.style import Style
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.ace.tui.widgets._vim_search import (
    SearchDirection,
    SearchSelection,
    SearchSpan,
    find_search_matches,
    select_search_match,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class SearchHighlightMixin(_MixinBase):
    """Overlay prompt search matches on top of TextArea highlighting."""

    if TYPE_CHECKING:
        _search_match_spans: tuple[SearchSpan, ...]
        _search_current_match_index: int | None

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._search_match_spans: tuple[SearchSpan, ...] = ()
        self._search_current_match_index: int | None = None
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        """Register search styles after earlier overlay themes are installed."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_search_text_area_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_search_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_search_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        if not self._search_match_spans:
            return

        text = self.text
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        current = self._search_current_match_index
        for index, (start, end) in enumerate(self._search_match_spans):
            style_name = "search.current" if index == current else "search.match"
            self._append_highlight_span(start, end, style_name)

    def _set_search_highlights(
        self,
        spans: Iterable[SearchSpan],
        current_index: int | None = None,
        *,
        refresh: bool = True,
    ) -> None:
        """Store prompt search spans and optionally refresh the overlay."""
        clean_spans: list[SearchSpan] = []
        for raw_start, raw_end in spans:
            start = max(0, raw_start)
            end = max(start, raw_end)
            if end > start:
                clean_spans.append((start, end))

        self._search_match_spans = tuple(clean_spans)
        if current_index is not None and 0 <= current_index < len(clean_spans):
            self._search_current_match_index = current_index
        else:
            self._search_current_match_index = None

        if refresh:
            self._refresh_search_overlay()

    def _preview_search_query_highlights(
        self,
        query: str,
        origin: int,
        direction: SearchDirection,
        *,
        include_origin: bool = True,
    ) -> SearchSelection | None:
        """Compute and render search highlights for a query without key handling."""
        spans = find_search_matches(self.text, query)
        selection = select_search_match(
            spans,
            origin,
            direction,
            include_origin=include_origin,
        )
        self._set_search_highlights(
            spans,
            current_index=selection.index if selection is not None else None,
        )
        return selection

    def _clear_search_highlights(self, *, refresh: bool = True) -> None:
        """Clear prompt search spans and optionally refresh the overlay."""
        self._search_match_spans = ()
        self._search_current_match_index = None
        if refresh:
            self._refresh_search_overlay()

    def _refresh_search_overlay(self) -> None:
        self._build_highlight_map()
        self.refresh()

    def _register_search_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_search_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        syntax_styles.update(
            {
                "search.match": Style(
                    color=app_theme.foreground,
                    bgcolor=app_theme.accent,
                    dim=True,
                ),
                "search.current": Style(
                    color=app_theme.foreground,
                    bgcolor=app_theme.warning,
                    bold=True,
                ),
            }
        )
        theme = dataclasses.replace(
            base,
            name=active_name,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)
        if apply:
            self._set_theme(theme.name)

    def _resolve_search_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme
