"""Markdown syntax highlighting with semantic xprompt overlays."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from hashlib import blake2b
from typing import Protocol

from pygments.lexers.markup import MarkdownLexer  # type: ignore[import-untyped]
from pygments.token import Token  # type: ignore[import-untyped]
from rich.style import StyleType
from rich.syntax import Syntax
from rich.text import Text

from sase.xprompt import alt_inspect, xprompt_inspect
from sase.xprompt.glossary_catalog import EditorGlossaryCatalog
from sase.xprompt.repo_mention_catalog import EditorRepoMentionCatalog

from .artifact_ref_syntax import (
    ArtifactRefStylePalette,
    apply_artifact_ref_overlays,
)
from .frontmatter_syntax import FRONTMATTER_MARKDOWN_LEXER
from .lazy_syntax import (
    MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES,
    MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES,
)
from .semantic_overlay import apply_semantic_overlays
from .semantic_styles import SemanticHighlightStyles

XPROMPT_TOKEN_STYLES: dict[str, str] = {
    "invocation": "bold #87D787",
    "invocation_arg": "#5FAF87",
    "directive": "bold #FFD75F",
    "directive_arg": "#D7AF5F",
    "skill": "bold #87AFD7",
    "alt_delimiter": "bold #D787FF",
    "branch_name": "bold #87D787",
    "error": "underline #FF5F5F",
    "separator": "dim bold #87AFFF",
}

_ALT_TOKEN_STYLE_KEYS = {
    "delimiter": "alt_delimiter",
    "separator": "alt_delimiter",
    "branch_name": "branch_name",
    "error": "error",
}


class _XPromptMarkdownLexer(MarkdownLexer):
    """Markdown lexer that keeps xprompt-led lines out of heading rules."""

    tokens = {
        **MarkdownLexer.tokens,
        "root": [
            (r"^#(?=[^#\s])", Token.Text),
            *MarkdownLexer.tokens["root"],
        ],
    }


_XPROMPT_MARKDOWN_LEXER = _XPromptMarkdownLexer()
_MARKDOWN_TEXT_CACHE_MAX_ENTRIES = 24
_markdown_text_cache: OrderedDict[tuple[object, ...], Text] = OrderedDict()


def _text_digest(text: str) -> str:
    return blake2b(text.encode("utf-8", errors="replace"), digest_size=16).hexdigest()


def _cached_highlighted_text(
    key: tuple[object, ...],
    factory: Callable[[], Text],
) -> Text:
    cached = _markdown_text_cache.get(key)
    if cached is not None:
        _markdown_text_cache.move_to_end(key)
        return cached
    highlighted = factory()
    _markdown_text_cache[key] = highlighted
    if len(_markdown_text_cache) > _MARKDOWN_TEXT_CACHE_MAX_ENTRIES:
        _markdown_text_cache.popitem(last=False)
    return highlighted


class _StylizableText(Protocol):
    def stylize(
        self,
        style: StyleType,
        start: int = 0,
        end: int | None = None,
    ) -> None: ...


def apply_xprompt_overlays(
    highlighted: _StylizableText,
    source: str,
    *,
    region_start: int = 0,
    known_skills: frozenset[str] = frozenset(),
) -> None:
    """Apply semantic xprompt styles from *source* to a Text region.

    Tokenization finishes before the target is mutated so callers can fail open
    without leaving partially-applied overlays. Oversized regions are left
    untouched, matching :func:`highlight_prompt_text`.
    """
    if (
        len(source.encode("utf-8", errors="replace"))
        > MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
    ):
        return

    overlays = [
        (XPROMPT_TOKEN_STYLES[span.kind], span.start, span.end)
        for span in xprompt_inspect.tokenize(source, known_skills=known_skills)
    ]
    overlays.extend(
        (
            XPROMPT_TOKEN_STYLES[_ALT_TOKEN_STYLE_KEYS[alt_span.kind]],
            alt_span.start,
            alt_span.end,
        )
        for alt_span in alt_inspect.tokenize(source)
    )
    for style, start, end in overlays:
        highlighted.stylize(
            style,
            region_start + start,
            region_start + end,
        )


def highlight_prompt_text(
    text: str,
    *,
    known_skills: frozenset[str] = frozenset(),
    glossary_catalog: EditorGlossaryCatalog | None = None,
    repo_catalog: EditorRepoMentionCatalog | None = None,
    semantic_styles: SemanticHighlightStyles | None = None,
    artifact_ref_known_kinds: frozenset[str] | None = None,
    artifact_ref_styles: ArtifactRefStylePalette | None = None,
) -> Text:
    """Return Markdown-highlighted prompt text with xprompt token overlays.

    Highlighting is presentation-only and deliberately fail-open: oversized or
    malformed input always remains fully visible as plain text. Glossary and
    repo roles, when supplied, annotate natural-language text before structural
    xprompt styles win.
    """
    if _exceeds_prompt_highlight_cap(text):
        return Text(text)
    key = (
        "prompt",
        _text_digest(text),
        frozenset(known_skills),
        semantic_styles.signature if semantic_styles is not None else "",
        id(glossary_catalog) if glossary_catalog is not None else 0,
        id(repo_catalog) if repo_catalog is not None else 0,
        frozenset(artifact_ref_known_kinds or ()),
        getattr(artifact_ref_styles, "signature", ""),
    )
    try:
        return _cached_highlighted_text(
            key,
            lambda: _highlight_prompt_text_uncached(
                text,
                known_skills=known_skills,
                glossary_catalog=glossary_catalog,
                repo_catalog=repo_catalog,
                semantic_styles=semantic_styles,
                artifact_ref_known_kinds=artifact_ref_known_kinds,
                artifact_ref_styles=artifact_ref_styles,
            ),
        )
    except Exception:
        return Text(text)


def highlight_markdown_text(
    text: str,
    *,
    glossary_catalog: EditorGlossaryCatalog | None = None,
    repo_catalog: EditorRepoMentionCatalog | None = None,
    semantic_styles: SemanticHighlightStyles | None = None,
) -> Text:
    """Return ordinary Markdown-highlighted text with optional semantic roles.

    Unlike :func:`highlight_prompt_text`, this path does not apply xprompt
    token styles. Oversized or malformed input remains fully visible.
    """
    if _exceeds_prompt_highlight_cap(text):
        return Text(text)
    key = (
        "markdown",
        _text_digest(text),
        semantic_styles.signature if semantic_styles is not None else "",
        id(glossary_catalog) if glossary_catalog is not None else 0,
        id(repo_catalog) if repo_catalog is not None else 0,
    )
    try:
        return _cached_highlighted_text(
            key,
            lambda: _highlight_markdown_text_uncached(
                text,
                glossary_catalog=glossary_catalog,
                repo_catalog=repo_catalog,
                semantic_styles=semantic_styles,
            ),
        )
    except Exception:
        return Text(text)


def _highlight_prompt_text_uncached(
    text: str,
    *,
    known_skills: frozenset[str],
    glossary_catalog: EditorGlossaryCatalog | None,
    repo_catalog: EditorRepoMentionCatalog | None,
    semantic_styles: SemanticHighlightStyles | None,
    artifact_ref_known_kinds: frozenset[str] | None,
    artifact_ref_styles: ArtifactRefStylePalette | None,
) -> Text:
    highlighted = Syntax(
        text,
        _XPROMPT_MARKDOWN_LEXER,
        theme="monokai",
    ).highlight(text)
    _trim_syntax_trailing_newline(highlighted, text)
    apply_semantic_overlays(
        highlighted,
        text,
        glossary_catalog=glossary_catalog,
        repo_catalog=repo_catalog,
        styles=semantic_styles,
        skip_xprompt=True,
        known_skills=known_skills,
    )
    apply_xprompt_overlays(
        highlighted,
        text,
        known_skills=known_skills,
    )
    if artifact_ref_known_kinds is not None:
        apply_artifact_ref_overlays(
            highlighted,
            text,
            known_kinds=artifact_ref_known_kinds,
            palette=artifact_ref_styles,
            max_bytes=MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES,
            max_lines=MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES,
        )
    return highlighted


def _highlight_markdown_text_uncached(
    text: str,
    *,
    glossary_catalog: EditorGlossaryCatalog | None,
    repo_catalog: EditorRepoMentionCatalog | None,
    semantic_styles: SemanticHighlightStyles | None,
) -> Text:
    highlighted = Syntax(
        text,
        FRONTMATTER_MARKDOWN_LEXER,
        theme="monokai",
    ).highlight(text)
    _trim_syntax_trailing_newline(highlighted, text)
    apply_semantic_overlays(
        highlighted,
        text,
        glossary_catalog=glossary_catalog,
        repo_catalog=repo_catalog,
        styles=semantic_styles,
    )
    return highlighted


def _exceeds_prompt_highlight_cap(text: str) -> bool:
    return (
        len(text.encode("utf-8", errors="replace"))
        > MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
        or text.count("\n") > MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES
    )


def _trim_syntax_trailing_newline(highlighted: Text, source: str) -> None:
    if not source.endswith("\n") and highlighted.plain.endswith("\n"):
        highlighted.right_crop(1)


__all__ = [
    "XPROMPT_TOKEN_STYLES",
    "apply_xprompt_overlays",
    "highlight_markdown_text",
    "highlight_prompt_text",
]
