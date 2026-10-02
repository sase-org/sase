"""Worker-backed loads for the Memory pane.

Owns the initial scope load, scope cycling, the scope picker, restat checks,
and audited strand reads behind :class:`MemoryPane`. Method calls reach the
rest of the widget through ``self``; this module imports no ``_``-prefixed
names from its sibling pane modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.ace.tui.memory_panel_catalog import (
    MemoryScopeSnapshot,
    load_memory_scope_snapshot,
)
from sase.memory.notes import MemoryNote

from .memory_panel_load import (
    MemoryPanelInitialLoad,
    MemoryPanelStrandRead,
    MemoryScopeChoice,
    load_memory_panel_initial_state,
    load_memory_scope_choices,
    note_digest_changed,
    record_memory_panel_strand_read,
)
from .memory_panel_scope_picker import MemoryScopePicker

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase

    from .memory_pane import MemoryPaneSession
else:
    _MixinBase = object


class MemoryPaneLoadingMixin(_MixinBase):
    """Initial/scope/picker/restat/strand-read workers for ``MemoryPane``."""

    if TYPE_CHECKING:
        _chip_cursor: int | None
        _chip_notes: tuple[Any, ...]
        _chip_parent_count: int
        _closed: bool
        _current_note: str | None
        _expanded_webs: set[str]
        _history_failed: set[tuple[str, str]]
        _history_worker: Worker[tuple[str, str, dict | None]] | None
        _host_visible: bool
        _launch_workspace: str | None
        _initial_scope_key: str | None
        _load_worker: Worker[MemoryPanelInitialLoad] | None
        _loading: bool
        _picker_worker: Worker[tuple[MemoryScopeChoice, ...]] | None
        _restat_worker: Worker[bool] | None
        _ring: tuple[Any, ...]
        _scope_index: int
        _scope_selection_memory: dict[str, str]
        _scope_worker: Worker[MemoryScopeSnapshot] | None
        _session: MemoryPaneSession
        _snapshot: MemoryScopeSnapshot | None
        _strand_read_status: dict[str, str]
        _strand_read_worker: Worker[MemoryPanelStrandRead] | None
        _strand_read_worker_identity: str | None
        _trail: list[str]

        def _apply_snapshot(
            self, snapshot: MemoryScopeSnapshot | None, *, preferred_note: str | None
        ) -> None: ...

        def _expand_web_for_identity(
            self, identity: str, snapshot: MemoryScopeSnapshot | None
        ) -> None: ...

        def _filter_input(self) -> Any: ...

        def _history_invalidate_scope_key(
            self, scope_key: str, *, clear_failures: bool = False
        ) -> None: ...

        def _mark_scope_unpublished(self, scope_key: str | None = None) -> None: ...

        def _on_history_state_changed(self, event: Worker.StateChanged) -> None: ...

        def _preferred_note_for_snapshot(
            self, snapshot: MemoryScopeSnapshot | None
        ) -> str | None: ...

        def _record_session_selection(self) -> None: ...

        def _render_note_card(self) -> None: ...

        def _reset_strand_read_state(self) -> None: ...

        def _selected_row(self) -> Any | None: ...

        def _snapshot_identities(
            self, snapshot: MemoryScopeSnapshot | None
        ) -> set[str]: ...

        def _update_footer(self) -> None: ...

        def _update_header(self) -> None: ...

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

    def _on_initial_load_state_changed(self, event: Worker.StateChanged) -> None:
        if self._closed or not self.is_mounted:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, MemoryPanelInitialLoad):
                return
            self._loading = False
            self._history_failed.clear()
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
            self._history_failed.clear()
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
        # Returning from $EDITOR may have rewritten the note or the git
        # state behind it: invalidate memoized history before the reload
        # refetches the visible subject.
        self._history_invalidate_scope_key(self._ring[self._scope_index].key)
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
