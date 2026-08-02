"""Markdown/code syntax highlighting for bead DESCRIPTION and NOTES bodies."""

from __future__ import annotations

from io import StringIO
import re

from pygments.lexer import Lexer  # type: ignore[import-untyped]
from pygments.lexers import get_lexer_by_name  # type: ignore[import-untyped]
from pygments.util import ClassNotFound  # type: ignore[import-untyped]
from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text

from sase.ansi_style import ANSI_RESET
from sase.bead.cli_detail_style import DetailStyle

_THEME = "ansi_dark"
_FALLBACK_LEXER_NAME = "text"
# Large enough that Rich never soft-wraps a realistic bead description.
_RENDER_WIDTH = 1_000_000
_FENCE_RE = re.compile(
    r"^```[ \t]*(?P<lang>\S*)[ \t]*\n(?P<body>.*?)^```[ \t]*$\n?",
    re.MULTILINE | re.DOTALL,
)
# Rich's Console unconditionally expands literal tabs to spaces while
# rendering a Text, with no way to opt out. Swap tabs for a private-use
# placeholder before highlighting and restore them afterward so a tab in a
# description survives RICH styling byte-for-byte, same as every other
# character.
_TAB_PLACEHOLDER = ""


def highlight_prose(text: str, *, style: DetailStyle) -> str:
    """Return *text* with additive ANSI markdown/code tinting.

    Returns *text* unchanged for every style level other than ``rich``, and
    fails open to the unhighlighted text on any highlighting error so an
    unhighlightable description always still prints. Raw ``\\x1b[...m`` bytes
    already present in *text* are passed through unchanged rather than
    sanitized — sanitizing would itself violate the plain-text byte
    invariant this feature exists to preserve. Such content can still leak
    color past its own line in a real terminal; this is a known, accepted
    limitation rather than something this function can fix.
    """
    if style is not DetailStyle.RICH or not text:
        return text
    try:
        protected = text.replace("\t", _TAB_PLACEHOLDER)
        highlighted = _highlight_markdown(protected)
        rendered = _render_text(highlighted)
        return rendered.replace(_TAB_PLACEHOLDER, "\t")
    except Exception:
        return text


def _highlight_markdown(text: str) -> Text:
    highlighted = Syntax(
        text, "markdown", theme=_THEME, background_color="default"
    ).highlight(text)
    _right_crop_added_newline(highlighted, text)

    for match in _FENCE_RE.finditer(text):
        body_start, body_end = match.span("body")
        body = text[body_start:body_end]
        if not body:
            continue
        fence_text = _highlight_fence_body(body, match.group("lang"))
        if fence_text is None:
            continue
        for span in fence_text.spans:
            highlighted.stylize(
                span.style, body_start + span.start, body_start + span.end
            )
    return highlighted


def _highlight_fence_body(body: str, lang: str) -> Text | None:
    lexer = _resolve_lexer(lang)
    if lexer is None:
        return None
    try:
        fence_text = Syntax(
            body, lexer, theme=_THEME, background_color="default"
        ).highlight(body)
    except Exception:
        return None
    _right_crop_added_newline(fence_text, body)
    return fence_text


def _resolve_lexer(lang: str) -> Lexer | None:
    for name in filter(None, (lang, _FALLBACK_LEXER_NAME)):
        try:
            return get_lexer_by_name(name)
        except ClassNotFound:
            continue
    return None


def _right_crop_added_newline(highlighted: Text, source: str) -> None:
    """Undo the trailing newline ``Syntax.highlight()`` always appends."""
    if highlighted.plain.endswith("\n") and not source.endswith("\n"):
        highlighted.right_crop(1)


def _render_text(highlighted: Text) -> str:
    console = Console(
        file=StringIO(),
        force_terminal=True,
        no_color=False,
        color_system="256",
        width=_RENDER_WIDTH,
        soft_wrap=True,
        markup=False,
        emoji=False,
        highlight=False,
    )
    with console.capture() as capture:
        console.print(highlighted, end="")
    # A style span from Syntax can cross a real newline (Rich itself reopens
    # it on the next line), but a raw escape byte already present in the
    # source content is invisible to Rich and would otherwise bleed past the
    # end of its own line. Force a reset at every line boundary to bound it.
    lines = capture.get().split("\n")
    return "\n".join(f"{line}{ANSI_RESET}" for line in lines)


__all__ = ["highlight_prose"]
