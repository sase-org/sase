"""Unified artifact graph modal for ace."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import subprocess

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.hints import build_editor_args
from sase.core.artifact_wire import (
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactPageRequestWire,
)

from .artifact_panel_state import (
    ARTIFACT_PANEL_SHOW_MORE_ACTION,
    ArtifactPanelPagedModel,
    ArtifactPanelNavigationState,
    ArtifactPanelRow,
    build_artifact_panel_rows,
    merge_relation_page_into_model,
    page_request_for_group,
    paged_model_from_legacy_detail,
    paged_model_from_paged_detail,
    parent_id_from_detail,
)
from .artifact_panel_renderers import (
    render_artifact_detail,
)
from .base import FilterInput, OptionListNavigationMixin

ArtifactShowFunc = Callable[[Path | str, str], ArtifactDetailWire]
ArtifactShowPagedFunc = Callable[
    [Path | str, str, ArtifactPageRequestWire | None], ArtifactDetailPagedWire
]
ArtifactGraphFunc = Callable[[Path | str, ArtifactGraphOptionsWire], ArtifactGraphWire]
ArtifactExportFunc = Callable[[Path | str, ArtifactGraphOptionsWire, str], str]
ArtifactDetailRenderer = Callable[[ArtifactDetailWire], RenderableType]
ArtifactRefreshFunc = Callable[
    [Path | str, str, Path | str | None, Path | str | None], None
]


class ArtifactPanelModal(OptionListNavigationMixin, ModalScreen[None]):
    """Modal that loads and displays one artifact graph node."""

    _option_list_id = "artifact-panel-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "open_selected", "Open"),
        ("b", "back", "Back"),
        ("f", "forward", "Forward"),
        ("p", "parent", "Parent"),
        ("r", "root", "Root"),
        ("/", "focus_filter", "Filter"),
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
        self._render_worker: Worker[RenderableType] | None = None
        self._row_by_option_id: dict[str, ArtifactPanelRow] = {}

    def compose(self) -> ComposeResult:
        with Container(id="artifact-panel-container"):
            with Vertical(id="artifact-panel-header"):
                yield Static(
                    _header_loading_primary(self._artifact_id),
                    id="artifact-panel-header-primary",
                )
                yield Static("Loading artifact...", id="artifact-panel-header-path")
                yield Static("", id="artifact-panel-header-counts")
            yield FilterInput(
                placeholder="Filter current artifact rows",
                id="artifact-panel-filter",
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
                "j/k: move  enter: open  b/f: history  p/r: parent/root  /: filter  y: copy  e: edit  g/G: graph  q/Esc: close",
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

    def _render_loading(self) -> None:
        self._row_by_option_id = {}
        self._update_header_loading()
        self._replace_options(
            [Option("Loading artifact...", id="__loading__", disabled=True)]
        )
        self._update_detail("Loading artifact...")

    def _render_error(self) -> None:
        message = self._error_message or "Artifact could not be loaded."
        self._row_by_option_id = {}
        if self._render_worker is not None:
            self._render_worker.cancel()
        self._update_header_error(message)
        self._replace_options([Option("Load failed", id="__error__", disabled=True)])
        text = Text()
        text.append("Artifact load failed\n", style="bold red")
        text.append(message, style="red")
        self._update_detail(text)

    def _render_detail(self, *, update_preview: bool = True) -> None:
        detail = self._detail
        if detail is None or detail.node is None:
            self._update_header_missing(self._artifact_id)
            self._replace_options([Option("Artifact not found", disabled=True)])
            self._update_detail(f"Artifact not found: {self._artifact_id}")
            return

        self._update_header(detail, self._paged_model)

        self._replace_options(
            self._build_options(detail), prefer_row_id=self._state.selected_row_id
        )
        if update_preview:
            self._start_detail_render(detail)

    def _build_options(self, detail: ArtifactDetailWire) -> list[Option]:
        options: list[Option] = []
        self._row_by_option_id = {}
        panel_rows = build_artifact_panel_rows(
            detail,
            paged_model=self._paged_model,
            filter_text=self._state.filter_text,
        )
        for row in panel_rows.rows:
            option = Option(
                _row_label(row),
                id=row.id,
                disabled=not row.selectable,
            )
            options.append(option)
            if row.selectable:
                self._row_by_option_id[row.id] = row
        if not options:
            message = (
                "No rows match the current filter"
                if self._state.filter_text
                else "No linked artifacts"
            )
            options.append(Option(message, disabled=True))
        return options

    def _build_detail_renderable(self, detail: ArtifactDetailWire) -> RenderableType:
        renderer = self._detail_renderer or render_artifact_detail
        return renderer(detail)

    def _start_detail_render(self, detail: ArtifactDetailWire) -> None:
        if self._render_worker is not None:
            self._render_worker.cancel()
        self._update_detail("Rendering artifact preview...")
        self._render_worker = self.run_worker(
            lambda: self._build_detail_renderable(detail),
            exit_on_error=False,
            thread=True,
        )

    def _replace_options(
        self,
        options: list[Option],
        *,
        prefer_row_id: str | None = None,
    ) -> None:
        option_list = self.query_one("#artifact-panel-list", OptionList)
        option_list.clear_options()
        option_list.add_options(options)
        self._highlight_first_selectable(option_list, prefer_row_id=prefer_row_id)

    def _update_detail(self, content: RenderableType) -> None:
        self.query_one("#artifact-panel-detail", Static).update(content)

    def _update_header_loading(self) -> None:
        self.query_one("#artifact-panel-header-primary", Static).update(
            _header_loading_primary(self._state.current_id)
        )
        self.query_one("#artifact-panel-header-path", Static).update(
            "Loading artifact..."
        )
        self.query_one("#artifact-panel-header-counts", Static).update("")

    def _update_header_error(self, message: str) -> None:
        primary = Text()
        primary.append("[ARTIFACT] ", style="bold")
        primary.append(self._state.current_id)
        primary.append("  load failed", style="red")
        self.query_one("#artifact-panel-header-primary", Static).update(primary)
        self.query_one("#artifact-panel-header-path", Static).update(message)
        self.query_one("#artifact-panel-header-counts", Static).update("")

    def _update_header_missing(self, artifact_id: str) -> None:
        primary = Text()
        primary.append("[ARTIFACT] ", style="bold")
        primary.append(artifact_id)
        primary.append("  not found", style="yellow")
        self.query_one("#artifact-panel-header-primary", Static).update(primary)
        self.query_one("#artifact-panel-header-path", Static).update("")
        self.query_one("#artifact-panel-header-counts", Static).update("")

    def _update_header(
        self,
        detail: ArtifactDetailWire,
        paged_model: ArtifactPanelPagedModel | None,
    ) -> None:
        assert detail.node is not None
        self.query_one("#artifact-panel-header-primary", Static).update(
            _header_primary(detail.node)
        )
        self.query_one("#artifact-panel-header-path", Static).update(
            _header_breadcrumb(detail)
        )
        self.query_one("#artifact-panel-header-counts", Static).update(
            _header_counts(paged_model)
        )

    def _highlight_first_selectable(
        self,
        option_list: OptionList,
        *,
        prefer_row_id: str | None = None,
    ) -> None:
        preferred: int | None = None
        fallback: int | None = None
        for index in range(option_list.option_count):
            option = option_list.get_option_at_index(index)
            if option.disabled:
                continue
            if fallback is None:
                fallback = index
            if option.id == prefer_row_id:
                preferred = index
                break
        option_list.highlighted = preferred if preferred is not None else fallback

    def _highlighted_row(self) -> ArtifactPanelRow | None:
        option_list = self.query_one("#artifact-panel-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        option = option_list.get_option_at_index(highlighted)
        if option.id is None:
            return None
        return self._row_by_option_id.get(option.id)

    def _navigate_to(self, artifact_id: str) -> None:
        if self._state.navigate_to(artifact_id):
            self._start_load(artifact_id)
        elif self._detail is not None:
            self._render_detail()

    def _start_page_load(self, row: ArtifactPanelRow) -> None:
        if self._paged_model is None or row.group_key is None:
            return
        if self._page_worker is not None:
            self._page_worker.cancel()
        artifact_id = self._state.current_id
        prefer_row_id = row.id
        self._page_worker = self.run_worker(
            lambda: (
                artifact_id,
                prefer_row_id,
                self._load_relation_page(row),
            ),
            exit_on_error=False,
            thread=True,
        )

    def _load_relation_page(self, row: ArtifactPanelRow) -> ArtifactDetailPagedWire:
        model = self._paged_model
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
            self._state.current_id,
            ArtifactPageRequestWire(
                group_key=row.group_key,
                relation=relation,
                link_type=link_type,
                offset=offset,
                limit=limit,
            ),
        )

    def action_open_selected(self) -> None:
        row = self._highlighted_row()
        if row is None:
            return
        if row.page_action == ARTIFACT_PANEL_SHOW_MORE_ACTION:
            self._state.selected_row_id = row.id
            self._start_page_load(row)
            return
        if row.artifact_id is None:
            return
        self._state.selected_row_id = row.id
        self._navigate_to(row.artifact_id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_open_selected()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        option_id = event.option.id
        if option_id in self._row_by_option_id:
            self._state.selected_row_id = option_id

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "artifact-panel-filter":
            return
        self._state.set_filter(event.value)
        if self._detail is not None:
            self._render_detail(update_preview=False)

    def action_focus_filter(self) -> None:
        self.query_one("#artifact-panel-filter", Input).focus()

    def action_back(self) -> None:
        artifact_id = self._state.back()
        if artifact_id is not None:
            self._start_load(artifact_id)

    def action_forward(self) -> None:
        artifact_id = self._state.forward()
        if artifact_id is not None:
            self._start_load(artifact_id)

    def action_parent(self) -> None:
        detail = self._detail
        if detail is None:
            return
        parent_id = parent_id_from_detail(detail, self._state.current_id)
        if parent_id is not None:
            self._navigate_to(parent_id)

    def action_root(self) -> None:
        self._navigate_to("/")

    def action_copy_artifact_id(self) -> None:
        from ..actions.clipboard import copy_to_system_clipboard

        if copy_to_system_clipboard(self._state.current_id):
            self.app.notify("Copied artifact ID")
        else:
            self.app.notify("Failed to copy artifact ID", severity="error")

    def action_open_file_in_editor(self) -> None:
        detail = self._detail
        if detail is None or detail.node is None or detail.node.kind != "file":
            self.app.notify("Current artifact is not a file", severity="warning")
            return
        path = detail.node.metadata.get("path") or detail.node.id
        expanded = os.path.expanduser(str(path))
        if not os.path.isfile(expanded):
            self.app.notify("File artifact path not found", severity="warning")
            return
        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [expanded])
        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

    def action_preview_graph(self) -> None:
        options = ArtifactGraphOptionsWire(root_id=self._state.current_id, limit=100)
        if self._graph_func is None:
            from sase.core.artifact_facade import artifact_graph

            graph = artifact_graph(self._index_path, options)
        else:
            graph = self._graph_func(self._index_path, options)
        self._update_detail(_graph_preview_text(graph))

    def action_export_graph(self) -> None:
        options = ArtifactGraphOptionsWire(root_id=self._state.current_id, limit=100)
        if self._export_func is None:
            from sase.core.artifact_facade import artifact_export

            exported = artifact_export(self._index_path, options, "mermaid")
        else:
            exported = self._export_func(self._index_path, options, "mermaid")
        self._update_detail(exported)

    def action_scroll_detail_down(self) -> None:
        self.query_one("#artifact-panel-detail-scroll", VerticalScroll).scroll_down(
            animate=False
        )

    def action_scroll_detail_up(self) -> None:
        self.query_one("#artifact-panel-detail-scroll", VerticalScroll).scroll_up(
            animate=False
        )


def _row_label(row: ArtifactPanelRow) -> Text:
    if not row.selectable:
        text = Text(row.label)
        text.stylize("bold cyan" if row.row_type == "group" else "yellow")
        return text
    if row.page_action == ARTIFACT_PANEL_SHOW_MORE_ACTION:
        text = Text(row.label)
        text.stylize("bold cyan")
        return text

    badge = _semantic_badge(row.artifact_kind, row.file_type)
    text = Text()
    text.append(f"[{badge}] ", style="bold")
    text.append(row.title or row.label)
    compact_subtitle = " · ".join(
        part for part in (row.subtitle, row.updated_label) if part
    )
    if compact_subtitle:
        text.append(f"  {compact_subtitle}", style="dim")
    right_side = " · ".join(
        part for part in (row.artifact_id, row.status_label) if part
    )
    if right_side:
        text.append(f"  {right_side}", style="dim")
    if row.row_type == "path":
        text.stylize("dim")
    elif row.row_type in {"outbound", "inbound"}:
        text.stylize("bold", 0, len(f"[{badge}]"))
        if row.edge_direction:
            text.append(f"  {row.edge_direction}", style="dim")
    return text


def _header_loading_primary(artifact_id: str) -> Text:
    text = Text()
    text.append("[ARTIFACT] ", style="bold")
    text.append(artifact_id)
    return text


def _header_primary(node: object) -> Text:
    kind = str(getattr(node, "kind", "") or "")
    metadata = getattr(node, "metadata", {}) or {}
    file_type = metadata.get("artifact_type")
    badge = _semantic_badge(kind, str(file_type) if file_type else None)
    title = str(getattr(node, "display_title", "") or getattr(node, "id", ""))
    provenance = str(getattr(node, "provenance", "") or "")
    source = _join_compact(
        [
            str(getattr(node, "source_kind", "") or ""),
            str(getattr(node, "source_id", "") or ""),
        ],
        separator=":",
    )
    markers = [
        str(metadata.get("status") or metadata.get("state") or ""),
        provenance,
        source,
    ]
    text = Text()
    text.append(f"[{badge}] ", style="bold")
    text.append(title or str(getattr(node, "id", "")), style="bold")
    marker_text = _join_compact(markers)
    if marker_text:
        text.append(f"  {marker_text}", style="dim")
    return text


def _header_breadcrumb(detail: ArtifactDetailWire) -> Text:
    parts = [node.display_title or node.id for node in detail.path_to_root]
    if detail.node is not None:
        current = detail.node.display_title or detail.node.id
        if not parts or parts[-1] != current:
            parts.append(current)
    text = Text()
    text.append("Path: ", style="dim")
    text.append(_compressed_breadcrumb(parts))
    return text


def _header_counts(paged_model: ArtifactPanelPagedModel | None) -> Text:
    if paged_model is None:
        return Text("")

    paged = paged_model.paged_detail
    chunks: list[str] = []
    if paged.children_page is not None:
        chunks.append(f"children {_summary_count(paged.children_page.summary)}")
    outbound_total = sum(page.summary.total_count for page in paged.outbound_pages)
    inbound_total = sum(page.summary.total_count for page in paged.inbound_pages)
    if outbound_total:
        chunks.append(f"outbound {outbound_total}")
    if inbound_total:
        chunks.append(f"inbound {inbound_total}")
    chunks.extend(
        f"{_semantic_badge(type_count.artifact_type, type_count.artifact_type).lower()} {type_count.total_count}"
        for type_count in paged.type_counts[:6]
    )
    text = Text()
    text.append("Counts: ", style="dim")
    text.append("  ".join(chunks) if chunks else "none", style="dim")
    return text


def _summary_count(summary: object) -> str:
    loaded = int(getattr(summary, "loaded_count", 0) or 0)
    total = int(getattr(summary, "total_count", 0) or 0)
    if total > loaded:
        return f"{loaded}/{total}"
    return str(total or loaded)


def _semantic_badge(kind: str | None, file_type: str | None = None) -> str:
    if file_type:
        return {
            "plan": "PLAN",
            "diff": "DIFF",
            "chat": "CHAT",
            "project": "PROJECT",
            "prompt": "PROMPT",
            "misc": "MISC",
        }.get(file_type, file_type.upper())
    return {
        "agent": "AGENT",
        "bead": "BEAD",
        "changespec": "CL",
        "cl": "CL",
        "commit": "COMMIT",
        "directory": "DIR",
        "dir": "DIR",
        "file": "FILE",
        "project": "PROJECT",
        "root": "ROOT",
        "thought": "THOUGHT",
    }.get(kind or "", (kind or "artifact").upper())


def _compressed_breadcrumb(parts: list[str]) -> str:
    cleaned = [part for part in parts if part]
    if len(cleaned) <= 4:
        return " > ".join(cleaned)
    return " > ".join([cleaned[0], "...", *cleaned[-3:]])


def _join_compact(parts: list[str], *, separator: str = " · ") -> str:
    return separator.join(part for part in parts if part)


def _graph_preview_text(graph: ArtifactGraphWire) -> Text:
    text = Text()
    text.append("Graph preview\n", style="bold")
    text.append("Root: ", style="bold")
    text.append(f"{graph.root_id or ''}\n")
    text.append("Nodes: ", style="bold")
    text.append(f"{graph.node_count or len(graph.nodes)}\n")
    text.append("Links: ", style="bold")
    text.append(f"{graph.link_count or len(graph.links)}\n")
    text.append("Truncated: ", style="bold")
    text.append(f"{graph.truncated}\n")
    for node in graph.nodes[:10]:
        text.append(f"- {node.kind} {node.display_title}  {node.id}\n")
    return text
