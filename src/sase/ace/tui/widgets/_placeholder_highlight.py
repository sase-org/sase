"""Placeholder highlighting and per-document scan caches for the prompt."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from rich.style import Style
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.ace.tui.widgets.placeholder_completion import (
    PlaceholderCompletionResult,
    build_placeholder_completion_result,
    editor_range_to_offsets,
)
from sase.xprompt.placeholder_completion import PlaceholderSpan, placeholder_spans

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class PlaceholderHighlightMixin(_MixinBase):
    """Overlay placeholders and memoize Rust scans for one document edit."""

    if TYPE_CHECKING:

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._placeholder_cache_text: str | None = None
        self._placeholder_cached_spans: tuple[PlaceholderSpan, ...] | None = None
        self._placeholder_cached_completion_key: tuple[int, int] | None = None
        self._placeholder_cached_completion: PlaceholderCompletionResult | None = None
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        """Register placeholder styles after the shared overlay theme exists."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_placeholder_text_area_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_placeholder_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_placeholder_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        if "<" not in text or ">" not in text:
            return
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        for span in self._placeholder_spans_for_document():
            full_range = editor_range_to_offsets(text, span.range)
            inner_range = editor_range_to_offsets(text, span.inner_range)
            if full_range is None or inner_range is None:
                continue
            full_start, full_end = full_range
            inner_start, inner_end = inner_range
            self._append_highlight_span(
                full_start,
                inner_start,
                "placeholder.delimiter",
            )
            self._append_highlight_span(
                inner_start,
                inner_end,
                "placeholder.inner",
            )
            self._append_highlight_span(
                inner_end,
                full_end,
                "placeholder.delimiter",
            )

    def _placeholder_completion_at_cursor(
        self,
    ) -> PlaceholderCompletionResult | None:
        """Return a completion payload cached for the current text and cursor."""
        text = self.text
        self._invalidate_placeholder_cache_for(text)
        cursor_offset = self._absolute_offset(self.cursor_location)
        key = (cursor_offset, len(text))
        if self._placeholder_cached_completion_key != key:
            self._placeholder_cached_completion = build_placeholder_completion_result(
                text,
                cursor_offset,
            )
            self._placeholder_cached_completion_key = key
        return self._placeholder_cached_completion

    def _placeholder_spans_for_document(self) -> tuple[PlaceholderSpan, ...]:
        """Return spans cached for the current prompt text."""
        text = self.text
        self._invalidate_placeholder_cache_for(text)
        if self._placeholder_cached_spans is None:
            self._placeholder_cached_spans = placeholder_spans(text)
        return self._placeholder_cached_spans

    def _invalidate_placeholder_cache_for(self, text: str) -> None:
        if self._placeholder_cache_text == text:
            return
        self._placeholder_cache_text = text
        self._placeholder_cached_spans = None
        self._placeholder_cached_completion_key = None
        self._placeholder_cached_completion = None

    def _register_placeholder_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_placeholder_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        syntax_styles.update(
            {
                "placeholder.delimiter": Style(color=app_theme.accent, dim=True),
                "placeholder.inner": Style(color=app_theme.secondary, bold=True),
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

    def _resolve_placeholder_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme
