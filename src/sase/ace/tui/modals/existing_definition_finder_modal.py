"""Shared fuzzy finder for existing macro and snippet definitions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.frontmatter_syntax import markdown_document_syntax
from sase.ace.tui.widgets._completion_match_highlight import append_highlighted

from .existing_definition_entries import (
    ExistingDefinitionEntry,
    ExistingKind,
    RankedExistingEntry,
    existing_entry_verdict,
    rank_existing_entries,
)

_VISIBLE_ROWS = 200
_MATCH_STYLE = "bold #FFD700"
_STATUS_STYLES = {
    "active": "bold #7DDA75",
    "shadowed": "bold #D7AF5F",
    "read_only": "bold #D7AF5F",
    "incompatible": "bold #FF6B6B",
}
_STATUS_LABELS = {
    "active": "● active",
    "shadowed": "◐ shadowed",
    "read_only": "🔒 read-only",
    "incompatible": "✗ incompatible",
}


@dataclass(frozen=True, slots=True)
class ExistingDefinitionPick:
    """The selected definition identity and last finder query."""

    entry_id: str
    query: str


@dataclass(frozen=True, slots=True)
class ExistingFinderBack:
    """Shift+Tab result carrying the query back to the location picker."""

    query: str


PreviewLoader = Callable[[str], str]


class _FinderInput(Input):
    """Filter field; navigation bindings are owned by the parent modal."""

    BINDINGS = [
        Binding("ctrl+f", "cursor_right", show=False),
        Binding("ctrl+b", "cursor_left", show=False),
    ]


class _FinderOptionList(OptionList):
    """OptionList that can select programmatically without posting an echo."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._programmatic_highlight = False

    def set_highlighted(self, index: int | None) -> None:
        self._programmatic_highlight = True
        try:
            self.highlighted = index
        finally:
            self._programmatic_highlight = False

    def watch_highlighted(self, highlighted: int | None) -> None:
        if self._programmatic_highlight:
            return
        super().watch_highlighted(highlighted)


class ExistingDefinitionFinderModal(
    ModalScreen[ExistingDefinitionPick | ExistingFinderBack | None]
):
    """Fuzzy filter, preview, and choose one physical existing definition."""

    BINDINGS = [
        Binding("escape", "cancel", priority=True, show=False),
        Binding("shift+tab", "go_back", priority=True, show=False),
        Binding("enter", "open_selected", priority=True, show=False),
        Binding("up", "cursor_prev", priority=True, show=False),
        Binding("down", "cursor_next", priority=True, show=False),
        Binding("ctrl+p", "cursor_prev", priority=True, show=False),
        Binding("ctrl+n", "cursor_next", priority=True, show=False),
        Binding("ctrl+u", "preview_up", priority=True, show=False),
        Binding("ctrl+d", "preview_down", priority=True, show=False),
    ]

    def __init__(
        self,
        kind: ExistingKind,
        entries: Sequence[ExistingDefinitionEntry],
        *,
        initial_query: str = "",
        preview_loader: PreviewLoader | None = None,
    ) -> None:
        super().__init__()
        self._kind = kind
        self._entries = tuple(entries)
        self._initial_query = initial_query
        self._preview_loader = preview_loader
        self._ranked: tuple[RankedExistingEntry, ...] = ()
        self._visible: tuple[RankedExistingEntry, ...] = ()
        self._selected_index: int | None = None
        self._debouncer: DetailPanelDebouncer | None = None
        self._preview_cache: dict[str, str] = {}
        self._preview_errors: set[str] = set()
        self._preview_generation = 0
        self._preview_tasks: set[asyncio.Task[None]] = set()

    def compose(self) -> ComposeResult:
        kind_label = "macro" if self._kind == "macro" else "snippet"
        with Container(id="existing-definition-finder-container"):
            with Horizontal(id="existing-definition-finder-heading"):
                yield Static(
                    f"✎ Edit existing {kind_label}", id="existing-finder-title"
                )
                yield Static("✓ Existing › ● Find", id="existing-finder-stepper")
            with Horizontal(id="existing-definition-finder-query-row"):
                yield Static("❯", id="existing-finder-query-prompt")
                yield _FinderInput(
                    value=self._initial_query,
                    placeholder="Type to filter definitions…",
                    id="existing-finder-query",
                )
                yield Static("0 / 0", id="existing-finder-counter")
            with Horizontal(id="existing-definition-finder-body"):
                with Vertical(id="existing-finder-matches-panel"):
                    yield Static("Matches", classes="existing-finder-panel-title")
                    yield _FinderOptionList(id="existing-finder-list")
                with Vertical(id="existing-finder-preview-panel"):
                    yield Static("Preview", classes="existing-finder-panel-title")
                    yield Static("", id="existing-finder-preview-title")
                    with VerticalScroll(id="existing-finder-preview-scroll"):
                        yield Static("", id="existing-finder-preview-body")
            yield Static("", id="existing-finder-verdict")
            yield Static(
                "↑↓ / ^n/^p move · enter open · ^d/^u scroll preview · ⇧tab locations · esc cancel",
                id="existing-finder-hints",
            )

    def on_mount(self) -> None:
        self._debouncer = DetailPanelDebouncer(self.app, delay_s=0.15)
        self.query_one("#existing-finder-query", _FinderInput).focus()
        self._refresh_matches()

    def on_unmount(self) -> None:
        if self._debouncer is not None:
            self._debouncer.cancel()
            self._debouncer = None
        self._preview_generation += 1
        for task in tuple(self._preview_tasks):
            task.cancel()
        self._preview_tasks.clear()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "existing-finder-query":
            self._refresh_matches()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "existing-finder-query":
            self.action_open_selected()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id != "existing-finder-list":
            return
        index = event.option_index
        if index is None or not 0 <= index < len(self._visible):
            return
        self._selected_index = index
        self.query_one("#existing-finder-query", _FinderInput).focus()
        self._refresh_verdict()
        self._schedule_preview()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "existing-finder-list":
            self._selected_index = event.option_index
            self.action_open_selected()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_go_back(self) -> None:
        self.dismiss(ExistingFinderBack(self._query()))

    def action_cursor_next(self) -> None:
        self._move_selection(1)

    def action_cursor_prev(self) -> None:
        self._move_selection(-1)

    def action_preview_down(self) -> None:
        self.query_one("#existing-finder-preview-scroll", VerticalScroll).scroll_down(
            animate=False
        )

    def action_preview_up(self) -> None:
        self.query_one("#existing-finder-preview-scroll", VerticalScroll).scroll_up(
            animate=False
        )

    def action_open_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        if entry.status == "incompatible":
            self._set_verdict(*existing_entry_verdict(entry))
            return
        self.dismiss(ExistingDefinitionPick(entry.entry_id, self._query()))

    def _query(self) -> str:
        return self.query_one("#existing-finder-query", _FinderInput).value

    def _selected_entry(self) -> ExistingDefinitionEntry | None:
        if self._selected_index is None:
            return None
        if not 0 <= self._selected_index < len(self._visible):
            return None
        return self._visible[self._selected_index].entry

    def _move_selection(self, direction: int) -> None:
        if not self._visible:
            return
        if self._selected_index is None:
            next_index = 0 if direction > 0 else len(self._visible) - 1
        else:
            next_index = (self._selected_index + direction) % len(self._visible)
        self._selected_index = next_index
        option_list = self.query_one("#existing-finder-list", _FinderOptionList)
        option_list.set_highlighted(next_index)
        self.query_one("#existing-finder-query", _FinderInput).focus()
        self._refresh_verdict()
        self._schedule_preview()

    def _refresh_matches(self) -> None:
        prior_entry = self._selected_entry()
        query = self._query()
        limit = max(1, len(self._entries))
        self._ranked = rank_existing_entries(self._entries, query, limit=limit)
        self._visible = self._ranked[:_VISIBLE_ROWS]
        prior_id = prior_entry.entry_id if prior_entry is not None else None
        self._selected_index = next(
            (
                index
                for index, ranked in enumerate(self._visible)
                if ranked.entry.entry_id == prior_id
            ),
            0 if self._visible else None,
        )
        option_list = self.query_one("#existing-finder-list", _FinderOptionList)
        option_list._programmatic_highlight = True
        try:
            option_list.clear_options()
            if self._visible:
                for index, ranked in enumerate(self._visible):
                    option_list.add_option(
                        Option(self._row_prompt(ranked), id=f"entry-row-{index}")
                    )
            else:
                option_list.add_option(
                    Option(Text(self._empty_message(query), style="dim"), disabled=True)
                )
            option_list.highlighted = self._selected_index
        finally:
            option_list._programmatic_highlight = False

        counter = self.query_one("#existing-finder-counter", Static)
        counter.update(f"{len(self._visible)} / {len(self._ranked)}")
        self._refresh_verdict()
        self._schedule_preview()

    def _row_prompt(self, ranked: RankedExistingEntry) -> Text:
        entry = ranked.entry
        text = Text(no_wrap=True, overflow="ellipsis")
        prefix = "#" if entry.kind == "macro" else "⇥ "
        text.append("  " + prefix)
        append_highlighted(
            text,
            entry.name,
            ranked.name_match.runs if ranked.name_match is not None else (),
            base_style="bold",
            match_style=_MATCH_STYLE,
            cellwise=True,
        )
        text.append("  ")
        chip = _STATUS_LABELS[entry.status]
        if entry.status == "read_only":
            chip = f"🔒 {entry.chip or 'read-only'}"
        elif entry.status == "incompatible":
            chip = f"✗ {entry.chip or 'incompatible'}"
        text.append(chip, style=_STATUS_STYLES[entry.status])
        text.append("\n   ")
        append_highlighted(
            text,
            entry.display_path,
            ranked.path_match.runs
            if ranked.name_match is None and ranked.path_match
            else (),
            base_style="dim",
            match_style=_MATCH_STYLE,
            cellwise=True,
        )
        return text

    def _empty_message(self, query: str) -> str:
        label = "macros" if self._kind == "macro" else "snippets"
        if not self._entries:
            return f"No {label} yet · ⇧tab to create one"
        return f"No {label} match ‘{query}’ · ⇧tab to create one"

    def _refresh_verdict(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            if not self._entries:
                message = self._empty_message("")
            else:
                message = self._empty_message(self._query())
            self._set_verdict("warning", message)
            return
        self._set_verdict(*existing_entry_verdict(entry))

    def _set_verdict(self, kind: str, message: str) -> None:
        verdict = self.query_one("#existing-finder-verdict", Static)
        verdict.set_classes(f"existing-finder-verdict-{kind}")
        verdict.update(message)

    def _schedule_preview(self) -> None:
        self._preview_generation += 1
        generation = self._preview_generation
        entry = self._selected_entry()
        self._render_preview_header(entry)
        if entry is None:
            self._render_preview_body("Select a definition to preview.")
            return
        if entry.preview_text is not None:
            self._render_preview_body(entry.preview_text, entry=entry)
            return
        cached = self._preview_cache.get(entry.entry_id)
        if cached is not None:
            self._render_preview_body(cached, entry=entry)
            return
        if entry.entry_id in self._preview_errors:
            self._render_preview_body("Could not load preview.", error=True)
            return
        if self._preview_loader is None:
            self._render_preview_body("Preview unavailable.", error=True)
            return
        self._render_preview_body("Loading…")
        if self._debouncer is None:
            return

        def launch() -> None:
            task = asyncio.create_task(self._load_preview(entry.entry_id, generation))
            self._preview_tasks.add(task)
            task.add_done_callback(self._preview_tasks.discard)

        self._debouncer.schedule(launch)

    async def _load_preview(self, entry_id: str, generation: int) -> None:
        loader = self._preview_loader
        if loader is None:
            return
        try:
            content = await asyncio.to_thread(loader, entry_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._preview_errors.add(entry_id)
            if self.is_mounted and generation == self._preview_generation:
                self._render_preview_body("Could not load preview.", error=True)
            return
        self._preview_cache[entry_id] = content
        if self.is_mounted and generation == self._preview_generation:
            entry = self._selected_entry()
            if entry is not None and entry.entry_id == entry_id:
                self._render_preview_body(content, entry=entry)

    def _render_preview_header(self, entry: ExistingDefinitionEntry | None) -> None:
        title = self.query_one("#existing-finder-preview-title", Static)
        if entry is None:
            title.update("")
            return
        text = Text(f"{entry.reference} · {entry.display_path}", no_wrap=True)
        if entry.shadowed_by:
            text.append(f"\nshadowed by {entry.shadowed_by}", style="bold #D7AF5F")
        elif entry.shadows:
            text.append(f"\nshadows {entry.shadows}", style="dim")
        elif entry.origin_label:
            text.append(f"\n{entry.origin_label}", style="dim")
        title.update(text)

    def _render_preview_body(
        self,
        content: str,
        *,
        entry: ExistingDefinitionEntry | None = None,
        error: bool = False,
    ) -> None:
        body = self.query_one("#existing-finder-preview-body", Static)
        if error:
            body.set_classes("existing-finder-preview-error")
            body.update(Text(content, style="dim"))
        elif entry is not None and entry.kind == "macro":
            body.set_classes("")
            body.update(markdown_document_syntax(content))
        else:
            body.set_classes("")
            body.update(Text(content, no_wrap=False, overflow="fold"))


__all__ = [
    "ExistingDefinitionFinderModal",
    "ExistingDefinitionPick",
    "ExistingFinderBack",
    "PreviewLoader",
]
