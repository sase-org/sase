"""Jinja2 syntax highlighting overlay for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from rich.style import Style
from textual.widgets._text_area import TextAreaTheme

from sase.xprompt import jinja_inspect
from sase.xprompt.highlight import MAX_HIGHLIGHT_BYTES, MAX_HIGHLIGHT_LINES

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object

_JINJA_THEME_NAME = "sase-jinja-prompt"
_MAX_OVERLAY_BYTES = MAX_HIGHLIGHT_BYTES
_MAX_OVERLAY_LINES = MAX_HIGHLIGHT_LINES


class JinjaHighlightMixin(_MixinBase):
    """Overlay Jinja2 spans on top of TextArea's markdown highlighting."""

    if TYPE_CHECKING:
        _jinja_error_span: tuple[int, int] | None
        _jinja_matching_delimiter_spans: tuple[tuple[int, int], ...]
        _jinja_unknown_spans: tuple[tuple[int, int], ...]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._jinja_error_span: tuple[int, int] | None = None
        self._jinja_unknown_spans: tuple[tuple[int, int], ...] = ()
        self._jinja_matching_delimiter_spans: tuple[tuple[int, int], ...] = ()
        self._jinja_base_theme_name = "css"
        super().__init__(*args, **kwargs)
        self._jinja_base_theme_name = str(getattr(self, "theme", "css"))

    def on_mount(self) -> None:
        """Register the theme-aware Jinja overlay after the app is available."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_jinja_text_area_theme()
        self.theme = _JINJA_THEME_NAME

    def _app_theme_changed(self) -> None:
        self._register_jinja_text_area_theme()
        super()._app_theme_changed()

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        for span in jinja_inspect.tokenize(text):
            self._append_highlight_span(
                span.start,
                span.end,
                f"jinja.{span.kind}",
            )
        if self._jinja_error_span is not None:
            start, end = self._jinja_error_span
            self._append_highlight_span(start, end, "jinja.error")
        for start, end in self._jinja_unknown_spans:
            self._append_highlight_span(start, end, "jinja.unknown")
        for start, end in self._jinja_matching_delimiter_spans:
            self._append_highlight_span(start, end, "jinja.match")

    def _append_highlight_span(
        self,
        start: int,
        end: int,
        style_name: str,
    ) -> None:
        if end <= start:
            end = start + 1
        for row, start_byte, end_byte in _line_byte_spans(self.text, start, end):
            self._highlights[row].append((start_byte, end_byte, style_name))

    def _refresh_jinja_overlay(self) -> None:
        self._build_highlight_map()
        self.refresh()

    def _register_jinja_text_area_theme(self) -> None:
        base = self._resolve_jinja_base_theme()
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        syntax_styles.update(
            {
                "jinja.delimiter": Style(color=app_theme.accent, dim=True),
                "jinja.statement": Style(color=app_theme.accent, bold=True),
                "jinja.keyword": Style(color=app_theme.accent, bold=True),
                "jinja.variable": Style(color=app_theme.secondary, bold=True),
                "jinja.filter": Style(color=app_theme.success),
                "jinja.comment": Style(
                    color=app_theme.foreground, dim=True, italic=True
                ),
                "jinja.operator": Style(color=app_theme.foreground, dim=True),
                "jinja.error": Style(color=app_theme.error, underline=True),
                "jinja.unknown": Style(color=app_theme.warning, underline=True),
                "jinja.match": Style(
                    color=app_theme.foreground,
                    bgcolor=app_theme.accent,
                    bold=True,
                ),
            }
        )
        theme = dataclasses.replace(
            base,
            name=_JINJA_THEME_NAME,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)

    def _resolve_jinja_base_theme(self) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[self._jinja_base_theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(self._jinja_base_theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme


def _line_byte_spans(
    text: str,
    start: int,
    end: int,
) -> list[tuple[int, int, int | None]]:
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    spans: list[tuple[int, int, int | None]] = []
    row = text.count("\n", 0, start)
    line_start = text.rfind("\n", 0, start) + 1
    cursor = start
    while cursor < end:
        newline = text.find("\n", cursor, end)
        line_end = end if newline == -1 else newline
        start_byte = len(text[line_start:cursor].encode("utf-8"))
        end_byte = len(text[line_start:line_end].encode("utf-8"))
        spans.append((row, start_byte, end_byte))
        if newline == -1:
            break
        row += 1
        cursor = newline + 1
        line_start = cursor
    if not spans:
        line_start = text.rfind("\n", 0, start) + 1
        row = text.count("\n", 0, start)
        start_byte = len(text[line_start:start].encode("utf-8"))
        spans.append((row, start_byte, start_byte + 1))
    return spans
