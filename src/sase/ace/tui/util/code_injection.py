"""Tree-sitter highlighting for code embedded in prompt Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from textual._tree_sitter import get_language
from textual.widgets._text_area import BUILTIN_LANGUAGES, TextArea
from tree_sitter import Parser, Query, QueryCursor

_MAX_INJECTION_BYTES = 40_000
_MAX_INJECTION_LINES = 600
_LANGUAGE_ALIASES = {
    "console": "bash",
    "golang": "go",
    "htm": "html",
    "js": "javascript",
    "jsx": "javascript",
    "md": "markdown",
    "py": "python",
    "python3": "python",
    "regexp": "regex",
    "rs": "rust",
    "sh": "bash",
    "shell": "bash",
    "svg": "xml",
    "yml": "yaml",
    "zsh": "bash",
}
_BUILTIN_LANGUAGE_NAMES = frozenset(BUILTIN_LANGUAGES)


@dataclass(frozen=True, slots=True)
class _InjectedHighlight:
    """A TextArea-compatible byte span within extracted code."""

    row: int
    start_byte: int
    end_byte: int | None
    name: str


def language_for_info_string(info: str) -> str | None:
    """Resolve the first word of a Markdown info string to a builtin parser."""
    words = info.strip().split(maxsplit=1)
    if not words:
        return None
    language = words[0].lower()
    language = _LANGUAGE_ALIASES.get(language, language)
    return language if language in _BUILTIN_LANGUAGE_NAMES else None


@lru_cache(maxsize=32)
def injected_highlights(language: str, code: str) -> tuple[_InjectedHighlight, ...]:
    """Return Textual-theme capture spans for an embedded code substring."""
    if (
        language not in _BUILTIN_LANGUAGE_NAMES
        or len(code.encode("utf-8")) > _MAX_INJECTION_BYTES
        or code.count("\n") > _MAX_INJECTION_LINES
    ):
        return ()

    try:
        parser, query = _parser_and_query(language)
        tree = parser.parse(code.encode("utf-8"))
        captures = QueryCursor(query).captures(tree.root_node)
    except Exception:
        return ()

    highlights: list[_InjectedHighlight] = []
    for name, nodes in captures.items():
        for node in nodes:
            start_row, start_byte = node.start_point
            end_row, end_byte = node.end_point
            if start_row == end_row:
                highlights.append(
                    _InjectedHighlight(start_row, start_byte, end_byte, name)
                )
                continue

            highlights.append(_InjectedHighlight(start_row, start_byte, None, name))
            highlights.extend(
                _InjectedHighlight(row, 0, None, name)
                for row in range(start_row + 1, end_row)
            )
            if end_byte:
                highlights.append(_InjectedHighlight(end_row, 0, end_byte, name))

    return tuple(highlights)


@lru_cache(maxsize=len(BUILTIN_LANGUAGES))
def _parser_and_query(language: str) -> tuple[Parser, Query]:
    tree_sitter_language = get_language(language)
    if tree_sitter_language is None:
        raise ValueError(f"tree-sitter language is unavailable: {language}")
    query_source = TextArea._get_builtin_highlight_query(language)
    return Parser(tree_sitter_language), Query(tree_sitter_language, query_source)


__all__ = [
    "injected_highlights",
    "language_for_info_string",
]
