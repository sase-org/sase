"""Tabbed Prompts overlay unifying Stash, History, and Trash recall.

One stable frame hosts the reusable :class:`StashPane`,
:class:`HistoryPane`, and :class:`TrashPane` widgets behind a
:class:`PanelTabStrip` (no number shortcuts). Each tab keeps its highlight,
scroll, filter, loaded pages, preview position, and staged marks across
switches; the History pane mounts lazily on first activation so opening
Stash performs no history disk I/O. ``[``/``]`` cycle tabs with wraparound
(even from the focused history filter), clicking a tab selects it, ``Esc``
closes, and ``q`` closes only when focus is outside a text input.

Stash delete marks commit to Trash rather than permanent deletion; Trash
restores move rows back to Stash while the overlay stays open, and purges
need an explicit host confirmation. After every store outcome the affected
panes repaint from the authoritative snapshot, never from optimistic local
state.

A typed :class:`PromptsOrigin` records which entry point opened the overlay
(a live prompt bar or a home/MRU launcher) and every outcome is reported as
a :class:`PromptsResult` naming the tab that produced it, so switching tabs
can never silently apply the initial tab's callback to the wrong action.

Existing external entry points keep pushing the standalone pickers until the
rollout phase routes them here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static

from sase.core.prompt_stash_wire import (
    PromptStashEntryWire,
    PromptStashTrashRecordWire,
)
from sase.project_display_names import ProjectDisplaySnapshot

from ..widgets.panel_tab_strip import PanelTab, PanelTabStrip
from ._prompt_history_models import PromptHistoryResult
from .base import FilterInput
from .history_pane import HistoryPane
from .stash_pane import StashPane, StashRestoreResult
from .trash_pane import TrashActionResult, TrashPane

PromptsOriginKind = Literal["live_bar", "home_mru"]


class PromptsTab(Enum):
    """Tabs of the Prompts overlay."""

    STASH = "stash"
    HISTORY = "history"
    TRASH = "trash"


_TAB_ORDER: tuple[PromptsTab, ...] = (
    PromptsTab.STASH,
    PromptsTab.HISTORY,
    PromptsTab.TRASH,
)


@dataclass(frozen=True, slots=True)
class PromptsOrigin:
    """Typed launch context for the Prompts overlay.

    ``kind`` distinguishes a live prompt bar (history ``LOAD`` restores into
    its captured pane with frontmatter conflict handling) from a home/MRU
    launcher (submit/edit callbacks of its own). History seed/filter options
    ride along so the overlay opens on the same query either entry point
    would have used.
    """

    kind: PromptsOriginKind = "live_bar"
    show_cancelled: bool = False
    initial_filter: str = ""
    prompt_seed: str | None = None


@dataclass(frozen=True, slots=True)
class PromptsResult:
    """Outcome of the Prompts overlay, tagged with the producing tab."""

    tab: PromptsTab
    origin: PromptsOrigin
    stash: StashRestoreResult | None = None
    history: PromptHistoryResult | None = None
    trash: TrashActionResult | None = None


_STASH_ACCENT = "orchid"
_HISTORY_ACCENT = "cyan"
# Amber at rest (hex: "amber" is not a Rich-parseable color name).
_TRASH_ACCENT = "#EBC04F"

_SPLIT_PANE_MIN_TERMINAL_WIDTH = 110


class PromptsModal(ModalScreen[PromptsResult | None]):
    """Lazy tabbed shell around the reusable Stash and History panes."""

    BINDINGS = [
        Binding("[", "prev_tab", "Previous tab"),
        Binding("]", "next_tab", "Next tab"),
    ]

    def __init__(
        self,
        entries: list[PromptStashEntryWire],
        *,
        project_display_snapshot: ProjectDisplaySnapshot | None = None,
        origin: PromptsOrigin | None = None,
        initial_tab: PromptsTab = PromptsTab.STASH,
        trash: list[PromptStashTrashRecordWire] | None = None,
        trash_limit: int = 20,
    ) -> None:
        super().__init__()
        stash_entries = list(entries)
        trash_records = list(trash) if trash is not None else []
        self._origin = origin or PromptsOrigin()
        self._active_tab = initial_tab
        self._trash_limit = trash_limit
        self._stash_pane = StashPane(
            stash_entries,
            project_display_snapshot=project_display_snapshot,
            trash_limit=trash_limit,
            trash_count=len(trash_records),
        )
        self._history_pane: HistoryPane | None = None
        self._history_mounted = False
        self._trash_pane: TrashPane | None = None
        self._trash_mounted = False
        self._trash_records = trash_records
        self._stash_count = len(stash_entries)
        # Last focused selector per tab, restored on every switch.
        self._focus_memory: dict[PromptsTab, str] = {}
        self._tabs = self._build_tabs()

    # -- tab strip -----------------------------------------------------------

    def _build_tabs(self) -> tuple[PanelTab, ...]:
        trash_count = len(self._trash_records)
        return (
            PanelTab(
                id=PromptsTab.STASH.value,
                label=f"Stash {self._stash_count}",
                accent_color=_STASH_ACCENT,
                compact_label=f"S{self._stash_count}",
            ),
            PanelTab(
                id=PromptsTab.HISTORY.value,
                label="History",
                accent_color=_HISTORY_ACCENT,
                compact_label="H",
            ),
            PanelTab(
                id=PromptsTab.TRASH.value,
                label=f"Trash {trash_count}/{self._trash_limit}",
                accent_color=_TRASH_ACCENT,
                compact_label=f"T{trash_count}/{self._trash_limit}",
            ),
        )

    def _tab_for_id(self, tab_id: str) -> PromptsTab | None:
        for tab in _TAB_ORDER:
            if tab.value == tab_id:
                return tab
        return None

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="prompts-modal-container"):
            yield Label("Prompts", id="prompts-modal-title")
            yield PanelTabStrip(
                self._tabs,
                self._active_tab.value,
                show_numbers=False,
                compact_below=_SPLIT_PANE_MIN_TERMINAL_WIDTH,
                id="prompts-modal-tabs",
            )
            with Vertical(id="prompts-modal-body"):
                pass
            yield Static("", id="prompts-modal-footer")

    def on_mount(self) -> None:
        self._set_narrow_mode(
            self.app.size.width < _SPLIT_PANE_MIN_TERMINAL_WIDTH  # type: ignore[attr-defined]
        )
        body = self.query_one("#prompts-modal-body", Vertical)
        if self._active_tab is PromptsTab.HISTORY:
            pane: StashPane | HistoryPane | TrashPane = self._ensure_history_pane()
            body.mount(pane)
            self._sync_chrome()
            self._focus_history_default()
        elif self._active_tab is PromptsTab.TRASH:
            pane = self._ensure_trash_pane()
            body.mount(pane)
            self._sync_chrome()
            pane.focus_trash_list()
        else:
            body.mount(self._stash_pane)
            self._sync_chrome()
            self._stash_pane.focus_stash_list()
        self.call_after_refresh(self._sync_chrome)

    def on_unmount(self) -> None:
        self._remember_focus()

    def on_resize(self, event: events.Resize) -> None:
        self._set_narrow_mode(event.size.width < _SPLIT_PANE_MIN_TERMINAL_WIDTH)

    def _set_narrow_mode(self, narrow: bool) -> None:
        try:
            container = self.query_one("#prompts-modal-container", Container)
        except Exception:
            return
        container.set_class(narrow, "-narrow")

    def _ensure_history_pane(self) -> HistoryPane:
        if self._history_pane is None:
            self._history_pane = HistoryPane(
                show_cancelled=self._origin.show_cancelled,
                initial_filter=self._origin.initial_filter,
                prompt_seed=self._origin.prompt_seed,
                tab_cycle_brackets=True,
            )
        return self._history_pane

    def _visible_pane(self) -> StashPane | HistoryPane | TrashPane:
        if self._active_tab is PromptsTab.HISTORY:
            return self._ensure_history_pane()
        if self._active_tab is PromptsTab.TRASH:
            return self._ensure_trash_pane()
        return self._stash_pane

    def _sync_chrome(self) -> None:
        """Keep the tab strip and per-tab footer in lockstep."""
        try:
            strip = self.query_one("#prompts-modal-tabs", PanelTabStrip)
        except Exception:
            return
        strip.set_active_tab(self._active_tab.value)
        try:
            footer = self.query_one("#prompts-modal-footer", Static)
        except Exception:
            return
        footer.update(self._footer_text())

    def _footer_text(self) -> str:
        if self._active_tab is PromptsTab.HISTORY:
            return self._ensure_history_pane()._hints_text()
        if self._active_tab is PromptsTab.TRASH:
            return self._ensure_trash_pane()._hint_text()
        return self._stash_pane._hint_text()

    # -- authoritative repaint -------------------------------------------------

    def apply_lifecycle_snapshot(
        self,
        active: list[PromptStashEntryWire],
        trash: list[PromptStashTrashRecordWire],
    ) -> None:
        """Repaint Stash and Trash panes from an authoritative store outcome.

        Tab counts (``Stash N``, ``Trash M/N``) follow the snapshot, and the
        Stash empty-state hint follows the Trash count. Marks for IDs absent
        from the snapshot are dropped; surviving marks are kept.
        """
        self._stash_count = len(active)
        self._trash_records = list(trash)
        self._stash_pane.apply_lifecycle_snapshot(
            active, trash_count=len(self._trash_records)
        )
        if self._trash_pane is not None:
            self._trash_pane.apply_snapshot(self._trash_records)
        self._refresh_tabs()
        self._sync_chrome()

    def apply_store_failure(self) -> None:
        """Repaint both panes truthfully after a failed write."""
        self._stash_pane.apply_store_failure()
        if self._trash_pane is not None:
            self._trash_pane.apply_store_failure()
        self._sync_chrome()

    def _refresh_tabs(self) -> None:
        self._tabs = self._build_tabs()
        try:
            strip = self.query_one("#prompts-modal-tabs", PanelTabStrip)
        except Exception:
            return
        strip.set_tabs(self._tabs)

    # -- tab switching -------------------------------------------------------

    def action_prev_tab(self) -> None:
        """Cycle to the previous tab with wraparound."""
        self._cycle_tab(-1)

    def action_next_tab(self) -> None:
        """Cycle to the next tab with wraparound."""
        self._cycle_tab(1)

    def _cycle_tab(self, step: int) -> None:
        index = _TAB_ORDER.index(self._active_tab)
        self._activate(_TAB_ORDER[(index + step) % len(_TAB_ORDER)])

    def _ensure_trash_pane(self) -> TrashPane:
        if self._trash_pane is None:
            self._trash_pane = TrashPane(
                self._trash_records,
                trash_limit=self._trash_limit,
            )
        return self._trash_pane

    def _remember_focus(self) -> None:
        try:
            focused = self.focused
        except Exception:
            return
        if focused is None:
            return
        focused_id = getattr(focused, "id", None)
        if focused_id == "prompt-history-filter-input":
            self._focus_memory[self._active_tab] = "#prompt-history-filter-input"
        elif focused_id in (
            "stashed-prompts-list",
            "prompt-history-list",
            "trash-list",
        ):
            self._focus_memory[self._active_tab] = f"#{focused_id}"

    def _activate(self, tab: PromptsTab) -> None:
        if tab is self._active_tab and self._pane_mounted(tab):
            self._focus_active_default()
            return
        self._remember_focus()
        self._active_tab = tab
        body = self.query_one("#prompts-modal-body", Vertical)
        if tab is PromptsTab.HISTORY:
            pane = self._ensure_history_pane()
            self._stash_pane.display = False
            if self._trash_pane is not None and self._trash_mounted:
                self._trash_pane.display = False
            if not self._history_mounted:
                body.mount(pane)
                self._history_mounted = True
            else:
                pane.display = True
        elif tab is PromptsTab.TRASH:
            trash_pane = self._ensure_trash_pane()
            self._stash_pane.display = False
            if self._history_pane is not None and self._history_mounted:
                self._history_pane.display = False
            if not self._trash_mounted:
                body.mount(trash_pane)
                self._trash_mounted = True
            else:
                trash_pane.display = True
        else:
            if self._history_pane is not None and self._history_mounted:
                self._history_pane.display = False
            if self._trash_pane is not None and self._trash_mounted:
                self._trash_pane.display = False
            if not self._stash_pane.is_mounted:
                body.mount(self._stash_pane)
            self._stash_pane.display = True
        self._sync_chrome()
        self.call_after_refresh(self._focus_restored)

    def _pane_mounted(self, tab: PromptsTab) -> bool:
        if tab is PromptsTab.HISTORY:
            return self._history_pane is not None and self._history_mounted
        if tab is PromptsTab.TRASH:
            return self._trash_pane is not None and self._trash_mounted
        return self._stash_pane.is_mounted

    def _focus_restored(self) -> None:
        remembered = self._focus_memory.get(self._active_tab)
        if remembered == "#prompt-history-filter-input":
            pane = self._history_pane
            if pane is not None and pane.display:
                pane.focus_history_filter()
                return
        elif remembered == "#prompt-history-list":
            try:
                self.query_one("#prompt-history-list", OptionList).focus()
                return
            except Exception:
                pass
        elif remembered == "#stashed-prompts-list":
            self._stash_pane.focus_stash_list()
            return
        elif remembered == "#trash-list":
            trash_pane = self._trash_pane
            if trash_pane is not None and trash_pane.display:
                trash_pane.focus_trash_list()
                return
        self._focus_active_default()

    def _focus_active_default(self) -> None:
        if self._active_tab is PromptsTab.HISTORY:
            self._focus_history_default()
        elif self._active_tab is PromptsTab.TRASH:
            self._ensure_trash_pane().focus_trash_list()
        else:
            self._stash_pane.focus_stash_list()

    def _focus_history_default(self) -> None:
        pane = self._history_pane
        if pane is None:
            return
        # The filter owns initial focus (matching the standalone modal);
        # fall back to the list when it is not mounted yet.
        try:
            self.query_one("#prompt-history-filter-input", FilterInput).focus()
        except Exception:
            try:
                self.query_one("#prompt-history-list", OptionList).focus()
            except Exception:
                pass

    @on(PanelTabStrip.TabClicked)
    def _on_tab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        """Select a tab by mouse click."""
        event.stop()
        tab = self._tab_for_id(event.tab_id)
        if tab is not None:
            self._activate(tab)

    @on(HistoryPane.CycleTabRequested)
    def _on_cycle_tab_requested(self, event: HistoryPane.CycleTabRequested) -> None:
        """Cycle tabs for a bracket typed in the history filter."""
        event.stop()
        self._cycle_tab(event.step)

    # -- results --------------------------------------------------------------

    @on(StashPane.Selected)
    def _on_stash_selected(self, event: StashPane.Selected) -> None:
        if event.result is None:
            self.dismiss(None)
            return
        self.dismiss(
            PromptsResult(
                tab=PromptsTab.STASH,
                origin=self._origin,
                stash=event.result,
            )
        )

    @on(HistoryPane.Selected)
    def _on_history_selected(self, event: HistoryPane.Selected) -> None:
        if event.result is None:
            self.dismiss(None)
            return
        self.dismiss(
            PromptsResult(
                tab=PromptsTab.HISTORY,
                origin=self._origin,
                history=event.result,
            )
        )

    @on(TrashPane.Selected)
    def _on_trash_selected(self, event: TrashPane.Selected) -> None:
        if event.result is None:
            self.dismiss(None)
            return
        self.dismiss(
            PromptsResult(
                tab=PromptsTab.TRASH,
                origin=self._origin,
                trash=event.result,
            )
        )


__all__ = [
    "PromptsModal",
    "PromptsOrigin",
    "PromptsOriginKind",
    "PromptsResult",
    "PromptsTab",
]
