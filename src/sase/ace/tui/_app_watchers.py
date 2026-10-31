"""Reactive selection and tab watchers for :class:`AceApp`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from textual.events import Click

from .artifact_tabs import ArtifactsSubTab, FilesSubTab
from .artifacts_description import ArtifactsDescriptionMode
from .artifacts_split import ArtifactsSplitMode
from .tab_order import ARTIFACTS_TAB, SERVICES_TAB, TabName
from .widgets import ArtifactsView, TabBar

if TYPE_CHECKING:
    from .actions.navigation._types import BannerJumpTarget, PanelJumpTarget


_SCOPE_HINTS: tuple[tuple[str, str], ...] = (
    ("statistic", "statistics"),
    ("confighub", "config"),
    ("config_hub", "config"),
    ("gate", "gate"),
    ("machine", "machines"),
    ("memory", "memory"),
    ("snippet", "snippets"),
    ("project", "projects"),
    ("toolrun", "tool_runs"),
    ("tool_run", "tool_runs"),
    ("commandline", "command_line"),
    ("command_line", "command_line"),
)

# Built-in prefix modes recorded through the mode seam. ``saved_query``
# is handled separately (digit slots); ``custom`` collapses to ~custom.
_BUILTIN_MODES: tuple[str, ...] = ("fold", "copy", "leader", "bang", "bead_issue")

# Copy-mode keymap subgroups keyed by where the copy runs.
_COPY_GROUP_FOR_PANE: dict[str, str] = {
    "patches": "patches",
    "stitches": "artifacts_stitches",
    "plans": "artifacts_plans",
    "documents": "artifacts_documents",
    "beads": "artifacts_beads",
}

_CLASS_SCOPE_CACHE: dict[type, str] = {}
_IDS_MODULE: Any | None = None


def _load_ids() -> Any | None:
    """Load footprint identifiers only after the TUI records its first hit."""
    global _IDS_MODULE
    if _IDS_MODULE is not None:
        return _IDS_MODULE
    try:
        from sase.footprint import ids
    except Exception:
        return None
    _IDS_MODULE = ids
    return ids


def _scope_for(namespace: Any) -> str:
    """Return the keymap scope for a run_action namespace object.

    Only the concrete class name is considered: matching against the full
    MRO would catch mixin names (for example ``AgentDismissMemoryMixin``
    on ``AceApp``) and mis-scope app actions.
    """
    if namespace is None:
        return "app"
    cls = type(namespace)
    cached = _CLASS_SCOPE_CACHE.get(cls)
    if cached is not None:
        return cached
    name = cls.__name__.lower()
    scope = "app"
    for fragment, candidate in _SCOPE_HINTS:
        if fragment in name:
            scope = candidate
            break
    _CLASS_SCOPE_CACHE[cls] = scope
    return scope


def _flatten(keys: Mapping[str, Any], prefix: str, out: dict[str, str]) -> None:
    """Map raw key strings to dotted fields, mirroring the catalog generator."""
    for field, spec in keys.items():
        if isinstance(spec, dict):
            _flatten(spec, f"{prefix}.{field}", out)
        else:
            out[str(spec)] = f"{prefix}.{field}" if prefix else field


class FootprintTuiMixin:
    """Recording seams for :class:`AceApp`. First in the bases order."""

    _footprint_mouse_flag: bool = False
    _footprint_mode_maps_id: int | None = None
    _footprint_mode_maps: dict[str, dict[str, list[str]]] | None = None
    _footprint_tabs_seen: set[str] | None = None

    # -- low-level ------------------------------------------------------
    def _footprint_bump(self, feature_id: str, via: str) -> None:
        try:
            from sase.footprint._tui import bump

            bump(feature_id, via)
        except Exception:
            pass

    # -- run_action seam --------------------------------------------------
    async def run_action(  # type: ignore[no-untyped-def]
        self,
        action,
        default_namespace=None,
        namespaces=None,
    ) -> bool:
        result = await super().run_action(action, default_namespace, namespaces)  # type: ignore[misc]
        if result:
            try:
                self._footprint_record_action(action, default_namespace)
            except Exception:
                pass
        return result

    def _footprint_record_action(self, action: Any, namespace: Any) -> None:
        if isinstance(action, tuple):
            name = action[1] if len(action) > 1 and isinstance(action[1], str) else ""
        elif isinstance(action, str):
            name = action.split("(", 1)[0].strip()
            if ":" in name:
                name = name.rsplit(":", 1)[-1]
        else:
            return
        if not name:
            return
        ids = _load_ids()
        if ids is None:
            return
        scope = _scope_for(namespace if namespace is not None else self)
        feature_id = ids.tui_id(scope, name)
        if feature_id in ids.NAVIGATION_ACTIONS:
            return
        via = "mouse" if self._footprint_mouse_flag else "key"
        self._footprint_mouse_flag = False
        self._footprint_bump(feature_id, via)

    # -- mouse seam ---------------------------------------------------------
    def on_mouse_down(self, event: Any) -> None:
        self._footprint_mouse_flag = True
        return super().on_mouse_down(event)  # type: ignore[misc]

    # -- palette seam target --------------------------------------------------
    def _footprint_record_palette(self, spec_id: str) -> None:
        if not isinstance(spec_id, str) or not spec_id:
            return
        ids = _load_ids()
        if ids is None:
            return
        if spec_id.startswith("custom."):
            self._footprint_bump(ids.custom_id("tui"), "palette")
            return
        feature_id = f"tui:{ids.sanitize(spec_id)}"
        if not ids.is_valid_feature_id(feature_id):
            self._footprint_bump(ids.other_id("tui"), "palette")
            return
        if feature_id in ids.NAVIGATION_ACTIONS:
            return
        self._footprint_bump(feature_id, "palette")

    # -- prefix-mode seam ------------------------------------------------------
    def _footprint_mode_maps_current(self) -> dict[str, dict[str, list[str]]]:
        registry = getattr(self, "_keymap_registry", None)
        if registry is None:
            return {}
        if self._footprint_mode_maps is not None and self._footprint_mode_maps_id == id(
            registry
        ):
            return self._footprint_mode_maps
        modes: dict[str, dict[str, list[str]]] = {}
        for short in _BUILTIN_MODES:
            mode_name = f"{short}_mode" if short != "bead_issue" else "bead_issue_mode"
            mode = (getattr(registry, "modes", {}) or {}).get(mode_name)
            keys = getattr(mode, "keys", None)
            if not isinstance(keys, dict):
                continue
            flat: dict[str, str] = {}
            _flatten(keys, short, flat)
            grouped: dict[str, list[str]] = {}
            for raw_key, dotted in flat.items():
                grouped.setdefault(raw_key, []).append(dotted)
            modes[short] = grouped
        self._footprint_mode_maps = modes
        self._footprint_mode_maps_id = id(registry)
        return modes

    def _footprint_record_mode_key(self, mode: str, key: str) -> None:
        if not isinstance(key, str) or key == "escape":
            return
        if mode == "custom":
            ids = _load_ids()
            if ids is None:
                return
            self._footprint_bump(ids.custom_id("tui"), "mode")
            return
        if mode == "saved_query":
            if len(key) == 1 and key.isdigit():
                self._footprint_bump(f"tui:saved_query.{key}", "mode")
            return
        if mode not in _BUILTIN_MODES:
            return
        ids = _load_ids()
        if ids is None:
            return
        candidates = self._footprint_mode_maps_current().get(mode, {}).get(key)
        if not candidates:
            return
        dotted = self._footprint_disambiguate(mode, key, sorted(candidates))
        self._footprint_bump(f"tui:{dotted}", "mode")

    def _footprint_disambiguate(
        self, mode: str, key: str, candidates: list[str]
    ) -> str:
        del key
        if len(candidates) == 1 or mode != "copy":
            return candidates[0]
        try:
            if getattr(self, "current_tab", None) == "agents":
                for dotted in candidates:
                    if dotted in (
                        "copy.agents.chat",
                        "copy.agents.name",
                    ) or dotted.startswith("copy.agents."):
                        return dotted
            pane = getattr(self, "current_artifacts_pane_key", None)
            want = _COPY_GROUP_FOR_PANE.get(str(pane)) if pane is not None else None
            if want is not None:
                for dotted in candidates:
                    if dotted.startswith(f"copy.{want}."):
                        return dotted
        except Exception:
            pass
        return candidates[0]

    # -- view-entry seams ---------------------------------------------------------
    def _footprint_record_view(self, feature_id: str) -> None:
        ids = _load_ids()
        if ids is None:
            return
        if ids.is_valid_feature_id(feature_id):
            self._footprint_bump(feature_id, "key")

    def _footprint_record_tab(self, tab: Any) -> None:
        if getattr(self, "_mounting", False):
            return
        if getattr(self, "_startup_initial_tab", None) is None:
            return
        name = str(tab)
        seen = self._footprint_tabs_seen
        if seen is None:
            seen = set()
            self._footprint_tabs_seen = seen
        if name == str(getattr(self, "_startup_initial_tab", None)) and not seen:
            seen.add(name)
            return
        seen.add(name)
        ids = _load_ids()
        if ids is None:
            return
        self._footprint_record_view(ids.tab_view_id(name))

    def _footprint_record_subtab(self, subtab: Any) -> None:
        if getattr(self, "_mounting", False):
            return
        if getattr(self, "_startup_initial_tab", None) is None:
            return
        ids = _load_ids()
        if ids is None:
            return
        self._footprint_record_view(ids.tab_view_id(str(subtab)))

    def _footprint_record_admin_tab(self, tab: Any) -> None:
        ids = _load_ids()
        if ids is None:
            return
        self._footprint_record_view(ids.admin_view_id(str(tab)))

    def _footprint_record_stats_view(self, view: Any) -> None:
        ids = _load_ids()
        if ids is None:
            return
        name = getattr(view, "value", view)
        self._footprint_record_view(ids.stats_view_id(str(name)))

    # -- modal seam ------------------------------------------------------------------
    def push_screen(  # type: ignore[no-untyped-def]
        self,
        screen,
        callback=None,
        wait_for_dismiss=False,
        *,
        mode=None,
    ):
        try:
            from textual.screen import ModalScreen

            if isinstance(screen, ModalScreen):
                ids = _load_ids()
                if ids is not None:
                    self._footprint_record_view(ids.modal_id(type(screen).__name__))
        except Exception:
            pass
        return super().push_screen(  # type: ignore[misc]
            screen,
            callback,
            wait_for_dismiss,
            mode=mode,
        )


class AppWatchersMixin:
    """Respond to top-level selection and tab state changes."""

    def _cancel_selected_live_reply_follow(self: Any) -> None:
        """Invalidate the hidden prompt source on selection or tab changes."""
        get_panel = getattr(self, "_deck_source_panel", None)
        if not callable(get_panel):
            return
        try:
            panel = get_panel()
        except Exception:
            return
        cancel = getattr(panel, "cancel_live_reply_follow", None)
        if callable(cancel):
            cancel()

    def on_click(self: Any, event: Click) -> None:
        """A click outside the shelf ends its temporary focus state."""
        if getattr(getattr(event, "widget", None), "id", None) == (
            "agent-archive-shelf"
        ):
            return
        from .actions.agents._archive_shelf import clear_archive_shelf_focus

        clear_archive_shelf_focus(self)

    def watch_current_idx(self: Any, old_idx: int, new_idx: int) -> None:
        """React to current_idx changes."""
        if old_idx != new_idx:
            if self.current_tab == "agents":
                self._cancel_selected_live_reply_follow()
            clear_link_trail = getattr(self, "_clear_link_trail_if_unguarded", None)
            if callable(clear_link_trail):
                clear_link_trail()
            if (
                self.current_tab == ARTIFACTS_TAB
                and self.current_artifacts_subtab == "patches"
            ):
                self._refresh_patches_display_debounced()
            elif self.current_tab == "agents":
                self._refresh_agents_display_debounced()
            elif self.current_tab == SERVICES_TAB:
                self._refresh_axe_display_debounced()
            refresh_link_rail = getattr(self, "refresh_link_rail", None)
            if callable(refresh_link_rail):
                refresh_link_rail()
            if self._jk_perf is not None:
                self.call_after_refresh(self._jk_perf.mark_painted)

    def watch_current_tab(
        self: Any,
        old_tab: TabName,
        new_tab: TabName,
    ) -> None:
        """React to tab changes by showing/hiding views."""
        if old_tab == new_tab:
            return
        try:
            self._footprint_record_tab(new_tab)  # type: ignore[attr-defined]
        except Exception:
            pass

        if old_tab == "agents":
            self._cancel_selected_live_reply_follow()
            from .actions.agents._archive_shelf import clear_archive_shelf_focus

            clear_archive_shelf_focus(self)

        clear_link_trail = getattr(self, "_clear_link_trail_if_unguarded", None)
        if callable(clear_link_trail):
            clear_link_trail()

        cancel_member_jump = getattr(self, "_cancel_member_jump_pending", None)
        if callable(cancel_member_jump):
            cancel_member_jump(refresh_footer=False)

        from .util.trace import set_trace_context

        set_trace_context(current_tab=new_tab)

        if new_tab == SERVICES_TAB or (
            new_tab == ARTIFACTS_TAB and self.current_artifacts_subtab != "patches"
        ):
            self._fold_mode_active = False

        # Cancel pending detail-panel work for the tab we're leaving. The new
        # tab redraws fresh, so deferred work would land in a hidden view.
        if old_tab == "agents":
            if getattr(self, "_agent_hint_render_identity", None) is not None:
                self._remove_hint_input_bar(refresh=False)
            self._exit_agent_metadata_search_for_context_change()
            self._agent_detail_debouncer.cancel()
            self._expanded_panel_focus = False
        elif old_tab == SERVICES_TAB:
            self._axe_detail_debouncer.cancel()
        elif old_tab == ARTIFACTS_TAB and self.current_artifacts_subtab == "patches":
            self._patch_detail_debouncer.cancel()

        if old_tab == "agents" and getattr(self, "_panel_fold_hint_mode_active", False):
            self._teardown_panel_fold_hint_mode(refresh_titles=False)

        # Tab changes always cancel adaptive entry-jump mode.
        self._cancel_non_pr_artifacts_jump_mode()
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_target: dict[str, object] = {}
        self._entry_jump_pending_prefix = ""
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_banner: dict[str, BannerJumpTarget] = {}
        self._entry_jump_banner_to_hint: dict[BannerJumpTarget, str] = {}
        self._entry_jump_hint_to_panel: dict[str, PanelJumpTarget] = {}
        self._entry_jump_panel_to_hint: dict[PanelJumpTarget, str] = {}
        self._entry_jump_hint_to_patch_banner: dict[str, tuple[str, ...]] = {}
        self._entry_jump_patch_banner_to_hint: dict[tuple[str, ...], str] = {}

        tab_bar = self.query_one("#tab-bar", TabBar)
        tab_bar.update_tab(new_tab)

        patches_view = self.query_one("#artifacts-view", ArtifactsView)
        agents_view = self.query_one("#agents-view")
        axe_view = self.query_one("#axe-view")

        if old_tab == ARTIFACTS_TAB:
            patches_view.deactivate_current()

        if new_tab == ARTIFACTS_TAB:
            patches_view.remove_class("hidden")
            patches_view.disabled = False
            agents_view.add_class("hidden")
            agents_view.disabled = True
            axe_view.add_class("hidden")
            axe_view.disabled = True
            patches_view.activate_current()
            self._sync_active_artifacts_entry_state()
            if not getattr(self, "_mounting", False):
                maybe_rebuild = getattr(
                    self, "_maybe_schedule_visible_patch_relation_rebuild", None
                )
                if callable(maybe_rebuild):
                    maybe_rebuild()
        elif new_tab == "agents":
            patches_view.add_class("hidden")
            patches_view.disabled = True
            agents_view.remove_class("hidden")
            agents_view.disabled = False
            axe_view.add_class("hidden")
            axe_view.disabled = True
            self._sync_artifact_file_viewer_layout()
            startup_surface_started = False
            maybe_start_startup_surface = getattr(
                self,
                "_maybe_start_startup_surface_for_tab",
                None,
            )
            if callable(maybe_start_startup_surface):
                startup_surface_started = bool(maybe_start_startup_surface("agents"))
            # During mount, on_mount schedules the initial async load. On a
            # later tab switch, show cached data immediately and only re-fetch
            # when there is pending work to consume.
            if not self._mounting:
                reconcile_tool_runs = getattr(
                    self,
                    "_reconcile_tool_runs_on_agents_entry",
                    None,
                )
                if callable(reconcile_tool_runs):
                    try:
                        reconcile_tool_runs()
                    except Exception:
                        pass
                self._refilter_agents()
                refresh_capacity = getattr(
                    self,
                    "_schedule_agents_capacity_refresh_from_roster",
                    None,
                )
                if callable(refresh_capacity):
                    refresh_capacity(source="tab_switch")
                update_agents_header = getattr(self, "_update_agents_header", None)
                if callable(update_agents_header):
                    update_agents_header()
                schedule_fleet_refresh = getattr(
                    self,
                    "_schedule_agents_fleet_refresh",
                    None,
                )
                if callable(schedule_fleet_refresh):
                    schedule_fleet_refresh(source="tab_switch")
                if (
                    getattr(self, "_dirty_agents", False)
                    and not getattr(self, "_agents_loading", False)
                    and not startup_surface_started
                ):
                    if hasattr(self, "_schedule_agents_async_refresh"):
                        self._schedule_agents_async_refresh(source="tab_switch")
        else:  # axe
            patches_view.add_class("hidden")
            patches_view.disabled = True
            agents_view.add_class("hidden")
            agents_view.disabled = True
            axe_view.remove_class("hidden")
            axe_view.disabled = False
            startup_surface_started = False
            maybe_start_startup_surface = getattr(
                self,
                "_maybe_start_startup_surface_for_tab",
                None,
            )
            if callable(maybe_start_startup_surface):
                startup_surface_started = bool(
                    maybe_start_startup_surface(SERVICES_TAB)
                )
            self._refresh_axe_display()
            if not startup_surface_started:
                self._schedule_axe_async_refresh()

        if new_tab == "agents" and not self._mounting:
            get_panel = getattr(self, "_deck_source_panel", None)
            get_selected = getattr(self, "_get_selected_agent", None)
            if callable(get_panel) and callable(get_selected):
                try:
                    configure = getattr(
                        get_panel(), "configure_live_reply_follow", None
                    )
                    selected = get_selected()
                    if callable(configure) and selected is not None:
                        configure(selected)
                except Exception:
                    pass

        # Refresh an open tab-scoped help panel with the new context.
        from .modals import HelpModal

        screen = self.screen
        if isinstance(screen, HelpModal):
            if new_tab == "agents":
                self._prepare_agents_help_guide_state()
            pane_id = getattr(self, "current_artifacts_pane_key", "patches")
            query_context = getattr(self, "_query_history_help_context", None)
            if callable(query_context):
                active_query, query_history, query_history_enabled = query_context()
            else:
                active_query = self.canonical_query_string
                query_history = None
                query_history_enabled = False
            screen.refresh_for_tab(
                new_tab,
                active_query,
                registry=self._keymap_registry,
                saved_queries={
                    slot: record.canonical
                    for slot, record in self._saved_queries.get(pane_id, {}).items()
                },
                query_history=query_history,
                query_history_enabled=query_history_enabled,
                pane_id=pane_id,
                agents_launch_targets_available=(
                    self._agents_onboarding_launch_targets_available
                ),
                agents_plugins_installed=self._agents_onboarding_plugins_installed,
            )
        refresh_link_rail = getattr(self, "refresh_link_rail", None)
        if callable(refresh_link_rail):
            refresh_link_rail()

    def watch_current_artifacts_subtab(
        self: Any,
        old_subtab: ArtifactsSubTab,
        new_subtab: ArtifactsSubTab,
    ) -> None:
        """Switch Artifacts panes and preserve PR detail/refresh isolation."""
        if old_subtab == new_subtab:
            return
        try:
            self._footprint_record_subtab(new_subtab)  # type: ignore[attr-defined]
        except Exception:
            pass
        clear_link_trail = getattr(self, "_clear_link_trail_if_unguarded", None)
        if callable(clear_link_trail):
            clear_link_trail()
        if new_subtab != "patches":
            self._fold_mode_active = False
        if self._entry_jump_mode_active:
            self._exit_entry_jump_mode()
        else:
            self._cancel_non_pr_artifacts_jump_mode()
        try:
            view = self.query_one("#artifacts-view", ArtifactsView)
        except Exception:
            return
        if old_subtab == "patches":
            self._patch_detail_debouncer.cancel()
        view.switch_to(new_subtab)
        if self.current_tab != ARTIFACTS_TAB:
            return
        self._sync_active_artifacts_entry_state()
        if not getattr(self, "_mounting", False):
            maybe_rebuild = getattr(
                self, "_maybe_schedule_visible_patch_relation_rebuild", None
            )
            if callable(maybe_rebuild):
                maybe_rebuild()
        refresh_link_rail = getattr(self, "refresh_link_rail", None)
        if callable(refresh_link_rail):
            refresh_link_rail()
        from .modals import HelpModal

        screen = self.screen
        if isinstance(screen, HelpModal):
            pane_id = getattr(self, "current_artifacts_pane_key", "patches")
            query_context = getattr(self, "_query_history_help_context", None)
            if callable(query_context):
                active_query, query_history, query_history_enabled = query_context()
            else:
                active_query = self.canonical_query_string
                query_history = None
                query_history_enabled = False
            screen.refresh_for_tab(
                self.current_tab,
                active_query,
                registry=self._keymap_registry,
                saved_queries={
                    slot: record.canonical
                    for slot, record in self._saved_queries.get(pane_id, {}).items()
                },
                query_history=query_history,
                query_history_enabled=query_history_enabled,
                pane_id=pane_id,
                agents_launch_targets_available=(
                    self._agents_onboarding_launch_targets_available
                ),
                agents_plugins_installed=self._agents_onboarding_plugins_installed,
            )

    def watch_artifacts_split_mode(
        self: Any,
        old_mode: ArtifactsSplitMode,
        new_mode: ArtifactsSplitMode,
    ) -> None:
        """Apply the shared Artifacts split and refresh the Patch width cap."""

        if old_mode == new_mode:
            return
        try:
            view = self.query_one("#artifacts-view", ArtifactsView)
        except Exception:
            return
        view.apply_split_mode(new_mode)
        self._apply_patch_list_width()

    def watch_artifacts_description_mode(
        self: Any,
        old_mode: ArtifactsDescriptionMode,
        new_mode: ArtifactsDescriptionMode,
    ) -> None:
        """Apply the shared pane-brief description mode."""

        if old_mode == new_mode:
            return
        try:
            view = self.query_one("#artifacts-view", ArtifactsView)
        except Exception:
            return
        view.apply_description_mode(new_mode)

    def watch_current_files_subtab(
        self: Any,
        old_subtab: FilesSubTab,
        new_subtab: FilesSubTab,
    ) -> None:
        """Compatibility watcher for the retired nested Files panes."""
        del old_subtab
        try:
            self._footprint_record_subtab(new_subtab)  # type: ignore[attr-defined]
        except Exception:
            pass
