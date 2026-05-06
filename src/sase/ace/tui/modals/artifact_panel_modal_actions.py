"""Action and input handlers for the artifact panel modal."""

from __future__ import annotations

from typing import Any
import os
import subprocess

from textual.containers import VerticalScroll
from textual.widgets import Input, OptionList

from sase.ace.hints import build_editor_args
from sase.core.artifact_wire import ArtifactGraphOptionsWire

from .artifact_panel_modal_formatting import graph_preview_text
from .artifact_panel_state import ARTIFACT_PANEL_SHOW_MORE_ACTION, parent_id_from_detail


class ArtifactPanelActionsMixin:
    def action_open_selected(self: Any) -> None:
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

    def on_option_list_option_selected(
        self: Any, event: OptionList.OptionSelected
    ) -> None:
        event.stop()
        self.action_open_selected()

    def on_option_list_option_highlighted(
        self: Any, event: OptionList.OptionHighlighted
    ) -> None:
        option_id = event.option.id
        if option_id in self._row_by_option_id:
            self._state.selected_row_id = option_id

    def on_input_changed(self: Any, event: Input.Changed) -> None:
        if event.input.id == "artifact-panel-search":
            if self._suppress_search_input:
                return
            query = event.value.strip()
            if query:
                self._start_search(query)
            else:
                self._clear_search_state()
            return
        if event.input.id != "artifact-panel-filter":
            return
        self._state.set_filter(event.value)
        if self._detail is not None and not self._search_text:
            self._render_detail(update_preview=False)

    def action_focus_filter(self: Any) -> None:
        self.query_one("#artifact-panel-filter", Input).focus()

    def action_focus_global_search(self: Any) -> None:
        self.query_one("#artifact-panel-search", Input).focus()
        if not self._search_text:
            self._render_search_prompt()

    def action_back(self: Any) -> None:
        artifact_id = self._state.back()
        if artifact_id is not None:
            self._start_load(artifact_id)

    def action_forward(self: Any) -> None:
        artifact_id = self._state.forward()
        if artifact_id is not None:
            self._start_load(artifact_id)

    def action_parent(self: Any) -> None:
        detail = self._detail
        if detail is None:
            return
        parent_id = parent_id_from_detail(detail, self._state.current_id)
        if parent_id is not None:
            self._navigate_to(parent_id)

    def action_root(self: Any) -> None:
        self._navigate_to("/")

    def action_copy_artifact_id(self: Any) -> None:
        from ..actions.clipboard import copy_to_system_clipboard

        if copy_to_system_clipboard(self._state.current_id):
            self.app.notify("Copied artifact ID")
        else:
            self.app.notify("Failed to copy artifact ID", severity="error")

    def action_open_file_in_editor(self: Any) -> None:
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

    def action_preview_graph(self: Any) -> None:
        if self._render_worker is not None:
            self._render_worker.cancel()
            self._render_worker_artifact_id = "<cancelled>"
        options = ArtifactGraphOptionsWire(root_id=self._state.current_id, limit=100)
        if self._graph_func is None:
            from sase.core.artifact_facade import artifact_graph

            graph = artifact_graph(self._index_path, options)
        else:
            graph = self._graph_func(self._index_path, options)
        self._update_detail(graph_preview_text(graph))

    def action_export_graph(self: Any) -> None:
        if self._render_worker is not None:
            self._render_worker.cancel()
            self._render_worker_artifact_id = "<cancelled>"
        options = ArtifactGraphOptionsWire(root_id=self._state.current_id, limit=100)
        if self._export_func is None:
            from sase.core.artifact_facade import artifact_export

            exported = artifact_export(self._index_path, options, "mermaid")
        else:
            exported = self._export_func(self._index_path, options, "mermaid")
        self._update_detail(exported)

    def action_scroll_detail_down(self: Any) -> None:
        self.query_one("#artifact-panel-detail-scroll", VerticalScroll).scroll_down(
            animate=False
        )

    def action_scroll_detail_up(self: Any) -> None:
        self.query_one("#artifact-panel-detail-scroll", VerticalScroll).scroll_up(
            animate=False
        )
