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
add/edit/delete in :mod:`sase.ace.tui.modals.memory_panel_actions`, and
publish in :mod:`sase.ace.tui.modals.memory_panel_publish_actions`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Markdown, OptionList, Static
from textual.worker import Worker, WorkerState

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
    load_memory_scope_snapshot,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
from sase.memory.notes import MemoryNote

from .base import CopyModeForwardingMixin, FilterInput
from ._source_file_actions import SourceFileActionsMixin
from .catalog_pane_host import CatalogPaneHost
from .memory_panel_actions import MemoryPanelActionsMixin
from .memory_panel_help_modal import MemoryPanelHelpModal
from .memory_panel_load import (
    MemoryPanelInitialLoad,
    MemoryPanelStrandRead,
    MemoryScopeChoice,
    load_memory_panel_initial_state,
    load_memory_scope_choices,
    note_digest_changed,
    record_memory_panel_strand_read,
)
from .memory_panel_navigation import MemoryPanelNavigationMixin
from .memory_panel_rendering import memory_card_accent, memory_note_source_path
from .memory_panel_scope_picker import MemoryScopePicker
from .memory_panel_state import (
    _FILTER_INPUT_ID,
    _NOTE_LIST_ID,
    MemoryPanelStateMixin,
)
from .memory_panel_travel import MemoryPanelTravelMixin
from .memory_panel_view import MemoryPanelViewMixin
from .numbered_link_keys import (
    NUMBERED_LINK_BINDING,
    arm_numbered_link,
    clear_numbered_link_prefix,
    handle_numbered_link_key,
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


class MemoryPane(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    MemoryPanelActionsMixin,
    MemoryPanelStateMixin,
    MemoryPanelViewMixin,
    MemoryPanelNavigationMixin,
    MemoryPanelTravelMixin,
    Vertical,
):
    """Browse one scope's memory notes, tree-ordered, with a filter."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
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
        self._history_worker: Worker[tuple[str, str, dict | None]] | None = None
        self._history_request: tuple[str, str] | None = None
        self._history_service: Any | None = None
        self._history_open_worker: Worker[None] | None = None

    def on_key(self, event: events.Key) -> None:
        from .config_hub_keys import handle_config_hub_subtab_select_key

        if handle_config_hub_subtab_select_key(self, event):
            return
        if handle_numbered_link_key(self, event, follow=self.action_follow_link_number):
            return
        super().on_key(event)

    def action_arm_numbered_link(self) -> None:
        arm_numbered_link(self)

    def compose(self) -> ComposeResult:
        self._accent = memory_card_accent(self.app.current_theme)
        with Container(id="memory-panel-container"):
            yield Static(self._loading_header_text(), id="memory-panel-header")
            with Horizontal(id="memory-panel-body"):
                yield OptionList(id=_NOTE_LIST_ID)
                with VerticalScroll(id="memory-panel-detail"):
                    yield Static("", id="memory-panel-card-title")
                    yield Static("", id="memory-panel-card-description")
                    yield Markdown("", id="memory-panel-card-body")
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

    def on_unmount(self) -> None:
        self._closed = True
        clear_numbered_link_prefix(self)
        if self._debouncer is not None:
            self._debouncer.cancel()
        for worker in (
            self._load_worker,
            self._scope_worker,
            self._picker_worker,
            self._restat_worker,
            self._strand_read_worker,
            self._history_worker,
            self._history_open_worker,
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

    # --- loading --------------------------------------------------------

    def _start_initial_load(self) -> None:
        self._loading = True
        self._update_header()
        self._render_note_card()
        self._update_footer()
        settings = getattr(self.app, "_current_project_settings", None)
        seed_from_current_project = getattr(settings, "seed_filters", True)

        def task() -> MemoryPanelInitialLoad:
            return load_memory_panel_initial_state(
                launch_workspace=self._launch_workspace,
                initial_scope_key=self._initial_scope_key,
                session_scope_key=self._session.scope_key,
                seed_from_current_project=seed_from_current_project,
            )

        self._load_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="memory-panel-load",
            exit_on_error=False,
        )

    def _start_scope_load(self) -> None:
        self._loading = True
        self._update_header()
        self._render_note_card()
        self._update_footer()
        ref = self._ring[self._scope_index]

        def task() -> MemoryScopeSnapshot:
            return load_memory_scope_snapshot(ref)

        self._scope_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="memory-panel-scope",
            exit_on_error=False,
        )

    def _start_scope_picker_load(self) -> None:
        if self._picker_worker is not None and not self._picker_worker.is_finished:
            return
        ring = self._ring

        def task() -> tuple[MemoryScopeChoice, ...]:
            return load_memory_scope_choices(ring)

        self._picker_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="memory-panel-scope-picker",
            exit_on_error=False,
        )

    def _start_restat(self, note: MemoryNote) -> None:
        if self._restat_worker is not None and not self._restat_worker.is_finished:
            self._restat_worker.cancel()
        if not self._ring:
            return
        scope = self._ring[self._scope_index]
        previous = (
            self._snapshot.digests.get(note.relative_path) if self._snapshot else None
        )

        def task() -> bool:
            return note_digest_changed(scope, note, previous)

        self._restat_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="memory-panel-restat",
            exit_on_error=False,
        )

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

    def _on_initial_load_state_changed(self, event: Worker.StateChanged) -> None:
        if self._closed or not self.is_mounted:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, MemoryPanelInitialLoad):
                return
            self._loading = False
            self._ring = result.ring
            self._scope_index = result.scope_index
            self._apply_snapshot(
                result.snapshot,
                preferred_note=self._preferred_note_for_snapshot(result.snapshot),
            )
            self._record_session_selection()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._ring = ()
            self._apply_snapshot(None, preferred_note=None)

    def _on_scope_load_state_changed(self, event: Worker.StateChanged) -> None:
        if self._closed or not self.is_mounted:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, MemoryScopeSnapshot):
                return
            if not self._ring or result.scope.key != self._ring[self._scope_index].key:
                return  # Stale: the user cycled again before this load landed.
            self._loading = False
            preferred = self._scope_selection_memory.get(result.scope.key)
            self._apply_snapshot(result, preferred_note=preferred)
            self._record_session_selection()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._update_header()
            self._render_note_card()
            self._update_footer()

    def _on_scope_picker_load_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state != WorkerState.SUCCESS:
            return
        if (
            self._closed
            or not self.is_mounted
            or not self._host_visible
            or not self._ring
        ):
            return
        result = event.worker.result
        if not isinstance(result, tuple):
            return
        current_key = self._ring[self._scope_index].key
        self.app.push_screen(
            MemoryScopePicker(result, current_key=current_key), self._on_scope_picked
        )

    def _on_scope_picked(self, key: str | None) -> None:
        if (
            key is None
            or self._closed
            or not self.is_mounted
            or not self._ring
            or self._loading
        ):
            return
        for index, ref in enumerate(self._ring):
            if ref.key != key:
                continue
            if index == self._scope_index:
                return
            if self._snapshot is not None:
                self._scope_selection_memory[self._snapshot.scope.key] = (
                    self._current_note or ""
                )
            self._scope_index = index
            self._record_session_selection()
            self._filter_input().value = ""
            self._filter_input().display = False
            self._trail = []
            self._chip_notes = ()
            self._chip_parent_count = 0
            self._chip_cursor = None
            self._expanded_webs.clear()
            self._start_scope_load()
            return

    def _on_restat_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state != WorkerState.SUCCESS:
            return
        if self._closed or not self.is_mounted:
            return
        changed = event.worker.result
        if not changed or self._loading or not self._ring:
            return
        if self._current_note is not None:
            self._scope_selection_memory[self._ring[self._scope_index].key] = (
                self._current_note
            )
        self._mark_scope_unpublished()
        self._start_scope_load()

    def _ensure_strand_read_for_current_selection(self) -> None:
        node = self._selected_row()
        if node is None or node.strand is None or node.web is None or not self._ring:
            return
        identity = node.identity
        state = self._strand_read_status.get(identity)
        if state in {"pending", "ok"} or (
            state is not None and state.startswith("error:")
        ):
            return
        if (
            self._strand_read_worker is not None
            and not self._strand_read_worker.is_finished
        ):
            old_identity = self._strand_read_worker_identity
            if (
                old_identity is not None
                and self._strand_read_status.get(old_identity) == "pending"
            ):
                self._strand_read_status.pop(old_identity, None)
            self._strand_read_worker.cancel()
        scope = self._ring[self._scope_index]
        web_slug = node.web.slug
        strand_slug = node.strand.slug
        self._strand_read_status[identity] = "pending"
        self._strand_read_worker_identity = identity

        def task() -> MemoryPanelStrandRead:
            return record_memory_panel_strand_read(
                scope,
                web_slug=web_slug,
                strand_slug=strand_slug,
            )

        self._strand_read_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="memory-panel-strand-read",
            exit_on_error=False,
        )

    def _on_strand_read_state_changed(self, event: Worker.StateChanged) -> None:
        identity = self._strand_read_worker_identity
        if identity is None:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, MemoryPanelStrandRead):
                self._strand_read_status[result.identity] = "ok"
        elif event.state == WorkerState.ERROR:
            detail = str(event.worker.error or "unknown error")
            self._strand_read_status[identity] = f"error:{detail}"
        elif event.state == WorkerState.CANCELLED:
            if self._strand_read_status.get(identity) == "pending":
                self._strand_read_status.pop(identity, None)
        if self._current_note == identity and self.is_mounted and not self._closed:
            self._render_note_card()
            self._update_footer()

    # --- memory history (phase memory-panel) ------------------------------

    def _history_enabled_for_panel(self) -> bool:
        from .memory_panel_history import history_enabled

        return history_enabled()

    def _history_service_or_none(self) -> Any | None:
        if self._history_service is not None:
            return self._history_service
        try:
            from sase.memory.history.service import HistoryService

            self._history_service = HistoryService()
            return self._history_service
        except Exception:
            return None

    def _history_key_for_node(
        self, node: Any | None
    ) -> tuple[str, str, Any, str] | None:
        """Return ``(scope_key, selector, panel_ref, selector)`` for *node*."""
        if node is None or not self._ring:
            return None
        # Web descriptor rows carry no History row: only notes and strands.
        if (
            getattr(node, "web", None) is not None
            and getattr(node, "strand", None) is None
        ):
            return None
        try:
            from .memory_panel_history import selector_for_node

            selector = selector_for_node(node)
        except Exception:
            return None
        if not selector:
            return None
        ref = self._ring[self._scope_index]
        return (ref.key, selector, ref, selector)

    def _history_renderable_for_node(self, node: Any | None) -> Any | None:
        """Return the History row value without blocking.

        Returns ``None`` when the row is omitted (flag off, web rows, or
        no selection). Otherwise returns the cached summary or a dim
        ``…`` placeholder and schedules the off-thread load.
        """
        from rich.text import Text

        if not self._history_enabled_for_panel():
            return None
        keyed = self._history_key_for_node(node)
        if keyed is None:
            return None
        scope_key, selector, _ref, _raw = keyed
        cached = self._history_latest.get((scope_key, selector))
        if cached is not None:
            try:
                from .memory_panel_history import history_value_text

                return history_value_text(cached, accent=self._accent)
            except Exception:
                return Text("…", style="dim")
        self._ensure_history_load(scope_key, selector)
        return Text("…", style="dim")

    def _ensure_history_load(self, scope_key: str, selector: str) -> None:
        if not self._ring or self._loading:
            return
        request = (scope_key, selector)
        if self._history_request == request:
            if (
                self._history_worker is not None
                and not self._history_worker.is_finished
            ):
                return
        try:
            ref = self._ring[self._scope_index]
        except IndexError:
            return
        if ref.key != scope_key:
            return
        self._history_request = request
        if self._history_worker is not None and not self._history_worker.is_finished:
            self._history_worker.cancel()

        def task() -> tuple[str, str, dict | None]:
            try:
                from .memory_panel_history import (
                    fetch_history_summary,
                    history_cache_key,
                    history_scope_for_panel_ref,
                )

                service = self._history_service_or_none()
                if service is None:
                    return (scope_key, selector, None)
                scope = history_scope_for_panel_ref(ref, service)
                if scope is None:
                    return (scope_key, selector, None)
                summary = fetch_history_summary(service, scope, selector)
                if summary is not None:
                    try:
                        self._history_cache[history_cache_key(summary)] = summary
                    except Exception:
                        pass
                return (scope_key, selector, summary)
            except Exception:
                return (scope_key, selector, None)

        self._history_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="memory-panel-history",
            exit_on_error=False,
        )

    def _on_history_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state != WorkerState.SUCCESS:
            if event.state == WorkerState.CANCELLED:
                self._history_request = None
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 3:
            return
        scope_key, selector, summary = result
        self._history_request = None
        if summary is not None:
            self._history_latest[(scope_key, selector)] = summary
        else:
            # Fail-open: keep the placeholder unless a cached value exists.
            if (scope_key, selector) in self._history_latest:
                pass
            else:
                # Record nothing; the placeholder stays until the next paint.
                pass
        if self._closed or not self.is_mounted:
            return
        current = self._history_key_for_node(self._selected_row())
        if current is None:
            return
        if (current[0], current[1]) != (scope_key, selector):
            return  # Stale: the user moved before this load landed.
        try:
            self._render_note_card()
        except Exception:
            pass

    def action_open_history(self) -> None:
        """Open the selected note, web, or strand in the pager at now."""
        from .memory_panel_history import (
            history_enabled,
            history_scope_for_panel_ref,
            selector_for_node,
        )

        if not history_enabled():
            self.notify(
                "memory history needs the memory_history beta",
                severity="warning",
            )
            return
        node = self._selected_row()
        if node is None or not self._ring:
            return
        selector = selector_for_node(node)
        if not selector:
            return
        ref = self._ring[self._scope_index]
        scope_key = ref.key
        identity = node.identity

        async def _open() -> None:
            import asyncio

            def _build() -> Any | None:
                try:
                    from sase.memory.history.pager_provider import (
                        build_history_document,
                    )
                    from sase.memory.history.cli_history import (
                        translate_history_selector,
                    )
                    from pathlib import Path

                    service = self._history_service_or_none()
                    if service is None:
                        return None
                    scope = history_scope_for_panel_ref(ref, service)
                    if scope is None:
                        return None
                    try:
                        core_selector = translate_history_selector(
                            selector, Path(str(getattr(scope, "repo_root", ".")))
                        )
                    except Exception:
                        core_selector = selector
                    return build_history_document(
                        scope=scope,
                        subject=core_selector,
                        initial_revision="now",
                        view="read",
                        service=service,
                        title=selector,
                    )
                except Exception:
                    return None

            document = await asyncio.to_thread(_build)
            if document is None:
                self.app.call_from_thread(
                    self.notify,
                    "could not open history for this selection",
                    severity="error",
                )
                return
            # Drop the open when the selection moved while loading.
            try:
                current = self._selected_row()
            except Exception:
                current = None
            if current is None or current.identity != identity:
                return
            if not self._ring or self._ring[self._scope_index].key != scope_key:
                return

            def _push() -> None:
                try:
                    from sase.pager.screen import PagerScreen
                    from sase.pager.syntax_policy import (
                        pager_syntax_session_from_config,
                    )

                    session = pager_syntax_session_from_config()
                    self.app.push_screen(
                        PagerScreen(
                            document,
                            links_enabled=True,
                            syntax_enabled=session.syntax_enabled,
                        )
                    )
                except Exception as exc:
                    self.notify(f"Could not open pager: {exc}", severity="error")

            self.app.call_from_thread(_push)

        self._history_open_worker = self.run_worker(
            _open(),
            exclusive=True,
            group="memory-panel-history-open",
            exit_on_error=False,
        )

    def action_open_changes(self) -> None:
        """Open the cross-file changes feed for the enabled scopes."""
        from .memory_panel_history import history_enabled

        if not history_enabled():
            self.notify(
                "memory history needs the memory_history beta",
                severity="warning",
            )
            return
        if not self._ring:
            return
        ring = tuple(self._ring)

        async def _open_feed() -> None:
            import asyncio

            def _build_feed() -> Any | None:
                try:
                    from sase.memory.history.feed_document import (
                        build_feed_document,
                        parse_feed_subject_target,
                        resolve_feed_subject,
                    )
                    from sase.pager.targets import LinkResolution

                    from .memory_panel_history import history_scopes_for_ring

                    service = self._history_service_or_none()
                    if service is None:
                        return None
                    scopes = history_scopes_for_ring(ring, service)
                    if not scopes:
                        return None
                    feed = service.feed(
                        scopes, since=None, limit=None, include_hidden=True
                    )
                    scopes_label = " + ".join(
                        str(getattr(scope, "scope_key", "") or "") for scope in scopes
                    )
                    result = build_feed_document(feed, scopes_label)
                    scopes_by_key = {
                        str(getattr(scope, "scope_key", "")): scope for scope in scopes
                    }

                    def _resolve_ref(
                        ref: str, *, context: Any | None = None
                    ) -> Any | None:
                        if parse_feed_subject_target(ref) is not None:
                            target = resolve_feed_subject(service, scopes_by_key, ref)
                            if target is not None:
                                return target
                            return LinkResolution(
                                unresolved_message=f"{ref} could not be resolved.",
                                retryable=False,
                            )
                        try:
                            from sase.pager.resolve import resolve_link

                            return resolve_link(ref, context=context)
                        except Exception as exc:
                            return LinkResolution(
                                unresolved_message=str(exc), retryable=False
                            )

                    def _refresh() -> Any | None:
                        try:
                            fresh = service.feed(
                                scopes,
                                since=None,
                                limit=None,
                                include_hidden=True,
                            )
                            return build_feed_document(fresh, scopes_label).document
                        except Exception:
                            return None

                    return (result.document, _resolve_ref, _refresh)
                except Exception:
                    return None

            built = await asyncio.to_thread(_build_feed)
            if built is None:
                self.app.call_from_thread(
                    self.notify,
                    "could not open the memory changes feed",
                    severity="error",
                )
                return

            def _push_feed() -> None:
                try:
                    from sase.pager.screen import PagerScreen
                    from sase.pager.syntax_policy import (
                        pager_syntax_session_from_config,
                    )

                    document, resolve_ref, refresh = built
                    session = pager_syntax_session_from_config()
                    self.app.push_screen(
                        PagerScreen(
                            document,
                            links_enabled=True,
                            resolve_ref_fn=resolve_ref,
                            syntax_enabled=session.syntax_enabled,
                            refresh_document_fn=refresh,
                        )
                    )
                except Exception as exc:
                    self.notify(f"Could not open pager: {exc}", severity="error")

            self.app.call_from_thread(_push_feed)

        self._history_open_worker = self.run_worker(
            _open_feed(),
            exclusive=True,
            group="memory-panel-history-open",
            exit_on_error=False,
        )

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
