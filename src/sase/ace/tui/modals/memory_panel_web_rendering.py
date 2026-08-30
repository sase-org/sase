"""Web and strand metadata renderers for the Memory panel."""

from __future__ import annotations

from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text

from sase.ace.tui.memory_panel_catalog import (
    MemoryRailNode,
    MemoryScopeSnapshot,
    memory_rail_node_label,
    memory_rail_node_relations,
)
from sase.memory.notes import MemoryNote
from sase.notifications.models import format_relative_time

from .glossary_preview_render import build_numbered_chip_rows
from .memory_panel_rendering import (
    append_badge,
    build_note_badge_row,
    build_note_card_meta,
    build_property_grid,
    iso_from_mtime_ns,
    memory_note_source_path,
)
from .numbered_link_keys import NUMBERED_LINK_CHIP_PREFIX


def build_rail_node_card_meta(
    snapshot: MemoryScopeSnapshot,
    node: MemoryRailNode,
    *,
    accent: str,
    parent: tuple[MemoryNote, ...] | None = None,
    children: tuple[MemoryNote, ...] | None = None,
    focused_link_number: int | None = None,
    strand_read_state: str | None = None,
) -> RenderableType:
    """Build metadata for a note, web, or strand row."""
    if node.strand is None and node.web is None:
        return build_note_card_meta(
            snapshot,
            node.note,
            accent=accent,
            parent=parent,
            children=children,
            focused_link_number=focused_link_number,
        )
    if parent is None or children is None:
        parent, children = memory_rail_node_relations(snapshot, node)
    sections: list[RenderableType] = []
    badges = build_note_badge_row(
        snapshot, node.note, accent=accent, include_type=False
    )
    if badges is not None:
        sections.append(badges)
    extra_badges = _build_web_or_strand_badges(node, strand_read_state, accent=accent)
    if extra_badges is not None:
        sections.append(extra_badges)
    has_strand_relations = (
        node.strand is not None
        and node.web is not None
        and node.web.link_reference == "implicit"
    )
    first_label = "SEE ALSO" if has_strand_relations else "PARENT"
    second_label = "REFERENCED BY" if has_strand_relations else "CHILDREN"
    chip_rows = build_numbered_chip_rows(
        (
            (
                first_label,
                tuple(memory_rail_node_label(snapshot, item) for item in parent),
            ),
            (
                second_label,
                tuple(memory_rail_node_label(snapshot, item) for item in children),
            ),
        ),
        focused_number=focused_link_number,
        accent=accent,
        shortcut_prefix=NUMBERED_LINK_CHIP_PREFIX,
    )
    if chip_rows is not None:
        sections.append(chip_rows)
    sections.append(Text("-" * 44, style="dim"))
    if node.strand is not None and node.web is not None:
        sections.append(_build_strand_property_grid(snapshot, node, accent=accent))
    elif node.web is not None:
        sections.append(_build_web_property_grid(snapshot, node, accent=accent))
    return Group(*sections)


def _build_web_or_strand_badges(
    node: MemoryRailNode, strand_read_state: str | None, *, accent: str
) -> Text | None:
    badges: list[str] = []
    if node.strand is not None:
        badges.append("STRAND")
        if strand_read_state == "ok":
            badges.append("AUDITED")
        elif strand_read_state == "pending":
            badges.append("AUDITING")
        elif strand_read_state:
            badges.append("AUDIT FAILED")
    elif node.web is not None:
        badges.append("WEB")
        badges.append("EXPANDED" if node.expanded else "COLLAPSED")
    if not badges:
        return None
    text = Text()
    for badge in badges:
        append_badge(text, badge, accent=accent)
    return text


def _build_web_property_grid(
    snapshot: MemoryScopeSnapshot, node: MemoryRailNode, *, accent: str
) -> RenderableType:
    web = node.web
    assert web is not None
    strand_word = web.strand_noun if len(web.strands) == 1 else f"{web.strand_noun}s"
    rows = [
        ("Strands", f"{len(web.strands)} {strand_word}"),
        ("Roster", web.roster),
        ("Closure", web.closure),
    ]
    _append_file_rows(snapshot, node.note, rows)
    rows.append(("Source", memory_note_source_path(snapshot.scope, node.note)))
    return build_property_grid(rows, accent=accent)


def _build_strand_property_grid(
    snapshot: MemoryScopeSnapshot, node: MemoryRailNode, *, accent: str
) -> RenderableType:
    strand = node.strand
    web = node.web
    assert strand is not None and web is not None
    rows = [
        ("Web", web.slug),
        ("Keyword", strand.keyword),
        ("Slug", strand.slug),
        ("Scope", node.strand_scope or snapshot.scope.kind),
    ]
    if strand.aliases:
        rows.append(("Aliases", " · ".join(strand.aliases)))
    if strand.summary:
        rows.append(("Summary", strand.summary))
    if strand.metadata:
        rows.append(("Metadata", _metadata_value(strand.metadata)))
    _append_file_rows(snapshot, node.note, rows)
    rows.append(("Source", memory_note_source_path(snapshot.scope, node.note)))
    return build_property_grid(rows, accent=accent)


def _append_file_rows(
    snapshot: MemoryScopeSnapshot, note: MemoryNote, rows: list[tuple[str, str]]
) -> None:
    stats = snapshot.stats.get(note.relative_path)
    digest = snapshot.digests.get(note.relative_path)
    read_summary = snapshot.read_summaries.get(note.relative_path)
    if stats is not None:
        line_word = "line" if stats.line_count == 1 else "lines"
        rows.append(
            (
                "Size",
                f"{stats.line_count} {line_word}, ~{stats.approx_token_count} tokens",
            )
        )
    if digest is not None:
        rows.append(
            ("Last modified", format_relative_time(iso_from_mtime_ns(digest.mtime_ns)))
        )
    if read_summary is not None:
        rows.append(
            (
                "Last audited read",
                f"{read_summary.last_agent} · {read_summary.last_reason} · "
                f"{format_relative_time(read_summary.last_read_at)}",
            )
        )


def _metadata_value(metadata: dict[str, Any]) -> str:
    return "; ".join(f"{key}: {metadata[key]}" for key in sorted(metadata))


__all__ = ["build_rail_node_card_meta"]
