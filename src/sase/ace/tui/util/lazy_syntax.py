"""Lazy / capped Rich Syntax rendering (Phase 6).

Building a Rich ``Syntax`` for very large content is expensive — the lexer
walks every byte and the highlighted output is held in memory. For TUI hot
paths (prompt panel, file panel, axe dashboard) we cap the size at which
syntax highlighting is applied and fall back to a plain ``Text`` block with
a small notice when content exceeds the cap. Diff trimming is preserved by
counting only the visible/trimmed range against the cap.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import blake2b

from rich.console import Console, ConsoleOptions, Group, RenderableType
from rich.measure import Measurement
from rich.segment import Segment
from rich.syntax import Syntax
from rich.text import Text

SYNTAX_HIGHLIGHT_MAX_BYTES = 64_000
SYNTAX_HIGHLIGHT_MAX_LINES = 1_500
MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES = 24_000
MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES = 600


@dataclass(frozen=True)
class _SyntaxRenderableKey:
    content_digest: str
    content_length: int
    lexer: str
    theme: str
    word_wrap: bool
    line_range: tuple[int, int] | None
    line_numbers: bool


def _content_digest(content: str) -> str:
    return blake2b(
        content.encode("utf-8", errors="replace"), digest_size=16
    ).hexdigest()


def _render_options_key(options: object) -> tuple[object, ...]:
    return (
        getattr(options, "max_width", None),
        getattr(options, "min_width", None),
        getattr(options, "legacy_windows", None),
        getattr(options, "ascii_only", None),
        getattr(options, "no_wrap", None),
        getattr(options, "overflow", None),
        getattr(options, "height", None),
    )


class _CachedSyntaxRenderable:
    """Rich Syntax wrapper that reuses highlighted segments per render width."""

    def __init__(self, syntax: Syntax) -> None:
        self._syntax = syntax
        self._segments_by_options: OrderedDict[tuple[object, ...], tuple[Segment, ...]]
        self._segments_by_options = OrderedDict()
        self._max_width_entries = 4

    @property
    def code(self) -> str:
        """Expose underlying code for tests and plain-text flattening helpers."""
        return self._syntax.code

    def __str__(self) -> str:
        return self._syntax.code

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> Iterable[Segment]:
        key = _render_options_key(options)
        cached = self._segments_by_options.get(key)
        if cached is None:
            cached = tuple(console.render(self._syntax, options=options))
            self._segments_by_options[key] = cached
            if len(self._segments_by_options) > self._max_width_entries:
                self._segments_by_options.popitem(last=False)
        else:
            self._segments_by_options.move_to_end(key)
        yield from cached

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        return self._syntax.__rich_measure__(console, options)


class LazySyntaxRenderCache:
    """Small bounded cache for opt-in prompt-panel syntax renderables."""

    def __init__(self, max_entries: int = 16) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[_SyntaxRenderableKey, _CachedSyntaxRenderable]
        self._entries = OrderedDict()

    def clear(self) -> None:
        self._entries.clear()

    def get(
        self,
        content: str,
        lexer: str,
        *,
        theme: str,
        word_wrap: bool,
        line_range: tuple[int, int] | None,
        line_numbers: bool,
    ) -> _CachedSyntaxRenderable:
        key = _SyntaxRenderableKey(
            content_digest=_content_digest(content),
            content_length=len(content),
            lexer=lexer,
            theme=theme,
            word_wrap=word_wrap,
            line_range=line_range,
            line_numbers=line_numbers,
        )
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return cached

        renderable = _CachedSyntaxRenderable(
            Syntax(
                content,
                lexer,
                theme=theme,
                word_wrap=word_wrap,
                line_numbers=line_numbers,
                line_range=line_range,
            )
        )
        self._entries[key] = renderable
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return renderable


def _measure(content: str, line_range: tuple[int, int] | None) -> tuple[int, int]:
    """Return ``(byte_size, line_count)`` for the visible portion of content."""
    if line_range is None:
        return len(content.encode("utf-8", errors="replace")), content.count("\n") + 1

    start, end = line_range
    if start < 1:
        start = 1
    lines = content.split("\n")
    if end > len(lines):
        end = len(lines)
    visible = "\n".join(lines[start - 1 : end])
    return len(visible.encode("utf-8", errors="replace")), max(0, end - start + 1)


def _exceeds_cap(content: str, line_range: tuple[int, int] | None = None) -> bool:
    """Return True when content exceeds the syntax-highlight caps."""
    byte_size, line_count = _measure(content, line_range)
    return (
        byte_size > SYNTAX_HIGHLIGHT_MAX_BYTES
        or line_count > SYNTAX_HIGHLIGHT_MAX_LINES
    )


def _exceeds_lexer_cap(
    content: str,
    lexer: str,
    line_range: tuple[int, int] | None = None,
) -> bool:
    """Return True when content exceeds the cap for the requested lexer."""
    byte_size, line_count = _measure(content, line_range)
    if lexer == "markdown":
        return (
            byte_size > MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
            or line_count > MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES
        )
    return _exceeds_cap(content, line_range)


def lazy_renderable(
    content: str,
    lexer: str,
    *,
    line_range: tuple[int, int] | None = None,
    line_numbers: bool = False,
    word_wrap: bool = True,
    theme: str = "monokai",
    render_cache: LazySyntaxRenderCache | None = None,
) -> RenderableType:
    """Return a Rich ``Syntax`` when small enough, else a capped plain block.

    When ``content`` exceeds either cap, render a ``Text`` of the (visible)
    portion preceded by a one-line dim-italic notice. ``line_range`` lets
    diff/file panels measure only the trimmed range so partial views stay on
    the highlighted path even when the underlying file is huge.
    """
    if not _exceeds_lexer_cap(content, lexer, line_range):
        if render_cache is not None:
            return render_cache.get(
                content,
                lexer,
                theme=theme,
                word_wrap=word_wrap,
                line_range=line_range,
                line_numbers=line_numbers,
            )
        return Syntax(
            content,
            lexer,
            theme=theme,
            word_wrap=word_wrap,
            line_numbers=line_numbers,
            line_range=line_range,
        )

    notice = Text(
        "Large output rendered without syntax highlighting\n",
        style="dim italic #87D7FF",
    )
    if line_range is not None:
        start, end = line_range
        lines = content.split("\n")
        if start < 1:
            start = 1
        if end > len(lines):
            end = len(lines)
        visible = "\n".join(lines[start - 1 : end])
    else:
        visible = content
    return Group(notice, Text(visible, no_wrap=False))


def cap_ansi_output(output: str) -> str:
    """Cap ANSI-rich output to the configured byte budget (tail-biased).

    Tools that render append-only logs (axe dashboard, lumberjack output)
    keep working when the underlying log grows huge, but rendering the entire
    log through ``Text.from_ansi`` is expensive. We bound the work by keeping
    only the last ``SYNTAX_HIGHLIGHT_MAX_BYTES`` bytes — logs are tail-shaped
    so the head is rarely interesting.
    """
    if len(output) <= SYNTAX_HIGHLIGHT_MAX_BYTES:
        return output
    truncated = output[-SYNTAX_HIGHLIGHT_MAX_BYTES:]
    notice = "[…earlier output truncated to keep rendering fast…]\n"
    return notice + truncated
