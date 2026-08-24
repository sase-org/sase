"""Patch management mixin for the ace TUI app."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from ._display import PatchDisplayMixin
from ._filter_session import PatchFilterSessionActionsMixin
from ._grouping_nav import PatchGroupingNavMixin
from ._loading import PatchLoadingMixin
from ._query import PatchQueryMixin

if TYPE_CHECKING:
    from ....query.types import QueryExpr
    from ....query_history import QueryHistoryStacks
    from ...models.fold_state import FoldLevel
    from ...util.debounce import DetailPanelDebouncer
    from sase.core.artifact_relation_layout import RelationKeymap

from ....patch import Patch
from ...tab_order import ARTIFACTS_TAB


def _legacy_changespec_targets(targets: Any) -> Any:
    return [
        (
            # legacy compatibility alias
            "changespec" if kind == "patch" else kind,
            payload,
        )  # legacy compatibility alias
        for kind, payload in targets
    ]


class PatchMixin(
    PatchLoadingMixin,
    PatchFilterSessionActionsMixin,
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
    _query_history: dict[str, QueryHistoryStacks]
    _query_selections: dict[str, dict[str, str]]
    _all_patches: list[Patch]
    _relation_keymap: RelationKeymap
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
    def changespecs(self) -> list[Patch]:  # legacy compatibility alias
        """Legacy alias for :attr:`patches`."""
        return self.patches

    @changespecs.setter  # legacy compatibility alias
    def changespecs(self, value: list[Patch]) -> None:  # legacy compatibility alias
        self.patches = value

    @property
    def commits_collapsed(self) -> FoldLevel:
        """Legacy alias for :attr:`stitches_collapsed`."""
        return self.stitches_collapsed

    @commits_collapsed.setter
    def commits_collapsed(self, value: FoldLevel) -> None:
        self.stitches_collapsed = value

    @property
    def _all_changespecs(self) -> list[Patch]:  # legacy compatibility alias
        return self._legacy_get("_all_patches", [])

    @_all_changespecs.setter  # legacy compatibility alias
    def _all_changespecs(
        self, value: list[Patch]
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_all_patches", value)

    @property
    def _changespecs_last_idx(self) -> int:  # legacy compatibility alias
        return self._legacy_get("_patches_last_idx", 0)

    @_changespecs_last_idx.setter  # legacy compatibility alias
    def _changespecs_last_idx(self, value: int) -> None:  # legacy compatibility alias
        self._legacy_set("_patches_last_idx", value)

    @property
    def _changespecs_last_name(self) -> str | None:  # legacy compatibility alias
        return self._legacy_get("_patches_last_name")

    @_changespecs_last_name.setter  # legacy compatibility alias
    def _changespecs_last_name(
        self, value: str | None
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_patches_last_name", value)

    @property
    def _changespecs_loading(self) -> bool:  # legacy compatibility alias
        return self._legacy_get("_patches_loading", False)

    @_changespecs_loading.setter  # legacy compatibility alias
    def _changespecs_loading(self, value: bool) -> None:  # legacy compatibility alias
        self._legacy_set("_patches_loading", value)

    @property
    def _changespecs_refresh_scheduled(self) -> bool:  # legacy compatibility alias
        return self._legacy_get("_patches_refresh_scheduled", False)

    @_changespecs_refresh_scheduled.setter  # legacy compatibility alias
    def _changespecs_refresh_scheduled(
        self, value: bool
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_patches_refresh_scheduled", value)

    @property
    def _changespecs_refresh_pending(self) -> bool:  # legacy compatibility alias
        return self._legacy_get("_patches_refresh_pending", False)

    @_changespecs_refresh_pending.setter  # legacy compatibility alias
    def _changespecs_refresh_pending(
        self, value: bool
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_patches_refresh_pending", value)

    @property
    def _changespecs_first_load_done(self) -> bool:  # legacy compatibility alias
        return self._legacy_get("_patches_first_load_done", False)

    @_changespecs_first_load_done.setter  # legacy compatibility alias
    def _changespecs_first_load_done(
        self, value: bool
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_patches_first_load_done", value)

    @property
    def _dirty_changespecs(self) -> bool:  # legacy compatibility alias
        return self._legacy_get("_dirty_patches", False)

    @_dirty_changespecs.setter  # legacy compatibility alias
    def _dirty_changespecs(self, value: bool) -> None:  # legacy compatibility alias
        self._legacy_set("_dirty_patches", value)

    @property
    def _changespec_grouping_mode(self) -> Any:  # legacy compatibility alias
        return self._legacy_get("_patch_grouping_mode")

    @_changespec_grouping_mode.setter  # legacy compatibility alias
    def _changespec_grouping_mode(
        self, value: Any
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_patch_grouping_mode", value)

    @property
    def _changespec_group_fold_registries(self) -> Any:  # legacy compatibility alias
        return self._legacy_get("_patch_group_fold_registries", {})

    @_changespec_group_fold_registries.setter  # legacy compatibility alias
    def _changespec_group_fold_registries(
        self, value: Any
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_patch_group_fold_registries", value)

    @property
    def _changespec_group_fold_registry(self) -> Any:  # legacy compatibility alias
        return self._legacy_get("_patch_group_fold_registry")

    @_changespec_group_fold_registry.setter  # legacy compatibility alias
    def _changespec_group_fold_registry(
        self, value: Any
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_patch_group_fold_registry", value)

    @property
    # legacy compatibility alias
    def _current_changespec_group_key(
        self,
    ) -> tuple[str, ...] | None:  # legacy compatibility alias
        return self._legacy_get("_current_patch_group_key")

    @_current_changespec_group_key.setter  # legacy compatibility alias
    # legacy compatibility alias
    def _current_changespec_group_key(
        self, value: tuple[str, ...] | None
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_current_patch_group_key", value)

    @property
    def _changespec_graph_index(self) -> Any:  # legacy compatibility alias
        return self._legacy_get("_patch_graph_index")

    @_changespec_graph_index.setter  # legacy compatibility alias
    def _changespec_graph_index(self, value: Any) -> None:  # legacy compatibility alias
        self._legacy_set("_patch_graph_index", value)

    @property
    # legacy compatibility alias
    def _changespec_graph_index_for_id(
        self,
    ) -> int | None:  # legacy compatibility alias
        return self._legacy_get("_patch_graph_index_for_id")

    @_changespec_graph_index_for_id.setter  # legacy compatibility alias
    def _changespec_graph_index_for_id(
        self, value: int | None
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_patch_graph_index_for_id", value)

    @property
    # legacy compatibility alias
    def _entry_jump_hint_to_changespec_banner(
        self,
    ) -> dict[str, tuple[str, ...]]:  # legacy compatibility alias
        return self._legacy_get("_entry_jump_hint_to_patch_banner", {})

    @_entry_jump_hint_to_changespec_banner.setter  # legacy compatibility alias
    def _entry_jump_hint_to_changespec_banner(  # legacy compatibility alias
        self,
        value: dict[str, tuple[str, ...]],
    ) -> None:
        self._legacy_set("_entry_jump_hint_to_patch_banner", value)

    @property
    # legacy compatibility alias
    def _entry_jump_changespec_banner_to_hint(
        self,
    ) -> dict[tuple[str, ...], str]:  # legacy compatibility alias
        return self._legacy_get("_entry_jump_patch_banner_to_hint", {})

    @_entry_jump_changespec_banner_to_hint.setter  # legacy compatibility alias
    def _entry_jump_changespec_banner_to_hint(  # legacy compatibility alias
        self,
        value: dict[tuple[str, ...], str],
    ) -> None:
        self._legacy_set("_entry_jump_patch_banner_to_hint", value)

    @property
    def _w_changespec_list(self) -> Any:  # legacy compatibility alias
        return self._legacy_get("_w_patch_list")

    @_w_changespec_list.setter  # legacy compatibility alias
    def _w_changespec_list(self, value: Any) -> None:  # legacy compatibility alias
        self._legacy_set("_w_patch_list", value)

    @property
    def _w_changespec_detail(self) -> Any:  # legacy compatibility alias
        return self._legacy_get("_w_patch_detail")

    @_w_changespec_detail.setter  # legacy compatibility alias
    def _w_changespec_detail(self, value: Any) -> None:  # legacy compatibility alias
        self._legacy_set("_w_patch_detail", value)

    @property
    def _w_changespec_info_panel(self) -> Any:  # legacy compatibility alias
        return self._legacy_get("_w_patch_info_panel")

    @_w_changespec_info_panel.setter  # legacy compatibility alias
    def _w_changespec_info_panel(
        self, value: Any
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_w_patch_info_panel", value)

    @property
    # legacy compatibility alias
    def _changespec_detail_debouncer(
        self,
    ) -> DetailPanelDebouncer:  # legacy compatibility alias
        return self._legacy_get("_patch_detail_debouncer")

    @_changespec_detail_debouncer.setter  # legacy compatibility alias
    def _changespec_detail_debouncer(
        self, value: DetailPanelDebouncer
    ) -> None:  # legacy compatibility alias
        self._legacy_set("_patch_detail_debouncer", value)

    def _load_changespecs(self) -> None:  # legacy compatibility alias
        self._load_patches()

    # legacy compatibility alias
    def _filter_changespecs(
        self, patches: list[Patch]
    ) -> list[Patch]:  # legacy compatibility alias
        return self._filter_patches(patches)

    # legacy compatibility alias
    def _apply_changespecs(
        self, all_patches: list[Patch]
    ) -> None:  # legacy compatibility alias
        self._apply_patches(all_patches)

    def _apply_reloaded_changespecs(  # legacy compatibility alias
        self,
        all_patches: list[Patch],
        current_name: str | None,
        **kwargs: Any,
    ) -> None:
        self._apply_reloaded_patches(all_patches, current_name, **kwargs)

    def _read_changespecs_from_disk(self) -> list[Patch]:  # legacy compatibility alias
        from .... import changespec as changespec_module  # legacy compatibility alias
        from .... import patch as patch_module

        loader = self._compat_loader(
            changespec_module.find_all_changespecs_cached,  # legacy compatibility alias
            patch_module.find_all_patches_cached,
        )
        return loader()

    def _schedule_changespecs_async_refresh(self) -> None:  # legacy compatibility alias
        if not hasattr(self, "_changespecs_loading"):  # legacy compatibility alias
            self._schedule_patches_async_refresh()
            return
        if self._changespecs_loading:  # legacy compatibility alias
            self._changespecs_refresh_pending = True  # legacy compatibility alias
            return
        if getattr(
            self, "_changespecs_refresh_scheduled", False
        ):  # legacy compatibility alias
            return
        self._changespecs_refresh_scheduled = True  # legacy compatibility alias
        self._spawn_changespecs_refresh_task()  # legacy compatibility alias

    def _spawn_changespecs_refresh_task(self) -> None:  # legacy compatibility alias
        self._spawn_patches_refresh_task()

    # legacy compatibility alias
    async def _run_changespecs_async_refresh(
        self,
    ) -> None:  # legacy compatibility alias
        if not hasattr(self, "_changespecs_loading"):  # legacy compatibility alias
            await self._run_patches_async_refresh()
            return
        self._changespecs_refresh_scheduled = False  # legacy compatibility alias
        if self._changespecs_loading:  # legacy compatibility alias
            self._changespecs_refresh_pending = True  # legacy compatibility alias
            return
        self._changespecs_loading = True  # legacy compatibility alias
        try:
            await self._reload_and_reposition_async()
        finally:
            self._changespecs_loading = False  # legacy compatibility alias
            if self._changespecs_refresh_pending:  # legacy compatibility alias
                self._changespecs_refresh_pending = False  # legacy compatibility alias
                self._schedule_changespecs_async_refresh()  # legacy compatibility alias

    # legacy compatibility alias
    def _refresh_changespecs_display_debounced(
        self,
    ) -> None:  # legacy compatibility alias
        self._refresh_patches_display_debounced()

    def _refresh_changespec_detail_only(self) -> None:  # legacy compatibility alias
        self._refresh_patch_detail_only()

    def _try_patch_changespec_row(self, idx: int) -> bool:  # legacy compatibility alias
        return self._try_patch_patch_row(idx)

    def _get_changespec_graph_index(self) -> Any:  # legacy compatibility alias
        return self._get_patch_graph_index()

    def _get_changespec_list_widget(self) -> Any:  # legacy compatibility alias
        return self._get_patch_list_widget()

    def _get_changespec_detail_widget(self) -> Any:  # legacy compatibility alias
        return self._get_patch_detail_widget()

    def _should_show_changespecs_onboarding(self) -> bool:  # legacy compatibility alias
        return self._should_show_patches_onboarding()

    def _sync_changespecs_onboarding(self) -> bool:  # legacy compatibility alias
        return self._sync_patches_onboarding()

    def _changespec_navigation_stops(self) -> Any:  # legacy compatibility alias
        return _legacy_changespec_targets(self._patch_navigation_stops())

    # legacy compatibility alias
    def _navigate_changespec_panel(
        self, direction: int
    ) -> None:  # legacy compatibility alias
        self._navigate_patch_panel(direction)

    # legacy compatibility alias
    def _changespec_banner_focus_still_valid(
        self,
    ) -> bool:  # legacy compatibility alias
        return self._patch_banner_focus_still_valid()

    def _changespec_jump_targets(self) -> Any:  # legacy compatibility alias
        return _legacy_changespec_targets(self._patch_jump_targets())

    def action_edit_spec(self) -> None:
        """Edit the current Patch in $EDITOR."""
        if not (0 <= self.current_idx < len(self.patches)):
            return
        patch = self.patches[self.current_idx]
        self._open_spec_in_editor(patch)

    def action_show_agent_run_log(self) -> None:
        """Open the Agent Run Log modal for the current Patch."""
        if self.current_tab not in {
            "artifacts",
            "patches",
            "changespecs",  # legacy compatibility tab id
        }:
            return
        patches = getattr(
            self, "patches", getattr(self, "changespecs", [])
        )  # legacy compatibility alias
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
        from ...widgets.artifacts.patch_entry import patch_row_target

        if self.patches:
            idx = min(self.current_idx, len(self.patches) - 1)
            target = patch_row_target(self.patches[idx])
            canonical = self.canonical_query_string  # type: ignore[attr-defined]
            pane_id = "patches"
            remember = getattr(self, "_remember_artifacts_query_selection", None)
            if callable(remember):
                remember(pane_id, canonical, target)
                return
            selections = dict(self._query_selections.get(pane_id, {}))
            # Pop and re-insert to mark as recently used
            selections.pop(canonical, None)
            selections[canonical] = target.to_token()
            self._query_selections[pane_id] = selections
            save_query_selections(pane_id, selections)

    def _restore_selection_for_current_query(self) -> None:
        """Restore the saved Patch selection for the current query."""
        from ...widgets.artifacts.entry_navigation import ArtifactEntryTarget
        from ...widgets.artifacts.patch_entry import patch_row_target

        canonical = self.canonical_query_string  # type: ignore[attr-defined]
        token = self._query_selections.get("patches", {}).get(canonical)
        if token is None:
            return
        try:
            target = ArtifactEntryTarget.from_token(token)
        except ValueError:
            return
        for idx, cs in enumerate(self.patches):
            if patch_row_target(cs) == target:
                self.current_idx = idx
                return

    def action_toggle_hide_reverted(self) -> None:
        """Toggle visibility of non-run agents or axe commands."""
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

    def action_patches_toggle_reverted(self) -> None:
        """Toggle visibility of reverted Patches."""
        if (
            self.current_tab != ARTIFACTS_TAB
            or getattr(self, "current_artifacts_pane_key", None) != "patches"
        ):
            return
        self.hide_reverted = not self.hide_reverted
        self._reload_and_reposition()

    def action_toggle_hide_submitted(self) -> None:
        """Toggle visibility of submitted Patches."""
        if self.current_tab != "artifacts":
            return
        self.hide_submitted = not self.hide_submitted
        self._reload_and_reposition()
