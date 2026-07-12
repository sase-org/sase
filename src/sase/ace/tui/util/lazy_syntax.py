"""Lazy / capped Rich Syntax rendering (Phase 6).

Building a Rich ``Syntax`` for very large content is expensive — the lexer
walks every byte and the highlighted output is held in memory. For TUI hot
paths (prompt panel, file panel, axe dashboard) we cap the size at which
syntax highlighting is applied and fall back to a plain ``Text`` block with
a small notice when content exceeds the cap. File panels additionally apply a
large line-count safety valve so pathological outputs cannot monopolize the UI
thread during plain-text layout.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable
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
# Rich plain-text wrapping measured ~77 ms median at this size on the target
# host; 10,000 lines measured ~164 ms. Keep the pathological path sub-100 ms.
FILE_PANEL_MAX_RENDER_LINES = 5_000


@dataclass(frozen=True)
class _SyntaxRenderableKey:
    content_digest: str
    content_length: int
    lexer: str
    theme: str
    word_wrap: bool
    line_range: tuple[int, int] | None
    line_numbers: bool
    render_kind: str = "syntax"
    max_render_lines: int | None = None


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
    )


class _CachedRenderable:
    """Rich wrapper that reuses rendered segments per render width."""

    def __init__(self, renderable: RenderableType, content: str) -> None:
        self._renderable = renderable
        self._content = content
        self._segments_by_options: OrderedDict[tuple[object, ...], tuple[Segment, ...]]
        self._segments_by_options = OrderedDict()
        self._measurements_by_options: OrderedDict[tuple[object, ...], Measurement] = (
            OrderedDict()
        )
        self._max_width_entries = 8

    @property
    def code(self) -> str:
        """Expose source content for tests and plain-text flattening helpers."""
        return self._content

    def __str__(self) -> str:
        return self._content

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> Iterable[Segment]:
        key = _render_options_key(options)
        cached = self._segments_by_options.get(key)
        if cached is None:
            cached = tuple(console.render(self._renderable, options=options))
            self._segments_by_options[key] = cached
            if len(self._segments_by_options) > self._max_width_entries:
                self._segments_by_options.popitem(last=False)
        else:
            self._segments_by_options.move_to_end(key)
        yield from cached

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        key = _render_options_key(options)
        cached = self._measurements_by_options.get(key)
        if cached is None:
            cached = Measurement.get(console, options, self._renderable)
            self._measurements_by_options[key] = cached
            if len(self._measurements_by_options) > self._max_width_entries:
                self._measurements_by_options.popitem(last=False)
        else:
            self._measurements_by_options.move_to_end(key)
        return cached


class LazySyntaxRenderCache:
    """Small bounded cache for opt-in prompt-panel syntax renderables."""

    def __init__(self, max_entries: int = 16) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[_SyntaxRenderableKey, _CachedRenderable]
        self._entries = OrderedDict()
        self.hits = 0
        self.misses = 0

    def clear(self) -> None:
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    def get(
        self,
        content: str,
        lexer: str,
        *,
        theme: str,
        word_wrap: bool,
        line_range: tuple[int, int] | None,
        line_numbers: bool,
    ) -> _CachedRenderable:
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
            self.hits += 1
            self._entries.move_to_end(key)
            return cached

        self.misses += 1
        renderable = _CachedRenderable(
            Syntax(
                content,
                lexer,
                theme=theme,
                word_wrap=word_wrap,
                line_numbers=line_numbers,
                line_range=line_range,
            ),
            content,
        )
        self._entries[key] = renderable
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return renderable

    def get_plain(
        self,
        content: str,
        lexer: str,
        *,
        theme: str,
        word_wrap: bool,
        line_range: tuple[int, int] | None,
        line_numbers: bool,
        max_render_lines: int | None,
        renderable_factory: Callable[[], RenderableType],
    ) -> _CachedRenderable:
        """Return a cached over-highlight-cap plain-text renderable."""
        key = _SyntaxRenderableKey(
            content_digest=_content_digest(content),
            content_length=len(content),
            lexer=lexer,
            theme=theme,
            word_wrap=word_wrap,
            line_range=line_range,
            line_numbers=line_numbers,
            render_kind="plain",
            max_render_lines=max_render_lines,
        )
        cached = self._entries.get(key)
        if cached is not None:
            self.hits += 1
            self._entries.move_to_end(key)
            return cached

        self.misses += 1
        cached = _CachedRenderable(renderable_factory(), content)
        self._entries[key] = cached
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return cached


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
    max_render_lines: int | None = None,
) -> RenderableType:
    """Return a Rich ``Syntax`` when small enough, else a capped plain block.

    When ``content`` exceeds either highlight cap, render a ``Text`` of the
    visible portion preceded by a one-line dim-italic notice. Callers may set
    ``max_render_lines`` to add a separate plain-text layout safety valve.
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

    def build_plain() -> RenderableType:
        rendered_content = visible
        total_lines = rendered_content.count("\n") + (
            1 if not rendered_content.endswith("\n") else 0
        )
        remaining = 0
        if max_render_lines is not None and total_lines > max_render_lines:
            visible_lines = rendered_content.splitlines(keepends=True)
            rendered_content = (
                "".join(visible_lines[:max_render_lines])
                .removesuffix("\n")
                .removesuffix("\r")
            )
            remaining = total_lines - max_render_lines

        renderables: list[RenderableType] = [
            notice,
            Text(rendered_content, no_wrap=False),
        ]
        if remaining:
            renderables.append(
                Text(
                    f"\n… {remaining} more lines — press E to open in editor",
                    style="dim italic #87D7FF",
                )
            )
        return Group(*renderables)

    if render_cache is not None:
        return render_cache.get_plain(
            content,
            lexer,
            theme=theme,
            word_wrap=word_wrap,
            line_range=line_range,
            line_numbers=line_numbers,
            max_render_lines=max_render_lines,
            renderable_factory=build_plain,
        )
    return build_plain()


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
