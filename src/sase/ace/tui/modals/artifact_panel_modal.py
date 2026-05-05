"""Unified artifact graph modal for ace."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import os
from pathlib import Path
import subprocess

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.hints import build_editor_args
from sase.core.artifact_wire import (
    ArtifactDetailWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactLinkWire,
)

from .artifact_panel_state import (
    ArtifactPanelNavigationState,
    ArtifactPanelRow,
    build_artifact_panel_rows,
    parent_id_from_detail,
)
from .base import FilterInput, OptionListNavigationMixin

ArtifactShowFunc = Callable[[Path | str, str], ArtifactDetailWire]
ArtifactGraphFunc = Callable[[Path | str, ArtifactGraphOptionsWire], ArtifactGraphWire]
ArtifactExportFunc = Callable[[Path | str, ArtifactGraphOptionsWire, str], str]


def _default_artifact_index_path() -> Path:
    """Return the default unified artifact SQLite index path."""
    return Path.home() / ".sase" / "artifacts.sqlite"


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
        show_func: ArtifactShowFunc | None = None,
        graph_func: ArtifactGraphFunc | None = None,
        export_func: ArtifactExportFunc | None = None,
    ) -> None:
        super().__init__()
        self._artifact_id = artifact_id
        self._state = ArtifactPanelNavigationState(current_id=artifact_id)
        self._index_path = index_path or _default_artifact_index_path()
        self._show_func = show_func
        self._graph_func = graph_func
        self._export_func = export_func
        self._detail: ArtifactDetailWire | None = None
        self._error_message: str | None = None
        self._load_worker: Worker[ArtifactDetailWire] | None = None
        self._row_by_option_id: dict[str, ArtifactPanelRow] = {}

    def compose(self) -> ComposeResult:
        with Container(id="artifact-panel-container"):
            yield Label(f"Artifacts: {self._artifact_id}", id="artifact-panel-title")
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
        self._load_worker = self.run_worker(
            lambda: self._load_detail(artifact_id),
            thread=True,
        )

    def _load_detail(self, artifact_id: str) -> ArtifactDetailWire:
        show_func = self._show_func
        if show_func is None:
            from sase.core.artifact_facade import artifact_show

            show_func = artifact_show
        return show_func(self._index_path, artifact_id)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Render the artifact load result."""
        if event.worker != self._load_worker:
            return

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            assert result is not None
            self._detail = result
            self._state.set_detail(result)
            self._error_message = None
            self._render_detail()
        elif event.state == WorkerState.ERROR:
            self._detail = None
            self._state.detail = None
            self._error_message = str(event.worker.error or "Unknown artifact error")
            self._render_error()

    def _render_loading(self) -> None:
        self._row_by_option_id = {}
        self._replace_options(
            [Option("Loading artifact...", id="__loading__", disabled=True)]
        )
        self._update_detail("Loading artifact...")

    def _render_error(self) -> None:
        message = self._error_message or "Artifact could not be loaded."
        self._row_by_option_id = {}
        self._replace_options([Option("Load failed", id="__error__", disabled=True)])
        text = Text()
        text.append("Artifact load failed\n", style="bold red")
        text.append(message, style="red")
        self._update_detail(text)

    def _render_detail(self) -> None:
        detail = self._detail
        if detail is None or detail.node is None:
            self._replace_options([Option("Artifact not found", disabled=True)])
            self._update_detail(f"Artifact not found: {self._artifact_id}")
            return

        title = self.query_one("#artifact-panel-title", Label)
        title.update(f"Artifacts: {detail.node.display_title}")

        self._replace_options(
            self._build_options(detail), prefer_row_id=self._state.selected_row_id
        )
        self._update_detail(self._build_detail_text(detail))

    def _build_options(self, detail: ArtifactDetailWire) -> list[Option]:
        options: list[Option] = []
        self._row_by_option_id = {}
        panel_rows = build_artifact_panel_rows(
            detail,
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

    def _build_detail_text(self, detail: ArtifactDetailWire) -> Text:
        node = detail.node
        assert node is not None

        outbound_counts = _link_counts(detail.outbound_links)
        inbound_counts = _link_counts(detail.inbound_links)

        text = Text()
        text.append("Artifact\n", style="bold")
        text.append("ID: ", style="bold")
        text.append(f"{node.id}\n")
        text.append("Kind: ", style="bold")
        text.append(f"{node.kind}\n")
        text.append("Title: ", style="bold")
        text.append(f"{node.display_title}\n")
        if node.subtitle:
            text.append("Subtitle: ", style="bold")
            text.append(f"{node.subtitle}\n")
        text.append("Provenance: ", style="bold")
        text.append(f"{node.provenance}\n")
        text.append("\n")
        text.append(f"Path to root: {len(detail.path_to_root)}\n")
        text.append(f"Children: {len(detail.children)}\n")
        text.append(f"Outbound links: {_format_counts(outbound_counts)}\n")
        text.append(f"Inbound links: {_format_counts(inbound_counts)}\n")
        if self._state.filter_text:
            text.append("Filter: ", style="bold")
            text.append(f"{self._state.filter_text}\n")
        if detail.payloads:
            text.append(f"Payloads: {len(detail.payloads)}\n")
        if detail.diagnostics:
            text.append("\nDiagnostics\n", style="bold yellow")
            for issue in detail.diagnostics[:5]:
                text.append(f"- {issue.severity}: {issue.message}\n")
        return text

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

    def _update_detail(self, content: str | Text) -> None:
        self.query_one("#artifact-panel-detail", Static).update(content)

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

    def action_open_selected(self) -> None:
        row = self._highlighted_row()
        if row is None or row.artifact_id is None:
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
            self._render_detail()

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
        text.stylize("bold" if row.row_type == "group" else "yellow")
        return text
    if row.row_type in {"outbound", "inbound"}:
        text = Text()
        text.append(f"{row.link_type or 'link'} ", style="bold")
        text.append(row.artifact_id or "")
        return text
    if row.row_type == "path":
        text = Text()
        text.append("breadcrumb ", style="dim")
        text.append(row.label)
        return text
    return Text(row.label)


def _link_counts(links: list[ArtifactLinkWire]) -> dict[str, int]:
    return dict(Counter(link.link_type for link in links))


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "0"
    return ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))


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
