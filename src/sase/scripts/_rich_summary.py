"""Rich ``Text`` primitives for bounded persisted summary documents."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
import re

from rich.cells import cell_len
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

_MARKDOWN_CODE_THEME = "monokai"
_MARKDOWN_HINT_RE = re.compile(
    r"(?m)(?:"
    r"^\s{0,3}(?:#{1,6}\s|>\s|[-+*]\s|\d+[.)]\s|```|~~~)|"
    r"(?<!\\)(?:`|\*\*|__|~~|\[[^\]\n]+\]\([^\)\n]+\)|"
    r"(?<!\w)[*_][^*_\n]+[*_](?!\w))"
    r")"
)


@dataclass(frozen=True)
class _RenderedMarkdown:
    """Markdown rendered to complete, independently serializable lines."""

    lines: tuple[Text, ...]
    used_markdown: bool
    truncated: bool = False

    def cap(self, max_lines: int, *, width: int) -> _RenderedMarkdown:
        """Return at most ``max_lines``, adding an ellipsis only if truncated."""
        if max_lines < 1:
            return replace(self, lines=(), truncated=bool(self.lines))
        if len(self.lines) <= max_lines:
            return self

        kept = [line.copy() for line in self.lines[:max_lines]]
        last = kept[-1]
        last.truncate(max(width - 1, 0), overflow="crop")
        last.append("…")
        return replace(self, lines=tuple(kept), truncated=True)

    def styled(self, style: str) -> _RenderedMarkdown:
        """Layer a base style under the semantic Markdown styles."""
        lines: list[Text] = []
        for source in self.lines:
            line = source.copy()
            if line:
                line.stylize(style, 0, len(line))
            lines.append(line)
        return replace(self, lines=tuple(lines))

    @property
    def markup(self) -> str:
        """Serialize the styled lines as parseable Rich markup."""
        return "\n".join(line.markup for line in self.lines)


def render_markdown_lines(value: str, *, width: int) -> _RenderedMarkdown:
    """Render Markdown at a deterministic width without capture padding."""
    width = max(width, 1)
    stripped = value.strip()
    if not stripped:
        return _RenderedMarkdown((), used_markdown=False)

    console = _summary_console(width)
    uses_markdown = _MARKDOWN_HINT_RE.search(stripped) is not None
    if not uses_markdown:
        lines = Text(stripped).wrap(console, width, overflow="fold")
        return _RenderedMarkdown(_trim_lines(lines), used_markdown=False)

    with console.capture() as capture:
        console.print(
            Markdown(
                stripped,
                code_theme=_MARKDOWN_CODE_THEME,
                inline_code_theme=_MARKDOWN_CODE_THEME,
                hyperlinks=False,
            ),
            end="",
        )
    rendered = Text.from_ansi(capture.get())
    return _RenderedMarkdown(
        _trim_lines(rendered.split("\n", allow_blank=True)),
        used_markdown=True,
    )


def shorten_text(value: Text, *, width: int) -> Text:
    """Shorten one styled line to a visible-cell width."""
    shortened = value.copy()
    shortened.truncate(max(width, 0), overflow="ellipsis")
    return shortened


def visible_width(value: Text | str) -> int:
    """Return terminal cell width rather than Python character count."""
    return cell_len(value.plain if isinstance(value, Text) else value)


def serialize_lines(lines: tuple[Text, ...] | list[Text]) -> str:
    """Serialize only after all line-level sizing and composition is complete."""
    return "\n".join(line.markup for line in lines)


def _summary_console(width: int) -> Console:
    return Console(
        width=width,
        color_system="truecolor",
        force_terminal=True,
        force_interactive=False,
        legacy_windows=False,
        highlight=False,
        markup=False,
        emoji=False,
    )


def _trim_lines(lines: Iterable[Text]) -> tuple[Text, ...]:
    trimmed = [line.copy() for line in lines]
    for line in trimmed:
        line.rstrip()
    while trimmed and not trimmed[0].plain:
        trimmed.pop(0)
    while trimmed and not trimmed[-1].plain:
        trimmed.pop()
    return tuple(trimmed)
