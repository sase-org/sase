"""Markdown syntax highlighting with semantic xprompt overlays."""

from __future__ import annotations

from rich.syntax import Syntax
from rich.text import Text

from sase.xprompt import alt_inspect, xprompt_inspect

from .lazy_syntax import MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES

XPROMPT_TOKEN_STYLES: dict[str, str] = {
    "invocation": "bold #87D787",
    "invocation_arg": "#5FAF87",
    "directive": "bold #FFD75F",
    "directive_arg": "#D7AF5F",
    "alt_delimiter": "bold #D787FF",
    "branch_name": "bold #87D787",
    "error": "underline #FF5F5F",
    "separator": "dim bold #87AFFF",
}


def _apply_xprompt_overlays(text: str, highlighted: Text) -> None:
    for span in xprompt_inspect.tokenize(text):
        highlighted.stylize(XPROMPT_TOKEN_STYLES[span.kind], span.start, span.end)

    alt_style_keys = {
        "delimiter": "alt_delimiter",
        "separator": "alt_delimiter",
        "branch_name": "branch_name",
        "error": "error",
    }
    for alt_span in alt_inspect.tokenize(text):
        highlighted.stylize(
            XPROMPT_TOKEN_STYLES[alt_style_keys[alt_span.kind]],
            alt_span.start,
            alt_span.end,
        )


def highlight_prompt_text(text: str) -> Text:
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
        _apply_xprompt_overlays(text, highlighted)
        return highlighted
    except Exception:
        return Text(text)


__all__ = ["XPROMPT_TOKEN_STYLES", "highlight_prompt_text"]
