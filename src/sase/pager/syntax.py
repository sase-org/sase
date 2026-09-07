"""Offset-preserving syntax spans for pager source text."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from pygments.lexers import get_lexer_by_name  # type: ignore[import-untyped]
from pygments.token import (  # type: ignore[import-untyped]
    Comment,
    Error,
    Generic,
    Keyword,
    Literal as TokenLiteral,
    Name,
)
from pygments.util import ClassNotFound  # type: ignore[import-untyped]
from rich.style import Style
from rich.text import Text


MAX_SYNTAX_BYTES: Final = 80_000
MAX_SYNTAX_LINES: Final = 1_200
MAX_SYNTAX_LINE_CHARS: Final = 4_096
MAX_SYNTAX_SPANS: Final = 20_000
MAX_MARKDOWN_NESTING: Final = 3


class SyntaxDisposition(StrEnum):
    """The outcome of a bounded syntax preparation attempt."""

    HIGHLIGHTED = "highlighted"
    PLAIN = "plain"
    PRESERVED = "preserved"
    TOO_LARGE = "too_large"
    FAILED = "failed"


class SyntaxRole(StrEnum):
    """Closed semantic role vocabulary for pager syntax styling."""

    KEYWORD = "keyword"
    TYPE = "type"
    FUNCTION = "function"
    DECORATOR = "decorator"
    CONSTANT = "constant"
    NUMBER = "number"
    STRING = "string"
    COMMENT = "comment"
    ERROR = "error"
    MARKDOWN_HEADING = "markdown_heading"
    MARKDOWN_STRONG = "markdown_strong"
    MARKDOWN_EMPHASIS = "markdown_emphasis"
    MARKDOWN_CODE = "markdown_code"
    DIFF_ADDED = "diff_added"
    DIFF_DELETED = "diff_deleted"
    DIFF_HEADER = "diff_header"
    DIFF_HUNK = "diff_hunk"


@dataclass(frozen=True, slots=True)
class SyntaxLimits:
    """Protection limits for one pager section."""

    max_bytes: int = MAX_SYNTAX_BYTES
    max_lines: int = MAX_SYNTAX_LINES
    max_line_chars: int = MAX_SYNTAX_LINE_CHARS
    max_spans: int = MAX_SYNTAX_SPANS
    max_markdown_nesting: int = MAX_MARKDOWN_NESTING


DEFAULT_SYNTAX_LIMITS: Final = SyntaxLimits()


@dataclass(frozen=True, slots=True)
class SyntaxSpan:
    """A role span in Python character offsets into the original source."""

    start: int
    end: int
    role: SyntaxRole

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < 0:
            raise ValueError("syntax span cannot be negative")
        if self.start >= self.end:
            raise ValueError("syntax span must be non-empty")


@dataclass(frozen=True, slots=True)
class SyntaxResult:
    """Immutable syntax output for one source section."""

    language: str | None
    disposition: SyntaxDisposition
    source_length: int
    spans: tuple[SyntaxSpan, ...] = ()
    reason: str | None = None


class _PygmentsLexer(Protocol):
    """The offset-producing subset of a Pygments lexer."""

    def get_tokens_unprocessed(
        self,
        text: str,
    ) -> Iterable[tuple[int, Any, str]]: ...


LexerFactory = Callable[[str], _PygmentsLexer]
RoleMapper = Callable[[Any], SyntaxRole | None]

_PLAIN_ALIASES: Final = frozenset({"", "none", "plain", "text", "txt"})
_LANGUAGE_ALIASES: Final = {
    "bash": "bash",
    "c": "c",
    "c++": "cpp",
    "cpp": "cpp",
    "css": "css",
    "diff": "diff",
    "docker": "docker",
    "dockerfile": "docker",
    "env": "bash",
    "frontmatter-markdown": "markdown",
    "go": "go",
    "html": "html",
    "java": "java",
    "javascript": "javascript",
    "jinja": "jinja",
    "jinja2": "jinja",
    "json": "json",
    "jsonl": "json",
    "jsx": "jsx",
    "lua": "lua",
    "make": "make",
    "makefile": "make",
    "markdown": "markdown",
    "md": "markdown",
    "patch": "diff",
    "py": "python",
    "python": "python",
    "rb": "ruby",
    "rst": "rst",
    "ruby": "ruby",
    "rust": "rust",
    "sh": "bash",
    "shell": "bash",
    "sql": "sql",
    "toml": "toml",
    "ts": "typescript",
    "tsx": "tsx",
    "typescript": "typescript",
    "udiff": "diff",
    "xml": "xml",
    "yaml": "yaml",
    "yml": "yaml",
    "zsh": "zsh",
}


def highlight_source(
    source: str,
    language: str | None,
    *,
    base_text: Text | None = None,
    raw_source: str | None = None,
    limits: SyntaxLimits = DEFAULT_SYNTAX_LIMITS,
    lexer_factory: LexerFactory | None = None,
) -> SyntaxResult:
    """Return immutable syntax spans without reconstructing *source*.

    Pygments is used only through ``get_tokens_unprocessed()`` with options that
    disable newline stripping, newline insertion, and tab expansion. Each token's
    value is checked against the original source slice before any span is accepted.
    """

    language_key = normalize_language(language)
    source_length = len(source)
    if language_key is None:
        return SyntaxResult(
            language=None,
            disposition=SyntaxDisposition.PLAIN,
            source_length=source_length,
        )
    if (raw_source is not None and "\x1b" in raw_source) or "\x1b" in source:
        return SyntaxResult(
            language=language_key,
            disposition=SyntaxDisposition.PRESERVED,
            source_length=source_length,
            reason="ansi-source",
        )
    if base_text is not None:
        if base_text.plain != source:
            return SyntaxResult(
                language=language_key,
                disposition=SyntaxDisposition.FAILED,
                source_length=source_length,
                reason="base-text-mismatch",
            )
        if text_has_producer_style(base_text):
            return SyntaxResult(
                language=language_key,
                disposition=SyntaxDisposition.PRESERVED,
                source_length=source_length,
                reason="producer-style",
            )

    if limit_reason := _syntax_limit_reason(source, limits):
        return SyntaxResult(
            language=language_key,
            disposition=SyntaxDisposition.TOO_LARGE,
            source_length=source_length,
            reason=limit_reason,
        )
    if source == "":
        return SyntaxResult(
            language=language_key,
            disposition=SyntaxDisposition.PLAIN,
            source_length=source_length,
        )

    budget = SpanBudget(limits.max_spans)
    factory = lexer_factory or _default_lexer_factory
    try:
        if language_key == "markdown":
            from sase.pager._markdown_syntax import markdown_syntax_spans

            spans = markdown_syntax_spans(
                source,
                lexer_factory=factory,
                budget=budget,
                limits=limits,
            )
        else:
            lexer = factory(language_key)
            mapper = _diff_token_role if language_key == "diff" else source_token_role
            spans = lex_pygments_spans(source, lexer, budget=budget, role_mapper=mapper)
    except ClassNotFound:
        return SyntaxResult(
            language=language_key,
            disposition=SyntaxDisposition.FAILED,
            source_length=source_length,
            reason="unknown-language",
        )
    except SpanBudgetExceeded:
        return SyntaxResult(
            language=language_key,
            disposition=SyntaxDisposition.TOO_LARGE,
            source_length=source_length,
            reason="span-limit",
        )
    except Exception:
        return SyntaxResult(
            language=language_key,
            disposition=SyntaxDisposition.FAILED,
            source_length=source_length,
            reason="lexer-failed",
        )

    return SyntaxResult(
        language=language_key,
        disposition=SyntaxDisposition.HIGHLIGHTED if spans else SyntaxDisposition.PLAIN,
        source_length=source_length,
        spans=spans,
    )


def normalize_language(language: str | None) -> str | None:
    """Return the pager engine alias for *language*, or ``None`` for plain text."""

    if language is None:
        return None
    key = language.strip().lower()
    if key in _PLAIN_ALIASES:
        return None
    return _LANGUAGE_ALIASES.get(key, key)


#: Short display forms for the subject-line language hint (design doc: "· py",
#: "· md", "· diff" — a concise alias, not a fixed-width promise). Languages
#: missing here fall back to their canonical engine name.
_SYNTAX_HINT_ALIASES: Final[Mapping[str, str]] = {
    "bash": "sh",
    "cpp": "cpp",
    "diff": "diff",
    "docker": "docker",
    "javascript": "js",
    "jsx": "jsx",
    "markdown": "md",
    "python": "py",
    "ruby": "rb",
    "rust": "rs",
    "typescript": "ts",
    "tsx": "tsx",
    "zsh": "zsh",
}


def syntax_hint_alias(language: str) -> str:
    """Return a short display form of *language* for the subject-line hint."""

    return _SYNTAX_HINT_ALIASES.get(language, language)


def resolve_pygments_alias(language: str) -> str | None:
    """Validate and normalize an explicit Pygments alias for the pager engine."""

    language_key = normalize_language(language)
    if language_key is None:
        return None
    if language_key == "markdown":
        return "markdown"
    lexer = _default_lexer_factory(language_key)
    aliases = getattr(lexer, "aliases", None)
    if aliases:
        return str(aliases[0])
    return language_key


def _syntax_limit_reason(
    source: str,
    limits: SyntaxLimits = DEFAULT_SYNTAX_LIMITS,
) -> str | None:
    """Return the first exceeded syntax limit for *source*, if any."""

    if len(source.encode("utf-8")) > limits.max_bytes:
        return "byte-limit"
    logical_lines = source.splitlines()
    if len(logical_lines) > limits.max_lines:
        return "line-limit"
    if any(len(line) > limits.max_line_chars for line in logical_lines):
        return "line-length-limit"
    return None


def text_has_producer_style(text: Text) -> bool:
    """Return true when *text* already carries caller-authored styling."""

    return bool(text.spans) or _style_is_non_neutral(text.style)


def style_source_text(
    source_text: Text,
    result: SyntaxResult,
    styles: Mapping[SyntaxRole, Style],
) -> Text:
    """Style a copy of *source_text* from syntax spans, preserving its characters."""

    if len(source_text.plain) != result.source_length:
        raise ValueError("syntax result length does not match source text")
    styled = source_text.copy()
    if result.disposition is not SyntaxDisposition.HIGHLIGHTED:
        return styled
    for span in result.spans:
        style = styles.get(span.role)
        if style is not None:
            styled.stylize(style, span.start, span.end)
    return styled


def _default_lexer_factory(language: str) -> _PygmentsLexer:
    return get_lexer_by_name(
        language,
        stripnl=False,
        ensurenl=False,
        stripall=False,
        tabsize=0,
    )


def lex_pygments_spans(
    source: str,
    lexer: _PygmentsLexer,
    *,
    budget: SpanBudget,
    role_mapper: RoleMapper,
    offset: int = 0,
) -> tuple[SyntaxSpan, ...]:
    spans: list[SyntaxSpan] = []
    cursor = 0
    for token_start, token, value in lexer.get_tokens_unprocessed(source):
        if not isinstance(token_start, int) or not isinstance(value, str):
            raise InvalidSyntaxOffsets
        token_end = token_start + len(value)
        if (
            token_start < cursor
            or token_start < 0
            or token_end > len(source)
            or source[token_start:token_end] != value
        ):
            raise InvalidSyntaxOffsets
        cursor = token_end
        if value and (role := role_mapper(token)) is not None:
            budget.append(
                spans, SyntaxSpan(offset + token_start, offset + token_end, role)
            )
    return tuple(spans)


def source_token_role(token: Any) -> SyntaxRole | None:
    if token in Error:
        return SyntaxRole.ERROR
    if token in Comment:
        return SyntaxRole.COMMENT
    if token in Name.Decorator:
        return SyntaxRole.DECORATOR
    if token in Name.Class or token in Name.Exception or token in Name.Namespace:
        return SyntaxRole.TYPE
    if token in Name.Function or token in Name.Builtin:
        return SyntaxRole.FUNCTION
    if (
        token in Keyword.Constant
        or token in Name.Constant
        or token in Name.Tag
        or token in Name.Builtin.Pseudo
    ):
        return SyntaxRole.CONSTANT
    if token in Keyword:
        return SyntaxRole.KEYWORD
    if token in TokenLiteral.String:
        return SyntaxRole.STRING
    if token in TokenLiteral.Number:
        return SyntaxRole.NUMBER
    if token in TokenLiteral:
        return SyntaxRole.CONSTANT
    return None


def markdown_token_role(token: Any) -> SyntaxRole | None:
    if token in Error:
        return SyntaxRole.ERROR
    if token in Generic.Heading:
        return SyntaxRole.MARKDOWN_HEADING
    if token in Generic.Strong:
        return SyntaxRole.MARKDOWN_STRONG
    if token in Generic.Emph:
        return SyntaxRole.MARKDOWN_EMPHASIS
    if token in TokenLiteral.String.Backtick:
        return SyntaxRole.MARKDOWN_CODE
    return source_token_role(token)


def _diff_token_role(token: Any) -> SyntaxRole | None:
    if token in Error:
        return SyntaxRole.ERROR
    if token in Generic.Inserted:
        return SyntaxRole.DIFF_ADDED
    if token in Generic.Deleted:
        return SyntaxRole.DIFF_DELETED
    if token in Generic.Subheading:
        return SyntaxRole.DIFF_HUNK
    if token in Generic.Heading:
        return SyntaxRole.DIFF_HEADER
    return None


def _style_is_non_neutral(style: str | Style) -> bool:
    if isinstance(style, Style):
        return bool(style)
    return bool(str(style).strip())


class SpanBudget:
    def __init__(self, max_spans: int) -> None:
        self._max_spans = max_spans
        self._count = 0

    def append(self, spans: list[SyntaxSpan], span: SyntaxSpan) -> None:
        if spans and spans[-1].end == span.start and spans[-1].role is span.role:
            spans[-1] = SyntaxSpan(spans[-1].start, span.end, span.role)
            return
        if self._count >= self._max_spans:
            raise SpanBudgetExceeded
        spans.append(span)
        self._count += 1

    def snapshot(self) -> int:
        return self._count

    def restore(self, count: int) -> None:
        self._count = count


class InvalidSyntaxOffsets(ValueError):
    """A lexer produced offsets that do not match the source text."""


class SpanBudgetExceeded(RuntimeError):
    """A lexer produced more spans than the pager will retain."""


__all__ = [
    "LexerFactory",
    "DEFAULT_SYNTAX_LIMITS",
    "MAX_MARKDOWN_NESTING",
    "MAX_SYNTAX_BYTES",
    "MAX_SYNTAX_LINE_CHARS",
    "MAX_SYNTAX_LINES",
    "MAX_SYNTAX_SPANS",
    "SyntaxDisposition",
    "SyntaxLimits",
    "SyntaxResult",
    "SyntaxRole",
    "SyntaxSpan",
    "highlight_source",
    "normalize_language",
    "resolve_pygments_alias",
    "style_source_text",
    "syntax_hint_alias",
    "text_has_producer_style",
]
