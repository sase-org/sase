"""Unified artifact graph modal for ace."""

from __future__ import annotations

from pathlib import Path
import subprocess  # noqa: F401 - compatibility for existing monkeypatch paths.

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.core.artifact_wire import (
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactNodeWire,
    ArtifactPageRequestWire,
)

from .artifact_panel_modal_actions import ArtifactPanelActionsMixin
from .artifact_panel_modal_data import ArtifactPanelDataMixin
from .artifact_panel_modal_formatting import (
    _ARTIFACT_PANEL_NORMAL_HINTS,
    graph_preview_text,
    header_breadcrumb,
    header_counts,
    header_loading_primary,
    header_primary,
    row_label,
    state_message,
)
from .artifact_panel_modal_jump import ArtifactPanelJumpMixin
from .artifact_panel_modal_rendering import ArtifactPanelRenderingMixin
from .artifact_panel_modal_types import (
    ArtifactDetailRenderer,
    ArtifactExportFunc,
    ArtifactGraphFunc,
    ArtifactRefreshFunc,
    ArtifactSearchFunc,
    ArtifactShowFunc,
    ArtifactShowPagedFunc,
)
from .artifact_panel_state import (
    ArtifactPanelNavigationState,
    ArtifactPanelPagedModel,
    ArtifactPanelRow,
    merge_relation_page_into_model,
    paged_model_from_legacy_detail,
    paged_model_from_paged_detail,
)
from .base import FilterInput, OptionListNavigationMixin

_graph_preview_text = graph_preview_text
_header_breadcrumb = header_breadcrumb
_header_counts = header_counts
_header_loading_primary = header_loading_primary
_header_primary = header_primary
_row_label = row_label
_state_message = state_message


class ArtifactPanelModal(
    ArtifactPanelActionsMixin,
    ArtifactPanelDataMixin,
    ArtifactPanelJumpMixin,
    ArtifactPanelRenderingMixin,
    OptionListNavigationMixin,
    ModalScreen[None],
):
    """Modal that loads and displays one artifact graph node."""

    _option_list_id = "artifact-panel-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "open_selected", "Open"),
        ("apostrophe", "jump_to_entry", "Jump"),
        ("b", "back", "Back"),
        ("f", "forward", "Forward"),
        ("p", "parent", "Parent"),
        ("r", "root", "Root"),
        ("/", "focus_filter", "Filter"),
        ("S", "focus_global_search", "Search"),
        ("y", "copy_artifact_id", "Copy ID"),
        ("e", "open_file_in_editor", "Edit"),
        ("g", "preview_graph", "Graph"),
        ("G", "export_graph", "Export"),
        ("ctrl+d", "scroll_detail_down", "Scroll down"),
        ("ctrl+u", "scroll_detail_up", "Scroll up"),
    ]

    def __init__(
        self,
        *,
        artifact_id: str,
        index_path: Path | str | None = None,
        show_paged_func: ArtifactShowPagedFunc | None = None,
        show_func: ArtifactShowFunc | None = None,
        graph_func: ArtifactGraphFunc | None = None,
        export_func: ArtifactExportFunc | None = None,
        search_func: ArtifactSearchFunc | None = None,
        detail_renderer: ArtifactDetailRenderer | None = None,
        refresh_missing_func: ArtifactRefreshFunc | None = None,
        context_path: Path | str | None = None,
        artifact_dir: Path | str | None = None,
    ) -> None:
        super().__init__()
        self._artifact_id = artifact_id
        self._state = ArtifactPanelNavigationState(current_id=artifact_id)
        if index_path is None:
            from ..artifact_graph_refresh import default_artifact_index_path

            index_path = default_artifact_index_path()
        self._index_path = index_path
        self._show_paged_func = show_paged_func
        self._show_func = show_func
        self._graph_func = graph_func
        self._export_func = export_func
        self._search_func = search_func
        self._detail_renderer = detail_renderer
        self._refresh_missing_func = refresh_missing_func
        self._context_path = context_path
        self._context_artifact_dir = artifact_dir
        self._missing_refresh_attempted: set[str] = set()
        self._paged_model: ArtifactPanelPagedModel | None = None
        self._detail: ArtifactDetailWire | None = None
        self._error_message: str | None = None
        self._load_worker: Worker[ArtifactPanelPagedModel] | None = None
        self._page_worker: Worker[tuple[str, str, ArtifactDetailPagedWire]] | None = (
            None
        )
        self._search_worker: Worker[tuple[str, list[ArtifactNodeWire]]] | None = None
        self._render_worker: Worker[RenderableType] | None = None
        self._row_by_option_id: dict[str, ArtifactPanelRow] = {}
        self._search_text = ""
        self._search_results: list[ArtifactNodeWire] | None = None
        self._search_error: str | None = None
        self._suppress_search_input = False
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_row_id: dict[str, str] = {}
        self._entry_jump_row_id_to_hint: dict[str, str] = {}
        self._entry_jump_last_row_id: str | None = None

    def compose(self) -> ComposeResult:
        with Container(id="artifact-panel-container"):
            with Vertical(id="artifact-panel-header"):
                yield Static(
                    header_loading_primary(self._artifact_id),
                    id="artifact-panel-header-primary",
                )
                yield Static("Loading artifact...", id="artifact-panel-header-path")
                yield Static("", id="artifact-panel-header-counts")
            yield FilterInput(
                placeholder="Filter current artifact rows",
                id="artifact-panel-filter",
            )
            yield FilterInput(
                placeholder="Search all artifacts",
                id="artifact-panel-search",
            )
            with Horizontal(id="artifact-panel-body"):
                with Vertical(id="artifact-panel-left"):
                    yield OptionList(
                        Option("Loading artifact...", id="__loading__", disabled=True),
                        id="artifact-panel-list",
                    )
                with Vertical(id="artifact-panel-right"):
                    with VerticalScroll(id="artifact-panel-detail-scroll"):
                        yield Static("Loading artifact...", id="artifact-panel-detail")
            yield Static(
                _ARTIFACT_PANEL_NORMAL_HINTS,
                id="artifact-panel-hints",
            )

    def on_mount(self) -> None:
        """Start the initial artifact detail load."""
        self.query_one("#artifact-panel-list", OptionList).focus()
        self._start_load(self._state.current_id)

    def _start_load(self, artifact_id: str) -> None:
        self._artifact_id = artifact_id
        self._render_loading()
        if self._load_worker is not None:
            self._load_worker.cancel()
        if self._render_worker is not None:
            self._render_worker.cancel()
        if self._page_worker is not None:
            self._page_worker.cancel()
        if self._search_worker is not None:
            self._search_worker.cancel()
        self._clear_search_state(render=False)
        self._load_worker = self.run_worker(
            lambda: self._load_detail(artifact_id),
            exit_on_error=False,
            thread=True,
        )

    def _load_detail(self, artifact_id: str) -> ArtifactPanelPagedModel:
        model = self._show_paged_model(artifact_id)
        if (
            model.detail.node is not None
            or artifact_id in self._missing_refresh_attempted
        ):
            return model

        self._missing_refresh_attempted.add(artifact_id)
        refresh_func = self._refresh_missing_func
        if refresh_func is None:
            from ..artifact_graph_refresh import (
                refresh_artifact_graph_for_missing_artifact,
            )

            def refresh_func(
                index_path: Path | str,
                artifact_id: str,
                context_path: Path | str | None,
                artifact_dir: Path | str | None,
            ) -> None:
                refresh_artifact_graph_for_missing_artifact(
                    index_path,
                    artifact_id,
                    context_path=context_path,
                    artifact_dir=artifact_dir,
                )

        refresh_func(
            self._index_path,
            artifact_id,
            self._context_path,
            self._context_artifact_dir,
        )
        return self._show_paged_model(artifact_id)

    def _show_paged_model(self, artifact_id: str) -> ArtifactPanelPagedModel:
        show_func = self._show_func
        if show_func is not None:
            return paged_model_from_legacy_detail(
                show_func(self._index_path, artifact_id)
            )

        show_paged_func = self._show_paged_func
        if show_paged_func is None:
            from sase.core.artifact_facade import artifact_show_paged

            show_paged_func = artifact_show_paged
        paged_detail = show_paged_func(
            self._index_path,
            artifact_id,
            ArtifactPageRequestWire(),
        )
        return paged_model_from_paged_detail(paged_detail)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Render the artifact load result."""
        if event.worker == self._load_worker:
            self._handle_load_worker_state(event)
        elif event.worker == self._page_worker:
            self._handle_page_worker_state(event)
        elif event.worker == self._search_worker:
            self._handle_search_worker_state(event)
        elif event.worker == self._render_worker:
            self._handle_render_worker_state(event)

    def _handle_load_worker_state(self, event: Worker.StateChanged) -> None:
        if event.worker != self._load_worker:
            return

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            assert result is not None
            self._paged_model = result
            self._detail = result.detail
            self._state.set_paged_model(result)
            self._error_message = None
            self._render_detail()
        elif event.state == WorkerState.ERROR:
            self._paged_model = None
            self._detail = None
            self._state.detail = None
            self._state.paged_model = None
            self._error_message = str(event.worker.error or "Unknown artifact error")
            self._render_error()

    def _handle_render_worker_state(self, event: Worker.StateChanged) -> None:
        if event.worker != self._render_worker:
            return

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            assert result is not None
            self._update_detail(result)
        elif event.state == WorkerState.ERROR:
            message = str(event.worker.error or "Unknown artifact render error")
            text = Text()
            text.append("Artifact preview failed\n", style="bold yellow")
            text.append(message, style="yellow")
            self._update_detail(text)

    def _handle_page_worker_state(self, event: Worker.StateChanged) -> None:
        if event.worker != self._page_worker:
            return

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            assert result is not None
            artifact_id, prefer_row_id, page_detail = result
            if artifact_id != self._state.current_id or self._paged_model is None:
                return
            self._paged_model = merge_relation_page_into_model(
                self._paged_model,
                page_detail,
            )
            self._detail = self._paged_model.detail
            self._state.set_paged_model(self._paged_model)
            self._state.selected_row_id = prefer_row_id
            self._render_detail(update_preview=False)
        elif event.state == WorkerState.ERROR:
            message = str(event.worker.error or "Unknown artifact page error")
            self.app.notify(
                f"Failed to load more artifacts: {message}", severity="error"
            )

    def _handle_search_worker_state(self, event: Worker.StateChanged) -> None:
        if event.worker != self._search_worker:
            return

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            assert result is not None
            query, nodes = result
            if query != self._search_text:
                return
            self._search_results = nodes
            self._search_error = None
            self._render_search_options()
        elif event.state == WorkerState.ERROR:
            self._search_results = None
            self._search_error = str(
                event.worker.error or "Unknown artifact search error"
            )
            self._render_search_options()
