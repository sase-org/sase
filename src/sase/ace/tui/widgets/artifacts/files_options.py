"""Option-list reconciliation and summary rendering for the Files pane."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from rich.console import RenderableType
from textual.widgets import Static
from textual.widgets.option_list import Option

from sase.ace.query.limit_token import apply_limit
from sase.ace.tui.keymaps import KeymapRegistry, key_display_name
from sase.core.artifact_file_types import ArtifactFile
from sase.core.query_profile_corpus_facade import ArtifactQueryIndex
from sase.project_display_names import ProjectRefDisplaySnapshot

from ..._artifact_tab_model import PaneGroupingModeDecl
from ...models.artifact_groups import (
    ArtifactGroupBuildResult,
    group_banner_option_id,
    group_banner_target,
)
from ...models.group_fold import GroupFoldRegistry
from .entry_navigation import ArtifactEntryTarget, LinkRequestState
from .file_filter_bar import FileFilterBar
from .files_data import FilesSnapshot, LogicalFile
from .files_filtering import (
    FilesFilterQueryError,
    FilesFilterValues,
    to_query_string,
)
from .files_list import (
    FILES_PANE_ID,
    FileRow,
    build_file_options,
    build_grouped_file_rows,
)
from .files_navigation import FilesOptionList
from .files_rendering import (
    build_files_hints,
    build_files_info,
    build_files_status,
)
from .query_session import ArtifactQuerySession
from .shell import build_empty_card
from .types import ARTIFACTS_ACCENTS, ArtifactsPaneContract

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class FilesOptionsMixin(_MixinBase):
    """Own list rebuilding, match counts, and pane summary text."""

    contract: ArtifactsPaneContract | None
    project_scope: str | None
    _project_display_name: str | None
    _project_ref_display: ProjectRefDisplaySnapshot
    _registry: KeymapRegistry
    _snapshot: FilesSnapshot | None
    _loading: bool
    _loading_full: bool
    _load_error: str | None
    _rows: dict[str, FileRow]
    _entry_jump_hints: dict[ArtifactEntryTarget, str]
    _entry_marks: set[ArtifactEntryTarget]
    _option_id_by_target: dict[ArtifactEntryTarget, str]
    _pending_entry_target: ArtifactEntryTarget | None
    _syncing_options: bool
    filters: FilesFilterValues
    _filter_session_open: bool
    _live_filter_values: FilesFilterValues | None
    _filter_query_error: FilesFilterQueryError | None
    _filtered_count: int | None
    _query_index: ArtifactQueryIndex | None
    _query_session: ArtifactQuerySession

    if TYPE_CHECKING:

        @property
        def selected_entry(self) -> ArtifactFile | None: ...

        def selected_entry_target(self) -> ArtifactEntryTarget | None: ...

        def _display_filter_values(self) -> FilesFilterValues: ...

        def _option_list(self) -> FilesOptionList | None: ...

        def _schedule_detail(self) -> None: ...

        def _set_file_rows(
            self,
            rows: dict[str, FileRow],
            options: list[Option],
            banner_targets: dict[str, ArtifactEntryTarget] | None = None,
        ) -> None: ...

        def _active_grouping_mode(self) -> PaneGroupingModeDecl | None: ...

        def _group_fold_registry(self) -> GroupFoldRegistry: ...

        def _complete_entry_request(
            self, state: LinkRequestState
        ) -> LinkRequestState: ...

    def _init_files_options(self) -> None:
        self._filtered_count = None

    def _group_pane_id(self) -> str:
        return FILES_PANE_ID

    def _group_build_result(
        self,
        *,
        fold_registry: GroupFoldRegistry,
    ) -> ArtifactGroupBuildResult[LogicalFile]:
        mode = self._active_grouping_mode()
        snapshot = self._current_snapshot()
        if mode is None or snapshot is None:
            return ArtifactGroupBuildResult(rows=(), known_group_keys=())
        return build_grouped_file_rows(
            snapshot,
            mode=mode,
            project_ref_display=self._project_ref_display,
            fold_registry=fold_registry,
        )

    def _group_refresh(self, preferred_target: ArtifactEntryTarget | None) -> None:
        self._refresh_options(preferred_target=preferred_target)

    def _refresh_options(
        self,
        *,
        preferred_target: ArtifactEntryTarget | None = None,
    ) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        pending_target = self._pending_entry_target
        if pending_target is not None:
            # A deferred cross-pane request wins over "keep the current
            # selection" — the caller landed here specifically to resolve it.
            preferred_target = pending_target
        elif preferred_target is None:
            preferred_target = self.selected_entry_target()
        values = self._display_filter_values()
        filtered, exact, pending, truncated = self._filtered_snapshot(values)
        if pending:
            self._sync_query_bar(None, exact=False)
            return
        self._filtered_count = None if filtered is None else len(filtered.rows)
        mode = self._active_grouping_mode()
        registry = self._group_fold_registry() if mode is not None else None
        options, rows, known_group_keys = build_file_options(
            filtered,
            project_scope=self.project_scope,
            project_ref_display=self._project_ref_display,
            loading=self._loading,
            mode=mode,
            fold_registry=registry,
            accent=self._accent(),
            jump_hints=self._entry_jump_hints,
            marks=self._entry_marks,
        )
        if registry is not None:
            registry.clear_unknown(known_group_keys)
        banner_targets_by_option_id = (
            {}
            if mode is None
            else {
                group_banner_option_id(mode.id, key): group_banner_target(
                    FILES_PANE_ID, mode.id, key
                )
                for key in known_group_keys
            }
        )
        self._set_file_rows(rows, options, banner_targets_by_option_id)
        # Resolve the target against the freshly built ``options`` list
        # directly rather than the live OptionList, which still reflects
        # the pre-rebuild rows until ``replace_options`` runs below.
        preferred_option_id = (
            None
            if preferred_target is None
            else self._option_id_by_target.get(preferred_target)
        )
        highlighted = next(
            (
                index
                for index, option in enumerate(options)
                if option.id == preferred_option_id
            ),
            None,
        )
        if pending_target is not None:
            if highlighted is not None:
                self._complete_entry_request(LinkRequestState.SELECTED)
            elif registry is not None and self._expand_group_for_pending_target(
                pending_target, registry
            ):
                self._refresh_options(preferred_target=pending_target)
                return
            elif self._pending_entry_resolution_complete():
                snapshot = self._current_snapshot()
                state = (
                    LinkRequestState.FAILED
                    if snapshot is not None and snapshot.load_error is not None
                    else LinkRequestState.MISSING
                )
                self._complete_entry_request(state)
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
        self._update_static("#files-info", self._scope_text())
        self._update_static("#files-hints", self._hints_text())
        self._sync_query_bar(
            self._filtered_count,
            exact=exact and not truncated,
            blank=(
                not self._filter_session_open
                and values.is_empty
                and values.limit is None
            ),
            coverage_label="capped" if truncated else None,
            lower_bound=truncated,
        )
        self._schedule_detail()

    def _expand_group_for_pending_target(
        self,
        target: ArtifactEntryTarget,
        registry: GroupFoldRegistry,
    ) -> bool:
        result = self._group_build_result(fold_registry=registry)
        changed = False
        for row in result.rows:
            if (
                row.kind == "banner"
                and row.banner is not None
                and row.banner.collapsed
                and target in row.banner.member_targets
            ):
                if registry.expand(row.banner.group_key):
                    changed = True
        return changed

    def host_query_row_for_target(self, target: ArtifactEntryTarget) -> dict | None:
        """Return the unfiltered Files query row backing *target*."""
        if target.pane_id != "files" or not target.parts:
            return None
        snapshot = self._current_snapshot()
        if snapshot is None:
            return None
        from .query_rows import file_query_entry

        logical_id = target.parts[0]
        for row in snapshot.rows:
            if row.logical_id == logical_id:
                return file_query_entry(
                    row,
                    project_ref_display=self._project_ref_display,
                )
        return None

    def _pending_entry_resolution_complete(self) -> bool:
        if self._loading or self._loading_full:
            return False
        snapshot = self._current_snapshot()
        if snapshot is None:
            return False
        return snapshot.complete or snapshot.load_error is not None

    def _filtered_snapshot(
        self, values: FilesFilterValues
    ) -> tuple[FilesSnapshot | None, bool, bool, bool]:
        snapshot = self._current_snapshot()
        if snapshot is None:
            return snapshot, True, False, False
        query_index = self._query_index
        query = to_query_string(values)
        if values.is_empty:
            rows = snapshot.rows
        else:
            if query_index is None or not query:
                return snapshot, False, True, False
            result = self._query_session.result(query, query_index)
            if result is None:
                return snapshot, False, True, False
            matched = frozenset(result.matched_row_ids)
            rows = tuple(
                row for row in snapshot.rows if f"file:{row.logical_id}" in matched
            )
        rows, truncated = apply_limit(rows, values.limit)
        if truncated or not values.is_empty:
            snapshot = replace(snapshot, rows=rows)
        return snapshot, not truncated, False, truncated

    def _update_empty(self) -> None:
        if not self.is_mounted:
            return
        empty = self.query_one("#files-empty", Static)
        option_list = self.query_one("#files-list", FilesOptionList)
        has_current_snapshot = (
            self._snapshot is not None and self._snapshot.project == self.project_scope
        )
        show_empty = (
            has_current_snapshot
            and not self._rows
            and not self._loading
            and self._load_error is None
        )
        if show_empty:
            values = self._display_filter_values()
            has_active_filter = not values.is_empty
            if self.contract is not None:
                empty.update(
                    build_empty_card(
                        self.contract,
                        has_active_filter=has_active_filter,
                        clear_filter_hint=(
                            f"Press {key_display_name(self._registry.app.files_filters)} "
                            "to edit or clear it."
                        ),
                    )
                )
            else:
                empty.update(
                    "No artifact files found."
                    if not has_active_filter
                    else "No artifact files match the active filters. "
                    f"Press {key_display_name(self._registry.app.files_filters)} "
                    "to edit or clear them."
                )
        empty.display = show_empty
        option_list.display = not show_empty

    def _update_status(self) -> None:
        self._update_static("#files-status", self._status_text())

    def _update_static(self, selector: str, content: RenderableType) -> None:
        if self.is_mounted:
            self.query_one(selector, Static).update(content)

    def _accent(self) -> str:
        contract = self.contract
        return ARTIFACTS_ACCENTS["files"] if contract is None else contract.accent

    def _sync_query_bar(
        self,
        match_count: int | None,
        *,
        exact: bool,
        blank: bool = False,
        coverage_label: str | None = None,
        lower_bound: bool = False,
    ) -> None:
        """Keep the persistent Files bar's text and status lane truthful.

        Called from every ``_refresh_options()`` exit path, including the
        pending-query early return, since a permanent bar must stay correct
        even while the user is not editing it. *blank* clears the status
        lane for an idle, empty query, where the placeholder already says
        there is no filter.
        """
        bar = self.query_one(FileFilterBar)
        if not self._filter_session_open:
            bar.set_query(to_query_string(self.filters))
        if self._filter_query_error is not None:
            return
        if blank:
            bar.clear_status()
        else:
            bar.set_status(
                match_count,
                exact=exact,
                error=None,
                coverage_label=coverage_label,
                lower_bound=lower_bound,
            )

    def _scope_text(self) -> RenderableType:
        snapshot = self._current_snapshot()
        return build_files_info(
            self._registry,
            snapshot,
            project_scope=self.project_scope,
            project_display_name=self._project_display_name,
            filters=self._display_filter_values(),
            filtered_count=self._filtered_count,
            accent=self._accent(),
            pane=self,
        )

    def _status_text(self) -> RenderableType:
        snapshot = self._current_snapshot()
        return build_files_status(
            snapshot,
            loading=self._loading,
            load_error=self._load_error,
            extending=self._loading_full,
        )

    def _hints_text(self) -> RenderableType:
        entry = self.selected_entry
        return build_files_hints(
            self._registry,
            has_agent=bool(entry is not None and entry.agent_name),
            accent=self._accent(),
        )

    def _current_snapshot(self) -> FilesSnapshot | None:
        snapshot = self._snapshot
        if snapshot is None or snapshot.project != self.project_scope:
            return None
        return snapshot

    def _snapshot_matches_scope(self) -> bool:
        return self._current_snapshot() is not None

    def _snapshot_row_count(self) -> int:
        snapshot = self._current_snapshot()
        return 0 if snapshot is None else len(snapshot.rows)

    def _set_filter_completion_sources(self) -> None:
        if self._query_index is None:
            self.query_one(FileFilterBar).set_completion_sources(
                projects=(), agents=(), workflows=()
            )
            return
        self.query_one(FileFilterBar).set_observed_facets(
            {
                key: values
                for key, values in self._query_index.facets.items()
                if key not in {"since", "until"}
            }
        )


__all__ = ["FilesOptionsMixin"]
