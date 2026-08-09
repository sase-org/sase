"""Purpose-built glossary definition preview modal."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.core.glossary_facade import GlossaryEntry
from sase.xprompt.glossary_catalog import EditorGlossaryCatalog

from ._source_file_actions import SourceFileActionsMixin
from .base import CopyModeForwardingMixin
from .glossary_preview_render import (
    build_alias_chips,
    build_glossary_title,
    build_property_grid,
    build_see_also_chips,
    glossary_card_accent,
    glossary_cross_references,
    glossary_definition_markdown,
    glossary_definition_position,
    glossary_reference_spans,
    glossary_source_display,
    glossary_source_path,
)

_COLOR_LABEL = "dim"


class GlossaryPreviewModal(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    ModalScreen[None],
):
    """Display one glossary entry as a structured definition card."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("y", "copy_definition", "Copy definition"),
        ("Y", "copy_path", "Copy path"),
        ("shift+y", "copy_path", "Copy path"),
        ("o", "open_in_editor", "Open in editor"),
        ("Z", "open_in_viewer", "Open in viewer"),
        ("shift+z", "open_in_viewer", "Open in viewer"),
        ("backspace", "go_back", "Back"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("j", "scroll_line_down", "Line down"),
        ("k", "scroll_line_up", "Line up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("shift+g", "scroll_bottom", "Bottom"),
        *(
            (str(index), f"follow_reference({index})", f"See also {index}")
            for index in range(1, 10)
        ),
    ]

    def __init__(
        self,
        catalog: EditorGlossaryCatalog,
        entry: GlossaryEntry,
        *,
        matched_text: str | None,
    ) -> None:
        super().__init__()
        self._catalog = catalog
        self._history: list[GlossaryEntry] = []
        self._accent = "#87D7FF"
        self._entry = entry
        self._matched_text = matched_text
        self._references: tuple[GlossaryEntry, ...] = ()
        self._definition_content = ""
        self._set_entry(entry, matched_text=matched_text)

    def compose(self) -> ComposeResult:
        self._accent = glossary_card_accent(self.app.current_theme)
        with Container(id="glossary-preview-container"):
            yield Static(self._build_title(), id="glossary-preview-title")
            with VerticalScroll(id="glossary-preview-scroll"):
                yield Markdown(
                    self._definition_markdown(),
                    id="glossary-preview-definition",
                )
                yield Static(self._build_meta(), id="glossary-preview-meta")
            yield Static(self._build_footer(), id="glossary-preview-footer")

    def action_close(self) -> None:
        self.dismiss(None)

    async def action_follow_reference(self, number: int) -> None:
        index = number - 1
        if index < 0 or index >= len(self._references):
            return
        self._history.append(self._entry)
        self._set_entry(self._references[index], matched_text=None)
        await self._refresh_widgets(reset_scroll=True)

    async def action_go_back(self) -> None:
        if not self._history:
            return
        self._set_entry(self._history.pop(), matched_text=None)
        await self._refresh_widgets(reset_scroll=True)

    def action_copy_definition(self) -> None:
        schedule_copy_delivery(
            self,
            self._entry.definition.strip(),
            copied_label="glossary definition",
            task_name="sase-glossary-preview-copy-definition",
        )

    def _source_action_path(self) -> str | None:
        return glossary_source_path(self._catalog, self._entry)

    def _source_action_position(self) -> tuple[int | None, int | None]:
        return glossary_definition_position(self._entry)

    def _build_title(self) -> RenderableType:
        return build_glossary_title(
            self._entry,
            matched_text=self._matched_text,
            project_name=self._project_name(),
            accent=self._accent,
        )

    def _definition_markdown(self) -> str:
        return self._definition_content

    def _set_entry(
        self,
        entry: GlossaryEntry,
        *,
        matched_text: str | None,
    ) -> None:
        spans = glossary_reference_spans(self._catalog, entry)
        self._entry = entry
        self._matched_text = matched_text
        self._references = glossary_cross_references(
            self._catalog,
            entry,
            spans=spans,
        )
        self._definition_content = glossary_definition_markdown(
            self._catalog,
            entry,
            spans=spans,
        )

    def _build_meta(self) -> RenderableType:
        sections: list[RenderableType] = []
        chip_rows = self._build_chip_rows()
        if chip_rows is not None:
            sections.append(chip_rows)

        property_grid = build_property_grid(
            self._entry,
            project_name=self._project_name(),
            source_display=glossary_source_display(self._catalog, self._entry),
            effective_count=len(self._entry.effective_aliases),
            accent=self._accent,
        )
        sections.append(Text("-" * 66, style="dim"))
        sections.append(property_grid)
        return Group(*sections)

    def _build_chip_rows(self) -> RenderableType | None:
        rows: list[tuple[str, Text]] = []
        alias_chips = build_alias_chips(
            self._entry.display_aliases, accent=self._accent
        )
        if alias_chips is not None:
            rows.append(("ALSO KNOWN AS", alias_chips))
        see_also_chips = build_see_also_chips(self._references, accent=self._accent)
        if see_also_chips is not None:
            rows.append(("SEE ALSO", see_also_chips))
        if not rows:
            return None

        grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1, overflow="fold")
        for label, chips in rows:
            grid.add_row(Text(label, style=_COLOR_LABEL), chips)
        return grid

    def _build_footer(self) -> str:
        parts = ["j/k"]
        if self._references:
            parts.append("1-9 see also")
        if self._history:
            parts.append("backspace")
        parts.append("y def")
        if self._source_action_path():
            parts.extend(("Y path", "o edit", "Z view"))
        parts.append("esc")
        return " | ".join(parts)

    async def _refresh_widgets(self, *, reset_scroll: bool) -> None:
        if not self.is_attached:
            return
        self.query_one("#glossary-preview-title", Static).update(self._build_title())
        definition = self.query_one("#glossary-preview-definition", Markdown)
        await definition.update(self._definition_markdown())
        self.query_one("#glossary-preview-meta", Static).update(self._build_meta())
        self.query_one("#glossary-preview-footer", Static).update(self._build_footer())
        if reset_scroll:
            self.query_one("#glossary-preview-scroll", VerticalScroll).scroll_home(
                animate=False
            )

    def _project_name(self) -> str:
        return (
            getattr(self._catalog.project, "name", None)
            or getattr(self._catalog.project, "key", "")
            or ""
        )

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#glossary-preview-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=height, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#glossary-preview-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=-height, animate=False)

    def action_scroll_line_down(self) -> None:
        scroll = self.query_one("#glossary-preview-scroll", VerticalScroll)
        scroll.scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        scroll = self.query_one("#glossary-preview-scroll", VerticalScroll)
        scroll.scroll_relative(y=-1, animate=False)

    def action_scroll_top(self) -> None:
        scroll = self.query_one("#glossary-preview-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        scroll = self.query_one("#glossary-preview-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)


__all__ = ["GlossaryPreviewModal"]
