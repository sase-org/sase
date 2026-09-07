"""Offset-safe Markdown regions for pager syntax highlighting."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from pygments.lexers.markup import MarkdownLexer  # type: ignore[import-untyped]
from pygments.util import ClassNotFound  # type: ignore[import-untyped]

from sase.pager.syntax import (
    InvalidSyntaxOffsets,
    LexerFactory,
    SpanBudget,
    SpanBudgetExceeded,
    SyntaxLimits,
    SyntaxRole,
    SyntaxSpan,
    lex_pygments_spans,
    markdown_token_role,
    normalize_language,
    source_token_role,
)

_OPENING_FENCE_RE = re.compile(
    r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*)$"
)


@dataclass(frozen=True, slots=True)
class _Line:
    start: int
    end: int
    content_end: int
    text: str


@dataclass(frozen=True, slots=True)
class _FenceRegion:
    start: int
    end: int
    opening_end: int
    closing_start: int | None
    content_start: int
    content_end: int
    language: str | None
    closed: bool


RegionKind = Literal["prose", "frontmatter", "fence"]


@dataclass(frozen=True, slots=True)
class _Region:
    kind: RegionKind
    start: int
    end: int
    fence: _FenceRegion | None = None


def markdown_syntax_spans(
    source: str,
    *,
    lexer_factory: LexerFactory,
    budget: SpanBudget,
    limits: SyntaxLimits,
    offset: int = 0,
    depth: int = 0,
) -> tuple[SyntaxSpan, ...]:
    """Return Markdown spans whose offsets point into the enclosing source."""

    spans: list[SyntaxSpan] = []
    for region in _regions(source):
        if region.kind == "prose":
            _extend_spans(
                spans,
                _lex_markdown_prose(
                    source[region.start : region.end], budget, offset + region.start
                ),
            )
        elif region.kind == "frontmatter":
            _extend_spans(
                spans,
                _lex_child(
                    source[region.start : region.end],
                    "yaml",
                    lexer_factory=lexer_factory,
                    budget=budget,
                    offset=offset + region.start,
                ),
            )
        elif region.fence is not None:
            _extend_spans(
                spans,
                _fence_spans(
                    source,
                    region.fence,
                    lexer_factory=lexer_factory,
                    budget=budget,
                    limits=limits,
                    offset=offset,
                    depth=depth,
                ),
            )
    return tuple(spans)


def _lex_markdown_prose(
    source: str,
    budget: SpanBudget,
    offset: int,
) -> tuple[SyntaxSpan, ...]:
    lexer = MarkdownLexer(
        handlecodeblocks=False,
        stripnl=False,
        ensurenl=False,
        stripall=False,
        tabsize=0,
    )
    return lex_pygments_spans(
        source,
        lexer,
        budget=budget,
        role_mapper=markdown_token_role,
        offset=offset,
    )


def _fence_spans(
    source: str,
    fence: _FenceRegion,
    *,
    lexer_factory: LexerFactory,
    budget: SpanBudget,
    limits: SyntaxLimits,
    offset: int,
    depth: int,
) -> tuple[SyntaxSpan, ...]:
    if not fence.closed:
        return ()
    language = normalize_language(fence.language)
    if language is None:
        return _quiet_code_spans(fence, budget, offset)
    if language == "markdown" and depth >= limits.max_markdown_nesting:
        return _quiet_code_spans(fence, budget, offset)

    spans: list[SyntaxSpan] = []
    budget_snapshot = budget.snapshot()
    try:
        budget.append(
            spans,
            SyntaxSpan(
                offset + fence.start,
                offset + fence.opening_end,
                SyntaxRole.MARKDOWN_CODE,
            ),
        )
        if language == "markdown":
            _extend_spans(
                spans,
                markdown_syntax_spans(
                    source[fence.content_start : fence.content_end],
                    lexer_factory=lexer_factory,
                    budget=budget,
                    limits=limits,
                    offset=offset + fence.content_start,
                    depth=depth + 1,
                ),
            )
        else:
            _extend_spans(
                spans,
                _lex_child(
                    source[fence.content_start : fence.content_end],
                    language,
                    lexer_factory=lexer_factory,
                    budget=budget,
                    offset=offset + fence.content_start,
                ),
            )
        if fence.closing_start is not None:
            budget.append(
                spans,
                SyntaxSpan(
                    offset + fence.closing_start,
                    offset + fence.end,
                    SyntaxRole.MARKDOWN_CODE,
                ),
            )
    except ClassNotFound:
        budget.restore(budget_snapshot)
        return _quiet_code_spans(fence, budget, offset)
    except InvalidSyntaxOffsets:
        budget.restore(budget_snapshot)
        return ()
    except SpanBudgetExceeded:
        raise
    except Exception:
        budget.restore(budget_snapshot)
        return ()
    return tuple(spans)


def _quiet_code_spans(
    fence: _FenceRegion,
    budget: SpanBudget,
    offset: int,
) -> tuple[SyntaxSpan, ...]:
    spans: list[SyntaxSpan] = []
    budget.append(
        spans,
        SyntaxSpan(offset + fence.start, offset + fence.end, SyntaxRole.MARKDOWN_CODE),
    )
    return tuple(spans)


def _lex_child(
    source: str,
    language: str,
    *,
    lexer_factory: LexerFactory,
    budget: SpanBudget,
    offset: int,
) -> tuple[SyntaxSpan, ...]:
    return lex_pygments_spans(
        source,
        lexer_factory(language),
        budget=budget,
        role_mapper=source_token_role,
        offset=offset,
    )


def _regions(source: str) -> tuple[_Region, ...]:
    lines = _lines(source)
    regions: list[_Region] = []
    cursor = 0
    frontmatter = _frontmatter_region(lines)
    if frontmatter is not None:
        regions.append(_Region("frontmatter", frontmatter.start, frontmatter.end))
        cursor = frontmatter.end

    for fence in _fences(lines, start=cursor):
        if cursor < fence.start:
            regions.append(_Region("prose", cursor, fence.start))
        regions.append(_Region("fence", fence.start, fence.end, fence))
        cursor = fence.end
    if cursor < len(source):
        regions.append(_Region("prose", cursor, len(source)))
    return tuple(regions)


def _frontmatter_region(lines: tuple[_Line, ...]) -> _Region | None:
    if len(lines) < 2 or _line_content(lines[0]) != "---":
        return None
    for line in lines[1:]:
        if _line_content(line) == "---":
            return _Region("frontmatter", 0, line.end)
    return None


def _fences(lines: tuple[_Line, ...], *, start: int) -> tuple[_FenceRegion, ...]:
    regions: list[_FenceRegion] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.start < start:
            index += 1
            continue
        match = _OPENING_FENCE_RE.match(_line_without_break(line))
        if match is None:
            index += 1
            continue
        fence_text = match.group("fence")
        fence_char = fence_text[0]
        fence_len = len(fence_text)
        language = _language_from_info(match.group("info"))
        content_start = line.end
        close_index = _find_closing_fence(lines, index + 1, fence_char, fence_len)
        if close_index is None:
            regions.append(
                _FenceRegion(
                    start=line.start,
                    end=lines[-1].end if lines else line.end,
                    opening_end=line.end,
                    closing_start=None,
                    content_start=content_start,
                    content_end=lines[-1].end if lines else line.end,
                    language=language,
                    closed=False,
                )
            )
            break
        closing = lines[close_index]
        regions.append(
            _FenceRegion(
                start=line.start,
                end=closing.end,
                opening_end=line.end,
                closing_start=closing.start,
                content_start=content_start,
                content_end=closing.start,
                language=language,
                closed=True,
            )
        )
        index = close_index + 1
    return tuple(regions)


def _find_closing_fence(
    lines: tuple[_Line, ...],
    start_index: int,
    fence_char: str,
    fence_len: int,
) -> int | None:
    closing_re = re.compile(
        rf"^[ ]{{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*$"
    )
    for index in range(start_index, len(lines)):
        if closing_re.match(_line_without_break(lines[index])):
            return index
    return None


def _lines(source: str) -> tuple[_Line, ...]:
    lines: list[_Line] = []
    cursor = 0
    for text in source.splitlines(keepends=True):
        end = cursor + len(text)
        content_end = end
        if text.endswith("\r\n"):
            content_end -= 2
        elif text.endswith(("\n", "\r")):
            content_end -= 1
        lines.append(_Line(cursor, end, content_end, text))
        cursor = end
    return tuple(lines)


def _line_without_break(line: _Line) -> str:
    return line.text[: line.content_end - line.start]


def _line_content(line: _Line) -> str:
    return _line_without_break(line).strip()


def _language_from_info(info: str) -> str | None:
    stripped = info.strip()
    if not stripped:
        return None
    first = stripped.split(None, 1)[0].strip("{}")
    if first.startswith("."):
        first = first[1:]
    return first or None


def _extend_spans(target: list[SyntaxSpan], spans: tuple[SyntaxSpan, ...]) -> None:
    target.extend(spans)


__all__ = ["markdown_syntax_spans"]
