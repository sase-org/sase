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


def tinted_document_text(
    folded: str,
    spans: list[dict[str, object]],
    values: dict[str, object],
    fold_map: dict[int, int] | None = None,
) -> object:
    """Tint folded callout lines from cached spans without hiding any line.

    Builds highlighted text from the cached lexer and overlays the tint, so
    syntax colours survive. Every line stays visible. Callers must only pass
    the cached spans + draft values; this never validates, parses YAML, or
    stats.
    """
    try:
        from sase.ace.tui.modals.plan_decision_document import (
            classify_callout as _classify,
        )
    except Exception:
        _classify = None  # type: ignore[assignment]

    lines = folded.splitlines()
    # Folded index -> style. Raw spans are 1-based; fold_map is 0-based raw->folded.
    line_styles: dict[int, str] = {}
    for span in spans or []:
        if not isinstance(span, dict):
            continue
        try:
            raw_start = int(str(span.get("start_line", 0))) - 1
            raw_end = int(str(span.get("end_line", raw_start + 1))) - 1
        except Exception:
            continue
        if _classify is not None:
            try:
                kind = _classify(span, values)  # type: ignore[arg-type]
            except Exception:
                kind = "dimmed"
        else:
            kind = "dimmed"
        for raw in range(max(0, raw_start), max(0, raw_end) + 1):
            folded_index = raw
            if fold_map is not None:
                folded_index = fold_map.get(raw, raw)
            if not 0 <= folded_index < len(lines):
                continue
            if kind == "chosen":
                # Only the header gets the green bold; continuation keeps its
                # token styles so multi-line callouts do not flood the pane.
                if raw == max(0, raw_start):
                    line_styles[folded_index] = "bold green"
                elif folded_index not in line_styles:
                    line_styles[folded_index] = ""
            else:
                line_styles.setdefault(folded_index, "dim")
    try:
        syntax = Syntax(
            folded,
            FRONTMATTER_MARKDOWN_LEXER,
            theme="monokai",
            word_wrap=True,
        )
        text = syntax.highlight(folded)
    except Exception:
        from rich.text import Text as _Text

        text = _Text(folded)
    # Overlay tint spans; token spans from highlight stay in place.
    offset = 0
    for index, line in enumerate(lines):
        style = line_styles.get(index, "")
        if style:
            try:
                text.stylize(style, offset, offset + len(line))
            except Exception:
                pass
        offset += len(line) + 1
    return text


__all__ = [
    "FRONTMATTER_MARKDOWN_LEXER",
    "FrontmatterMarkdownLexer",
    "markdown_document_syntax",
    "tinted_document_text",
]
