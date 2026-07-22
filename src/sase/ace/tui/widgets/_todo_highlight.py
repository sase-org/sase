"""TODO annotation detection and highlighting for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.color import Color as RichColor
from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.strip import Strip
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.models.agent_status import RUNNING_COLOR
from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


_TODO_HEADER_RE = re.compile(r"(?<!\w)TODO(?!\w)(?:\([^()\n]+\))?:?")
_TODO_MARKER_FOREGROUND = "#000000"
_TODO_NOTE_FOREGROUND_WARMTH = 0.30


@dataclass(frozen=True, slots=True)
class _TodoAnnotationSpan:
    """Character offsets for one TODO header and its remaining line body."""

    header_start: int
    header_end: int
    body_start: int
    body_end: int


def _todo_annotation_spans(text: str) -> tuple[_TodoAnnotationSpan, ...]:
    """Return bounded uppercase-TODO annotations in *text*.

    Offsets are Python character offsets. ``PromptTextArea`` converts them to
    Textual's UTF-8 byte columns through its shared overlay span helper.
    """
    if "TODO" not in text:
        return ()
    if len(text) > _MAX_OVERLAY_BYTES:
        return ()
    if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
        return ()
    if text.count("\n") > _MAX_OVERLAY_LINES:
        return ()
    return _scan_todo_annotation_spans(text)


def todo_annotation_count(text: str) -> int:
    """Return the number of bounded TODO annotations in *text*."""
    return len(_todo_annotation_spans(text))


def _scan_todo_annotation_spans(text: str) -> tuple[_TodoAnnotationSpan, ...]:
    matches = tuple(_TODO_HEADER_RE.finditer(text))
    annotations: list[_TodoAnnotationSpan] = []
    for index, match in enumerate(matches):
        line_end = text.find("\n", match.end())
        if line_end == -1:
            line_end = len(text)
        next_start = matches[index + 1].start() if index + 1 < len(matches) else None
        body_end = (
            next_start
            if next_start is not None and next_start <= line_end
            else line_end
        )
        annotations.append(
            _TodoAnnotationSpan(
                header_start=match.start(),
                header_end=match.end(),
                body_start=match.end(),
                body_end=body_end if match.group().endswith(":") else match.end(),
            )
        )
    return tuple(annotations)


def todo_theme_colors(
    foreground: str | None,
    *,
    dark: bool,
) -> tuple[Color, Color, Color]:
    """Return running-gold chip colors and a theme-aware note foreground."""
    text = Color.parse(foreground or ("#ffffff" if dark else "#000000"))
    chip_background = Color.parse(RUNNING_COLOR)
    chip_foreground = Color.parse(_TODO_MARKER_FOREGROUND)
    note_foreground = text.blend(chip_background, _TODO_NOTE_FOREGROUND_WARMTH)
    return chip_foreground, chip_background, note_foreground


class TodoHighlightMixin(_MixinBase):
    """Overlay cached TODO annotations above prompt syntax highlighting."""

    if TYPE_CHECKING:

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._todo_cache_text: str | None = None
        self._todo_cached_annotations: tuple[_TodoAnnotationSpan, ...] | None = None
        super().__init__(*args, **kwargs)

    @property
    def todo_annotation_count(self) -> int:
        """Return the cached annotation count for the current document."""
        return len(self._todo_annotations_for_document())

    def on_mount(self) -> None:
        """Register TODO styles after the base prompt overlay theme exists."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_todo_text_area_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_todo_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_todo_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        for annotation in self._todo_annotations_for_document():
            self._append_highlight_span(
                annotation.header_start,
                annotation.header_end,
                "todo.header",
            )
            if annotation.body_end > annotation.body_start:
                self._append_highlight_span(
                    annotation.body_start,
                    annotation.body_end,
                    "todo.body",
                )

    def _render_line(self, y: int) -> Strip:
        """Restore selection chrome that the TODO marker chip would hide."""
        strip = super()._render_line(y)
        try:
            return self._restore_todo_selection(strip, y)
        except Exception:
            return strip

    def _restore_todo_selection(self, strip: Strip, y: int) -> Strip:
        selection_start, selection_end = self.selection
        if selection_start == selection_end:
            return strip

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
        selection_top, selection_bottom = sorted(self.selection)
        top_row, top_column = selection_top
        bottom_row, bottom_column = selection_bottom
        if not top_row <= line_index <= bottom_row:
            return strip

        line_length = len(self.document.get_line(line_index))
        selected_start = top_column if line_index == top_row else 0
        selected_end = bottom_column if line_index == bottom_row else line_length
        if selected_end <= selected_start:
            return strip

        start_offset = wrapped_document.location_to_offset((line_index, selected_start))
        end_offset = wrapped_document.location_to_offset((line_index, selected_end))
        if start_offset.y > y_offset or end_offset.y < y_offset:
            return strip

        gutter_width = self.gutter_width
        gutter = strip.crop(0, gutter_width) if gutter_width else None
        content = strip.crop(gutter_width)
        start_cell = start_offset.x if start_offset.y == y_offset else 0
        end_cell = end_offset.x if end_offset.y == y_offset else content.cell_length
        if not self.soft_wrap:
            start_cell -= _scroll_x
            end_cell -= _scroll_x
        start_cell = max(0, min(start_cell, content.cell_length))
        end_cell = max(start_cell, min(end_cell, content.cell_length))
        if end_cell <= start_cell:
            return strip

        selection_style = self._theme.selection_style
        if selection_style is None or selection_style.bgcolor is None:
            return strip
        todo_backgrounds: set[RichColor] = {
            style.bgcolor
            for name in ("todo.header", "todo.body")
            if (style := self._theme.syntax_styles.get(name)) is not None
            and style.bgcolor is not None
        }
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
            and segment.style.bgcolor in todo_backgrounds
            else segment
            for segment in selected._segments
        ]
        restored_content = Strip.join(
            (
                content.crop(0, start_cell),
                Strip(selected_segments, selected.cell_length),
                content.crop(end_cell),
            )
        )
        return Strip.join((gutter, restored_content))

    def _todo_annotations_for_document(self) -> tuple[_TodoAnnotationSpan, ...]:
        """Return annotations cached by exact prompt text."""
        text = self.text
        if self._todo_cache_text != text:
            self._todo_cache_text = text
            self._todo_cached_annotations = _todo_annotation_spans(text)
        return self._todo_cached_annotations or ()

    def _register_todo_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_todo_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        chip_fg, chip_bg, note_fg = todo_theme_colors(
            app_theme.foreground,
            dark=app_theme.dark,
        )
        syntax_styles.update(
            {
                "todo.header": Style(
                    color=chip_fg.hex,
                    bgcolor=chip_bg.hex,
                    bold=True,
                ),
                "todo.body": Style(
                    color=note_fg.hex,
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

    def _resolve_todo_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme
