"""Fenced and inline code highlighting for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from rich.style import Style
from textual.color import Color
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.util.code_injection import (
    injected_highlights,
    language_for_info_string,
)
from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.xprompt._fenced_blocks import fenced_block_details
from sase.xprompt._literal_zones import inline_literal_ranges

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class CodeBlockHighlightMixin(_MixinBase):
    """Overlay launch-accurate code literal zones and injected syntax spans."""

    if TYPE_CHECKING:

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def on_mount(self) -> None:
        """Register code styles after the base Jinja theme exists."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_codeblock_text_area_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_codeblock_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_codeblock_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        if "`" not in text and "~" not in text:
            return
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        try:
            details = fenced_block_details(text)
            inline_ranges = inline_literal_ranges(text)
        except Exception:
            return

        for block in details:
            if block.content_range[1] > block.content_range[0]:
                self._append_highlight_span(
                    *block.content_range,
                    "codeblock.content",
                )
            self._append_highlight_span(*block.opening_fence, "codeblock.fence")
            if block.info_string is not None:
                self._append_highlight_span(*block.info_string, "codeblock.lang")
            if block.closing_fence is not None:
                self._append_highlight_span(*block.closing_fence, "codeblock.fence")
            self._append_injected_highlights(
                text, block.content_range, block.info_string
            )

        for start, end in inline_ranges:
            delimiter_length = _backtick_run_length(text, start)
            content_start = start + delimiter_length
            content_end = end - delimiter_length
            if content_end > content_start:
                self._append_highlight_span(
                    content_start,
                    content_end,
                    "codeblock.inline",
                )
            self._append_highlight_span(
                start,
                content_start,
                "codeblock.delimiter",
            )
            self._append_highlight_span(
                content_end,
                end,
                "codeblock.delimiter",
            )

    def _append_injected_highlights(
        self,
        text: str,
        content_range: tuple[int, int],
        info_string: tuple[int, int] | None,
    ) -> None:
        if info_string is None:
            return
        language = language_for_info_string(text[slice(*info_string)])
        if language is None:
            return
        content_start, content_end = content_range
        code = text[content_start:content_end]
        start_row = text.count("\n", 0, content_start)
        try:
            highlights = injected_highlights(language, code)
        except Exception:
            return
        for highlight in highlights:
            self._highlights[start_row + highlight.row].append(
                (
                    highlight.start_byte,
                    highlight.end_byte,
                    highlight.name,
                )
            )

    def _register_codeblock_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_codeblock_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        background = app_theme.background or "#000000"
        foreground = app_theme.foreground or "#ffffff"
        background_color = Color.parse(background)
        foreground_color = Color.parse(foreground)
        syntax_styles.update(
            {
                "codeblock.content": Style(
                    bgcolor=background_color.blend(foreground_color, 0.07).hex,
                ),
                "codeblock.inline": Style(
                    bgcolor=background_color.blend(foreground_color, 0.10).hex,
                ),
                "codeblock.fence": Style(
                    color=foreground_color.blend(background_color, 0.45).hex,
                    dim=True,
                ),
                "codeblock.delimiter": Style(
                    color=foreground_color.blend(background_color, 0.45).hex,
                    dim=True,
                ),
                "codeblock.lang": Style(
                    color=app_theme.accent,
                    italic=True,
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

    def _resolve_codeblock_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme


def _backtick_run_length(text: str, start: int) -> int:
    end = start
    while end < len(text) and text[end] == "`":
        end += 1
    return end - start
