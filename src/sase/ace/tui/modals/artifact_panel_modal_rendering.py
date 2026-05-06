"""Rendering methods for the artifact panel modal."""

from __future__ import annotations

import shlex
from typing import Any

from rich.console import RenderableType
from rich.text import Text
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.core.artifact_wire import ArtifactDetailWire

from .artifact_panel_modal_formatting import (
    _ARTIFACT_BADGE_STYLES,
    header_breadcrumb,
    header_counts,
    header_loading_primary,
    header_primary,
    row_label,
    state_message,
)
from .artifact_panel_renderers import render_artifact_detail
from .artifact_panel_state import (
    ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT,
    ArtifactDetailRenderContext,
    ArtifactPanelPagedModel,
    ArtifactPanelRow,
    build_artifact_panel_rows,
    build_artifact_search_rows,
    detail_render_context_from_paged_model,
)


class ArtifactPanelRenderingMixin:
    def _render_loading(self: Any) -> None:
        self._row_by_option_id: dict[str, ArtifactPanelRow] = {}
        self._clear_entry_jump_hints()
        self._update_header_loading()
        self._replace_options(
            [
                Option(
                    state_message(
                        "Loading artifact",
                        "Fetching relationship pages for the navigator.",
                        style="cyan",
                    ),
                    id="__loading__",
                    disabled=True,
                )
            ]
        )
        self._update_detail(
            state_message(
                "Loading artifact",
                "Preparing the relationship navigator and preview.",
                style="cyan",
            )
        )

    def _render_error(self: Any) -> None:
        message = self._error_message or "Artifact could not be loaded."
        self._row_by_option_id = {}
        self._clear_entry_jump_hints()
        if self._render_worker is not None:
            self._render_worker.cancel()
            self._render_worker_artifact_id = "<cancelled>"
        title = self._error_title or "Artifact load failed"
        style = self._error_style or "red"
        self._update_header_error(message)
        self._replace_options(
            [
                Option(
                    state_message(
                        title,
                        "The artifact backend returned an error.",
                        style=style,
                    ),
                    id="__error__",
                    disabled=True,
                )
            ]
        )
        self._update_detail(state_message(title, message, style=style))

    def _render_detail(self: Any, *, update_preview: bool = True) -> None:
        detail = self._detail
        if detail is None or detail.node is None:
            self._clear_entry_jump_hints()
            self._update_header_missing(self._artifact_id)
            missing_message = self._missing_artifact_message(self._artifact_id)
            self._replace_options(
                [
                    Option(
                        missing_message,
                        id="__missing__",
                        disabled=True,
                    )
                ]
            )
            self._update_detail(missing_message)
            return

        self._update_header(detail, self._paged_model)

        self._replace_options(
            self._build_options(detail), prefer_row_id=self._state.selected_row_id
        )
        if update_preview:
            self._start_detail_render(detail)

    def _render_search_prompt(self: Any) -> None:
        self._row_by_option_id = {}
        self._clear_entry_jump_hints()
        self._replace_options(
            [
                Option(
                    state_message(
                        "Global artifact search",
                        "Type a query to search the artifact index.",
                        style="cyan",
                    ),
                    id="__search_prompt__",
                    disabled=True,
                )
            ]
        )

    def _render_search_loading(self: Any, query: str) -> None:
        self._row_by_option_id = {}
        self._clear_entry_jump_hints()
        self._replace_options(
            [
                Option(
                    state_message(
                        f"Searching for {query!r}",
                        "Checking the artifact index.",
                        style="cyan",
                    ),
                    id="__search_loading__",
                    disabled=True,
                )
            ]
        )

    def _render_search_options(self: Any) -> None:
        query = self._search_text
        if not query:
            self._render_search_prompt()
            return

        self._row_by_option_id = {}
        if self._search_error is not None:
            self._clear_entry_jump_hints()
            self._replace_options(
                [
                    Option(
                        state_message(
                            f"Search failed: {self._search_error}",
                            "Edit the query to try again.",
                            style="red",
                        ),
                        id="__search_error__",
                        disabled=True,
                    )
                ]
            )
            return

        results = self._search_results
        if results is None:
            self._render_search_loading(query)
            return
        if not results:
            self._clear_entry_jump_hints()
            self._replace_options(
                [
                    Option(
                        state_message(
                            f"No global results for {query!r}",
                            "Try another query or return to local navigation.",
                            style="yellow",
                        ),
                        id="__search_empty__",
                        disabled=True,
                    )
                ]
            )
            return

        options: list[Option] = []
        panel_rows = build_artifact_search_rows(
            results,
            query=query,
            limit=ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT,
        )
        for row in panel_rows.rows:
            option = Option(
                row_label(row, hint_char=self._entry_jump_row_id_to_hint.get(row.id)),
                id=row.id,
                disabled=not row.selectable,
            )
            options.append(option)
            if row.selectable:
                self._row_by_option_id[row.id] = row
        self._replace_options(options, prefer_row_id=self._state.selected_row_id)

    def _build_options(self: Any, detail: ArtifactDetailWire) -> list[Option]:
        options: list[Option] = []
        self._row_by_option_id = {}
        panel_rows = build_artifact_panel_rows(
            detail,
            paged_model=self._paged_model,
            filter_text=self._state.filter_text,
        )
        for row in panel_rows.rows:
            option = Option(
                row_label(row, hint_char=self._entry_jump_row_id_to_hint.get(row.id)),
                id=row.id,
                disabled=not row.selectable,
            )
            options.append(option)
            if row.selectable:
                self._row_by_option_id[row.id] = row
        if not options:
            self._clear_entry_jump_hints()
            if self._state.filter_text:
                message = state_message(
                    "No rows match the current filter",
                    "Local filter only checks loaded relationship rows.",
                    style="yellow",
                )
                option_id = "__filter_empty__"
            else:
                message = state_message(
                    "No linked artifacts",
                    "This artifact has no loaded path, child, outbound, or inbound rows.",
                    style="dim",
                )
                option_id = "__relationships_empty__"
            options.append(Option(message, id=option_id, disabled=True))
        return options

    def _build_detail_renderable(
        self: Any,
        detail: ArtifactDetailWire,
        *,
        render_context: ArtifactDetailRenderContext | None = None,
    ) -> RenderableType:
        if self._detail_renderer is not None:
            return self._detail_renderer(detail)
        return render_artifact_detail(
            detail,
            render_context=render_context,
        )

    def _start_detail_render(self: Any, detail: ArtifactDetailWire) -> None:
        if self._render_worker is not None:
            self._render_worker.cancel()
            self._render_worker_artifact_id = "<cancelled>"
        self._update_detail("Rendering artifact preview...")
        artifact_id = (
            detail.node.id if detail.node is not None else self._state.current_id
        )
        render_context = detail_render_context_from_paged_model(self._paged_model)
        self._render_worker_artifact_id = artifact_id
        self._render_worker = self.run_worker(
            lambda: self._build_detail_renderable(
                detail,
                render_context=render_context,
            ),
            exit_on_error=False,
            thread=True,
        )

    def _replace_options(
        self: Any,
        options: list[Option],
        *,
        prefer_row_id: str | None = None,
    ) -> None:
        option_list = self.query_one("#artifact-panel-list", OptionList)
        option_list.clear_options()
        option_list.add_options(options)
        self._highlight_first_selectable(option_list, prefer_row_id=prefer_row_id)
        if self._entry_jump_mode_active:
            self._sync_jump_hints_to_visible_rows()

    def _update_detail(self: Any, content: RenderableType) -> None:
        self.query_one("#artifact-panel-detail", Static).update(content)

    def _update_header_loading(self: Any) -> None:
        self.query_one("#artifact-panel-header-primary", Static).update(
            header_loading_primary(self._state.current_id)
        )
        self.query_one("#artifact-panel-header-path", Static).update(
            "Loading artifact..."
        )
        self.query_one("#artifact-panel-header-counts", Static).update("")

    def _update_header_error(self: Any, message: str) -> None:
        primary = Text()
        primary.append("[ARTIFACT] ", style=f"bold {_ARTIFACT_BADGE_STYLES['file']}")
        primary.append(self._state.current_id)
        primary.append("  load failed", style="red")
        self.query_one("#artifact-panel-header-primary", Static).update(primary)
        self.query_one("#artifact-panel-header-path", Static).update(message)
        self.query_one("#artifact-panel-header-counts", Static).update("")

    def _update_header_missing(self: Any, artifact_id: str) -> None:
        primary = Text()
        primary.append("[ARTIFACT] ", style=f"bold {_ARTIFACT_BADGE_STYLES['file']}")
        primary.append(artifact_id)
        primary.append("  not found", style="yellow")
        self.query_one("#artifact-panel-header-primary", Static).update(primary)
        self.query_one("#artifact-panel-header-path", Static).update(
            self._missing_artifact_context_label()
        )
        self.query_one("#artifact-panel-header-counts", Static).update("")

    def _missing_artifact_message(self: Any, artifact_id: str) -> Text:
        detail_lines = [
            f"ID: {artifact_id}",
            self._missing_artifact_context_label(prefix="Refresh context"),
            (
                "Likely reason: not indexed yet, historical artifacts not synced, "
                "source moved/deleted, or index unavailable."
            ),
            "Manual: sase artifact sync -j",
        ]
        context_command = self._missing_artifact_context_command()
        if context_command is not None:
            detail_lines.append(f"Manual: {context_command}")
        return state_message(
            "Artifact not found after targeted refresh",
            "\n".join(line for line in detail_lines if line),
            style="yellow",
        )

    def _missing_artifact_context_label(self: Any, *, prefix: str = "") -> str:
        if self._context_artifact_dir is not None:
            label = f"artifact dir {self._context_artifact_dir}"
        elif self._context_path is not None:
            label = f"path {self._context_path}"
        else:
            label = "Indexing needed or source no longer exists"
        return f"{prefix}: {label}" if prefix else label

    def _missing_artifact_context_command(self: Any) -> str | None:
        if self._context_artifact_dir is not None:
            artifact_dir = shlex.quote(str(self._context_artifact_dir))
            return f"sase artifact sync -j -a {artifact_dir}"
        if self._context_path is not None:
            context_path = shlex.quote(str(self._context_path))
            return f"sase artifact rebuild -j -t {context_path}"
        return None

    def _update_header(
        self: Any,
        detail: ArtifactDetailWire,
        paged_model: ArtifactPanelPagedModel | None,
    ) -> None:
        assert detail.node is not None
        self.query_one("#artifact-panel-header-primary", Static).update(
            header_primary(detail.node)
        )
        self.query_one("#artifact-panel-header-path", Static).update(
            header_breadcrumb(detail)
        )
        self.query_one("#artifact-panel-header-counts", Static).update(
            header_counts(paged_model)
        )

    def _highlight_first_selectable(
        self: Any,
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

    def _highlighted_row(self: Any) -> ArtifactPanelRow | None:
        option_list = self.query_one("#artifact-panel-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        option = option_list.get_option_at_index(highlighted)
        if option.id is None:
            return None
        return self._row_by_option_id.get(option.id)

    def _highlighted_row_id(self: Any) -> str | None:
        option_list = self.query_one("#artifact-panel-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        option = option_list.get_option_at_index(highlighted)
        option_id = option.id
        if option_id is None or option_id not in self._row_by_option_id:
            return None
        return option_id
