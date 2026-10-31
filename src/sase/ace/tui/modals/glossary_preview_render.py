"""Pure render helpers for the ACE glossary preview card."""

from __future__ import annotations

from urllib.parse import quote
from typing import Any

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.core.glossary_facade import (
    GlossaryCatalog,
    GlossaryEntry,
    GlossarySpan,
    scan_glossary_spans,
)
from sase.memory.web.resolution import resolve_glossary_closure
from sase.memory.web.catalog import glossary_source_from_wire
from sase.macro.highlight_theme import derive_argument_color

_COLOR_MUTED = "dim"
_COLOR_LABEL = "dim"
_COLOR_TITLE = "bold"
_FALLBACK_ACCENT = "#87D7FF"
_PILL_FOREGROUND = "#1a1a1a"


def glossary_card_accent(theme: Any) -> str:
    """Return the theme-derived glossary accent used by prompt highlighting."""
    background = getattr(theme, "background", None) or "#000000"
    accent = derive_argument_color(
        getattr(theme, "primary", None),
        foreground=getattr(theme, "foreground", None),
        background=background,
    )
    return accent or _FALLBACK_ACCENT


def build_glossary_title(
    entry: GlossaryEntry,
    *,
    matched_text: str | None,
    project_name: str,
    accent: str,
) -> RenderableType:
    """Build the card title with an optional matched-text disclosure line."""
    identity = Text()
    identity.append("G", style=f"bold {accent}")
    identity.append(" ")
    identity.append("GLOSSARY", style=f"bold {accent}")
    identity.append("  ")
    identity.append(entry.term, style=_COLOR_TITLE)

    if project_name:
        first_line = Table.grid(expand=True, padding=(0, 0, 0, 2))
        first_line.add_column(ratio=1, overflow="ellipsis")
        first_line.add_column(justify="right", no_wrap=True)
        first_line.add_row(identity, Text(project_name, style=f"bold {accent}"))
        lines: list[RenderableType] = [first_line]
    else:
        lines = [identity]

    if _should_show_matched_text(entry, matched_text):
        display_matched_text = _normalize_matched_text(matched_text)
        match = Text()
        match.append('matched "', style=_COLOR_MUTED)
        match.append(display_matched_text, style=f"bold underline {accent}")
        match.append('"', style=_COLOR_MUTED)
        lines.append(match)
    return Group(*lines)


def build_alias_chips(
    display_aliases: tuple[str, ...],
    *,
    accent: str,
) -> Text | None:
    """Build alias chips, or ``None`` when no display aliases should render."""
    aliases = tuple(alias for alias in display_aliases if alias)
    if not aliases:
        return None
    text = Text()
    for alias in aliases:
        _append_chip(text, alias, accent=accent)
    return text


def build_see_also_chips(
    references: tuple[GlossaryEntry, ...],
    *,
    accent: str,
) -> Text | None:
    """Build numbered cross-reference chips, or ``None`` when absent."""
    if not references:
        return None
    text = Text()
    for index, reference in enumerate(references[:9], start=1):
        _append_chip(text, f"{index} {reference.term}", accent=accent)
    return text


def build_numbered_chip_rows(
    groups: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    focused_number: int | None,
    accent: str,
    shortcut_prefix: str = "",
) -> RenderableType | None:
    """Build labeled numbered chip rows with continuous numbering.

    Empty groups are omitted rather than rendered empty. Numbering is
    continuous across the rendered rows so a numbered shortcut is never
    ambiguous. Returns ``None`` when every group is empty. Glossary
    ``SEE ALSO`` / ``REFERENCED BY`` chips and Memory ``PARENT`` /
    ``CHILDREN`` chips share this renderer so the two surfaces cannot
    drift visually. *shortcut_prefix* is prepended to each chip number
    (``.1 name``); callers such as Snippets and the compact glossary
    preview leave it empty.
    """
    rows: list[tuple[str, Text]] = []
    next_number = 1
    for label, names in groups:
        if not names:
            continue
        rows.append(
            (
                label,
                _numbered_chips(
                    names,
                    start=next_number,
                    focused_number=focused_number,
                    accent=accent,
                    shortcut_prefix=shortcut_prefix,
                ),
            )
        )
        next_number += len(names)
    if not rows:
        return None
    grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    for label, chips in rows:
        grid.add_row(Text(label, style=_COLOR_LABEL), chips)
    return grid


def _numbered_chips(
    names: tuple[str, ...],
    *,
    start: int,
    focused_number: int | None,
    accent: str,
    shortcut_prefix: str = "",
) -> Text:
    text = Text()
    for offset, name in enumerate(names):
        number = start + offset
        _append_chip(
            text,
            f"{shortcut_prefix}{number} {name}",
            accent=accent,
            focused=number == focused_number,
        )
    return text


def build_property_grid(
    entry: GlossaryEntry,
    *,
    project_name: str,
    source_display: str | None,
    effective_count: int,
    accent: str | None = None,
) -> RenderableType:
    """Build the aligned project/source/match metadata grid."""
    rows: list[tuple[str, str]] = []
    if project_name:
        rows.append(("Project", project_name))
    if source_display:
        rows.append(("Source", source_display))
    if effective_count > 0:
        rows.append(("Matches", _format_match_count(entry, effective_count)))

    grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    for label, value in rows:
        grid.add_row(
            Text(label, style=_COLOR_LABEL),
            Text(value, style=accent or ""),
        )
    return grid


def glossary_source_display(catalog: Any, entry: GlossaryEntry) -> str | None:
    """Return a displayable source path with an optional definition position."""
    path = glossary_source_path(catalog, entry)
    if path is None:
        return None
    line, col = glossary_definition_position(entry)
    if line is None:
        return path
    if col is None:
        return f"{path}:{line}"
    return f"{path}:{line}:{col}"


def glossary_source_path(catalog: Any, entry: GlossaryEntry) -> str | None:
    """Return the source path for a glossary entry, if resolvable."""
    source = glossary_source_from_wire(entry.source)
    if source is not None and source.source_path is not None:
        return source.source_path
    config_path = getattr(catalog, "config_path", None)
    return str(config_path) if config_path is not None else None


def glossary_definition_position(
    entry: GlossaryEntry,
) -> tuple[int | None, int | None]:
    """Return one-based definition line/column metadata for editor handoffs."""
    source = glossary_source_from_wire(entry.source)
    if source is None or source.body_range is None:
        return None, None
    start = source.body_range.get("start")
    if not isinstance(start, dict):
        return None, None
    line = start.get("line")
    character = start.get("character")
    out_line = int(line) + 1 if isinstance(line, int) and line >= 0 else None
    out_col = (
        int(character) + 1 if isinstance(character, int) and character >= 0 else None
    )
    return out_line, out_col


def glossary_cross_references(
    catalog: Any,
    entry: GlossaryEntry,
    *,
    spans: tuple[GlossarySpan, ...] | None = None,
) -> tuple[GlossaryEntry, ...]:
    """Return referenced glossary entries, authored links first, capped at nine.

    Entries the definition targets with an authored ``[[link]]`` come first (in
    first-link order) so deliberate links are never crowded out of the ``1-9``
    follow keys by incidental phrase matches; mention-only entries follow in
    first-mention order.
    """
    if spans is None and _definition_links(catalog, entry):
        spans = glossary_reference_spans(catalog, entry)
    closure = resolve_glossary_closure(
        _as_glossary_catalog(catalog),
        getattr(catalog, "compiled", None),
        (entry,),
        depth=1,
        precomputed_spans=None if spans is None else {entry.index: spans},
    )
    related = tuple(node.entry for node in closure.nodes if node.origin == "related")
    return _links_first(related, spans)[:9]


def _links_first(
    related: tuple[GlossaryEntry, ...],
    spans: tuple[GlossarySpan, ...] | None,
) -> tuple[GlossaryEntry, ...]:
    """Stable-partition *related* so link-targeted entries precede mention-only ones."""
    if not spans:
        return related
    by_index = {entry.index: entry for entry in related}
    linked: list[GlossaryEntry] = []
    for span in sorted(spans, key=lambda item: (item.byte_start, item.byte_end)):
        if span.kind != "link":
            continue
        target = by_index.get(span.entry_index)
        if target is not None and target not in linked:
            linked.append(target)
    if not linked:
        return related
    return (*linked, *(entry for entry in related if entry not in linked))


def glossary_definition_markdown(
    catalog: Any,
    entry: GlossaryEntry,
    *,
    spans: tuple[GlossarySpan, ...] | None = None,
) -> str:
    """Return definition Markdown with non-self glossary references linked.

    Authored ``[[target]]`` links that resolve to a glossary term render as
    followable links labelled with the target's term; a link back to *entry*
    itself renders as plain term text.
    """
    definition = entry.definition.strip()
    if not definition:
        return "_No definition provided._"

    entries_by_index = {candidate.index: candidate for candidate in catalog.entries}
    pieces: list[str] = []
    cursor = 0
    reference_spans = (
        spans if spans is not None else glossary_reference_spans(catalog, entry)
    )
    for span in reference_spans:
        is_link = span.kind == "link"
        target = entries_by_index.get(span.entry_index)
        if target is None or (span.entry_index == entry.index and not is_link):
            continue
        start = _char_offset_from_byte(definition, span.byte_start)
        end = _char_offset_from_byte(definition, span.byte_end)
        if start is None or end is None or start < cursor or end <= start:
            continue
        pieces.append(definition[cursor:start])
        label = _escape_markdown_link_text(
            _normalize_matched_text(target.term if is_link else definition[start:end])
        )
        if span.entry_index == entry.index:
            pieces.append(label)
        else:
            pieces.append(f"[{label}](glossary:{quote(str(target.index))})")
        cursor = end
    if not pieces:
        return definition
    pieces.append(definition[cursor:])
    return "".join(pieces)


def glossary_reference_spans(
    catalog: Any,
    entry: GlossaryEntry,
) -> tuple[GlossarySpan, ...]:
    """Return a definition's mention and authored-link spans, ordered by position.

    Phrase mentions overlapping any authored ``[[link]]`` are dropped, whether
    the link resolves, leaves the glossary, or is unresolved: text inside link
    brackets is never hyperlinked or counted as a mention. Links that resolve to
    a glossary term become synthetic ``kind="link"`` spans. The mention scan
    degrades to no spans on failure.
    """
    try:
        mentions = scan_glossary_spans(catalog.compiled, entry.definition.strip())
    except Exception:
        mentions = ()
    links = _definition_links(catalog, entry)
    if not links:
        return mentions

    term_by_index = {candidate.index: candidate.term for candidate in catalog.entries}
    kept = tuple(
        span
        for span in mentions
        if not any(
            span.byte_start < link.byte_end and span.byte_end > link.byte_start
            for link in links
        )
    )
    link_spans = tuple(
        GlossarySpan(
            term=term_by_index[link.target_index],
            entry_index=link.target_index,
            alias_index=-1,
            alias="",
            matched_text=link.raw,
            byte_start=link.byte_start,
            byte_end=link.byte_end,
            range={},
            segments=(),
            kind="link",
        )
        for link in links
        if link.target_index is not None and link.target_index in term_by_index
    )
    return tuple(
        sorted(
            (*kept, *link_spans),
            key=lambda span: (span.byte_start, span.byte_end),
        )
    )


def _definition_links(catalog: Any, entry: GlossaryEntry) -> tuple[Any, ...]:
    """Return *entry*'s pre-resolved authored links, tolerating bare catalogs."""
    return tuple(
        (getattr(catalog, "definition_links", None) or {}).get(entry.index, ())
    )


def _as_glossary_catalog(catalog: Any) -> GlossaryCatalog:
    inner = getattr(catalog, "catalog", None)
    if isinstance(inner, GlossaryCatalog):
        return inner
    if isinstance(catalog, GlossaryCatalog):
        return catalog
    return GlossaryCatalog(
        schema_version=int(getattr(catalog, "schema_version", 1) or 1),
        entries=tuple(getattr(catalog, "entries", ())),
    )


def _append_chip(text: Text, label: str, *, accent: str, focused: bool = False) -> None:
    if text.plain:
        text.append(" ")
    style = (
        f"bold {accent} on {_PILL_FOREGROUND}"
        if focused
        else f"bold {_PILL_FOREGROUND} on {accent}"
    )
    text.append(f" {label} ", style=style)


def _format_match_count(entry: GlossaryEntry, effective_count: int) -> str:
    forms = "form" if effective_count == 1 else "forms"
    alias_count = max(0, effective_count - 1)
    if alias_count == 0:
        detail = "term"
    else:
        aliases = "alias" if alias_count == 1 else "aliases"
        detail = f"term, {alias_count} {aliases}"
    return f"{effective_count} {forms} ({detail})"


def _should_show_matched_text(
    entry: GlossaryEntry,
    matched_text: str | None,
) -> bool:
    if not matched_text:
        return False
    return _normalize_matched_text(matched_text).casefold() != (
        _normalize_matched_text(entry.term).casefold()
    )


def _normalize_matched_text(value: str | None) -> str:
    return " ".join(str(value or "").split())


def _char_offset_from_byte(text: str, byte_offset: int) -> int | None:
    try:
        return len(text.encode("utf-8")[:byte_offset].decode("utf-8"))
    except UnicodeDecodeError:
        return None


def _escape_markdown_link_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


__all__ = [
    "build_alias_chips",
    "build_glossary_title",
    "build_numbered_chip_rows",
    "build_property_grid",
    "build_see_also_chips",
    "glossary_card_accent",
    "glossary_cross_references",
    "glossary_definition_markdown",
    "glossary_definition_position",
    "glossary_reference_spans",
    "glossary_source_display",
    "glossary_source_path",
]
