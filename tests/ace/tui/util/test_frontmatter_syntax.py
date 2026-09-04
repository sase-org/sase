"""Tests for frontmatter-aware Markdown syntax highlighting."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from pygments.lexers.markup import MarkdownLexer  # type: ignore[import-untyped]
from pygments.token import Token  # type: ignore[import-untyped]

from sase.ace.tui.util.frontmatter_syntax import (
    FrontmatterMarkdownLexer,
)
from sase.sdd.frontmatter import frontmatter_span, parse_frontmatter


def _tokens(source: str) -> list[tuple[int, object, str]]:
    return list(FrontmatterMarkdownLexer().get_tokens_unprocessed(source))


def _reconstruct(tokens: Iterable[tuple[int, object, str]]) -> str:
    return "".join(value for _, _, value in tokens)


def test_realistic_plan_token_stream_is_byte_exact() -> None:
    source = (
        "---\n"
        "tier: tale\n"
        "title: Frontmatter syntax highlighting\n"
        "goal: >\n"
        "  Render YAML metadata clearly in gate review documents.\n"
        "---\n"
        "\n"
        "# Plan\n"
        "\n"
        "Implement the shared lexer.\n"
    )

    assert _reconstruct(_tokens(source)) == source


def test_frontmatter_fences_yaml_keys_and_markdown_body_are_distinct_tokens() -> None:
    source = "---\ntier: tale\ntitle: Example\n---\n# Plan\n"
    tokens = _tokens(source)

    assert [value for _, token, value in tokens if token is Token.Comment.Preproc] == [
        "---\n",
        "---\n",
    ]
    assert {value for _, token, value in tokens if token is Token.Name.Tag} >= {
        "tier",
        "title",
    }
    assert any(
        token is Token.Generic.Heading and value == "# Plan"
        for _, token, value in tokens
    )


@pytest.mark.parametrize(
    "source",
    [
        "",
        "# Plan\n\nNo frontmatter.\n",
        "---\ntier: tale\n",
    ],
)
def test_non_frontmatter_stream_matches_plain_markdown(source: str) -> None:
    expected = list(MarkdownLexer().get_tokens_unprocessed(source))

    assert _tokens(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "---\ntier: [broken\n---\n# Body\n",
        "---\n- tale\n---\n# Body\n",
    ],
)
def test_span_rule_highlights_invalid_or_non_mapping_yaml(source: str) -> None:
    assert frontmatter_span(source) is not None
    tokens = _tokens(source)
    assert any(token is Token.Comment.Preproc for _, token, _ in tokens)
    assert tokens != list(MarkdownLexer().get_tokens_unprocessed(source))


@pytest.mark.parametrize(
    ("source", "expected_span"),
    [
        ("", None),
        ("# Body\n", None),
        ("---\ntier: tale\n", None),
        ("---\ntier: tale\n---\n# Body\n", 14),
        ("---\ntier: [broken\n---\n# Body\n", 17),
    ],
)
def test_lexer_engagement_matches_frontmatter_span(
    source: str, expected_span: int | None
) -> None:
    span = frontmatter_span(source)
    engaged = any(token is Token.Comment.Preproc for _, token, _ in _tokens(source))

    assert span == expected_span
    assert engaged is (span is not None)


def test_lexer_reuses_tokens_for_unchanged_content(monkeypatch) -> None:
    calls = 0
    original = MarkdownLexer.get_tokens_unprocessed

    def counted(self, text):
        nonlocal calls
        calls += 1
        return original(self, text)

    monkeypatch.setattr(MarkdownLexer, "get_tokens_unprocessed", counted)
    source = "# Unique idle prompt panel document for token reuse\n\nUnchanged body.\n"
    first = _tokens(source)
    second = _tokens(source)

    assert first == second
    assert calls == 1


def test_parse_frontmatter_semantics_are_preserved() -> None:
    valid = "---\ntier: tale\n---\n# Body\n"
    invalid = "---\ntier: [broken\n---\n# Body\n"
    non_mapping = "---\n- tale\n---\n# Body\n"

    assert parse_frontmatter(valid) == ({"tier": "tale"}, "# Body\n", True)
    assert parse_frontmatter(invalid) == ({}, invalid, False)
    assert parse_frontmatter(non_mapping) == ({}, "# Body\n", True)
