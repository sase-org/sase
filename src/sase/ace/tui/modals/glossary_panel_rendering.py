"""Pure render helpers for the Glossary panel shell.

Term-list rows, the header/footer strips, and empty/error states are built
here. The definition card itself is assembled from the shared
``glossary_preview_render`` helpers so it can never drift from
:class:`~sase.ace.tui.modals.glossary_preview_modal.GlossaryPreviewModal`.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.ace.tui.keymaps.app_keymaps import GlossaryPanelKeymaps
from sase.ace.tui.keymaps.display import key_display_name
from sase.ace.tui.modals.glossary_preview_render import (
    build_alias_chips,
    build_glossary_title,
    build_property_grid,
    glossary_source_display,
)
from sase.core.glossary_facade import GlossaryEntry
from sase.xprompt.glossary_catalog import EditorGlossaryCatalog

_COLOR_LABEL = "dim"


def sorted_glossary_entries(
    catalog: EditorGlossaryCatalog | None,
) -> tuple[GlossaryEntry, ...]:
    """Return *catalog*'s entries in alphabetical term order."""
    if catalog is None:
        return ()
    return tuple(
        sorted(catalog.entries, key=lambda entry: (entry.term.casefold(), entry.term))
    )


def build_panel_header(
    *,
    project_display_name: str,
    term_count: int,
    project_index: int,
    project_count: int,
    accent: str,
) -> RenderableType:
    """Build the ``GLOSSARY · project · N terms · project i/N`` header line."""
    text = Text()
    text.append("GLOSSARY", style=f"bold {accent}")
    if project_display_name:
        text.append("  ·  ")
        text.append(project_display_name, style="bold")
    term_word = "term" if term_count == 1 else "terms"
    text.append(f"  ·  {term_count} {term_word}", style="dim")
    if project_count > 0:
        text.append(f"  ·  project {project_index + 1}/{project_count}", style="dim")
    return text


def build_term_row_text(entry: GlossaryEntry) -> Text:
    """Build one term-list row: the term plus a dim alias summary."""
    text = Text()
    text.append(entry.term)
    if entry.display_aliases:
        text.append("  ")
        text.append(" · ".join(entry.display_aliases), style="dim")
    return text


def build_definition_card_meta(
    catalog: EditorGlossaryCatalog,
    entry: GlossaryEntry,
    *,
    project_name: str,
    accent: str,
) -> RenderableType:
    """Build the alias chips and property grid below the definition body."""
    sections: list[RenderableType] = []
    alias_chips = build_alias_chips(entry.display_aliases, accent=accent)
    if alias_chips is not None:
        grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1, overflow="fold")
        grid.add_row(Text("ALSO KNOWN AS", style=_COLOR_LABEL), alias_chips)
        sections.append(grid)

    sections.append(Text("-" * 44, style="dim"))
    sections.append(
        build_property_grid(
            entry,
            project_name=project_name,
            source_display=glossary_source_display(catalog, entry),
            effective_count=len(entry.effective_aliases),
            accent=accent,
        )
    )
    return Group(*sections)


def build_definition_card_title(
    entry: GlossaryEntry,
    *,
    project_name: str,
    accent: str,
) -> RenderableType:
    """Build the definition card's title line."""
    return build_glossary_title(
        entry,
        matched_text=None,
        project_name=project_name,
        accent=accent,
    )


def build_empty_project_message(project_display_name: str, *, accent: str) -> Text:
    """Build the centered invitation shown for a project with no glossary."""
    text = Text(justify="center")
    text.append(f"{project_display_name} has no glossary terms yet.\n\n", style="bold")
    text.append("Press ", style="dim")
    text.append("a", style=f"bold {accent}")
    text.append(" to add the first one.", style="dim")
    return text


def build_diagnostics_message(
    diagnostics: tuple[str, ...], *, accent: str
) -> RenderableType:
    """Build the error state shown for a project whose glossary failed to load."""
    text = Text(justify="left")
    text.append("Glossary failed to load:\n\n", style=f"bold {accent}")
    for index, diagnostic in enumerate(diagnostics):
        if index:
            text.append("\n")
        text.append(diagnostic, style="dim")
    return text


def build_no_match_message(pattern: str) -> Text:
    """Build the message shown when a filter pattern matches no terms."""
    return Text(f"no terms matched: {pattern}", style="dim")


def build_panel_footer(
    keymaps: GlossaryPanelKeymaps,
    *,
    has_entries: bool,
    has_source_path: bool,
    ring_size: int,
) -> str:
    """Build the footer strip, showing only currently-conditional keymaps."""
    parts = [
        f"{key_display_name(keymaps.next_term)}/{key_display_name(keymaps.prev_term)} term",
        f"{key_display_name(keymaps.filter_terms)} filter",
    ]
    if ring_size > 1:
        parts.append(
            f"{key_display_name(keymaps.next_project)}/"
            f"{key_display_name(keymaps.prev_project)} project"
        )
    if has_entries:
        parts.append(f"{key_display_name(keymaps.copy_definition)} copy")
    if has_source_path:
        parts.append(f"{key_display_name(keymaps.open_source)} edit")
        parts.append(f"{key_display_name(keymaps.open_viewer)} view")
    parts.append(f"{key_display_name(keymaps.refresh)} refresh")
    parts.append(f"{key_display_name(keymaps.help)} help")
    parts.append("esc close")
    return "  ·  ".join(parts)


__all__ = [
    "build_definition_card_meta",
    "build_definition_card_title",
    "build_diagnostics_message",
    "build_empty_project_message",
    "build_no_match_message",
    "build_panel_footer",
    "build_panel_header",
    "build_term_row_text",
    "sorted_glossary_entries",
]
