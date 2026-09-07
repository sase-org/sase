"""Tests for pager-local offset-preserving syntax spans."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest
from pygments.lexers import get_lexer_by_name
from pygments.token import Keyword, Name
from pygments.util import ClassNotFound
from rich.text import Text

from sase.pager.syntax import (
    SyntaxDisposition,
    SyntaxLimits,
    SyntaxResult,
    SyntaxRole,
    SyntaxSpan,
    highlight_source,
    normalize_language,
    resolve_pygments_alias,
    style_source_text,
    text_has_producer_style,
    _syntax_limit_reason,
)
from sase.pager.syntax_theme import syntax_palette_from_theme


def test_python_spans_preserve_tabs_crlf_trailing_newlines_and_unicode() -> None:
    source = "\tif café:\r\n    value = '🐍'\r\n\r\n"

    result = highlight_source(source, "py")

    assert result.disposition is SyntaxDisposition.HIGHLIGHTED
    assert _span_texts(source, result, SyntaxRole.KEYWORD) == ["if"]
    assert "'🐍'" in _span_texts(source, result, SyntaxRole.STRING)


@pytest.mark.parametrize("source", ["", "one", "one\n", "one\n\n"])
def test_empty_and_trailing_newline_inputs_keep_exact_source(source: str) -> None:
    result = highlight_source(source, "python")

    assert _style_source(source, result).plain == source


def test_markdown_frontmatter_uses_absolute_offsets_and_handles_crlf() -> None:
    source = "---\r\ntitle: Demo\r\n---\r\n# Heading\r\n"

    result = highlight_source(source, "markdown")

    assert result.disposition is SyntaxDisposition.HIGHLIGHTED
    assert _spans_containing(source, result, "title")[0].role is SyntaxRole.CONSTANT
    heading = _spans_containing(source, result, "# Heading")[0]
    assert heading.start == source.index("# Heading")
    assert heading == SyntaxSpan(
        source.index("# Heading"),
        source.index("# Heading") + len("# Heading\r"),
        SyntaxRole.MARKDOWN_HEADING,
    )


def test_markdown_frontmatter_closing_fence_can_be_at_eof() -> None:
    source = "---\ntitle: Demo\n---"

    result = highlight_source(source, "md")

    assert result.disposition is SyntaxDisposition.HIGHLIGHTED
    assert _spans_containing(source, result, "title")


def test_unclosed_frontmatter_falls_back_to_markdown_source_styling() -> None:
    source = "---\ntitle: Demo\n# Heading\n"

    result = highlight_source(source, "markdown")

    assert _style_source(source, result).plain == source
    assert not _spans_containing(source, result, "title")
    assert _span_texts(source, result, SyntaxRole.MARKDOWN_HEADING) == ["# Heading"]


def test_markdown_fenced_child_spans_are_absolute_for_multiple_fences() -> None:
    source = (
        "# Intro\n\n"
        "```python\n"
        "if x:\n"
        "    value = 'a'\n"
        "```\n"
        "text\n"
        "   ~~~python meta\n"
        "number = 42\n"
        "   ~~~\n"
    )

    result = highlight_source(source, "frontmatter-markdown")

    assert result.disposition is SyntaxDisposition.HIGHLIGHTED
    assert _style_source(source, result).plain == source
    assert _exact_span(source, result, "if", SyntaxRole.KEYWORD)
    assert _exact_span(source, result, "'a'", SyntaxRole.STRING)
    assert _exact_span(source, result, "42", SyntaxRole.NUMBER)
    assert _span_texts(source, result, SyntaxRole.MARKDOWN_CODE)[0] == "```python\n"


def test_unknown_and_unlabeled_markdown_fences_get_quiet_code_style() -> None:
    unknown = "```definitely-not-a-lexer\nx\n```\n"
    unlabeled = "```\nx\n```\n"

    for source in (unknown, unlabeled):
        result = highlight_source(source, "markdown")
        assert result.disposition is SyntaxDisposition.HIGHLIGHTED
        assert _span_texts(source, result, SyntaxRole.MARKDOWN_CODE) == [source]


def test_incomplete_markdown_fence_is_left_plain_but_surrounding_markdown_survives() -> (
    None
):
    source = "# Heading\n\n```python\nif x:\n"

    result = highlight_source(source, "markdown")

    assert _span_texts(source, result, SyntaxRole.MARKDOWN_HEADING) == ["# Heading"]
    assert not _spans_containing(source, result, "if")


def test_markdown_child_lexer_failure_leaves_only_that_fence_plain() -> None:
    source = "# Heading\n```python\nif x:\n```\n**strong**\n"

    result = highlight_source(source, "markdown", lexer_factory=_failing_python_factory)

    assert result.disposition is SyntaxDisposition.HIGHLIGHTED
    assert _span_texts(source, result, SyntaxRole.MARKDOWN_HEADING) == ["# Heading"]
    assert _span_texts(source, result, SyntaxRole.MARKDOWN_STRONG) == ["**strong**"]
    assert not _spans_containing(source, result, "if")


def test_nested_markdown_fences_share_the_enclosing_budget() -> None:
    source = "````markdown\n```python\nif x:\n```\n````\n"

    result = highlight_source(source, "markdown")

    assert result.disposition is SyntaxDisposition.HIGHLIGHTED
    assert _exact_span(source, result, "if", SyntaxRole.KEYWORD)


def test_nested_markdown_depth_limit_fails_open_to_quiet_code() -> None:
    source = "````markdown\n```python\nif x:\n```\n````\n"

    result = highlight_source(
        source,
        "markdown",
        limits=SyntaxLimits(max_markdown_nesting=0),
    )

    assert result.disposition is SyntaxDisposition.HIGHLIGHTED
    assert not _exact_span(source, result, "if", SyntaxRole.KEYWORD)
    assert _span_texts(source, result, SyntaxRole.MARKDOWN_CODE) == [source]


def test_diff_roles_are_distinct_from_markdown_headings() -> None:
    source = "diff --git a/a b/a\n@@ -1 +1 @@\n-old\n+new\n"

    result = highlight_source(source, "patch")

    assert _span_texts(source, result, SyntaxRole.DIFF_HEADER) == ["diff --git a/a b/a"]
    assert _span_texts(source, result, SyntaxRole.DIFF_HUNK) == ["@@ -1 +1 @@"]
    assert _span_texts(source, result, SyntaxRole.DIFF_DELETED) == ["-old"]
    assert _span_texts(source, result, SyntaxRole.DIFF_ADDED) == ["+new"]


def test_top_level_invalid_offsets_fail_open() -> None:
    result = highlight_source(
        "abc", "python", lexer_factory=lambda _alias: _BadOffsetLexer()
    )

    assert result == SyntaxResult(
        language="python",
        disposition=SyntaxDisposition.FAILED,
        source_length=3,
        reason="lexer-failed",
    )


def test_span_budget_exhaustion_discards_work() -> None:
    result = highlight_source(
        "abab",
        "python",
        limits=SyntaxLimits(max_spans=2),
        lexer_factory=lambda _alias: _ManyRoleLexer(),
    )

    assert result.disposition is SyntaxDisposition.TOO_LARGE
    assert result.spans == ()
    assert result.reason == "span-limit"


def test_size_limits_are_checked_before_lexing() -> None:
    assert _syntax_limit_reason("one\n", SyntaxLimits(max_lines=1)) is None
    assert _syntax_limit_reason("one\ntwo", SyntaxLimits(max_lines=1)) == "line-limit"
    assert (
        _syntax_limit_reason("abcd", SyntaxLimits(max_line_chars=3))
        == "line-length-limit"
    )
    assert _syntax_limit_reason("é" * 3, SyntaxLimits(max_bytes=5)) == "byte-limit"


def test_producer_styles_and_ansi_sources_are_preserved() -> None:
    source = "if x:\n"
    styled = Text(source, style="red")
    spanned = Text(source)
    spanned.stylize("red", 0, 2)

    assert text_has_producer_style(styled)
    assert text_has_producer_style(spanned)
    assert (
        highlight_source(source, "python", base_text=styled).disposition
        is SyntaxDisposition.PRESERVED
    )
    assert (
        highlight_source(source, "python", base_text=spanned).disposition
        is SyntaxDisposition.PRESERVED
    )
    assert (
        highlight_source(
            source, "python", raw_source="\x1b[31mif x:\x1b[0m\n"
        ).disposition
        is SyntaxDisposition.PRESERVED
    )


def test_style_source_text_rejects_mismatched_length() -> None:
    result = highlight_source("if x:\n", "python")

    with pytest.raises(ValueError, match="length does not match"):
        style_source_text(Text("if x:"), result, {})


def test_alias_normalization_and_validation() -> None:
    assert normalize_language("text") is None
    assert normalize_language("md") == "markdown"
    assert resolve_pygments_alias("py") == "python"
    assert resolve_pygments_alias("plain") is None

    with pytest.raises(ClassNotFound):
        resolve_pygments_alias("definitely-not-a-lexer")


class _BadOffsetLexer:
    def get_tokens_unprocessed(self, _text: str) -> Iterable[tuple[int, Any, str]]:
        yield 1, Keyword, "a"


class _ManyRoleLexer:
    def get_tokens_unprocessed(self, text: str) -> Iterable[tuple[int, Any, str]]:
        for index, char in enumerate(text):
            yield index, Keyword if char == "a" else Name.Function, char


class _FailingLexer:
    def get_tokens_unprocessed(self, _text: str) -> Iterable[tuple[int, Any, str]]:
        raise RuntimeError("boom")


def _failing_python_factory(alias: str) -> Any:
    if alias == "python":
        return _FailingLexer()
    return get_lexer_by_name(
        alias,
        stripnl=False,
        ensurenl=False,
        stripall=False,
        tabsize=0,
    )


def _style_source(source: str, result: SyntaxResult) -> Text:
    palette = syntax_palette_from_theme(None)
    return style_source_text(Text(source), result, palette.rich_styles)


def _span_texts(
    source: str,
    result: SyntaxResult,
    role: SyntaxRole,
) -> list[str]:
    return [source[span.start : span.end] for span in result.spans if span.role is role]


def _spans_containing(
    source: str,
    result: SyntaxResult,
    needle: str,
) -> list[SyntaxSpan]:
    start = source.index(needle)
    end = start + len(needle)
    return [span for span in result.spans if span.start <= start and end <= span.end]


def _exact_span(
    source: str,
    result: SyntaxResult,
    text: str,
    role: SyntaxRole,
) -> bool:
    start = source.index(text)
    end = start + len(text)
    return SyntaxSpan(start, end, role) in result.spans
