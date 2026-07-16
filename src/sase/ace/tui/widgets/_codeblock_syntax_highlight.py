"""Fenced and inline code highlighting for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from rich.color import Color as RichColor
from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.strip import Strip
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

_FENCED_CODE_SURFACE_BLEND = 0.08
_INLINE_CODE_SURFACE_BLEND = 0.22
_INLINE_CODE_DELIMITER_BLEND = 0.45

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class CodeBlockHighlightMixin(_MixinBase):
    """Overlay launch-accurate code literal zones and injected syntax spans."""

    if TYPE_CHECKING:
        _codeblock_band_lines: frozenset[int]

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._codeblock_band_lines: frozenset[int] = frozenset()
        super().__init__(*args, **kwargs)

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
        self._codeblock_band_lines = frozenset()
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

        band_lines: set[int] = set()
        line_cursor = 0
        offset_cursor = 0
        for block in details:
            block_start, block_end = block.block_range
            first_line = line_cursor + text.count("\n", offset_cursor, block_start)
            last_line = first_line + text.count("\n", block_start, block_end)
            band_lines.update(range(first_line, last_line + 1))
            line_cursor = last_line
            offset_cursor = block_end
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
        self._codeblock_band_lines = frozenset(band_lines)

        for start, end in inline_ranges:
            delimiter_length = _backtick_run_length(text, start)
            content_start = start + delimiter_length
            content_end = end - delimiter_length
            self._append_highlight_span(start, end, "codeblock.inline")
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

    def _render_line(self, y: int) -> Strip:
        """Paint fenced code blocks as full-width, overlay-safe cards."""
        strip = super()._render_line(y)
        original_strip = strip
        try:
            _scroll_x, scroll_y = self.scroll_offset
            y_offset = y + scroll_y
            wrapped_document = self.wrapped_document
            if y_offset >= wrapped_document.height:
                return strip

            try:
                line_info = wrapped_document._offset_to_line_info[y_offset]
            except IndexError:
                return strip
            if line_info is None:
                return strip

            line_index, _section_offset = line_info
            if line_index not in self._codeblock_band_lines:
                return strip

            theme = self._theme
            card_style = theme.syntax_styles.get("codeblock.content")
            if card_style is None or card_style.bgcolor is None:
                return strip

            base_style = theme.base_style or self.rich_style
            fill_backgrounds = {base_style.bgcolor}
            if theme.cursor_line_style is not None:
                fill_backgrounds.add(theme.cursor_line_style.bgcolor)
            fill_backgrounds.discard(None)
            if not fill_backgrounds:
                return strip

            gutter_width = self.gutter_width
            gutter = strip.crop(0, gutter_width) if gutter_width else None
            content = strip.crop(gutter_width)
            card_background = Style(bgcolor=card_style.bgcolor)
            segments = [
                Segment(
                    segment.text,
                    (segment.style or Style.null()) + card_background,
                    segment.control,
                )
                if segment.control is None
                and segment.style is not None
                and segment.style.bgcolor in fill_backgrounds
                else segment
                for segment in content._segments
            ]
            painted_content = Strip(segments, content.cell_length)
            painted_content = self._restore_codeblock_selection(
                painted_content,
                line_index=line_index,
                y_offset=y_offset,
                scroll_x=_scroll_x,
                card_background=card_style.bgcolor,
            )
            return Strip.join((gutter, painted_content))
        except Exception:
            return original_strip

    def _restore_codeblock_selection(
        self,
        content: Strip,
        *,
        line_index: int,
        y_offset: int,
        scroll_x: int,
        card_background: RichColor,
    ) -> Strip:
        """Restore a selection background hidden by the fallback content tint."""
        selection_start, selection_end = self.selection
        if selection_start == selection_end:
            return content

        selection_top, selection_bottom = sorted(self.selection)
        top_row, top_column = selection_top
        bottom_row, bottom_column = selection_bottom
        if not top_row <= line_index <= bottom_row:
            return content

        line_length = len(self.document.get_line(line_index))
        selected_start = top_column if line_index == top_row else 0
        selected_end = bottom_column if line_index == bottom_row else line_length
        if selected_end <= selected_start:
            return content

        wrapped_document = self.wrapped_document
        start_offset = wrapped_document.location_to_offset((line_index, selected_start))
        end_offset = wrapped_document.location_to_offset((line_index, selected_end))
        if start_offset.y > y_offset or end_offset.y < y_offset:
            return content

        start_cell = start_offset.x if start_offset.y == y_offset else 0
        end_cell = end_offset.x if end_offset.y == y_offset else content.cell_length
        if not self.soft_wrap:
            start_cell -= scroll_x
            end_cell -= scroll_x
        start_cell = max(0, min(start_cell, content.cell_length))
        end_cell = max(start_cell, min(end_cell, content.cell_length))
        if end_cell <= start_cell:
            return content

        selection_style = self._theme.selection_style
        if selection_style is None or selection_style.bgcolor is None:
            return content
        selection_background = Style(bgcolor=selection_style.bgcolor)
        selected = content.crop(start_cell, end_cell)
        selected_segments = [
            Segment(
                segment.text,
                (segment.style or Style.null()) + selection_background,
                segment.control,
            )
            if segment.control is None
            and segment.style is not None
            and segment.style.bgcolor == card_background
            else segment
            for segment in selected._segments
        ]
        return Strip.join(
            (
                content.crop(0, start_cell),
                Strip(selected_segments, selected.cell_length),
                content.crop(end_cell),
            )
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
        background_color = Color.parse(app_theme.background or "#000000")
        foreground_color = Color.parse(app_theme.foreground or "#ffffff")
        inline_background_color, inline_foreground_color = (
            _resolve_codeblock_theme_colors(
                app_theme.background,
                app_theme.foreground,
                dark=app_theme.dark,
            )
        )
        card_background = background_color.blend(
            foreground_color, _FENCED_CODE_SURFACE_BLEND
        )
        inline_background = inline_background_color.blend(
            inline_foreground_color, _INLINE_CODE_SURFACE_BLEND
        )
        delimiter_foreground = inline_foreground_color.blend(
            inline_background, _INLINE_CODE_DELIMITER_BLEND
        )
        syntax_styles.update(
            {
                "codeblock.content": Style(
                    bgcolor=card_background.hex,
                ),
                "codeblock.inline": Style(
                    color=inline_foreground_color.hex,
                    bgcolor=inline_background.hex,
                    bold=False,
                    italic=False,
                ),
                "codeblock.fence": Style(
                    color=foreground_color.blend(background_color, 0.35).hex,
                ),
                "codeblock.delimiter": Style(
                    color=delimiter_foreground.hex,
                    bgcolor=inline_background.hex,
                    bold=False,
                    italic=False,
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


def _resolve_codeblock_theme_colors(
    background: str | None,
    foreground: str | None,
    *,
    dark: bool,
) -> tuple[Color, Color]:
    """Resolve a neutral canvas and legible text color for code treatments."""
    background_fallback = "#000000" if dark else "#ffffff"
    foreground_fallback = "#ffffff" if dark else "#000000"
    return (
        Color.parse(background or background_fallback),
        Color.parse(foreground or foreground_fallback),
    )


def _backtick_run_length(text: str, start: int) -> int:
    end = start
    while end < len(text) and text[end] == "`":
        end += 1
    return end - start
