"""Reusable Memory catalog pane -- browse one scope's SASE memory notes.

This widget owns composition, scoped bindings, worker-backed loads,
debouncing, selection, relationship travel, mutations, publish, and
source/copy/help actions. A thin :class:`~sase.ace.tui.modals.memory_panel.MemoryPanel`
adapter hosts it as the current standalone modal. A later Config hub can
mount the same widget without changing this content behavior.

Mixin split: snapshot and selection state in
:mod:`sase.ace.tui.modals.memory_panel_state`, widget rendering in
:mod:`sase.ace.tui.modals.memory_panel_view`, note/filter/scope movement in
:mod:`sase.ace.tui.modals.memory_panel_navigation`, parent/child chip
travel in :mod:`sase.ace.tui.modals.memory_panel_travel`,
add/edit/delete in :mod:`sase.ace.tui.modals.memory_panel_actions`,
publish in :mod:`sase.ace.tui.modals.memory_panel_publish_actions`,
worker-backed loads in :mod:`sase.ace.tui.modals.memory_pane_loading`,
and history rows/pager actions in
:mod:`sase.ace.tui.modals.memory_pane_history`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, OptionList, Static
from textual.worker import Worker

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.keymaps import (
    MemoryPanelKeymaps,
    build_memory_bindings,
    load_keymap_registry,
)
from sase.ace.tui.memory_panel_catalog import (
    MemoryRailNode,
    MemoryScopeRef,
    MemoryScopeSnapshot,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import ProgrammaticSelectionGuard

from .base import CopyModeForwardingMixin, FilterInput
from ._source_file_actions import SourceFileActionsMixin
from .catalog_pane_host import CatalogPaneHost
from .memory_panel_actions import MemoryPanelActionsMixin
from .memory_panel_help_modal import MemoryPanelHelpModal
from .memory_panel_navigation import MemoryPanelNavigationMixin
from .memory_panel_rendering import memory_card_accent, memory_note_source_path
from .memory_panel_state import (
    _FILTER_INPUT_ID,
    _NOTE_LIST_ID,
    MemoryPanelStateMixin,
)
from .memory_panel_travel import MemoryPanelTravelMixin
from .memory_panel_view import MemoryPanelViewMixin
from .memory_pane_changes_lens import MemoryPaneChangesLensMixin
from .memory_pane_diff import MemoryPaneDiffMixin
from .memory_pane_history import MemoryPaneHistoryMixin
from .memory_pane_lens import MemoryPaneLensMixin
from .memory_pane_loading import MemoryPaneLoadingMixin
from .memory_pane_time import MemoryPaneTimeMixin
from .memory_pane_timeline_lens import MemoryPaneTimelineLensMixin
from .numbered_link_keys import (
    NUMBERED_LINK_BINDING,
    arm_numbered_link,
    clear_numbered_link_prefix,
    handle_numbered_link_key,
)

if TYPE_CHECKING:
    from sase.memory.notes import MemoryNote

    from .memory_panel_load import (
        MemoryPanelInitialLoad,
        MemoryPanelStrandRead,
        MemoryScopeChoice,
    )


@dataclass
class MemoryPaneSession:
    """Injected bookmarks for the active Memory scope and selected note.

    An explicit ``#memory/<stem>`` seed on :class:`MemoryPane` overrides
    these values on direct entry. Missing or vanished notes and scopes fall
    back here, then to the default ring entry.
    """

    scope_key: str | None = None
    note: str | None = None


class _MemoryFilterInput(FilterInput):
    """The pane's inline filter box; Escape closes it without cancelling."""

    BINDINGS = [*FilterInput.BINDINGS, ("escape", "close_filter", "Close filter")]

    def on_key(self, event: events.Key) -> None:
        from .config_hub_keys import handle_config_hub_bracket_key

        handle_config_hub_bracket_key(self, event)

    def action_close_filter(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane._close_filter()

    def _pane(self) -> MemoryPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, MemoryPane):
                return node
            node = getattr(node, "parent", None)
        return None


class _TimeStripLink(Static):
    """The pinned time strip; clicking it opens the Timeline lens."""

    def on_click(self, _event: events.Click) -> None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, MemoryPane) and node._lens == "notes":
                try:
                    node.action_history_timeline()
                except Exception:
                    pass
                return
            node = getattr(node, "parent", None)


class MemoryPane(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    # Lens mixins come first so their rail/selection/header/footer and
    # hand-off overrides win over the Notes paths they re-home; every
    # fallback delegates explicitly to the owning mixin.
    MemoryPaneChangesLensMixin,
    MemoryPaneTimelineLensMixin,
    MemoryPaneLensMixin,
    MemoryPanelActionsMixin,
    MemoryPaneLoadingMixin,
    MemoryPaneHistoryMixin,
    MemoryPaneTimeMixin,
    MemoryPaneDiffMixin,
    MemoryPanelStateMixin,
    MemoryPanelViewMixin,
    MemoryPanelNavigationMixin,
    MemoryPanelTravelMixin,
    Vertical,
):
    """Browse one scope's memory notes, tree-ordered, with a filter."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close_direct", "Close"),
        NUMBERED_LINK_BINDING,
    ]

    def __init__(
        self,
        *,
        host: CatalogPaneHost | None = None,
        keymaps: MemoryPanelKeymaps | None = None,
        launch_workspace: str | None = None,
        initial_scope_key: str | None = None,
        initial_note: str | None = None,
        session: MemoryPaneSession | None = None,
        activate_on_mount: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._host = host
        self._keymaps = keymaps or load_keymap_registry({}).memory
        self._bindings = BindingsMap(
            [*build_memory_bindings(self._keymaps), *self.BINDINGS]
        )
        self._launch_workspace = launch_workspace
        self._initial_scope_key = initial_scope_key
        self._initial_note = initial_note
        self._session = session if session is not None else MemoryPaneSession()
        self._host_visible = activate_on_mount
        self._closed = False
        self._accent = "#87D7FF"
        self._ring: tuple[MemoryScopeRef, ...] = ()
        self._scope_index = 0
        self._snapshot: MemoryScopeSnapshot | None = None
        self._all_rows: tuple[MemoryRailNode, ...] = ()
        self._rows: tuple[MemoryRailNode, ...] = ()
        self._current_note: str | None = None
        self._filter_text = ""
        self._filter_bodies = False
        self._loading = True
        self._load_worker: Worker[MemoryPanelInitialLoad] | None = None
        self._scope_worker: Worker[MemoryScopeSnapshot] | None = None
        self._picker_worker: Worker[tuple[MemoryScopeChoice, ...]] | None = None
        self._restat_worker: Worker[bool] | None = None
        self._strand_read_worker: Worker[MemoryPanelStrandRead] | None = None
        self._strand_read_worker_identity: str | None = None
        self._strand_read_status: dict[str, str] = {}
        self._selection_guard = ProgrammaticSelectionGuard()
        self._debouncer: DetailPanelDebouncer | None = None
        self._scope_selection_memory: dict[str, str] = {}
        self._expanded_webs: set[str] = set()
        self._chip_notes: tuple[MemoryNote, ...] = ()
        self._chip_parent_count = 0
        self._chip_cursor: int | None = None
        self._pending_numbered_link = False
        self._trail: list[str] = []
        self._write_busy = False
        self._unpublished_scopes: set[str] = set()
        self._pending_delete_path: str | None = None
        self._pending_delete_neighbor: str | None = None
        self._pending_delete_strand: tuple[str, str] | None = None
        self._history_cache: dict[tuple[str, str, str], dict] = {}
        self._history_latest: dict[tuple[str, str], dict] = {}
        # Keys whose summary load settled unavailable. Renders show the
        # retry row without respawning workers; scope reloads and `r`
        # clear the set so a repaired checkout retries.
        self._history_failed: set[tuple[str, str]] = set()
        self._history_worker: Worker[tuple[str, str, dict | None]] | None = None
        self._history_request: tuple[str, str] | None = None
        self._history_open_worker: Worker[None] | None = None
        self._history_probe_worker: Worker[tuple[str, str, bool]] | None = None
        self._history_poll_timer: Any | None = None
        self._time_pins: dict[tuple[str, str], int] = {}
        self._time_applied: dict[tuple[str, str], int] = {}
        self._time_pending: dict[tuple[str, str], str] = {}
        self._time_bodies: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._time_parsed: dict[tuple[str, str, int], Any] = {}
        self._time_prefetched_key: tuple[str, str] | None = None
        self._time_generation = 0
        self._time_request: tuple[str, str, int, int] | None = None
        self._time_worker: Worker[Any] | None = None
        self._time_diff_view = False
        self._time_diffs: dict[tuple[str, str, int, int], dict[str, Any]] = {}
        self._diff_failed: set[tuple[str, str, int, int]] = set()
        self._diff_generation = 0
        self._diff_request: tuple[str, str, int, int, int] | None = None
        self._diff_worker: Worker[Any] | None = None
        self._lens = "notes"
        self._lens_snapshot = None
        self._timeline_subject_node = None
        self._timeline_subject_key: tuple[str, str] | None = None
        self._timeline_subject_identity: str | None = None
        self._timeline_rows_all: tuple[dict[str, Any], ...] = ()
        self._timeline_listed: tuple[dict[str, Any], ...] = ()
        self._timeline_cursor = 0
        self._timeline_open_key: tuple[str, str] | None = None
        self._timeline_base: int | None = None
        self._timeline_show_hidden = False
        self._timeline_filter = ""
        self._timeline_preview_pending = False
        self._timeline_scheduled = -1
        self._timeline_has_hidden_line = False
        self._changes_feed: dict[str, Any] | None = None
        self._changes_listed: tuple[dict[str, Any], ...] = ()
        self._changes_cursor = 0
        self._changes_scheduled = -1
        self._changes_filter = ""
        self._changes_limit = 100
        self._changes_all_scopes = False
        self._changes_failed: tuple[str, ...] = ()
        self._changes_scope_label = ""
        self._changes_total = 0
        self._changes_older = 0
        self._changes_loading = False
        self._changes_generation = 0
        self._changes_sections: dict[tuple[str, str, str], str] = {}
        self._changes_section_failed: set[tuple[str, str, str]] = set()
        self._changes_worker: Worker[None] | None = None

    def on_key(self, event: events.Key) -> None:
        from .config_hub_keys import handle_config_hub_subtab_select_key

        if handle_config_hub_subtab_select_key(self, event):
            return
        if self._lens == "timeline" and self._is_timeline_hidden_key(event):
            # `.` reveals hidden versions in the Timeline lens; chip
            # shortcuts are inert there (D3 key routing).
            event.prevent_default()
            event.stop()
            try:
                self.action_history_toggle_hidden()
            except Exception:
                pass
            return
        if handle_numbered_link_key(self, event, follow=self.action_follow_link_number):
            return
        super().on_key(event)

    def _is_timeline_hidden_key(self, event: events.Key) -> bool:
        """Return whether *event* is the lens-local hidden toggle (``.``)."""
        try:
            if event.key == "full_stop":
                return True
        except Exception:
            pass
        try:
            if getattr(event, "character", None) == ".":
                return True
        except Exception:
            pass
        return False

    def action_arm_numbered_link(self) -> None:
        arm_numbered_link(self)

    def compose(self) -> ComposeResult:
        self._accent = memory_card_accent(self.app.current_theme)
        with Container(id="memory-panel-container"):
            yield Static(self._loading_header_text(), id="memory-panel-header")
            with Horizontal(id="memory-panel-body"):
                yield OptionList(id=_NOTE_LIST_ID)
                with Vertical(id="memory-panel-detail"):
                    yield Static("", id="memory-panel-card-title")
                    yield _TimeStripLink("", id="memory-panel-time-strip")
                    with VerticalScroll(id="memory-panel-card-scroll"):
                        yield Static("", id="memory-panel-card-description")
                        yield Markdown("", id="memory-panel-card-body")
                        yield Static("", id="memory-panel-card-diff")
                        yield Static("", id="memory-panel-card-meta")
            yield _MemoryFilterInput(
                placeholder="Filter notes…",
                id=_FILTER_INPUT_ID,
            )
            yield Static("", id="memory-panel-trail")
            yield Static("", id="memory-panel-footer")

    def on_mount(self) -> None:
        self._debouncer = DetailPanelDebouncer(self.app)
        self._filter_input().display = False
        self._trail_strip().display = False
        if self._host_visible:
            self.focus_default()
        self._start_initial_load()
        self._start_history_poll()

    def on_unmount(self) -> None:
        self._closed = True
        clear_numbered_link_prefix(self)
        if self._debouncer is not None:
            self._debouncer.cancel()
        self._stop_history_poll()
        for worker in (
            self._load_worker,
            self._scope_worker,
            self._picker_worker,
            self._restat_worker,
            self._strand_read_worker,
            self._history_worker,
            self._history_open_worker,
            self._history_probe_worker,
            self._time_worker,
            self._diff_worker,
            self._changes_worker,
        ):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    def on_resize(self, _event: events.Resize) -> None:
        """Re-fit the note rail when the terminal changes size."""
        self._resize_note_rail()

    def focus_default(self) -> None:
        """Focus the note rail when the host shows this pane."""
        if self._closed or not self._host_visible or not self.is_mounted:
            return
        try:
            self._note_list().focus()
        except Exception:
            return

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """Stop stealing focus while a host is showing another child."""
        self._host_visible = active
        if not active:
            clear_numbered_link_prefix(self)
            return
        self.focus_default()

    def action_close(self) -> None:
        # Esc ladder: the filter closes first, then the lens, then a past
        # pin returns to now, then the host closes. `q` closes directly.
        try:
            if self._filter_input().display:
                self._close_filter()
                return
        except Exception:
            pass
        try:
            if self._lens_exit_if_in_lens():
                return
        except Exception:
            pass
        try:
            if self._time_unpin_if_pinned():
                return
        except Exception:
            pass
        if self._host is not None:
            self._host.close_catalog_pane()

    def action_close_direct(self) -> None:
        if self._host is not None:
            self._host.close_catalog_pane()

    def _record_session_selection(self) -> None:
        if self._ring:
            self._session.scope_key = self._ring[self._scope_index].key
        if self._current_note is not None:
            self._session.note = self._current_note

    def _preferred_note_for_snapshot(
        self, snapshot: MemoryScopeSnapshot | None
    ) -> str | None:
        """Honor a direct-entry seed, then the session bookmark, then fallback."""
        paths = self._snapshot_identities(snapshot)
        if self._initial_note and self._initial_note in paths:
            self._expand_web_for_identity(self._initial_note, snapshot)
            return self._initial_note
        remembered = self._session.note
        if remembered and remembered in paths:
            self._expand_web_for_identity(remembered, snapshot)
            return remembered
        if self._initial_note:
            return self._initial_note
        return remembered

    def _snapshot_identities(self, snapshot: MemoryScopeSnapshot | None) -> set[str]:
        if snapshot is None:
            return set()
        identities = {node.identity for node in snapshot.tree}
        for web in snapshot.webs:
            identities.update(f"{web.slug}:{strand.slug}" for strand in web.strands)
        return identities

    def _expand_web_for_identity(
        self, identity: str, snapshot: MemoryScopeSnapshot | None
    ) -> None:
        if snapshot is None or ":" not in identity:
            return
        web_slug, _, strand_slug = identity.partition(":")
        if not strand_slug:
            return
        if any(web.slug == web_slug for web in snapshot.webs):
            self._expanded_webs.add(web_slug)

    def _reset_strand_read_state(self) -> None:
        if (
            self._strand_read_worker is not None
            and not self._strand_read_worker.is_finished
        ):
            self._strand_read_worker.cancel()
        self._strand_read_worker = None
        self._strand_read_worker_identity = None
        self._strand_read_status.clear()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._load_worker:
            self._on_initial_load_state_changed(event)
        elif event.worker is self._scope_worker:
            self._on_scope_load_state_changed(event)
        elif event.worker is self._picker_worker:
            self._on_scope_picker_load_state_changed(event)
        elif event.worker is self._restat_worker:
            self._on_restat_state_changed(event)
        elif event.worker is self._strand_read_worker:
            self._on_strand_read_state_changed(event)
        elif event.worker is self._history_worker:
            self._on_history_state_changed(event)
        elif event.worker is self._history_probe_worker:
            self._on_history_probe_state_changed(event)
        elif event.worker is self._time_worker:
            self._on_time_body_state_changed(event)
        elif event.worker is self._diff_worker:
            self._on_diff_state_changed(event)

    # --- passive actions ------------------------------------------------

    def _source_action_path(self) -> str | None:
        node = self._selected_row()
        if node is None or not self._ring:
            return None
        return memory_note_source_path(self._ring[self._scope_index], node.note)

    def _source_action_position(self) -> tuple[int | None, int | None]:
        return None, None

    def action_open_source(self) -> None:
        node = self._selected_row()
        self.action_open_in_editor()
        if node is not None:
            self._start_restat(node.note)

    def action_open_viewer(self) -> None:
        self.action_open_in_viewer()

    def action_copy_source_path(self) -> None:
        self.action_copy_path()

    def action_copy_body(self) -> None:
        node = self._selected_row()
        if node is None:
            return
        try:
            past = self._past_card_for_node(node)
        except Exception:
            past = None
        if past is not None:
            # `y` copies the body on screen and names its version.
            if past.body_text is None:
                self.notify("past body is still loading", severity="warning")
                return
            try:
                past_note = self._time_past_note(node, past.body_text)
                shown = past_note.body if past_note is not None else past.body_text
            except Exception:
                shown = past.body_text
            schedule_copy_delivery(
                self,
                str(shown or "").strip(),
                copied_label=f"memory note body (v{past.applied_ordinal})",
                task_name="sase-memory-panel-copy-body",
            )
            return
        if node.is_strand and self._strand_read_status.get(node.identity) != "ok":
            self.notify("strand body is waiting on audited read", severity="warning")
            return
        schedule_copy_delivery(
            self,
            node.note.body.strip(),
            copied_label="memory note body",
            task_name="sase-memory-panel-copy-body",
        )

    def action_help(self) -> None:
        self.app.push_screen(MemoryPanelHelpModal(keymaps=self._keymaps))


__all__ = ["MemoryPane", "MemoryPaneSession"]
