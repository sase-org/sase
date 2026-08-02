"""Rich body renderables for ``sase xprompt show``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.segment import Segment
from rich.syntax import Syntax
from rich.text import Text

from sase.xprompt._fenced_blocks import fenced_block_details
from sase.xprompt.highlight import HighlightSpan, highlight_spans
from sase.xprompt.highlight_theme import highlight_theme

_SYNTAX_THEME = "ansi_dark"
_FALLBACK_LEXER = "text"


class _FenceDetails(Protocol):
    content_range: tuple[int, int]
    info_string: tuple[int, int] | None
    opening_fence: tuple[int, int]
    closing_fence: tuple[int, int] | None


@dataclass(frozen=True, slots=True)
class _TabPreserving:
    renderable: RenderableType
    placeholder: str

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        for segment in console.render(self.renderable, options):
            if self.placeholder not in segment.text:
                yield segment
                continue
            yield Segment(
                segment.text.replace(self.placeholder, "\t"),
                segment.style,
                segment.control,
            )


def highlighted_body(
    text: str,
    *,
    known_skills: frozenset[str] = frozenset(),
    styles_enabled: bool = True,
) -> Text:
    """Return *text* with semantic xprompt and fenced-code styles applied."""
    rendered = Text(text, overflow="fold", no_wrap=False)
    if not styles_enabled:
        return rendered
    styles = highlight_theme()

    # Syntax is the base layer. Semantic roles are applied afterward so a
    # future scanner that recognizes syntax inside code can still override it.
    for block in _safe_fenced_blocks(text):
        content_start, content_end = block.content_range
        content = text[content_start:content_end]
        if content:
            lexer = (
                text[slice(*block.info_string)].split(maxsplit=1)[0]
                if block.info_string is not None
                else _FALLBACK_LEXER
            )
            syntax = _syntax_text(content, lexer)
            for span in syntax.spans:
                rendered.stylize(
                    span.style,
                    content_start + span.start,
                    content_start + span.end,
                )

        fence_style = styles["code.fence"].rich_style
        rendered.stylize(fence_style, *block.opening_fence)
        if block.info_string is not None:
            rendered.stylize(fence_style, *block.info_string)
        if block.closing_fence is not None:
            rendered.stylize(fence_style, *block.closing_fence)

    semantic_spans: list[HighlightSpan] = highlight_spans(
        text,
        known_skills=known_skills,
    )
    for semantic_span in semantic_spans:
        if semantic_span.role == "code.fence":
            continue
        rendered.stylize(
            styles[semantic_span.role].rich_style,
            semantic_span.start,
            semantic_span.end,
        )
    return rendered


def body_block(
    text: str,
    *,
    first_line: int | None = None,
    known_skills: frozenset[str] = frozenset(),
    styles_enabled: bool = True,
) -> RenderableType:
    """Return a highlighted body with a stable, right-aligned line gutter."""
    if not text:
        return Text()

    highlighted = highlighted_body(
        text,
        known_skills=known_skills,
        styles_enabled=styles_enabled,
    )
    tab_placeholder = (
        _unused_tab_placeholder(highlighted.plain)
        if "\t" in highlighted.plain
        else None
    )
    if tab_placeholder is not None:
        highlighted.plain = highlighted.plain.replace("\t", tab_placeholder)
    line_ranges = _line_ranges(text)
    starting_line = first_line if first_line is not None else 1
    final_line = starting_line + len(line_ranges) - 1
    gutter_width = max(3, len(str(final_line)))
    rows: list[Text] = []
    for offset, (start, end) in enumerate(line_ranges):
        content_end = end
        if content_end > start and text[content_end - 1] == "\n":
            content_end -= 1
        if content_end > start and text[content_end - 1] == "\r":
            content_end -= 1
        row = Text(overflow="fold", no_wrap=False)
        row.append(
            f"{starting_line + offset:>{gutter_width}} │ ",
            style="dim" if styles_enabled else "",
        )
        row.append_text(highlighted[start:content_end])
        row.overflow = "fold"
        row.no_wrap = False
        rows.append(row)
    grouped = Group(*rows)
    if tab_placeholder is None:
        return grouped
    return _TabPreserving(grouped, tab_placeholder)


def syntax_body(
    text: str,
    lexer: str,
    *,
    styles_enabled: bool = True,
) -> Text:
    """Return a syntax-highlighted script body, falling back to plain text."""
    if not styles_enabled:
        return Text(text, overflow="fold", no_wrap=False)
    return _syntax_text(text, lexer)


def _syntax_text(text: str, lexer: str) -> Text:
    for candidate in (lexer, _FALLBACK_LEXER):
        try:
            highlighted = Syntax(
                text,
                candidate,
                theme=_SYNTAX_THEME,
                background_color="default",
                word_wrap=True,
            ).highlight(text)
        except Exception:
            continue
        if highlighted.plain.endswith("\n") and not text.endswith("\n"):
            highlighted.right_crop(1)
        highlighted.overflow = "fold"
        highlighted.no_wrap = False
        return highlighted
    return Text(text, overflow="fold", no_wrap=False)


def _safe_fenced_blocks(text: str) -> list[_FenceDetails]:
    try:
        return cast(list[_FenceDetails], list(fenced_block_details(text)))
    except Exception:
        return []


def _line_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        newline = text.find("\n", start)
        end = len(text) if newline < 0 else newline + 1
        ranges.append((start, end))
        start = end
    return ranges


def _unused_tab_placeholder(text: str) -> str | None:
    for codepoint in range(0xE000, 0xF900):
        candidate = chr(codepoint)
        if candidate not in text:
            return candidate
    return None


__all__ = ["body_block", "highlighted_body", "syntax_body"]
