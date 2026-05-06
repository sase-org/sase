"""Data loading helpers for the artifact panel modal."""

from __future__ import annotations

from typing import Any

from textual.widgets import Input

from sase.core.artifact_wire import (
    ArtifactDetailPagedWire,
    ArtifactNodeWire,
    ArtifactPageRequestWire,
    ArtifactQueryWire,
)

from .artifact_panel_state import (
    ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT,
    ArtifactPanelPagedModel,
    ArtifactPanelRow,
    page_request_for_group,
)


class ArtifactPanelDataMixin:
    def _navigate_to(self: Any, artifact_id: str) -> None:
        self._clear_search_state(render=False)
        if self._state.navigate_to(artifact_id):
            self._start_load(artifact_id)
        elif self._detail is not None:
            self._render_detail()

    def _clear_search_state(self: Any, *, render: bool = True) -> None:
        self._search_text = ""
        self._search_results: list[ArtifactNodeWire] | None = None
        self._search_error: str | None = None
        self._state.selected_row_id = None
        if self._search_worker is not None:
            self._search_worker.cancel()
            self._search_worker_query = "<cancelled>"
        try:
            search_input = self.query_one("#artifact-panel-search", Input)
        except Exception:
            search_input = None
        if search_input is not None and search_input.value:
            self._suppress_search_input = True
            try:
                search_input.value = ""
            finally:
                self._suppress_search_input = False
        if render and self._detail is not None:
            self._render_detail(update_preview=False)

    def _start_search(self: Any, query: str) -> None:
        self._search_text = query
        self._search_results = None
        self._search_error = None
        self._state.selected_row_id = None
        self._render_search_loading(query)
        if self._search_worker is not None:
            self._search_worker.cancel()
        self._search_worker_query = query
        self._search_worker = self.run_worker(
            lambda: (query, self._search_artifacts(query)),
            exit_on_error=False,
            thread=True,
        )

    def _search_artifacts(self: Any, query: str) -> list[ArtifactNodeWire]:
        search_func = self._search_func
        if search_func is None:
            from sase.core.artifact_facade import artifact_search

            search_func = artifact_search
        return search_func(
            self._index_path,
            ArtifactQueryWire(
                text=query,
                limit=ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT,
                offset=0,
            ),
        )

    def _start_page_load(self: Any, row: ArtifactPanelRow) -> None:
        if self._paged_model is None or row.group_key is None:
            return
        if self._page_worker is not None:
            self._page_worker.cancel()
        artifact_id = self._state.current_id
        prefer_row_id = row.id
        model = self._paged_model
        self._page_worker_artifact_id = artifact_id
        self._page_worker = self.run_worker(
            lambda: (
                artifact_id,
                prefer_row_id,
                self._load_relation_page(row, artifact_id=artifact_id, model=model),
            ),
            exit_on_error=False,
            thread=True,
        )

    def _load_relation_page(
        self: Any,
        row: ArtifactPanelRow,
        *,
        artifact_id: str,
        model: ArtifactPanelPagedModel,
    ) -> ArtifactDetailPagedWire:
        if model is None or row.group_key is None:
            raise RuntimeError("artifact page model is not loaded")
        request_parts = page_request_for_group(model, group_key=row.group_key)
        if request_parts is None:
            raise RuntimeError(f"unknown artifact relationship group {row.group_key}")
        relation, link_type, offset, limit = request_parts
        show_paged_func = self._show_paged_func
        if show_paged_func is None:
            from sase.core.artifact_facade import artifact_show_paged

            show_paged_func = artifact_show_paged
        return show_paged_func(
            self._index_path,
            artifact_id,
            ArtifactPageRequestWire(
                group_key=row.group_key,
                relation=relation,
                link_type=link_type,
                offset=offset,
                limit=limit,
            ),
        )
