"""Frontmatter-aware Markdown syntax highlighting for whole documents."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from hashlib import blake2b

from pygments.lexer import Lexer  # type: ignore[import-untyped]
from pygments.lexers.data import YamlLexer  # type: ignore[import-untyped]
from pygments.lexers.markup import MarkdownLexer  # type: ignore[import-untyped]
from pygments.token import Token  # type: ignore[import-untyped]
from rich.syntax import Syntax

from sase.sdd.frontmatter import frontmatter_span

_MARKDOWN_LEXER = MarkdownLexer()
_YAML_LEXER = YamlLexer()
_TOKEN_CACHE_MAX_ENTRIES = 16
_Token = tuple[int, object, str]
_token_cache: OrderedDict[str, tuple[_Token, ...]] = OrderedDict()


def _content_digest(text: str) -> str:
    return blake2b(text.encode("utf-8", errors="replace"), digest_size=16).hexdigest()


def _lex_frontmatter_markdown(text: str) -> tuple[_Token, ...]:
    """Return the composite YAML/Markdown token stream for ``text``."""
    end = frontmatter_span(text)
    if end is None:
        return tuple(_MARKDOWN_LEXER.get_tokens_unprocessed(text))

    tokens: list[_Token] = [(0, Token.Comment.Preproc, text[:4])]
    closing_start = end + 1
    for offset, token, value in _YAML_LEXER.get_tokens_unprocessed(
        text[4:closing_start]
    ):
        tokens.append((offset + 4, token, value))

    body_start = end + 5
    tokens.append(
        (closing_start, Token.Comment.Preproc, text[closing_start:body_start])
    )
    for offset, token, value in _MARKDOWN_LEXER.get_tokens_unprocessed(
        text[body_start:]
    ):
        tokens.append((offset + body_start, token, value))
    return tuple(tokens)


def _cached_frontmatter_tokens(text: str) -> tuple[_Token, ...]:
    digest = _content_digest(text)
    cached = _token_cache.get(digest)
    if cached is not None:
        _token_cache.move_to_end(digest)
        return cached
    tokens = _lex_frontmatter_markdown(text)
    _token_cache[digest] = tokens
    if len(_token_cache) > _TOKEN_CACHE_MAX_ENTRIES:
        _token_cache.popitem(last=False)
    return tokens


class FrontmatterMarkdownLexer(Lexer):
    """Highlight leading YAML frontmatter and delegate the body to Markdown."""

    name = "Frontmatter Markdown"

    def get_tokens_unprocessed(self, text: str) -> Iterator[_Token]:
        """Yield an offset-preserving composite YAML/Markdown token stream."""
        yield from _cached_frontmatter_tokens(text)


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
