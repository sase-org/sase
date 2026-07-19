"""Frontmatter-aware Markdown syntax highlighting for whole documents."""

from __future__ import annotations

from collections.abc import Iterator

from pygments.lexer import Lexer  # type: ignore[import-untyped]
from pygments.lexers.data import YamlLexer  # type: ignore[import-untyped]
from pygments.lexers.markup import MarkdownLexer  # type: ignore[import-untyped]
from pygments.token import Token  # type: ignore[import-untyped]
from rich.syntax import Syntax

from sase.sdd.frontmatter import frontmatter_span

_MARKDOWN_LEXER = MarkdownLexer()
_YAML_LEXER = YamlLexer()


class FrontmatterMarkdownLexer(Lexer):
    """Highlight leading YAML frontmatter and delegate the body to Markdown."""

    name = "Frontmatter Markdown"

    def get_tokens_unprocessed(self, text: str) -> Iterator[tuple[int, object, str]]:
        """Yield an offset-preserving composite YAML/Markdown token stream."""
        end = frontmatter_span(text)
        if end is None:
            yield from _MARKDOWN_LEXER.get_tokens_unprocessed(text)
            return

        yield 0, Token.Comment.Preproc, text[:4]

        closing_start = end + 1
        for offset, token, value in _YAML_LEXER.get_tokens_unprocessed(
            text[4:closing_start]
        ):
            yield offset + 4, token, value

        body_start = end + 5
        yield closing_start, Token.Comment.Preproc, text[closing_start:body_start]
        for offset, token, value in _MARKDOWN_LEXER.get_tokens_unprocessed(
            text[body_start:]
        ):
            yield offset + body_start, token, value


FRONTMATTER_MARKDOWN_LEXER = FrontmatterMarkdownLexer(
    stripnl=False,
    ensurenl=True,
    tabsize=4,
)


def markdown_document_syntax(content: str, *, word_wrap: bool = True) -> Syntax:
    """Build the standard frontmatter-aware Markdown document renderable."""
    return Syntax(
        content,
        FRONTMATTER_MARKDOWN_LEXER,
        theme="monokai",
        word_wrap=word_wrap,
    )


__all__ = [
    "FRONTMATTER_MARKDOWN_LEXER",
    "FrontmatterMarkdownLexer",
    "markdown_document_syntax",
]
