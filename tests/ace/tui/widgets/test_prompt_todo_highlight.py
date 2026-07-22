"""TODO annotation detection and ``PromptTextArea`` overlay coverage."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rich.color import Color
from rich.style import Style
from textual.app import App, ComposeResult
from textual.widgets.text_area import Selection

from sase.ace.tui.models.agent_status import RUNNING_COLOR
from sase.ace.tui.widgets import _todo_highlight
from sase.ace.tui.widgets._jinja_highlight import (
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.ace.tui.widgets._todo_highlight import (
    _TodoAnnotationSpan,
    _todo_annotation_spans,
    todo_theme_colors,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def _highlight_names(text_area: PromptTextArea) -> list[str]:
    return [name for row in text_area._highlights.values() for *_range, name in row]


@pytest.mark.parametrize(
    ("text", "expected_headers"),
    [
        ("TODO", ("TODO",)),
        ("TODO: ship it", ("TODO:",)),
        ("TODO(bryan) is owned", ("TODO(bryan)",)),
        ("- [ ] TODO(bryan): ship it", ("TODO(bryan):",)),
        ("preTODO TODOS TODO2 todo TODO", ("TODO",)),
        ("TODO: first TODO(owner): second", ("TODO:", "TODO(owner):")),
        ('A quoted "TODO" remains ordinary.', ("TODO",)),
        ("`TODO: literal`\n```\nTODO(dev): fenced\n```", ("TODO:", "TODO(dev):")),
    ],
)
def test_todo_annotation_contract(
    text: str,
    expected_headers: tuple[str, ...],
) -> None:
    spans = _todo_annotation_spans(text)

    assert tuple(text[span.header_start : span.header_end] for span in spans) == (
        expected_headers
    )


def test_todo_annotation_body_stops_before_the_next_marker_on_a_line() -> None:
    text = "TODO: first task; TODO(owner): second task"

    first, second = _todo_annotation_spans(text)

    assert text[first.body_start : first.body_end] == " first task; "
    assert text[second.body_start : second.body_end] == " second task"


def test_only_colon_terminated_todo_headers_activate_body_notes() -> None:
    text = 'A quoted "TODO" remains plain; TODO: styled note; TODO(owner)! plain'

    quoted, colon_terminated, owned = _todo_annotation_spans(text)

    assert quoted.body_start == quoted.body_end == quoted.header_end
    assert text[colon_terminated.body_start : colon_terminated.body_end] == (
        " styled note; "
    )
    assert owned.body_start == owned.body_end == owned.header_end


def test_todo_count_includes_all_supported_header_forms() -> None:
    assert (
        _todo_highlight.todo_annotation_count(
            "TODO TODO: TODO(owner) TODO(owner): note"
        )
        == 4
    )


def test_todo_annotation_fast_path_and_overlay_ceilings() -> None:
    with patch.object(_todo_highlight, "_scan_todo_annotation_spans") as scan:
        assert _todo_annotation_spans("ordinary lowercase todo") == ()
    scan.assert_not_called()

    oversized_bytes = "é" * (_MAX_OVERLAY_BYTES // 2 + 1) + " TODO"
    oversized_lines = "TODO\n" * (_MAX_OVERLAY_LINES + 2)
    assert _todo_annotation_spans(oversized_bytes) == ()
    assert _todo_annotation_spans(oversized_lines) == ()


def test_todo_annotation_empty_prompt() -> None:
    assert _todo_annotation_spans("") == ()


def test_todo_document_cache_reuses_and_invalidates() -> None:
    text_area = PromptTextArea("TODO: first")
    text_area._todo_cache_text = None
    text_area._todo_cached_annotations = None
    real_scan = _todo_highlight._todo_annotation_spans

    with patch.object(
        _todo_highlight,
        "_todo_annotation_spans",
        wraps=real_scan,
    ) as scan:
        first = text_area._todo_annotations_for_document()
        second = text_area._todo_annotations_for_document()
        assert second is first
        assert text_area.todo_annotation_count == 1
        assert scan.call_count == 1

        text_area.load_text("done")
        assert text_area.todo_annotation_count == 0
        assert scan.call_count == 2


@pytest.mark.parametrize(
    ("foreground", "dark", "expected_note"),
    [
        ("#ffffff", True, "#FFF3B2"),
        ("#111111", False, "#584C0B"),
    ],
)
def test_todo_palette_uses_running_gold_with_theme_aware_note(
    foreground: str,
    dark: bool,
    expected_note: str,
) -> None:
    chip_foreground, chip_background, note_foreground = todo_theme_colors(
        foreground,
        dark=dark,
    )

    assert chip_background.hex == RUNNING_COLOR
    assert chip_foreground.hex == "#000000"
    assert note_foreground.hex == expected_note


async def test_todo_overlay_uses_utf8_byte_columns_and_coexists_with_syntax() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        prefix = "🚀 café "
        text_area.load_text(
            f"{prefix}TODO(owner): fix #gh:sase {{% if root %}}now{{% endif %}} "
            "`TODO: literal`"
        )
        text_area._set_search_highlights(((len(prefix), len(prefix) + 4),), 0)
        text_area._yank_flash_span = (len(prefix), len(prefix) + 4)
        text_area._build_highlight_map()

        row = text_area._highlights[0]
        start_byte = len(prefix.encode("utf-8"))
        header_end_byte = start_byte + len(b"TODO(owner):")
        assert (start_byte, header_end_byte, "todo.header") in row

        names = _highlight_names(text_area)
        for name in (
            "codeblock.inline",
            "jinja.delimiter",
            "xprompt.invocation",
            "todo.header",
            "todo.body",
            "search.current",
            "yank.flash",
        ):
            assert name in names
        assert names.index("codeblock.inline") < names.index("todo.header")
        assert names.index("xprompt.invocation") < names.index("todo.header")
        assert names.index("todo.header") < names.index("search.current")
        assert names.index("search.current") < names.index("yank.flash")


async def test_todo_overlay_does_not_style_prose_after_a_bare_marker() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text = 'A quoted "TODO" leaves this prose ordinary; TODO: style this note'
        text_area.load_text(text)
        text_area._build_highlight_map()

        body_ranges = [
            (start, end)
            for start, end, name in text_area._highlights[0]
            if name == "todo.body"
        ]
        colon_header_end = text.index("TODO:") + len("TODO:")
        assert body_ranges == [(colon_header_end, len(text))]


async def test_todo_overlay_registers_theme_styles_and_updates_on_theme_change() -> (
    None
):
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("TODO: verify both themes")
        text_area._build_highlight_map()

        names = _highlight_names(text_area)
        assert "todo.header" in names
        assert "todo.body" in names
        dark_header = text_area._theme.syntax_styles["todo.header"]
        dark_body = text_area._theme.syntax_styles["todo.body"]
        assert dark_header.bold is True
        assert dark_header.bgcolor is not None
        assert dark_body.italic is True
        assert dark_body.bgcolor is None

        text_area._theme.syntax_styles["todo.header"] = Style(color="red")
        app.theme = "textual-light"
        await pilot.pause()

        expected = todo_theme_colors(
            app.current_theme.foreground,
            dark=app.current_theme.dark,
        )
        light_header = text_area._theme.syntax_styles["todo.header"]
        light_body = text_area._theme.syntax_styles["todo.body"]
        assert light_header.color == Color.parse("#000000")
        assert light_header.bgcolor == Color.parse(RUNNING_COLOR)
        assert light_header.color == Color.parse(expected[0].hex)
        assert light_header.bgcolor == Color.parse(expected[1].hex)
        assert light_body.color == Color.parse(expected[2].hex)
        assert light_body.italic is True
        assert light_body.bgcolor is None
        assert light_body != dark_body


class _TodoRenderApp(App[None]):
    CSS = "PromptTextArea { width: 40; height: 5; }"

    def __init__(self, text: str = "TODO: keep overlays legible") -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        yield PromptTextArea(
            self._text,
            language="markdown",
            soft_wrap=True,
        )


def _style_at(text_area: PromptTextArea, cell: int) -> Style | None:
    strip = text_area.render_line(0).crop(cell, cell + 1)
    for segment in strip._segments:
        if segment.control is None and segment.style is not None:
            return segment.style
    return None


def _background_at(text_area: PromptTextArea, cell: int) -> Color | None:
    style = _style_at(text_area, cell)
    return style.bgcolor if style is not None else None


@pytest.mark.parametrize("theme", ["textual-dark", "textual-light"])
async def test_todo_header_final_cells_are_black_on_running_gold(theme: str) -> None:
    header = "TODO(owner):"
    app = _TodoRenderApp(f"{header} keep the marker legible")
    async with app.run_test(size=(50, 10)) as pilot:
        app.theme = theme
        await pilot.pause()
        text_area = app.query_one(PromptTextArea)
        text_area.focus()
        text_area.cursor_location = (0, len(text_area.text))
        text_area._build_highlight_map()
        await pilot.pause()

        for cell in range(len(header)):
            style = _style_at(text_area, cell)
            assert style is not None
            assert style.color == Color.parse("#000000")
            assert style.bgcolor == Color.parse(RUNNING_COLOR)


async def test_todo_background_yields_to_selection_search_yank_and_cursor() -> None:
    app = _TodoRenderApp()
    async with app.run_test(size=(50, 10)) as pilot:
        text_area = app.query_one(PromptTextArea)
        text_area.focus()
        text_area.cursor_location = (0, len(text_area.text))
        text_area._build_highlight_map()
        await pilot.pause()

        todo_background = text_area._theme.syntax_styles["todo.header"].bgcolor
        assert _background_at(text_area, 0) == todo_background

        text_area.selection = Selection((0, 0), (0, 4))
        assert _background_at(text_area, 0) == text_area._theme.selection_style.bgcolor

        text_area.selection = Selection.cursor((0, len(text_area.text)))
        text_area._set_search_highlights(((0, 4),), 0)
        assert _background_at(text_area, 0) == (
            text_area._theme.syntax_styles["search.current"].bgcolor
        )

        text_area._yank_flash_span = (0, 4)
        text_area._build_highlight_map()
        assert _background_at(text_area, 0) == (
            text_area._theme.syntax_styles["yank.flash"].bgcolor
        )

        text_area._yank_flash_span = None
        text_area._clear_search_highlights()
        text_area.cursor_location = (0, 0)
        assert _background_at(text_area, 0) == text_area._theme.cursor_style.bgcolor


def test_todo_span_value_object() -> None:
    assert _TodoAnnotationSpan(0, 4, 4, 9) == _TodoAnnotationSpan(0, 4, 4, 9)
