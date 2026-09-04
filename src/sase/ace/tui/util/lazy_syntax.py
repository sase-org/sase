"""Lazy / capped Rich Syntax rendering (Phase 6).

Building a Rich ``Syntax`` for very large content is expensive — the lexer
walks every byte and the highlighted output is held in memory. For TUI hot
paths (prompt panel, file panel, axe dashboard) we cap the size at which
syntax highlighting is applied and fall back to a plain ``Text`` block with
a small notice when content exceeds the cap. The plain fallback is always
bounded by bytes and lines so pathological outputs cannot monopolize the UI
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

from .frontmatter_syntax import (
    FRONTMATTER_MARKDOWN_LEXER,
    FrontmatterMarkdownLexer,
)

SYNTAX_HIGHLIGHT_MAX_BYTES = 64_000
SYNTAX_HIGHLIGHT_MAX_LINES = 1_500
MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES = 24_000
MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES = 600
# Keep the pathological plain-text path within the module's sub-100 ms budget.
# The byte cap protects byte-heavy content with relatively few very long lines;
# the line cap protects content made up of many short lines.
PLAIN_RENDER_MAX_BYTES = 128_000
PLAIN_RENDER_MAX_LINES = 5_000
# Compatibility alias for file-panel line counts and tests.
FILE_PANEL_MAX_RENDER_LINES = PLAIN_RENDER_MAX_LINES
DEFAULT_TRUNCATION_HINT = "truncated for display"


@dataclass(frozen=True)
class _SyntaxRenderableKey:
    content_digest: str
    content_length: int
    lexer: str
    theme: str
    word_wrap: bool
    line_range: tuple[int, int] | None
    line_numbers: bool
    highlight_lines: frozenset[int] | None = None
    render_kind: str = "syntax"
    max_render_lines: int | None = None
    truncation_hint: str | None = None


def _content_digest(content: str) -> str:
    return blake2b(
        content.encode("utf-8", errors="replace"), digest_size=16
    ).hexdigest()


def _effective_lexer(lexer: str) -> FrontmatterMarkdownLexer | str:
    """Resolve Markdown to the shared frontmatter-aware composite lexer."""
    if lexer == "markdown":
        return FRONTMATTER_MARKDOWN_LEXER
    return lexer


def _render_options_key(options: object) -> tuple[object, ...]:
    """Return a primitive style/width token for Rich console options.

    Values are coerced to stable types so equivalent ConsoleOptions objects
    produced on idle refreshes share a cache entry.
    """
    overflow = getattr(options, "overflow", None)
    return (
        int(getattr(options, "max_width", 0) or 0),
        int(getattr(options, "min_width", 0) or 0),
        bool(getattr(options, "legacy_windows", False)),
        bool(getattr(options, "ascii_only", False)),
        bool(getattr(options, "no_wrap", False)),
        "" if overflow is None else str(overflow),
    )


_SEGMENT_CACHE_MAX_ENTRIES = 32
_HIGHLIGHT_CACHE_MAX_ENTRIES = 24
_segments_by_content_and_style: OrderedDict[
    tuple[str, tuple[object, ...]], tuple[Segment, ...]
] = OrderedDict()
_measurements_by_content_and_style: OrderedDict[
    tuple[str, tuple[object, ...]], Measurement
] = OrderedDict()
_highlight_by_content: OrderedDict[tuple[object, ...], Text] = OrderedDict()


def _bounded_store(
    cache: OrderedDict, key: object, value: object, max_entries: int
) -> None:
    cache[key] = value
    cache.move_to_end(key)
    if len(cache) > max_entries:
        cache.popitem(last=False)


def _syntax_highlight_key(
    syntax: Syntax,
    content_digest: str,
    line_range: tuple[int | None, int | None] | None,
) -> tuple[object, ...]:
    lexer = getattr(syntax, "lexer", None)
    theme = getattr(syntax, "theme", "")
    highlight_lines = getattr(syntax, "highlight_lines", None) or ()
    return (
        content_digest,
        type(lexer).__name__ if lexer is not None else "",
        str(theme),
        line_range,
        frozenset(highlight_lines),
    )


def _bind_syntax_highlight_cache(syntax: Syntax, content_digest: str) -> None:
    """Reuse Syntax.highlight() output across widths and equivalent documents."""
    if getattr(syntax, "_sase_highlight_cached", False):
        return
    original = syntax.highlight

    def cached_highlight(
        code: str,
        line_range: tuple[int | None, int | None] | None = None,
    ) -> Text:
        key = _syntax_highlight_key(syntax, content_digest, line_range)
        cached = _highlight_by_content.get(key)
        if cached is not None:
            _highlight_by_content.move_to_end(key)
            return cached
        highlighted = original(code, line_range)
        _bounded_store(
            _highlight_by_content,
            key,
            highlighted,
            _HIGHLIGHT_CACHE_MAX_ENTRIES,
        )
        return highlighted

    syntax.highlight = cached_highlight  # type: ignore[method-assign]
    syntax._sase_highlight_cached = True  # type: ignore[attr-defined]


class CachedRenderable:
    """Rich wrapper that reuses rendered segments per render width."""

    def __init__(self, renderable: RenderableType, content: str) -> None:
        self._renderable = renderable
        self._content = content
        self._digest = _content_digest(content)
        self._segments_by_options: OrderedDict[tuple[object, ...], tuple[Segment, ...]]
        self._segments_by_options = OrderedDict()
        self._measurements_by_options: OrderedDict[tuple[object, ...], Measurement] = (
            OrderedDict()
        )
        self._max_width_entries = 8
        if isinstance(renderable, Syntax):
            _bind_syntax_highlight_cache(renderable, self._digest)

    @property
    def content_digest(self) -> str:
        """Return the content hash used by document-level render caches."""
        return self._digest

    @property
    def code(self) -> str:
        """Expose source content for tests and plain-text flattening helpers."""
        return self._content

    @property
    def plain(self) -> str:
        """Expose the flattened document text for ``Text``-like consumers."""
        return self._content

    @property
    def renderable(self) -> RenderableType:
        """Return the wrapped Rich document."""
        return self._renderable

    def __str__(self) -> str:
        return self._content

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> Iterable[Segment]:
        style_key = _render_options_key(options)
        cached = self._segments_by_options.get(style_key)
        if cached is None:
            shared_key = (self._digest, style_key)
            cached = _segments_by_content_and_style.get(shared_key)
            if cached is None:
                cached = tuple(console.render(self._renderable, options=options))
                _bounded_store(
                    _segments_by_content_and_style,
                    shared_key,
                    cached,
                    _SEGMENT_CACHE_MAX_ENTRIES,
                )
            self._segments_by_options[style_key] = cached
            if len(self._segments_by_options) > self._max_width_entries:
                self._segments_by_options.popitem(last=False)
        else:
            self._segments_by_options.move_to_end(style_key)
            shared_key = (self._digest, style_key)
            if shared_key in _segments_by_content_and_style:
                _segments_by_content_and_style.move_to_end(shared_key)
        yield from cached

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        style_key = _render_options_key(options)
        cached = self._measurements_by_options.get(style_key)
        if cached is None:
            shared_key = (self._digest, style_key)
            cached = _measurements_by_content_and_style.get(shared_key)
            if cached is None:
                cached = Measurement.get(console, options, self._renderable)
                _bounded_store(
                    _measurements_by_content_and_style,
                    shared_key,
                    cached,
                    _SEGMENT_CACHE_MAX_ENTRIES,
                )
            self._measurements_by_options[style_key] = cached
            if len(self._measurements_by_options) > self._max_width_entries:
                self._measurements_by_options.popitem(last=False)
        else:
            self._measurements_by_options.move_to_end(style_key)
        return cached


class LazySyntaxRenderCache:
    """Small bounded cache for opt-in prompt-panel syntax renderables."""

    def __init__(self, max_entries: int = 16) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[_SyntaxRenderableKey, CachedRenderable]
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
        highlight_lines: frozenset[int] | None,
    ) -> CachedRenderable:
        key = _SyntaxRenderableKey(
            content_digest=_content_digest(content),
            content_length=len(content),
            lexer=lexer,
            theme=theme,
            word_wrap=word_wrap,
            line_range=line_range,
            line_numbers=line_numbers,
            highlight_lines=highlight_lines,
        )
        cached = self._entries.get(key)
        if cached is not None:
            self.hits += 1
            self._entries.move_to_end(key)
            return cached

        self.misses += 1
        renderable = CachedRenderable(
            Syntax(
                content,
                _effective_lexer(lexer),
                theme=theme,
                word_wrap=word_wrap,
                line_numbers=line_numbers,
                line_range=line_range,
                highlight_lines=set(highlight_lines or ()),
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
        highlight_lines: frozenset[int] | None,
        max_render_lines: int,
        truncation_hint: str,
        renderable_factory: Callable[[], RenderableType],
    ) -> CachedRenderable:
        """Return a cached over-highlight-cap plain-text renderable."""
        key = _SyntaxRenderableKey(
            content_digest=_content_digest(content),
            content_length=len(content),
            lexer=lexer,
            theme=theme,
            word_wrap=word_wrap,
            line_range=line_range,
            line_numbers=line_numbers,
            highlight_lines=highlight_lines,
            render_kind="plain",
            max_render_lines=max_render_lines,
            truncation_hint=truncation_hint,
        )
        cached = self._entries.get(key)
        if cached is not None:
            self.hits += 1
            self._entries.move_to_end(key)
            return cached

        self.misses += 1
        cached = CachedRenderable(renderable_factory(), content)
        self._entries[key] = cached
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return cached


_DEFAULT_SYNTAX_RENDER_CACHE = LazySyntaxRenderCache(max_entries=32)


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


def exceeds_syntax_highlight_cap(
    content: str,
    lexer: str,
    line_range: tuple[int, int] | None = None,
) -> bool:
    """Return whether ``lazy_renderable`` will use its plain-text path."""
    return _exceeds_lexer_cap(content, lexer, line_range)


def exceeds_plain_render_cap(
    content: str,
    line_range: tuple[int, int] | None = None,
) -> bool:
    """Return True when content is too large for bounded plain rendering."""
    byte_size, line_count = _measure(content, line_range)
    return byte_size > PLAIN_RENDER_MAX_BYTES or line_count > PLAIN_RENDER_MAX_LINES


def _line_count(content: str) -> int:
    """Return the logical line count used by capped plain rendering."""
    return content.count("\n") + (1 if not content.endswith("\n") else 0)


def _utf8_prefix(content: str, max_bytes: int) -> str:
    """Return the longest safe UTF-8 prefix within ``max_bytes``."""
    encoded = content.encode("utf-8", errors="replace")
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def truncate_plain_content(
    content: str,
    *,
    max_lines: int,
    max_bytes: int = PLAIN_RENDER_MAX_BYTES,
) -> tuple[str, int, int, bool, bool]:
    """Return a bounded head prefix and details about what was elided."""
    total_lines = _line_count(content)
    total_bytes = len(content.encode("utf-8", errors="replace"))
    line_truncated = total_lines > max_lines

    rendered_lines: list[str] = []
    rendered_bytes = 0
    byte_truncated = False
    line_start = 0
    for _ in range(max_lines):
        if line_start >= len(content):
            break
        newline = content.find("\n", line_start)
        line_end = len(content) if newline == -1 else newline + 1
        line = content[line_start:line_end]
        line_bytes = len(line.encode("utf-8", errors="replace"))
        if rendered_bytes + line_bytes <= max_bytes:
            rendered_lines.append(line)
            rendered_bytes += line_bytes
            line_start = line_end
            continue

        byte_truncated = True
        if not rendered_lines and max_bytes > 0:
            rendered_lines.append(_utf8_prefix(line, max_bytes))
        break

    rendered_content = "".join(rendered_lines)
    truncated = line_truncated or byte_truncated
    if truncated:
        rendered_content = rendered_content.removesuffix("\n").removesuffix("\r")

    remaining_lines = max(0, total_lines - _line_count(rendered_content))
    remaining_bytes = max(
        0,
        total_bytes - len(rendered_content.encode("utf-8", errors="replace")),
    )
    return (
        rendered_content,
        remaining_lines,
        remaining_bytes,
        line_truncated,
        byte_truncated,
    )


def _format_approx_bytes(byte_count: int) -> str:
    """Return a compact approximate size for a truncation notice."""
    if byte_count < 1_024:
        return f"{byte_count} B"
    if byte_count < 1_024 * 1_024:
        return f"{byte_count / 1_024:.1f} KiB"
    return f"{byte_count / (1_024 * 1_024):.1f} MiB"


def _segmented_plain_text(
    content: str,
    highlight_lines: frozenset[int] | None = None,
    *,
    start_line: int = 1,
) -> Text:
    """Build plain text whose rendered segments never span multiple lines."""
    text = Text(no_wrap=False)
    for line_number, line in enumerate(
        content.splitlines(keepends=True),
        start=start_line,
    ):
        # An explicit neutral span keeps Rich from merging the whole body into
        # one segment while preserving the same visible style.
        style = "on #5F5F00" if line_number in (highlight_lines or ()) else "none"
        text.append(line, style=style)
    return text


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
    truncation_hint: str = DEFAULT_TRUNCATION_HINT,
    highlight_lines: frozenset[int] | None = None,
) -> RenderableType:
    """Return a cached Syntax wrapper when small enough, else a capped plain block.

    Under the highlight cap, the result is a ``CachedRenderable`` keyed by
    content hash, width, and wrap options so idle refreshes of unchanged
    documents reuse highlighting. When ``content`` exceeds either highlight
    cap, render a ``Text`` of the visible portion preceded by a one-line
    dim-italic notice. The plain path is always byte- and line-capped;
    callers may lower the default line cap and customize the trailing
    truncation hint for their surface.
    """
    if not exceeds_syntax_highlight_cap(content, lexer, line_range):
        cache = _DEFAULT_SYNTAX_RENDER_CACHE if render_cache is None else render_cache
        return cache.get(
            content,
            lexer,
            theme=theme,
            word_wrap=word_wrap,
            line_range=line_range,
            line_numbers=line_numbers,
            highlight_lines=highlight_lines,
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

    effective_max_render_lines = (
        PLAIN_RENDER_MAX_LINES if max_render_lines is None else max(1, max_render_lines)
    )

    def build_plain() -> RenderableType:
        (
            rendered_content,
            remaining_lines,
            remaining_bytes,
            line_truncated,
            byte_truncated,
        ) = truncate_plain_content(
            visible,
            max_lines=effective_max_render_lines,
        )

        renderables: list[RenderableType] = [
            notice,
            _segmented_plain_text(
                rendered_content,
                highlight_lines,
                start_line=line_range[0] if line_range is not None else 1,
            ),
        ]
        if line_truncated or byte_truncated:
            omitted: list[str] = []
            if line_truncated and remaining_lines:
                omitted.append(f"{remaining_lines} more lines")
            if byte_truncated and remaining_bytes:
                omitted.append(
                    f"approximately {_format_approx_bytes(remaining_bytes)} omitted"
                )
            renderables.append(
                Text(
                    f"\n… {' and '.join(omitted)} — {truncation_hint}",
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
            highlight_lines=highlight_lines,
            max_render_lines=effective_max_render_lines,
            truncation_hint=truncation_hint,
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
