"""Catalog-backed list and lifecycle for the Artifacts Chats pane."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from rich.console import RenderableType
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import OptionList, Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry
from sase.ace.tui.util.pump_tasks import (
    cancel_pump_free_tasks,
    spawn_pump_free_task,
)
from sase.core.time import local_now
from sase.history.chat_catalog_provenance import (
    ChatCatalogEntry,
    ChatCatalogSnapshot,
    load_chat_catalog,
)

from .chats_data import CHATS_FIRST_PAGE_LIMIT, ChatsSnapshot, pane_snapshot
from .chats_list import build_chat_options
from .chats_navigation import ChatsNavigationMixin, ChatsOptionList
from .chats_rendering import (
    build_chats_hints,
    build_chats_scope,
    build_chats_status,
)
from .entry_navigation import ArtifactEntryTarget
from .lifecycle import ArtifactsPaneLifecycle


class ArtifactsChatsPane(ChatsNavigationMixin, ArtifactsPaneLifecycle, Vertical):
    """Browse date-grouped chat transcripts without blocking the event loop."""

    can_focus = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._snapshot: ChatsSnapshot | None = None
        self._loading = False
        self._loading_full = False
        self._reload_pending = False
        self._pending_force = False
        self._pending_full = False
        self._load_error: str | None = None
        self._worker: Worker[Any] | None = None
        self._worker_generation = -1
        self._worker_full = False
        self._load_generation = 0
        self._extension_generation = 0
        self._init_chats_navigation()

    def compose(self) -> ComposeResult:
        yield Static("", id="chats-filter-bar", classes="hidden")
        yield Static(
            self._scope_text(),
            classes="artifacts-pane-info",
            id="chats-info",
        )
        with Horizontal(id="chats-panels"):
            list_panel = Vertical(id="chats-list-panel")
            list_panel.border_title = "Chats"
            with list_panel:
                yield Static("No chat transcripts found.", id="chats-empty")
                yield Static(self._status_text(), id="chats-status")
                yield ChatsOptionList(id="chats-list")
            detail_panel = Vertical(id="chats-detail-panel")
            detail_panel.border_title = "Details"
            with detail_panel:
                with VerticalScroll(id="chats-detail-scroll"):
                    yield Static("", id="chats-detail")
        yield Static(self._hints_text(), id="chats-hints")

    def on_mount(self) -> None:
        self._refresh_options()

    def on_unmount(self) -> None:
        self._extension_generation += 1
        cancel_pump_free_tasks(self)
        if self._worker is not None and not self._worker.is_finished:
            self._worker.cancel()

    def on_first_activate(self) -> None:
        self._request_load(force=False, full=False)

    def on_activate(self) -> None:
        self.focus_list()
        if not self._loading and (
            self._snapshot is None or self._snapshot.project != self.project_scope
        ):
            self._request_load(force=False, full=False)

    def on_refresh(self) -> None:
        self._request_load(force=True, full=False)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use the active registry for pane-scoped key hints."""

        self._registry = registry
        self._update_static("#chats-info", self._scope_text())
        self._update_static("#chats-hints", self._hints_text())

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        """Update the shared project scope and lazily replace stale rows."""

        changed = project != self.project_scope
        self.project_scope = project
        self._project_display_name = display_name
        self._update_static("#chats-info", self._scope_text())
        if not changed:
            return
        self._load_generation += 1
        self._extension_generation += 1
        self._load_error = None
        if self.artifacts_active:
            self._request_load(force=False, full=False)
        else:
            self._refresh_options()

    @property
    def snapshot(self) -> ChatsSnapshot | None:
        return self._snapshot

    @property
    def selected_entry(self) -> ChatCatalogEntry | None:
        row = self.selected_row()
        return None if row is None else row.entry

    def _request_load(self, *, force: bool, full: bool) -> None:
        """Coalesce one off-thread load with last-request-wins semantics."""

        if self._loading:
            self._reload_pending = True
            self._pending_force = self._pending_force or force
            self._pending_full = self._pending_full or full
            return

        project = self.project_scope
        generation = self._load_generation
        requested_limit = None if full else CHATS_FIRST_PAGE_LIMIT
        self._loading = True
        self._loading_full = full
        self._load_error = None
        if self._snapshot is None or self._snapshot.project != project:
            self._refresh_options()
        else:
            self._update_status()

        def task() -> ChatsSnapshot:
            catalog = load_chat_catalog(
                limit=requested_limit,
                project=project,
                force=force,
            )
            return pane_snapshot(
                project,
                catalog,
                requested_limit=requested_limit,
            )

        worker = self.run_worker(
            task,
            thread=True,
            exclusive=False,
            exit_on_error=False,
        )
        self._worker = worker
        self._worker_generation = generation
        self._worker_full = full

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        terminal = event.state in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }
        full_request = self._worker_full
        generation = self._worker_generation
        if event.state == WorkerState.SUCCESS:
            self._loading = False
            self._loading_full = False
            result = event.worker.result
            if (
                isinstance(result, ChatsSnapshot)
                and generation == self._load_generation
                and result.project == self.project_scope
            ):
                preferred = self.selected_entry_target()
                cancel_jump = getattr(
                    self.app,
                    "_cancel_artifacts_jump_mode_for_model_change",
                    None,
                )
                if callable(cancel_jump):
                    cancel_jump("chats")
                self._snapshot = result
                self._load_error = None
                self._refresh_options(preferred_target=preferred)
                if not full_request and not result.complete:
                    self._schedule_full_extension(generation)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._loading_full = False
            self._load_error = str(event.worker.error or "Chats load failed")
            self._update_status()
        elif event.state == WorkerState.CANCELLED:
            self._loading = False
            self._loading_full = False

        if terminal and self._reload_pending:
            force = self._pending_force
            full = self._pending_full
            self._reload_pending = False
            self._pending_force = False
            self._pending_full = False
            self.call_later(lambda: self._request_load(force=force, full=full))

    @on(OptionList.OptionHighlighted, "#chats-list")
    def _on_option_highlighted(self, _event: OptionList.OptionHighlighted) -> None:
        if self._syncing_options:
            return

    @on(OptionList.OptionSelected, "#chats-list")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        cast(Any, self.app).action_chats_view_selected()

    def _schedule_full_extension(self, generation: int) -> None:
        """Yield first paint, then request the unbounded cached extension."""

        self._extension_generation += 1
        extension_generation = self._extension_generation

        async def extend() -> None:
            await asyncio.sleep(0)
            if (
                extension_generation != self._extension_generation
                or generation != self._load_generation
                or not self.artifacts_active
            ):
                return
            self._request_load(force=False, full=True)

        spawn_pump_free_task(
            self,
            extend(),
            name="sase-artifacts-chats-full-extension",
            registry_attr="_chats_extension_tasks",
        )

    def _refresh_options(
        self,
        *,
        preferred_target: ArtifactEntryTarget | None = None,
    ) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        if preferred_target is None:
            preferred_target = self.selected_entry_target()
        options, rows = build_chat_options(
            self._snapshot,
            project_scope=self.project_scope,
            loading=self._loading,
            now=local_now(),
            jump_hints=self._entry_jump_hints,
        )
        self._rows = rows
        highlighted = self._option_index_for_target(preferred_target)
        if highlighted is None:
            highlighted = next(
                (index for index, option in enumerate(options) if not option.disabled),
                None,
            )
        self._syncing_options = True
        try:
            option_list.replace_options(options, highlighted=highlighted)
        finally:
            self._syncing_options = False
        self._update_empty()
        self._update_status()

    def _update_empty(self) -> None:
        if not self.is_mounted:
            return
        empty = self.query_one("#chats-empty", Static)
        option_list = self.query_one("#chats-list", ChatsOptionList)
        has_current_snapshot = (
            self._snapshot is not None and self._snapshot.project == self.project_scope
        )
        show_empty = has_current_snapshot and not self._rows and not self._loading
        empty.display = show_empty
        option_list.display = not show_empty

    def _update_status(self) -> None:
        self._update_static("#chats-status", self._status_text())

    def _update_static(self, selector: str, content: RenderableType) -> None:
        if self.is_mounted:
            self.query_one(selector, Static).update(content)

    def _scope_text(self) -> RenderableType:
        return build_chats_scope(
            self._registry,
            project_scope=self.project_scope,
            project_display_name=self._project_display_name,
        )

    def _status_text(self) -> RenderableType:
        catalog: ChatCatalogSnapshot | None = (
            None if self._snapshot is None else self._snapshot.catalog
        )
        return build_chats_status(
            catalog,
            loading=self._loading,
            load_error=self._load_error,
            extending=self._loading_full,
        )

    def _hints_text(self) -> RenderableType:
        return build_chats_hints(self._registry)


__all__ = ["ArtifactsChatsPane"]
