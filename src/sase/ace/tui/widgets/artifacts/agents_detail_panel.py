"""Debounced detail-panel loading and rendering for the Agent pane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.agents.catalog import AgentCatalogRow

from .agents_detail import (
    AgentDetailCacheKey,
    AgentDetailData,
    build_agent_detail,
    load_agent_detail,
)

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class AgentsDetailMixin(_MixinBase):
    """Own the detail worker, its cache, and the rendered detail panel."""

    _detail_debouncer: DetailPanelDebouncer | None
    _detail_worker: Worker[Any] | None
    _detail_worker_generation: int
    _detail_generation: int
    _detail_cache: dict[AgentDetailCacheKey, AgentDetailData]
    _detail_keys_by_name: dict[str, AgentDetailCacheKey]

    if TYPE_CHECKING:

        def selected_row(self) -> Any: ...

        def refresh_relation_panel(self, *, refresh_footer: bool = True) -> Any: ...

    def _init_agents_detail(self) -> None:
        self._detail_debouncer = None
        self._detail_worker = None
        self._detail_worker_generation = -1
        self._detail_generation = 0
        self._detail_cache = {}
        self._detail_keys_by_name = {}

    def _start_detail_debouncer(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)

    def _cancel_detail_debouncer(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def _cancel_detail_worker(self) -> None:
        if self._detail_worker is not None and not self._detail_worker.is_finished:
            self._detail_worker.cancel()

    def _invalidate_detail_cache(self) -> None:
        """Drop every cached detail and retire any in-flight load."""

        self._detail_generation += 1
        self._cancel_detail_worker()
        self._detail_cache.clear()
        self._detail_keys_by_name.clear()

    def _selected_entry(self) -> AgentCatalogRow | None:
        row = self.selected_row()
        return None if row is None else row.entry

    def _schedule_detail(self) -> None:
        self._render_detail(loading=True)
        entry = self._selected_entry()
        if entry is None or self._detail_for(entry) is not None:
            self._render_detail(loading=False)
            return
        if self._detail_debouncer is None:
            self._request_detail()
        else:
            self._detail_debouncer.schedule(self._request_detail)

    def _request_detail(self) -> None:
        entry = self._selected_entry()
        if entry is None or self._detail_for(entry) is not None:
            self._render_detail(loading=False)
            return

        def task() -> AgentDetailData:
            return load_agent_detail(entry)

        self._detail_worker = self.run_worker(
            task,
            thread=True,
            group="artifacts-agents-detail",
            exclusive=True,
            exit_on_error=False,
        )
        self._detail_worker_generation = self._detail_generation

    def _on_detail_worker_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if (
                isinstance(result, AgentDetailData)
                and self._detail_worker_generation == self._detail_generation
            ):
                self._detail_cache[result.cache_key] = result
                self._detail_keys_by_name[result.name] = result.cache_key
                entry = self._selected_entry()
                if entry is not None and entry.name == result.name:
                    self._render_detail(loading=False)
        elif event.state == WorkerState.ERROR:
            self._render_detail(loading=False)

    def _detail_for(self, entry: AgentCatalogRow) -> AgentDetailData | None:
        key = self._detail_keys_by_name.get(entry.name)
        return None if key is None else self._detail_cache.get(key)

    def _render_detail(self, *, loading: bool) -> None:
        if not self.is_mounted:
            return
        entry = self._selected_entry()
        detail = None if entry is None else self._detail_for(entry)
        self.query_one("#agents-detail", Static).update(
            build_agent_detail(entry, detail, loading=loading and detail is None)
        )
        self.refresh_relation_panel()


__all__ = ["AgentsDetailMixin"]
