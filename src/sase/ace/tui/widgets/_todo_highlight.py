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
from sase.ace.tui.widgets._bullet_highlight import bullet_dash_spans
from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.xprompt._literal_zones import code_literal_ranges

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


_TODO_HEADER_RE = re.compile(r"(?<!\w)TODO(?!\w)(?:\([^()\n]+\))?:?")
_TODO_LIST_ITEM_QUERY = "(list_item) @item"
_TODO_MARKER_FOREGROUND = "#00005F"
_TODO_NOTE_FOREGROUND_WARMTH = 0.30


@dataclass(frozen=True, slots=True)
class _TodoAnnotationSpan:
    """Character offsets for one TODO header and its presentation body."""

    header_start: int
    header_end: int
    body_start: int
    body_end: int


@dataclass(frozen=True, slots=True)
class _TodoListItemSpan:
    """Character offsets for a dash-list item's content start and end."""

    content_start: int
    item_end: int


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
    matches = _todo_header_matches(text)
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


def _todo_header_matches(text: str) -> tuple[re.Match[str], ...]:
    """Return TODO matches whose starts are outside prompt code literals."""
    literal_ranges = code_literal_ranges(text) if "`" in text or "~~~" in text else ()
    if not literal_ranges:
        return tuple(_TODO_HEADER_RE.finditer(text))

    matches: list[re.Match[str]] = []
    literal_index = 0
    for match in _TODO_HEADER_RE.finditer(text):
        match_start = match.start()
        while (
            literal_index < len(literal_ranges)
            and literal_ranges[literal_index][1] <= match_start
        ):
            literal_index += 1
        if (
            literal_index < len(literal_ranges)
            and literal_ranges[literal_index][0]
            <= match_start
            < literal_ranges[literal_index][1]
        ):
            continue
        matches.append(match)
    return tuple(matches)


def _point_to_character_offset(
    text: str,
    line_starts: tuple[int, ...],
    point: tuple[int, int],
) -> int:
    """Convert a tree-sitter UTF-8 point to a clamped character offset."""
    row, byte_column = point
    if row < 0:
        return 0
    if row >= len(line_starts):
        return len(text)

    line_start = line_starts[row]
    newline = text.find("\n", line_start)
    line_end = len(text) if newline == -1 else newline
    encoded_line = text[line_start:line_end].encode("utf-8")
    byte_column = max(0, min(byte_column, len(encoded_line)))
    character_column = len(encoded_line[:byte_column].decode("utf-8", errors="ignore"))
    return min(len(text), line_start + character_column)


def _line_start_offsets(text: str) -> tuple[int, ...]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer("\n", text))
    return tuple(starts)


def _merged_body_ranges(
    annotations: tuple[_TodoAnnotationSpan, ...],
) -> tuple[tuple[int, int], ...]:
    """Return sorted, merged non-empty body ranges."""
    merged: list[tuple[int, int]] = []
    for annotation in annotations:
        start = annotation.body_start
        end = annotation.body_end
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _bullet_spans_overlapping_bodies(
    text: str,
    annotations: tuple[_TodoAnnotationSpan, ...],
) -> tuple[tuple[int, int], ...]:
    """Return structural dashes that need re-layering over TODO bodies."""
    bodies = _merged_body_ranges(annotations)
    if not bodies:
        return ()

    overlaps: list[tuple[int, int]] = []
    body_index = 0
    for start, end in bullet_dash_spans(text):
        while body_index < len(bodies) and bodies[body_index][1] <= start:
            body_index += 1
        if body_index >= len(bodies):
            break
        body_start, body_end = bodies[body_index]
        if body_start < end and start < body_end:
            overlaps.append((start, end))
    return tuple(overlaps)


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
        self._todo_cached_base_annotations: tuple[_TodoAnnotationSpan, ...] | None = (
            None
        )
        self._todo_cached_list_items: tuple[_TodoListItemSpan, ...] | None = None
        self._todo_cached_annotations: tuple[_TodoAnnotationSpan, ...] | None = None
        self._todo_list_item_query: Any | None = None
        self._todo_list_item_query_unavailable = False
        super().__init__(*args, **kwargs)

    @property
    def todo_annotation_count(self) -> int:
        """Return the cached annotation count for the current document."""
        return len(self._todo_base_annotations_for_document())

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
        annotations = self._todo_annotations_for_document()
        for annotation in annotations:
            if annotation.body_end > annotation.body_start:
                self._append_highlight_span(
                    annotation.body_start,
                    annotation.body_end,
                    "todo.body",
                )
        for annotation in annotations:
            self._append_highlight_span(
                annotation.header_start,
                annotation.header_end,
                "todo.header",
            )
        for start, end in _bullet_spans_overlapping_bodies(self.text, annotations):
            self._append_highlight_span(start, end, "bullet.dash")

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
        """Return list-aware annotations cached by exact prompt text."""
        text = self.text
        self._reset_todo_cache_for_text(text)
        if self._todo_cached_annotations is None:
            annotations = self._todo_base_annotations_for_document()
            item_ends = {
                item.content_start: item.item_end
                for item in self._todo_list_items_for_document()
            }
            self._todo_cached_annotations = tuple(
                dataclasses.replace(
                    annotation,
                    body_end=item_ends[annotation.header_start],
                )
                if text[annotation.header_start : annotation.header_end] == "TODO:"
                and annotation.header_start in item_ends
                else annotation
                for annotation in annotations
            )
        return self._todo_cached_annotations or ()

    def _todo_base_annotations_for_document(
        self,
    ) -> tuple[_TodoAnnotationSpan, ...]:
        """Return literal-aware annotations without querying Markdown."""
        text = self.text
        self._reset_todo_cache_for_text(text)
        if self._todo_cached_base_annotations is None:
            self._todo_cached_base_annotations = _todo_annotation_spans(text)
        return self._todo_cached_base_annotations

    def _todo_list_items_for_document(self) -> tuple[_TodoListItemSpan, ...]:
        """Return dash-list item boundaries from the incremental Markdown tree."""
        text = self.text
        self._reset_todo_cache_for_text(text)
        if self._todo_cached_list_items is not None:
            return self._todo_cached_list_items

        self._todo_cached_list_items = self._query_todo_list_items(text)
        return self._todo_cached_list_items

    def _query_todo_list_items(self, text: str) -> tuple[_TodoListItemSpan, ...]:
        if self._todo_list_item_query_unavailable:
            return ()

        document = self.document
        try:
            if self._todo_list_item_query is None:
                self._todo_list_item_query = document.prepare_query(
                    _TODO_LIST_ITEM_QUERY
                )
                if self._todo_list_item_query is None:
                    self._todo_list_item_query_unavailable = True
                    return ()
            captures = document.query_syntax_tree(self._todo_list_item_query)
        except Exception:
            self._todo_list_item_query_unavailable = True
            self._todo_list_item_query = None
            return ()

        line_starts = _line_start_offsets(text)
        items: list[_TodoListItemSpan] = []
        for item_node in captures.get("item", ()):
            named_children = item_node.named_children
            if not named_children:
                continue
            marker = named_children[0]
            if marker.type != "list_marker_minus":
                continue
            content_start = _point_to_character_offset(
                text,
                line_starts,
                marker.end_point,
            )
            item_end = _point_to_character_offset(
                text,
                line_starts,
                item_node.end_point,
            )
            if item_end >= content_start:
                items.append(
                    _TodoListItemSpan(
                        content_start=content_start,
                        item_end=min(item_end, len(text)),
                    )
                )
        return tuple(items)

    def _reset_todo_cache_for_text(self, text: str) -> None:
        if self._todo_cache_text == text:
            return
        self._todo_cache_text = text
        self._todo_cached_base_annotations = None
        self._todo_cached_list_items = None
        self._todo_cached_annotations = None

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
