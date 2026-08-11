"""Shared clan-summary Rich-markup parsing."""

from __future__ import annotations

from rich.errors import MarkupError, StyleSyntaxError
from rich.markup import RE_TAGS, Tag
from rich.style import Style
from rich.text import Text

from ...models.agent import Agent


def _is_renderable_style(style: object) -> bool:
    """Report whether a `Text` span style resolves without a Rich/Textual crash."""
    if not isinstance(style, str):
        return True
    try:
        Style.parse(style)
    except StyleSyntaxError:
        return False
    return True


def _escape_unrenderable_tags(markup: str) -> str:
    """Backslash-escape only the markup tags that would yield an unrenderable style.

    Mirrors `rich.markup.render`'s open/close tag stack so an opening tag and its
    matching closing tag are always escaped together, and tags left open at the end of
    the markup (the `[@file:<file>]` case) are treated the same way Rich treats them: as
    plain style-name spans, not meta tags.
    """
    open_stack: list[tuple[tuple[int, int], Tag]] = []
    escape_spans: set[tuple[int, int]] = set()

    def _mark_if_unrenderable(
        open_match: tuple[int, int],
        open_tag: Tag,
        close_match: tuple[int, int] | None,
    ) -> None:
        if _is_renderable_style(str(open_tag)):
            return
        escape_spans.add(open_match)
        if close_match is not None:
            escape_spans.add(close_match)

    def _handle_matched_close(
        open_match: tuple[int, int],
        open_tag: Tag,
        close_match: tuple[int, int] | None,
    ) -> None:
        if open_tag.name.startswith("@"):
            return  # Explicitly closed meta tags become Style(meta=...), never a str.
        _mark_if_unrenderable(open_match, open_tag, close_match)

    for match in RE_TAGS.finditer(markup):
        escapes, tag_text = match.group(2), match.group(3)
        if escapes:
            _, escaped = divmod(len(escapes), 2)
            if escaped:
                continue  # Already an escaped literal, not a tag.
        name, equals, parameters = tag_text.partition("=")
        tag = Tag(name, parameters if equals else None)
        if tag.name.startswith("/"):
            style_name = tag.name[1:].strip()
            if style_name:
                for index in range(len(open_stack) - 1, -1, -1):
                    open_match, open_tag = open_stack[index]
                    if open_tag.name == style_name:
                        del open_stack[index]
                        _handle_matched_close(open_match, open_tag, match.span())
                        break
            elif open_stack:
                open_match, open_tag = open_stack.pop()
                _handle_matched_close(open_match, open_tag, None)
        else:
            open_stack.append((match.span(), tag))

    for open_match, open_tag in open_stack:
        _mark_if_unrenderable(open_match, open_tag, None)

    if not escape_spans:
        return markup

    escaped_markup = markup
    for start, end in sorted(escape_spans, reverse=True):
        escaped_markup = f"{escaped_markup[:start]}\\{escaped_markup[start:end]}{escaped_markup[end:]}"
    return escaped_markup


def clan_summary_text(agent: Agent) -> Text:
    """Return a clan summary parsed as Rich markup with a plain fallback.

    Parses `raw` as markup and keeps it as-is when every span resolves to a renderable
    style. When a span does not resolve (for example an unclosed `[@file:<file>]`
    prompt token that Rich accepts as a tag but never validates), escapes just the
    offending tags and re-parses so intended markup elsewhere in the summary keeps its
    styling. Falls back to the raw text when the markup is structurally invalid or a
    span is still unrenderable after escaping.
    """
    raw = agent.clan_summary or ""
    try:
        text = Text.from_markup(raw)
        if all(_is_renderable_style(span.style) for span in text.spans):
            return text
        text = Text.from_markup(_escape_unrenderable_tags(raw))
        if all(_is_renderable_style(span.style) for span in text.spans):
            return text
    except MarkupError:
        pass
    return Text(raw)


__all__ = ["clan_summary_text"]
