"""Rendering methods for the artifact panel modal."""

from __future__ import annotations

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
    ArtifactPanelPagedModel,
    ArtifactPanelRow,
    build_artifact_panel_rows,
    build_artifact_search_rows,
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
        self._update_header_error(message)
        self._replace_options(
            [
                Option(
                    state_message(
                        "Load failed",
                        "The artifact backend returned an error.",
                        style="red",
                    ),
                    id="__error__",
                    disabled=True,
                )
            ]
        )
        self._update_detail(state_message("Artifact load failed", message, style="red"))

    def _render_detail(self: Any, *, update_preview: bool = True) -> None:
        detail = self._detail
        if detail is None or detail.node is None:
            self._clear_entry_jump_hints()
            self._update_header_missing(self._artifact_id)
            self._replace_options(
                [
                    Option(
                        state_message(
                            "Artifact not found",
                            "Targeted refresh found no indexed node.",
                            style="yellow",
                        ),
                        id="__missing__",
                        disabled=True,
                    )
                ]
            )
            self._update_detail(
                state_message(
                    "Artifact not found",
                    f"{self._artifact_id}\nIndexing may still be pending for this source.",
                    style="yellow",
                )
            )
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
        self: Any, detail: ArtifactDetailWire
    ) -> RenderableType:
        renderer = self._detail_renderer or render_artifact_detail
        return renderer(detail)

    def _start_detail_render(self: Any, detail: ArtifactDetailWire) -> None:
        if self._render_worker is not None:
            self._render_worker.cancel()
        self._update_detail("Rendering artifact preview...")
        self._render_worker = self.run_worker(
            lambda: self._build_detail_renderable(detail),
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
            "Indexing needed or source no longer exists"
        )
        self.query_one("#artifact-panel-header-counts", Static).update("")

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
