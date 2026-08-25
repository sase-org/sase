"""Pure render helpers for the Snippets panel shell.

Trigger-list rows, the header/footer strips, raw-template syntax accents,
the composed preview, and empty/error states are built here. Nothing in
this module touches the filesystem or a mounted widget.
"""

from __future__ import annotations

import re
from typing import Any

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.ace.tui.keymaps.app_keymaps import SnippetPanelKeymaps
from sase.ace.tui.keymaps.display import key_display_name
from sase.core.snippet_catalog_facade import SnippetCall
from sase.snippet.models import SnippetCatalog, SnippetEntry, SnippetSourceKind
from sase.xprompt.highlight_theme import derive_argument_color

from .glossary_preview_render import build_alias_chips, build_numbered_chip_rows
from .trail_strip import build_trail_strip

_COLOR_LABEL = "dim"
_COLOR_TITLE = "bold"
_BADGE_FOREGROUND = "#1a1a1a"
_FALLBACK_ACCENT = "#87D7FF"
_DIAGNOSTIC_CHIP = "#808080"

_TABSTOP_RE = re.compile(r"\$\{\d+\}|\$\d+")

_KIND_LABEL: dict[SnippetSourceKind, str] = {
    "xprompt": "xp",
    "default": "def",
    "plugin": "plug",
    "user": "cfg",
    "overlay": "ov",
    "project": "cfg",
    "configured": "cfg",
    "pending": "pend",
}

# The trigger rail is sized to fit its widest row. Chrome is everything in
# ``#snippets-panel-triggers`` that is not text: the 1-cell ``solid`` border
# on each side, ``OptionList``'s default ``padding: 0 1``, and the 2-cell
# vertical scrollbar held open by ``scrollbar-gutter: stable``.
_TRIGGER_RAIL_CHROME = 6
# Never narrower than the Glossary rail's historical fixed width, and never
# wide enough to crowd the preview card. Mirrored by the ``min-width`` /
# ``max-width`` backstops on ``#snippets-panel-triggers`` in ``styles.tcss``.
_TRIGGER_RAIL_MIN_WIDTH = 32
_TRIGGER_RAIL_MAX_WIDTH = 52
# Cells the preview card keeps for itself, chrome included; 56 leaves it
# ~50 columns of template text.
_TRIGGER_RAIL_DETAIL_RESERVED = 56

_COMPOSED_PREVIEW_MAX_LINES = 12
_COMPOSED_PREVIEW_MAX_CHARS = 400


def snippet_card_accent(theme: Any) -> str:
    """Return the theme-derived accent used by the Snippets panel."""
    background = getattr(theme, "background", None) or "#000000"
    accent = derive_argument_color(
        getattr(theme, "primary", None),
        foreground=getattr(theme, "foreground", None),
        background=background,
    )
    return accent or _FALLBACK_ACCENT


def sorted_snippet_entries(
    catalog: SnippetCatalog | None,
) -> tuple[SnippetEntry, ...]:
    """Return *catalog*'s explicit entries in alphabetical trigger order."""
    if catalog is None:
        return ()
    return tuple(
        sorted(
            catalog.entries,
            key=lambda entry: (entry.trigger.casefold(), entry.trigger),
        )
    )


def canonical_snippet_trigger(
    catalog: SnippetCatalog | None, reference: str | None
) -> str | None:
    """Resolve *reference* to an explicit trigger when it is an alias."""
    if reference is None or catalog is None:
        return reference
    if catalog.entry_for(reference) is not None:
        return reference
    source = catalog.alias_provenance.get(reference)
    if source is not None:
        return source
    for entry in catalog.entries:
        if reference in entry.aliases:
            return entry.trigger
    return reference


def build_panel_header(
    *,
    project_display_name: str,
    snippet_count: int,
    project_index: int,
    project_count: int,
    accent: str,
    include_bodies: bool = False,
) -> RenderableType:
    """Build the ``SNIPPETS · project · N snippets · project i/N`` header."""
    text = Text()
    text.append("SNIPPETS", style=f"bold {accent}")
    if project_display_name:
        text.append("  ·  ")
        text.append(project_display_name, style="bold")
    word = "snippet" if snippet_count == 1 else "snippets"
    text.append(f"  ·  {snippet_count} {word}", style="dim")
    if project_count > 0:
        text.append(f"  ·  project {project_index + 1}/{project_count}", style="dim")
    if include_bodies:
        text.append("  ·  bodies", style="dim")
    return text


def build_trigger_row_text(entry: SnippetEntry) -> Text:
    """Build one rail row: trigger, dim aliases, source/read-only/link marks."""
    text = Text()
    text.append(entry.trigger)
    if entry.aliases:
        text.append("  ")
        text.append(" · ".join(entry.aliases), style="dim")
    badges: list[str] = [_KIND_LABEL.get(entry.origin.kind, entry.origin.kind)]
    if not entry.origin.writable:
        badges.append("ro")
    if entry.relations.outbound:
        badges.append("→")
    if entry.relations.inbound:
        badges.append("←")
    text.append("  ")
    text.append(" ".join(badges), style="dim")
    return text


def trigger_rail_width(
    entries: tuple[SnippetEntry, ...], *, available_width: int
) -> int:
    """Return the width ``#snippets-panel-triggers`` should take."""
    if not entries:
        return _TRIGGER_RAIL_MIN_WIDTH
    widest = max(build_trigger_row_text(entry).cell_len for entry in entries)
    desired = widest + _TRIGGER_RAIL_CHROME
    cap = _TRIGGER_RAIL_MAX_WIDTH
    if available_width > 0:
        room = available_width - _TRIGGER_RAIL_DETAIL_RESERVED - 1
        cap = min(cap, max(_TRIGGER_RAIL_MIN_WIDTH, room))
    return max(_TRIGGER_RAIL_MIN_WIDTH, min(cap, desired))


def _highlight_raw_template(
    template: str,
    calls: tuple[SnippetCall, ...],
    *,
    accent: str,
) -> Text:
    """Render *template* with tabstop and ``#[...]`` call-site accents.

    The raw template is never interpreted as Markdown. Call spans use the
    shared Rust byte offsets; missing and cyclic calls render in a warning
    style so they stay visible without looking followable.
    """
    marks: list[tuple[int, int, str]] = []
    for call in calls:
        start = _char_offset(template, call.span.start)
        end = _char_offset(template, call.span.end)
        if start is None or end is None or end <= start:
            continue
        kind = "call-ok" if call.status == "resolved" else "call-bad"
        marks.append((start, end, kind))
    for match in _TABSTOP_RE.finditer(template):
        marks.append((match.start(), match.end(), "tabstop"))
    marks.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    accepted: list[tuple[int, int, str]] = []
    cursor = 0
    for start, end, kind in marks:
        if start < cursor:
            continue
        accepted.append((start, end, kind))
        cursor = end

    styles = {
        "tabstop": f"bold {accent}",
        "call-ok": f"bold underline {accent}",
        "call-bad": "bold underline red",
    }
    text = Text()
    pos = 0
    for start, end, kind in accepted:
        if start > pos:
            text.append(template[pos:start])
        text.append(template[start:end], style=styles[kind])
        pos = end
    if pos < len(template):
        text.append(template[pos:])
    elif not template:
        text.append("∅", style="dim")
    return text


def _bound_composed_preview(
    template: str,
    *,
    max_lines: int = _COMPOSED_PREVIEW_MAX_LINES,
    max_chars: int = _COMPOSED_PREVIEW_MAX_CHARS,
) -> str:
    """Return a bounded composed-template preview, eliding the tail."""
    lines = template.splitlines()
    truncated_lines = len(lines) > max_lines
    if truncated_lines:
        lines = lines[:max_lines]
    joined = "\n".join(lines) if lines else template
    if len(joined) > max_chars:
        return joined[: max(0, max_chars - 1)].rstrip() + "…"
    if truncated_lines:
        return joined.rstrip() + "\n…"
    return joined


def build_raw_section(entry: SnippetEntry, *, accent: str) -> RenderableType:
    """Build the labeled raw-template block."""
    return Group(
        Text("RAW", style=f"bold {accent}"),
        _highlight_raw_template(
            entry.raw_template, entry.relations.calls, accent=accent
        ),
    )


def build_composed_section(entry: SnippetEntry, *, accent: str) -> RenderableType:
    """Build the labeled, bounded composed-preview block."""
    preview = _bound_composed_preview(entry.composed_template)
    body = Text(preview) if preview else Text("∅", style="dim")
    return Group(Text("COMPOSED", style=f"bold {accent}"), body)


def build_snippet_card_title(
    entry: SnippetEntry,
    *,
    project_name: str,
    accent: str,
) -> RenderableType:
    """Build the card title with origin badges and the project name."""
    identity = Text()
    identity.append("S", style=f"bold {accent}")
    identity.append(" ")
    identity.append("SNIPPET", style=f"bold {accent}")
    identity.append("  ")
    identity.append(entry.trigger, style=_COLOR_TITLE)
    identity.append("  ")
    identity.append(
        _KIND_LABEL.get(entry.origin.kind, entry.origin.kind),
        style="dim",
    )
    if not entry.origin.writable:
        identity.append("  ")
        identity.append("read-only", style="dim")

    if not project_name:
        return identity
    first_line = Table.grid(expand=True, padding=(0, 0, 0, 2))
    first_line.add_column(ratio=1, overflow="ellipsis")
    first_line.add_column(justify="right", no_wrap=True)
    first_line.add_row(identity, Text(project_name, style=f"bold {accent}"))
    return first_line


def _snippet_call_diagnostics(entry: SnippetEntry) -> tuple[str, ...]:
    """Return unique missing/cycle labels that must not be followable chips."""
    labels: list[str] = []
    seen: set[str] = set()
    for call in entry.relations.calls:
        if call.status == "resolved":
            continue
        label = f"{call.status}: {call.authored_target}"
        if label in seen:
            continue
        seen.add(label)
        labels.append(label)
    for diagnostic in entry.diagnostics:
        message = diagnostic.message
        if message in seen:
            continue
        seen.add(message)
        labels.append(message)
    return tuple(labels)


def build_snippet_card_meta(
    entry: SnippetEntry,
    *,
    project_name: str,
    accent: str,
    outbound: tuple[SnippetEntry, ...] = (),
    inbound: tuple[SnippetEntry, ...] = (),
    focused_relation_number: int | None = None,
    layer_diagnostics: tuple[str, ...] = (),
) -> RenderableType:
    """Build chips, diagnostics, source stack, and the property grid."""
    sections: list[RenderableType] = []
    alias_chips = build_alias_chips(entry.aliases, accent=accent)
    if alias_chips is not None:
        grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1, overflow="fold")
        grid.add_row(Text("ALIASES", style=_COLOR_LABEL), alias_chips)
        sections.append(grid)

    relation_rows = build_numbered_chip_rows(
        (
            ("CALLS", tuple(item.trigger for item in outbound)),
            ("CALLED BY", tuple(item.trigger for item in inbound)),
        ),
        focused_number=focused_relation_number,
        accent=accent,
    )
    if relation_rows is not None:
        sections.append(relation_rows)

    unresolved = _snippet_call_diagnostics(entry)
    if unresolved:
        sections.append(_labeled_dim_chips("UNRESOLVED", unresolved))

    if layer_diagnostics:
        sections.append(_diagnostics_block(layer_diagnostics, accent=accent))

    sections.append(Text("-" * 44, style="dim"))
    sections.append(_build_source_stack(entry, accent=accent))
    sections.append(_property_grid(entry, project_name=project_name, accent=accent))
    return Group(*sections)


def _build_source_stack(entry: SnippetEntry, *, accent: str) -> RenderableType:
    """Build the ordered source stack, winner first, shadowed copies below."""
    grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    rows = tuple(reversed(entry.contributions))
    for index, contribution in enumerate(rows):
        label = "SOURCE STACK" if index == 0 else ""
        kind = _KIND_LABEL.get(contribution.kind, contribution.kind)
        path = contribution.display_path or contribution.path or contribution.kind
        status = "effective" if contribution.shadowed_by is None else "shadowed"
        value = Text()
        value.append(kind, style=f"bold {accent}" if index == 0 else "dim")
        value.append("  ")
        value.append(path, style="" if index == 0 else "dim")
        value.append("  ")
        value.append(status, style="dim")
        grid.add_row(Text(label, style=_COLOR_LABEL), value)
    if not rows:
        grid.add_row(Text("SOURCE STACK", style=_COLOR_LABEL), Text("—", style="dim"))
    return grid


def build_empty_project_message(project_display_name: str, *, accent: str) -> Text:
    """Build the centered empty state for a project with no snippets."""
    text = Text(justify="center")
    text.append("No snippets in ", style="dim")
    text.append(project_display_name, style="bold")
    text.append(" yet.", style="dim")
    return text


def build_diagnostics_message(
    diagnostics: tuple[str, ...], *, accent: str
) -> RenderableType:
    """Build the error state shown when a project's snippets failed to load."""
    return _diagnostics_block(
        diagnostics, accent=accent, heading="Snippets failed to load:"
    )


def build_no_match_message(pattern: str) -> Text:
    """Build the message shown when a filter pattern matches no snippets."""
    return Text(f"no snippets matched: {pattern}", style="dim")


def build_panel_footer(
    keymaps: SnippetPanelKeymaps,
    *,
    has_entries: bool,
    has_source_path: bool,
    ring_size: int,
    has_relations: bool = False,
    has_trail: bool = False,
    focused_relation_trigger: str | None = None,
    can_mutate: bool = False,
) -> str:
    """Build the footer strip, showing only currently-conditional keymaps."""
    parts: list[str] = []
    if ring_size > 1:
        parts.append(
            f"{key_display_name(keymaps.next_project)}/"
            f"{key_display_name(keymaps.prev_project)} project"
        )
    if has_relations:
        parts.append(f"{key_display_name(keymaps.next_relation)} relation")
        parts.append(f"{key_display_name(keymaps.follow_relation)} follow")
        if focused_relation_trigger:
            parts.append(f"→ {focused_relation_trigger}")
    if has_trail:
        parts.append(f"{key_display_name(keymaps.travel_back)} back")
    if can_mutate:
        parts.append(f"{key_display_name(keymaps.edit_snippet)} edit")
        parts.append(f"{key_display_name(keymaps.delete_snippet)} delete")
    if has_entries:
        parts.append(f"{key_display_name(keymaps.copy_template)} copy")
    if has_source_path:
        parts.append(f"{key_display_name(keymaps.open_source)} source")
        parts.append(f"{key_display_name(keymaps.open_viewer)} view")
    return "  ·  ".join(parts)


def _property_grid(
    entry: SnippetEntry, *, project_name: str, accent: str
) -> RenderableType:
    rows: list[tuple[str, str]] = []
    if project_name:
        rows.append(("Project", project_name))
    rows.append(("Origin", entry.origin.kind))
    source = entry.origin.display_path or entry.origin.path
    if source:
        rows.append(("Source", source))
    if entry.origin.xprompt_name:
        rows.append(("Xprompt", entry.origin.xprompt_name))
    rows.append(("Writable", "yes" if entry.origin.writable else "no"))
    shadowed = tuple(
        item.kind for item in entry.contributions if item.shadowed_by is not None
    )
    if shadowed:
        rows.append(("Shadows", ", ".join(shadowed)))
    tabstops = tuple(_TABSTOP_RE.findall(entry.raw_template))
    if tabstops:
        rows.append(("Tabstops", " ".join(tabstops)))

    grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    for label, value in rows:
        grid.add_row(Text(label, style=_COLOR_LABEL), Text(value, style=accent or ""))
    return grid


def _labeled_dim_chips(label: str, names: tuple[str, ...]) -> RenderableType:
    chips = Text()
    for name in names:
        if chips.plain:
            chips.append(" ")
        chips.append(
            f" {name} ",
            style=f"bold {_BADGE_FOREGROUND} on {_DIAGNOSTIC_CHIP}",
        )
    grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    grid.add_row(Text(label, style=_COLOR_LABEL), chips)
    return grid


def _diagnostics_block(
    diagnostics: tuple[str, ...], *, accent: str, heading: str = "Diagnostics:"
) -> RenderableType:
    text = Text(justify="left")
    text.append(f"{heading}\n\n", style=f"bold {accent}")
    for index, diagnostic in enumerate(diagnostics):
        if index:
            text.append("\n")
        text.append(diagnostic, style="dim")
    return text


def _char_offset(text: str, byte_offset: int) -> int | None:
    try:
        return len(text.encode("utf-8")[:byte_offset].decode("utf-8"))
    except UnicodeDecodeError:
        return None


__all__ = [
    "build_composed_section",
    "build_diagnostics_message",
    "build_empty_project_message",
    "build_no_match_message",
    "build_panel_footer",
    "build_panel_header",
    "build_raw_section",
    "build_snippet_card_meta",
    "build_snippet_card_title",
    "build_trail_strip",
    "build_trigger_row_text",
    "canonical_snippet_trigger",
    "snippet_card_accent",
    "sorted_snippet_entries",
    "trigger_rail_width",
]
