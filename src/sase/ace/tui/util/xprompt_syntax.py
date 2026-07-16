"""Markdown syntax highlighting with semantic xprompt overlays."""

from __future__ import annotations

from typing import Protocol

from rich.style import StyleType
from rich.syntax import Syntax
from rich.text import Text

from sase.xprompt import alt_inspect, xprompt_inspect

from .lazy_syntax import MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES

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
) -> Text:
    """Return Markdown-highlighted prompt text with xprompt token overlays.

    Highlighting is presentation-only and deliberately fail-open: oversized or
    malformed input always remains fully visible as plain text.
    """
    if (
        len(text.encode("utf-8", errors="replace"))
        > MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
    ):
        return Text(text)
    try:
        highlighted = Syntax(text, "markdown", theme="monokai").highlight(text)
        if not text.endswith("\n") and highlighted.plain.endswith("\n"):
            highlighted.right_crop(1)
        apply_xprompt_overlays(
            highlighted,
            text,
            known_skills=known_skills,
        )
        return highlighted
    except Exception:
        return Text(text)


__all__ = [
    "XPROMPT_TOKEN_STYLES",
    "apply_xprompt_overlays",
    "highlight_prompt_text",
]
