"""Rich renderers for the dictionary definition card."""

from __future__ import annotations

import re
from typing import Any

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.measure import Measurement
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .word_definition_card import DefinitionCard, DictBlock, DictEntry

_DARK_ACCENT = "#5FD7AF"
_DARK_PILL_FG = "#1a1a1a"
_LIGHT_ACCENT = "#00875F"
_LIGHT_PILL_FG = "#FFFFFF"

_CROSS_REF_RE = re.compile(r"\{([^{}]*)\}")


def definition_card_palette(theme: Any) -> tuple[str, str]:
    """Return ``(accent, pill_foreground)`` for the current theme."""
    dark = bool(getattr(theme, "dark", True))
    if dark:
        return (_DARK_ACCENT, _DARK_PILL_FG)
    return (_LIGHT_ACCENT, _LIGHT_PILL_FG)


class _HangingIndent:
    """A hanging-indent row: marker cell, then wrapped body text."""

    def __init__(self, marker: Text, body: Text, *, indent: int = 4) -> None:
        self._marker = marker
        self._body = body
        self._indent = indent

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        width = max(1, options.max_width - self._indent)
        lines = self._body.wrap(console, width)
        cell = self._marker.plain.rjust(3)
        marker_cell = Text(cell, style=self._marker.style)
        prefix = Text(" " * max(0, self._indent - 4))
        if not lines:
            yield prefix + marker_cell
            return
        yield Text.assemble(prefix, marker_cell, Text(" "), lines[0])
        pad = Text(" " * self._indent)
        for line in lines[1:]:
            yield pad + line

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        body = self._body.wrap(console, max(1, options.max_width - self._indent))
        width = max((len(line.plain) for line in body), default=0) + self._indent
        return Measurement(0, min(width, options.max_width))


def _append_cross_refs(text: Text, content: str, *, accent: str) -> None:
    cursor = 0
    for match in _CROSS_REF_RE.finditer(content):
        if match.start() > cursor:
            text.append(content[cursor : match.start()])
        ref = match.group(1).strip()
        if ref:
            text.append(ref, style=accent)
        cursor = match.end()
    if cursor < len(content):
        text.append(content[cursor:])


def _styled_text(content: str, *, accent: str) -> Text:
    text = Text()
    _append_cross_refs(text, content, accent=accent)
    return text


def _styled_text_with_base(content: str, *, accent: str, base_style: str) -> Text:
    text = Text()
    cursor = 0
    for match in _CROSS_REF_RE.finditer(content):
        if match.start() > cursor:
            text.append(content[cursor : match.start()], style=base_style)
        ref = match.group(1).strip()
        if ref:
            text.append(ref, style=accent)
        cursor = match.end()
    if cursor < len(content):
        text.append(content[cursor:], style=base_style)
    return text


def build_headline(
    card: DefinitionCard, *, accent: str, pill_fg: str
) -> RenderableType:
    left = Text()
    left.append(f" {card.headword} ", style=f"bold {pill_fg} on {accent}")
    if card.pos_display:
        left.append("  ")
        left.append(card.pos_display, style="italic")
    if card.syllables:
        left.append("  " if not card.pos_display else " ", style="")
        if card.pos_display:
            left.append("· ", style="dim")
        left.append(card.syllables, style="dim")
    if not card.show_looked_up:
        return left
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1, overflow="fold")
    grid.add_column(justify="right", no_wrap=True)
    right = Text()
    right.append("looked up ", style="dim")
    right.append(f"\u201c{card.word}\u201d", style="dim")
    grid.add_row(left, right)
    return grid


def build_lead(card: DefinitionCard) -> RenderableType | None:
    if card.lead is None:
        return None
    parts: list[RenderableType] = [Text(card.lead.gloss)]
    if card.lead.examples:
        examples = Text()
        for index, example in enumerate(card.lead.examples):
            if index:
                examples.append(" · ", style="dim")
            examples.append(f"\u201c{example}\u201d", style="italic dim")
        parts.append(examples)
    return Group(*parts)


def build_attribution(card: DefinitionCard) -> RenderableType | None:
    if card.lead is None:
        return None
    text = Text(card.lead.source_label, style="dim")
    if card.lead.sense_total > 1:
        text.append(f" · sense 1 of {card.lead.sense_total}", style="dim")
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(justify="right", no_wrap=True)
    grid.add_row(Text(""), text)
    return grid


def build_details(card: DefinitionCard, *, accent: str) -> RenderableType:
    sections: list[RenderableType] = []
    entries: tuple[DictEntry, ...] = card.entries
    for entry_index, entry in enumerate(entries):
        if entry_index:
            sections.append(Text(""))
        sections.append(
            Rule(
                Text(entry.heading, style=f"bold {accent}"),
                align="left",
                style=f"{accent} dim",
            )
        )
        for block in entry.blocks:
            sections.append(_render_block(block, accent=accent))
    if not sections:
        return Text("")
    return Group(*sections)


def _render_entry_line(content: str, *, accent: str) -> Text:
    parts = [part for part in content.split("  ") if part]
    text = Text()
    if parts:
        head = Text()
        _append_cross_refs(head, parts[0], accent=accent)
        head.stylize("bold")
        text.append_text(head)
    if len(parts) > 1:
        text.append("  ")
        text.append(parts[1], style="italic")
    if len(parts) > 2:
        text.append("  ")
        text.append(parts[2], style="dim")
    if len(parts) > 3:
        text.append("  ")
        _append_cross_refs(text, "  ".join(parts[3:]), accent=accent)
    return text


def _render_block(block: DictBlock, *, accent: str) -> RenderableType:
    if block.kind == "entry":
        return _render_entry_line(block.text, accent=accent)
    if block.kind == "meta":
        text = Text("  ")
        text.append_text(
            _styled_text_with_base(block.text, accent=accent, base_style="dim")
        )
        return text
    if block.kind == "sense":
        marker = Text(block.marker or "", style=f"bold {accent}", justify="right")
        body = Group(*_sense_body_lines(block, accent=accent))
        return _HangingIndent(marker, _flatten_group(body), indent=4)
    if block.kind == "subsense":
        marker = Text(block.marker or "", style=f"bold {accent}", justify="right")
        body = Group(*_sense_body_lines(block, accent=accent))
        return _HangingIndent(marker, _flatten_group(body), indent=6)
    if block.kind == "quote":
        text = Text()
        text.append("\u201c", style="italic dim")
        text.append_text(
            _styled_text_with_base(block.text, accent=accent, base_style="italic dim")
        )
        text.append("\u201d", style="italic dim")
        if block.author:
            text.append(f" \u2014 {block.author}", style="dim")
        return _HangingIndent(Text(""), text, indent=4)
    if block.kind == "labeled":
        items = [item.strip() for item in block.text.split(";")]
        items = [item for item in items if item]
        if block.label == "synonyms" and items:
            return _accent_labeled_row(block.label, items, accent=accent)
        text = Text()
        text.append(block.label, style="dim")
        text.append("  ")
        _append_cross_refs(text, block.text, accent=accent)
        return text
    if block.kind == "pos_heading":
        return Text(block.text, style=f"italic {accent}")
    if block.kind == "thesaurus":
        text = Text()
        for index, item in enumerate(block.items):
            if index:
                text.append(" · ", style="dim")
            text.append(item, style=accent)
        return text
    if block.kind == "phrase":
        text = Text()
        _append_cross_refs(text, block.text, accent=accent)
        return text
    text = Text()
    _append_cross_refs(text, block.text, accent=accent)
    return text


def _accent_labeled_row(label: str, items: list[str], *, accent: str) -> Text:
    text = Text()
    text.append(label, style="dim")
    text.append("  ")
    for index, item in enumerate(items):
        if index:
            text.append(" · ", style="dim")
        item_text = Text()
        _append_cross_refs(item_text, item, accent=accent)
        item_text.stylize(accent)
        text.append_text(item_text)
    return text


def _sense_body_lines(block: DictBlock, *, accent: str) -> list[RenderableType]:
    lines: list[RenderableType] = [_styled_text(block.text, accent=accent)]
    if block.items:
        examples = Text()
        for index, example in enumerate(block.items):
            if index:
                examples.append(" · ", style="dim")
            examples.append(f"\u201c{example}\u201d", style="italic dim")
        lines.append(examples)
    return lines


def _flatten_group(group: Group) -> Text:
    text = Text()
    for index, renderable in enumerate(group.renderables):
        if index:
            text.append("\n")
        if isinstance(renderable, Text):
            text.append_text(renderable)
        else:
            text.append(str(renderable))
    return text


def build_border_title(*, accent: str) -> Text:
    title = Text()
    title.append("≡", style=f"bold {accent}")
    title.append(" DICTIONARY", style=f"bold {accent}")
    return title


def build_border_subtitle(*, accent: str) -> Text:
    hints = [
        ("j/k", " scroll"),
        ("ctrl+d/u", " page"),
        ("g/G", " top/end"),
        ("y", " copy"),
        ("esc", " close"),
    ]
    text = Text()
    for index, (key, label) in enumerate(hints):
        if index:
            text.append(" · ", style="dim")
        text.append(key, style=f"bold {accent}")
        text.append(label, style="dim")
    return text


__all__ = [
    "build_attribution",
    "build_border_subtitle",
    "build_border_title",
    "build_details",
    "build_headline",
    "build_lead",
    "definition_card_palette",
]
