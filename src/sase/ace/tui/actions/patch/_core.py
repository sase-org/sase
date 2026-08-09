"""Patch management mixin for the ace TUI app."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from ._display import PatchDisplayMixin
from ._grouping_nav import PatchGroupingNavMixin
from ._loading import PatchLoadingMixin
from ._query import PatchQueryMixin

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from ....query_history import QueryHistoryStacks
    from ...models.fold_state import FoldLevel
    from ...util.debounce import DetailPanelDebouncer

from ....patch import Patch


def _legacy_changespec_targets(targets: Any) -> Any:
    return [
        ("changespec" if kind == "patch" else kind, payload)
        for kind, payload in targets
    ]


class PatchMixin(
    PatchLoadingMixin,
    PatchQueryMixin,
    PatchDisplayMixin,
    PatchGroupingNavMixin,
):
    """Mixin providing Patch loading, filtering, and display methods."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    query_string: str
    parsed_query: QueryExpr
    hooks_collapsed: FoldLevel
    stitches_collapsed: FoldLevel
    mentors_collapsed: FoldLevel
    timestamps_collapsed: FoldLevel
    deltas_collapsed: FoldLevel
    hide_reverted: bool
    hide_submitted: bool
    marked_indices: set[int]
    _hint_mode_active: bool
    _hint_mode_hints_for: str | None
    _leader_mode_active: bool
    _hint_mappings: dict[int, str]
    _hook_hint_to_idx: dict[int, int]
    _hint_to_entry_id: dict[int, str]
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]
    _query_history: QueryHistoryStacks
    _query_selections: dict[str, str]
    _all_patches: list[Patch]
    _ancestor_keys: dict[str, str]
    _children_keys: dict[str, str]
    _sibling_keys: dict[str, str]
    _hidden_reverted_count: int
    _hidden_submitted_count: int
    _axe_cmds_hidden: bool
    _patches_loading: bool
    _patches_refresh_scheduled: bool
    _patches_refresh_pending: bool

    # Debouncer for j/k navigation detail panel updates (artifacts tab).
    _patch_detail_debouncer: DetailPanelDebouncer

    def _legacy_get(self, canonical: str, default: Any = None) -> Any:
        return getattr(self, canonical, default)

    def _legacy_set(self, canonical: str, value: Any) -> None:
        setattr(self, canonical, value)

    @property
    def changespecs(self) -> list[Patch]:
        """Legacy alias for :attr:`patches`."""
        return self.patches

    @changespecs.setter
    def changespecs(self, value: list[Patch]) -> None:
        self.patches = value

    @property
    def commits_collapsed(self) -> FoldLevel:
        """Legacy alias for :attr:`stitches_collapsed`."""
        return self.stitches_collapsed

    @commits_collapsed.setter
    def commits_collapsed(self, value: FoldLevel) -> None:
        self.stitches_collapsed = value

    @property
    def _all_changespecs(self) -> list[Patch]:
        return self._legacy_get("_all_patches", [])

    @_all_changespecs.setter
    def _all_changespecs(self, value: list[Patch]) -> None:
        self._legacy_set("_all_patches", value)

    @property
    def _changespecs_last_idx(self) -> int:
        return self._legacy_get("_patches_last_idx", 0)

    @_changespecs_last_idx.setter
    def _changespecs_last_idx(self, value: int) -> None:
        self._legacy_set("_patches_last_idx", value)

    @property
    def _changespecs_last_name(self) -> str | None:
        return self._legacy_get("_patches_last_name")

    @_changespecs_last_name.setter
    def _changespecs_last_name(self, value: str | None) -> None:
        self._legacy_set("_patches_last_name", value)

    @property
    def _changespecs_loading(self) -> bool:
        return self._legacy_get("_patches_loading", False)

    @_changespecs_loading.setter
    def _changespecs_loading(self, value: bool) -> None:
        self._legacy_set("_patches_loading", value)

    @property
    def _changespecs_refresh_scheduled(self) -> bool:
        return self._legacy_get("_patches_refresh_scheduled", False)

    @_changespecs_refresh_scheduled.setter
    def _changespecs_refresh_scheduled(self, value: bool) -> None:
        self._legacy_set("_patches_refresh_scheduled", value)

    @property
    def _changespecs_refresh_pending(self) -> bool:
        return self._legacy_get("_patches_refresh_pending", False)

    @_changespecs_refresh_pending.setter
    def _changespecs_refresh_pending(self, value: bool) -> None:
        self._legacy_set("_patches_refresh_pending", value)

    @property
    def _changespecs_first_load_done(self) -> bool:
        return self._legacy_get("_patches_first_load_done", False)

    @_changespecs_first_load_done.setter
    def _changespecs_first_load_done(self, value: bool) -> None:
        self._legacy_set("_patches_first_load_done", value)

    @property
    def _dirty_changespecs(self) -> bool:
        return self._legacy_get("_dirty_patches", False)

    @_dirty_changespecs.setter
    def _dirty_changespecs(self, value: bool) -> None:
        self._legacy_set("_dirty_patches", value)

    @property
    def _changespec_grouping_mode(self) -> Any:
        return self._legacy_get("_patch_grouping_mode")

    @_changespec_grouping_mode.setter
    def _changespec_grouping_mode(self, value: Any) -> None:
        self._legacy_set("_patch_grouping_mode", value)

    @property
    def _changespec_group_fold_registries(self) -> Any:
        return self._legacy_get("_patch_group_fold_registries", {})

    @_changespec_group_fold_registries.setter
    def _changespec_group_fold_registries(self, value: Any) -> None:
        self._legacy_set("_patch_group_fold_registries", value)

    @property
    def _changespec_group_fold_registry(self) -> Any:
        return self._legacy_get("_patch_group_fold_registry")

    @_changespec_group_fold_registry.setter
    def _changespec_group_fold_registry(self, value: Any) -> None:
        self._legacy_set("_patch_group_fold_registry", value)

    @property
    def _current_changespec_group_key(self) -> tuple[str, ...] | None:
        return self._legacy_get("_current_patch_group_key")

    @_current_changespec_group_key.setter
    def _current_changespec_group_key(self, value: tuple[str, ...] | None) -> None:
        self._legacy_set("_current_patch_group_key", value)

    @property
    def _changespec_graph_index(self) -> Any:
        return self._legacy_get("_patch_graph_index")

    @_changespec_graph_index.setter
    def _changespec_graph_index(self, value: Any) -> None:
        self._legacy_set("_patch_graph_index", value)

    @property
    def _changespec_graph_index_for_id(self) -> int | None:
        return self._legacy_get("_patch_graph_index_for_id")

    @_changespec_graph_index_for_id.setter
    def _changespec_graph_index_for_id(self, value: int | None) -> None:
        self._legacy_set("_patch_graph_index_for_id", value)

    @property
    def _entry_jump_hint_to_changespec_banner(self) -> dict[str, tuple[str, ...]]:
        return self._legacy_get("_entry_jump_hint_to_patch_banner", {})

    @_entry_jump_hint_to_changespec_banner.setter
    def _entry_jump_hint_to_changespec_banner(
        self,
        value: dict[str, tuple[str, ...]],
    ) -> None:
        self._legacy_set("_entry_jump_hint_to_patch_banner", value)

    @property
    def _entry_jump_changespec_banner_to_hint(self) -> dict[tuple[str, ...], str]:
        return self._legacy_get("_entry_jump_patch_banner_to_hint", {})

    @_entry_jump_changespec_banner_to_hint.setter
    def _entry_jump_changespec_banner_to_hint(
        self,
        value: dict[tuple[str, ...], str],
    ) -> None:
        self._legacy_set("_entry_jump_patch_banner_to_hint", value)

    @property
    def _w_changespec_list(self) -> Any:
        return self._legacy_get("_w_patch_list")

    @_w_changespec_list.setter
    def _w_changespec_list(self, value: Any) -> None:
        self._legacy_set("_w_patch_list", value)

    @property
    def _w_changespec_detail(self) -> Any:
        return self._legacy_get("_w_patch_detail")

    @_w_changespec_detail.setter
    def _w_changespec_detail(self, value: Any) -> None:
        self._legacy_set("_w_patch_detail", value)

    @property
    def _w_changespec_info_panel(self) -> Any:
        return self._legacy_get("_w_patch_info_panel")

    @_w_changespec_info_panel.setter
    def _w_changespec_info_panel(self, value: Any) -> None:
        self._legacy_set("_w_patch_info_panel", value)

    @property
    def _changespec_detail_debouncer(self) -> DetailPanelDebouncer:
        return self._legacy_get("_patch_detail_debouncer")

    @_changespec_detail_debouncer.setter
    def _changespec_detail_debouncer(self, value: DetailPanelDebouncer) -> None:
        self._legacy_set("_patch_detail_debouncer", value)

    def _load_changespecs(self) -> None:
        self._load_patches()

    def _filter_changespecs(self, patches: list[Patch]) -> list[Patch]:
        return self._filter_patches(patches)

    def _apply_changespecs(self, all_patches: list[Patch]) -> None:
        self._apply_patches(all_patches)

    def _apply_reloaded_changespecs(
        self,
        all_patches: list[Patch],
        current_name: str | None,
        **kwargs: Any,
    ) -> None:
        self._apply_reloaded_patches(all_patches, current_name, **kwargs)

    def _read_changespecs_from_disk(self) -> list[Patch]:
        from ....changespec import find_all_changespecs_cached

        return find_all_changespecs_cached()

    def _schedule_changespecs_async_refresh(self) -> None:
        if not hasattr(self, "_changespecs_loading"):
            self._schedule_patches_async_refresh()
            return
        if self._changespecs_loading:
            self._changespecs_refresh_pending = True
            return
        if getattr(self, "_changespecs_refresh_scheduled", False):
            return
        self._changespecs_refresh_scheduled = True
        self._spawn_changespecs_refresh_task()

    def _spawn_changespecs_refresh_task(self) -> None:
        self._spawn_patches_refresh_task()

    async def _run_changespecs_async_refresh(self) -> None:
        if not hasattr(self, "_changespecs_loading"):
            await self._run_patches_async_refresh()
            return
        self._changespecs_refresh_scheduled = False
        if self._changespecs_loading:
            self._changespecs_refresh_pending = True
            return
        self._changespecs_loading = True
        try:
            await self._reload_and_reposition_async()
        finally:
            self._changespecs_loading = False
            if self._changespecs_refresh_pending:
                self._changespecs_refresh_pending = False
                self._schedule_changespecs_async_refresh()

    def _refresh_changespecs_display_debounced(self) -> None:
        self._refresh_patches_display_debounced()

    def _refresh_changespec_detail_only(self) -> None:
        self._refresh_patch_detail_only()

    def _try_patch_changespec_row(self, idx: int) -> bool:
        return self._try_patch_patch_row(idx)

    def _get_changespec_graph_index(self) -> Any:
        return self._get_patch_graph_index()

    def _get_changespec_list_widget(self) -> Any:
        return self._get_patch_list_widget()

    def _get_changespec_detail_widget(self) -> Any:
        return self._get_patch_detail_widget()

    def _should_show_changespecs_onboarding(self) -> bool:
        return self._should_show_patches_onboarding()

    def _sync_changespecs_onboarding(self) -> bool:
        return self._sync_patches_onboarding()

    def _changespec_navigation_stops(self) -> Any:
        return _legacy_changespec_targets(self._patch_navigation_stops())

    def _navigate_changespec_panel(self, direction: int) -> None:
        self._navigate_patch_panel(direction)

    def _changespec_banner_focus_still_valid(self) -> bool:
        return self._patch_banner_focus_still_valid()

    def _changespec_jump_targets(self) -> Any:
        return _legacy_changespec_targets(self._patch_jump_targets())

    def action_edit_spec(self) -> None:
        """Edit the current Patch in $EDITOR."""
        if not (0 <= self.current_idx < len(self.patches)):
            return
        patch = self.patches[self.current_idx]
        self._open_spec_in_editor(patch)

    def action_show_agent_run_log(self) -> None:
        """Open the Agent Run Log modal for the current Patch."""
        if self.current_tab not in {"artifacts", "patches", "changespecs"}:
            return
        patches = getattr(self, "patches", getattr(self, "changespecs", []))
        if not patches:
            return
        patch = patches[self.current_idx]
        from ...modals.agent_run_log_modal import AgentRunLogModal

        self.push_screen(AgentRunLogModal(cl_name=patch.name))  # type: ignore[attr-defined]

    def _open_spec_in_editor(self, patch: Patch) -> None:
        """Open Patch in editor with nvim enhancements."""
        import subprocess

        from ....patch.locking import acquire_edit_lock, release_edit_lock

        editor = os.environ.get("EDITOR") or "nvim"
        file_path = os.path.expanduser(patch.file_path)
        args = [editor]
        if "/nvim" in editor:
            args.extend(
                [
                    "-c",
                    f"/NAME: \\zs{patch.name}$",
                    "-c",
                    "normal zz",
                    "-c",
                    "nohlsearch",
                ]
            )
        args.append(file_path)
        acquire_edit_lock(file_path)
        try:
            with self.suspend():  # type: ignore[attr-defined]
                subprocess.run(args, check=False)
        finally:
            release_edit_lock(file_path)

    def _save_selection_for_current_query(self) -> None:
        """Save the current Patch selection keyed by current query."""
        from ....query_selection import save_query_selections

        if self.patches:
            idx = min(self.current_idx, len(self.patches) - 1)
            name = self.patches[idx].name
            canonical = self.canonical_query_string  # type: ignore[attr-defined]
            # Pop and re-insert to mark as recently used
            self._query_selections.pop(canonical, None)
            self._query_selections[canonical] = name
            save_query_selections(self._query_selections)

    def _restore_selection_for_current_query(self) -> None:
        """Restore the saved Patch selection for the current query."""
        canonical = self.canonical_query_string  # type: ignore[attr-defined]
        saved_name = self._query_selections.get(canonical)
        if saved_name is None:
            return
        for idx, cs in enumerate(self.patches):
            if cs.name == saved_name:
                self.current_idx = idx
                return

    def action_toggle_hide_reverted(self) -> None:
        """Toggle visibility of reverted Patches, non-run agents, or axe commands."""
        if self.current_tab == "agents":
            self._toggle_hide_non_run_agents()  # type: ignore[attr-defined]
            return
        if self.current_tab == "axe":
            self._axe_cmds_hidden = not self._axe_cmds_hidden  # type: ignore[attr-defined]
            # If hiding and current selection is a bgcmd, navigate to axe parent
            from ...widgets.bgcmd_list import BgCmdItem

            axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
            if (
                self._axe_cmds_hidden
                and axe_items
                and 0 <= self.current_idx < len(axe_items)
                and isinstance(axe_items[self.current_idx], BgCmdItem)
            ):
                self.current_idx = 0
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]
            return
        if self.current_tab != "artifacts":
            return
        self.hide_reverted = not self.hide_reverted
        self._reload_and_reposition()

    def action_toggle_hide_submitted(self) -> None:
        """Toggle visibility of submitted Patches."""
        if self.current_tab != "artifacts":
            return
        self.hide_submitted = not self.hide_submitted
        self._reload_and_reposition()
