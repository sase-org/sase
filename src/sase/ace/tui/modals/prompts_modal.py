"""Tabbed Prompts overlay unifying Stash, History, and the Stash Trash view.

One stable frame hosts the reusable :class:`StashPane`,
:class:`HistoryPane`, and :class:`TrashPane` widgets behind a dedicated
:class:`PromptsTabBar` (no number shortcuts). Each surface keeps its
highlight, scroll, filter, loaded pages, preview position, and staged marks
across switches; the History pane mounts lazily on first activation so
opening Stash performs no history disk I/O. ``[``/``]`` toggle between the
two top-level tabs with wraparound (even from the focused history filter),
clicking the Stash label always shows the list while clicking the trash chip
always shows Trash, ``t`` toggles the Trash view, ``Esc`` in Trash goes back
to the list, ``@`` on Stash restores the newest draft, and ``q`` closes only
when focus is outside a text input.

Stash delete marks commit to Trash rather than permanent deletion; Trash
restores move rows back to Stash while the overlay stays open, and purges
need an explicit host confirmation. After every store outcome the affected
panes repaint from the authoritative snapshot, never from optimistic local
state.

A typed :class:`PromptsOrigin` records which entry point opened the overlay
(a live prompt bar or a home/MRU launcher) and every outcome is reported as
a :class:`PromptsResult` naming the surface that produced it, so switching
surfaces can never silently apply the initial tab's callback to the wrong
action.

All Stash and History entry points open this overlay (on their correct
initial tab with a typed origin); the standalone ``StashedPromptsModal``
remains for focused unit tests only.
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
from textual.widgets import OptionList, Static

from sase.core.prompt_stash_wire import (
    PromptStashEntryWire,
    PromptStashTrashRecordWire,
)
from sase.project_display_names import ProjectDisplaySnapshot

from ._prompt_history_models import PromptHistoryResult
from .base import FilterInput
from .history_pane import HistoryPane
from .prompts_tab_bar import PromptsTabBar, PromptsTabBarState
from .stash_pane import StashPane, StashRestoreResult
from .trash_pane import BackRequested, TrashActionResult, TrashPane

PromptsOriginKind = Literal["live_bar", "home_mru"]


class PromptsTab(Enum):
    """Surfaces of the Prompts overlay.

    ``STASH`` and ``HISTORY`` are the top-level tabs; ``TRASH`` is the
    Stash tab's Trash view.
    """

    STASH = "stash"
    HISTORY = "history"
    TRASH = "trash"


_TOP_LEVEL_TABS: tuple[PromptsTab, ...] = (
    PromptsTab.STASH,
    PromptsTab.HISTORY,
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


_SPLIT_PANE_MIN_TERMINAL_WIDTH = 110


class PromptsModal(ModalScreen[PromptsResult | None]):
    """Lazy tabbed shell around the reusable Stash and History panes."""

    BINDINGS = [
        Binding("[", "prev_tab", "Previous tab"),
        Binding("]", "next_tab", "Next tab"),
        Binding("t", "toggle_trash_view", "Trash", show=False),
        Binding("at", "restore_newest_stash", "Restore newest", show=False),
    ]

    def __init__(
        self,
        entries: list[PromptStashEntryWire],
        *,
        project_display_snapshot: ProjectDisplaySnapshot | None = None,
        origin: PromptsOrigin | None = None,
        initial_tab: PromptsTab = PromptsTab.STASH,
        trash: list[PromptStashTrashRecordWire] | None = None,
        trash_limit: int = 100,
    ) -> None:
        super().__init__()
        stash_entries = list(entries)
        trash_records = list(trash) if trash is not None else []
        self._origin = origin or PromptsOrigin()
        self._active_tab = initial_tab
        self._stash_view = (
            PromptsTab.TRASH if initial_tab is PromptsTab.TRASH else PromptsTab.STASH
        )
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
        # Last focused selector per surface, restored on every switch.
        self._focus_memory: dict[PromptsTab, str] = {}

    # -- tab bar -------------------------------------------------------------

    def _tab_bar_state(self) -> PromptsTabBarState:
        return PromptsTabBarState(
            surface=self._active_tab.value,
            stash_count=self._stash_count,
            trash_count=len(self._trash_records),
            trash_limit=self._trash_limit,
        )

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="prompts-modal-container"):
            yield PromptsTabBar(
                self._tab_bar_state(),
                id="prompts-modal-tabs",
            )
            with Vertical(id="prompts-modal-body"):
                pass
            yield Static("", id="prompts-modal-footer")

    def on_mount(self) -> None:
        try:
            container = self.query_one("#prompts-modal-container", Container)
            container.border_title = "Prompts"
        except Exception:
            pass
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
        """Keep the tab bar and per-surface footer in lockstep."""
        try:
            bar = self.query_one("#prompts-modal-tabs", PromptsTabBar)
        except Exception:
            bar = None
        if bar is not None:
            bar.set_state(self._tab_bar_state())
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
        self._sync_chrome()

    def apply_store_failure(self) -> None:
        """Repaint both panes truthfully after a failed write."""
        self._stash_pane.apply_store_failure()
        if self._trash_pane is not None:
            self._trash_pane.apply_store_failure()
        self._sync_chrome()

    # -- tab switching -------------------------------------------------------

    def action_prev_tab(self) -> None:
        """Cycle to the previous top-level tab with wraparound."""
        self._cycle_tab(-1)

    def action_next_tab(self) -> None:
        """Cycle to the next top-level tab with wraparound."""
        self._cycle_tab(1)

    def action_toggle_trash_view(self) -> None:
        """Toggle the Stash tab between its list and Trash views."""
        if self._active_tab is PromptsTab.HISTORY:
            return
        if self._active_tab is PromptsTab.TRASH:
            self._activate(PromptsTab.STASH)
        else:
            self._activate(PromptsTab.TRASH)

    def action_restore_newest_stash(self) -> None:
        """Restore the newest stash entry (pin-aware, ignores staged marks)."""
        if self._active_tab is not PromptsTab.STASH:
            return
        result = self._stash_pane.newest_restore_result()
        if result is None:
            return
        self.dismiss(
            PromptsResult(
                tab=PromptsTab.STASH,
                origin=self._origin,
                stash=result,
            )
        )

    def _cycle_tab(self, step: int) -> None:
        # Trash counts as the Stash position; returning to Stash restores
        # the remembered Stash view.
        pos = 1 if self._active_tab is PromptsTab.HISTORY else 0
        new_top = _TOP_LEVEL_TABS[(pos + step) % len(_TOP_LEVEL_TABS)]
        if new_top is PromptsTab.STASH:
            self._activate(self._stash_view)
        else:
            self._activate(new_top)

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
        if tab in (PromptsTab.STASH, PromptsTab.TRASH):
            self._stash_view = tab
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

    @on(PromptsTabBar.SurfaceClicked)
    def _on_surface_clicked(self, event: PromptsTabBar.SurfaceClicked) -> None:
        """Select a surface by mouse click (Stash label shows the list)."""
        event.stop()
        if event.surface == "stash":
            self._activate(PromptsTab.STASH)
        elif event.surface == "trash":
            self._activate(PromptsTab.TRASH)
        elif event.surface == "history":
            self._activate(PromptsTab.HISTORY)

    @on(BackRequested)
    def _on_trash_back_requested(self, event: BackRequested) -> None:
        """Return from the Trash view to the Stash list."""
        event.stop()
        self._activate(PromptsTab.STASH)

    @on(HistoryPane.CycleTabRequested)
    def _on_cycle_tab_requested(self, event: HistoryPane.CycleTabRequested) -> None:
        """Cycle top-level tabs for a bracket typed in the history filter."""
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
