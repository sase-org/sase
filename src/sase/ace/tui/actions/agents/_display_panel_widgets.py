"""AgentList mounting and selective panel-widget refresh helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...models.agent_groups import (
    GroupingMode,
    machine_grouping_signature,
    status_grouping_signature,
)
from ...util.trace import tui_trace
from ._display_helpers import (
    agent_list_widgets_in,
    panel_widget_id,
    panel_widget_id_for_key,
)
from ._display_panel_state import PanelRefreshStateMixin
from ._fold_scope import panel_fold_registry
from ._panel_fold_intent import effective_panel_collapses
from ._refresh_trace import record_agents_refresh_trace

if TYPE_CHECKING:
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey
    from ...widgets import AgentList
    from ..navigation.jump_hints import BannerJumpTarget, PanelJumpTarget


def _panel_row_signature(
    agents: list[Any],
    grouping_mode: GroupingMode,
) -> tuple[tuple[Any, ...], ...]:
    """Return visible-row identities plus grouping signatures for *agents*."""
    rows: list[tuple[Any, ...]] = []
    for agent in agents:
        identity = getattr(agent, "identity", None)
        if grouping_mode is GroupingMode.BY_STATUS:
            extra: tuple[Any, ...] = status_grouping_signature(agent)
        elif grouping_mode is GroupingMode.BY_MACHINE:
            extra = machine_grouping_signature(agent)
        else:
            extra = ()
        rows.append((identity, extra, getattr(agent, "tribe", None)))
    return tuple(rows)


def _panel_agents_match(current: list[Any], target: list[Any]) -> bool:
    """Return whether *current* already holds *target*'s rows and row content."""
    if len(current) != len(target):
        return False
    return all(
        old is new or old == new for old, new in zip(current, target, strict=True)
    )


def _sorted_items(mapping: dict[Any, Any] | None) -> tuple[tuple[Any, Any], ...]:
    return tuple(sorted(mapping.items())) if mapping else ()


def _panel_paint_key(
    *,
    jump_hints: dict[int, str] | None,
    banner_jump_hints: dict[tuple[str, ...], str] | None,
    marked: set[Any],
    unread: set[Any],
    marked_fold_keys: Any,
    fold_counts: dict[str, tuple[int, int]],
    attempt_number: int | None,
    current_group_key: tuple[str, ...] | None,
    tribe_labels: list[str | None] | None,
    panel_tribe: str | None,
    visible_parent_keys: set[str],
    fully_expanded_parent_keys: set[str],
    fold_registry: Any,
) -> tuple[Any, ...]:
    """Snapshot every non-row input that changes how a panel's rows paint."""
    return (
        _sorted_items(jump_hints),
        _sorted_items(banner_jump_hints),
        frozenset(marked),
        frozenset(unread),
        tuple(marked_fold_keys),
        _sorted_items(fold_counts),
        attempt_number,
        current_group_key,
        None if tribe_labels is None else tuple(tribe_labels),
        panel_tribe,
        frozenset(visible_parent_keys),
        frozenset(fully_expanded_parent_keys),
        (id(fold_registry), getattr(fold_registry, "version", None)),
    )


class PanelWidgetRefreshMixin(PanelRefreshStateMixin):
    """Mount, remove, and repaint AgentList panel widgets."""

    def _panel_widget_id(self, panel_idx: int) -> str:
        """Test-compat wrapper: tribe-stable id for the current slot index."""
        keys = getattr(getattr(self, "_panel_group", None), "panel_keys", ())
        if 0 <= panel_idx < len(keys):
            return panel_widget_id_for_key(keys[panel_idx])
        return panel_widget_id(panel_idx)

    def _refresh_panel_widgets(
        self,
        *,
        jump_hints: dict[int, str] | None,
        banner_jump_hints: dict[BannerJumpTarget, str] | None = None,
        panel_jump_hints: dict[PanelJumpTarget, str] | None = None,
    ) -> None:
        """Mount/unmount AgentList widgets to match :attr:`_panel_group`."""
        with tui_trace(
            "agents.refresh_panel_widgets",
            agents=len(self._agents),
            panels=len(self._panel_group.panel_keys),
            panel_widget_ids=[
                panel_widget_id_for_key(key) for key in self._panel_group.panel_keys
            ],
        ):
            self._refresh_panel_widgets_impl(
                jump_hints=jump_hints,
                banner_jump_hints=banner_jump_hints,
                panel_jump_hints=panel_jump_hints,
            )

    def _unmount_agent_list(self, container: object, widget: AgentList) -> None:
        """Remove one AgentList from *container*, including test fakes."""
        remove = getattr(widget, "remove", None)
        if callable(remove):
            try:
                remove()
                return
            except Exception:
                pass
        children = getattr(container, "children", None)
        if isinstance(children, list) and widget in children:
            children.remove(widget)

    def _reorder_agent_list_widgets(
        self,
        container: object,
        ordered: list[AgentList],
    ) -> None:
        """Put mounted AgentList widgets into canonical panel order."""
        if agent_list_widgets_in(container) == ordered:
            return
        move_child = getattr(container, "move_child", None)
        if callable(move_child):
            for idx, widget in enumerate(ordered):
                current = agent_list_widgets_in(container)
                if idx < len(current) and current[idx] is widget:
                    continue
                try:
                    if idx == 0:
                        if current and current[0] is not widget:
                            move_child(widget, before=current[0])
                    else:
                        move_child(widget, after=ordered[idx - 1])
                except Exception:
                    children = getattr(container, "children", None)
                    if isinstance(children, list) and widget in children:
                        children.remove(widget)
                        children.insert(min(idx, len(children)), widget)
            return
        children = getattr(container, "children", None)
        if isinstance(children, list):
            others = [child for child in children if child not in ordered]
            children[:] = list(ordered) + others

    def _sync_mounted_panel_widgets(
        self,
        container: object,
        panel_keys: list[PanelKey],
        *,
        record_costs: bool = True,
    ) -> list[AgentList] | None:
        """Insert, remove, and reorder AgentList widgets to match *panel_keys*."""
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        existing = {
            widget.id: widget
            for widget in agent_list_widgets_in(container)
            if widget.id
        }
        keep_ids = {panel_widget_id_for_key(key) for key in panel_keys}
        inserted = 0
        removed = 0
        for key in panel_keys:
            wid = panel_widget_id_for_key(key)
            if wid in existing:
                continue
            widget = AgentList(id=wid)
            container.mount(widget)  # type: ignore[attr-defined]
            existing[wid] = widget
            inserted += 1

        for widget in list(agent_list_widgets_in(container)):
            if widget.id not in keep_ids:
                self._unmount_agent_list(container, widget)
                removed += 1

        ordered: list[AgentList] = []
        for key in panel_keys:
            wid = panel_widget_id_for_key(key)
            mounted: AgentList | None = existing.get(wid)
            if mounted is None:
                try:
                    mounted = self.query_one(  # type: ignore[attr-defined]
                        f"#{wid}", AgentList
                    )
                except NoMatches:
                    return None
            ordered.append(mounted)

        self._reorder_agent_list_widgets(container, ordered)
        if record_costs:
            source = getattr(self, "_agents_refresh_active_source", "unknown")
            if inserted:
                record_agents_refresh_trace(
                    self,
                    stage="display_patch",
                    source=source,
                    display_cost="display_panel_insert",
                    count=inserted,
                )
            if removed:
                record_agents_refresh_trace(
                    self,
                    stage="display_patch",
                    source=source,
                    display_cost="display_panel_remove",
                    count=removed,
                )
        return ordered

    def _panel_should_render_collapsed(
        self,
        key: PanelKey,
        panel_agents: list[Any],
        collapsed_keys: set[PanelKey],
    ) -> bool:
        """Return whether *key* should paint as a title-only strip."""
        if not panel_agents:
            expanded: set[PanelKey] = getattr(self, "_expanded_panel_keys", set())
            return key not in expanded
        return key in collapsed_keys

    def _panel_content_is_unchanged(
        self,
        widget: AgentList,
        panel_agents: list[Any],
        *,
        grouping_mode: GroupingMode,
        panel_collapsed: bool,
        paint_key: tuple[Any, ...],
    ) -> bool:
        """Return True when *widget* must not ``clear_options`` / ``update_list``.

        Row identities alone are not enough: a status change keeps every
        identity, and jump hints, marks, and fold state repaint the same rows.
        """
        if bool(getattr(widget, "_panel_collapsed", False)) != bool(panel_collapsed):
            return False
        if (
            getattr(widget, "_grouping_mode", GroupingMode.STANDARD)
            is not grouping_mode
        ):
            return False
        if panel_collapsed:
            return True
        current = list(getattr(widget, "_agents", None) or [])
        if _panel_row_signature(current, grouping_mode) != _panel_row_signature(
            panel_agents, grouping_mode
        ):
            return False
        if not current:
            return True
        return _panel_agents_match(current, panel_agents) and (
            getattr(widget, "_panel_paint_key", None) == paint_key
        )

    def _paint_panel_widget(
        self,
        widget: AgentList,
        *,
        idx: int,
        key: PanelKey,
        panel_index: Any,
        merge_tribe_panels: bool,
        effective_tribes: list[str],
        jump_hints: dict[int, str] | None,
        banner_jump_hints: dict[BannerJumpTarget, str] | None,
        panel_jump_hints: dict[PanelJumpTarget, str] | None,
        marked: set[tuple[AgentType, str, str | None]],
        unread: set[tuple[AgentType, str, str | None]],
        fold_counts: dict[str, tuple[int, int]],
        visible_parent_keys: set[str],
        fully_expanded_parent_keys: set[str],
        attempt_number: int | None,
        current_group_key: tuple[str, ...] | None,
        global_idx: int,
        grouping_mode: GroupingMode,
        collapsed_keys: set[PanelKey],
        panel_focus: Any,
        isolation_marked_keys: set[PanelKey],
        fold_restore_marked: dict[PanelKey, tuple[str, ...]],
        skip_content: bool,
    ) -> None:
        """Update chrome and, unless *skip_content*, rows for one panel."""
        slot = panel_index.slice_for(key)
        panel_agents = slot.agents
        global_indices = slot.global_indices
        global_to_local = slot.global_to_local
        panel_collapsed = self._panel_should_render_collapsed(
            key, panel_agents, collapsed_keys
        )
        marked_fold_keys = fold_restore_marked.get(key, ())
        selected_expanded = bool(
            panel_focus is not None
            and not panel_focus.collapsed
            and panel_focus.panel_key == key
        )
        self._set_agent_panel_title(
            widget,
            self._agent_panel_title(
                key,
                panel_agents,
                merge_tribe_panels=merge_tribe_panels,
                panel_jump_hints=panel_jump_hints,
                isolation_restore_marked=key in isolation_marked_keys,
                fold_restore_marked_count=len(marked_fold_keys),
            ),
        )
        if idx == 0:
            widget.remove_class("agent-panel-separated")
        else:
            widget.add_class("agent-panel-separated")

        local_idx = -1
        is_focused = key == self._panel_group.focused_key
        if is_focused and not selected_expanded and 0 <= global_idx < len(self._agents):
            local_idx = global_to_local.get(global_idx, -1)

        local_jump_hints: dict[int, str] | None = None
        if jump_hints:
            local_jump_hints = {}
            for local_i, gi in enumerate(global_indices):
                if gi in jump_hints:
                    local_jump_hints[local_i] = jump_hints[gi]

        local_banner_hints: dict[tuple[str, ...], str] | None = None
        if banner_jump_hints:
            occupancy_keys = getattr(self._panel_group, "panel_keys", ())
            try:
                occupancy_idx = occupancy_keys.index(key)
            except ValueError:
                occupancy_idx = -1
            local_banner_hints = {
                group_key: hint
                for (
                    kind,
                    panel_idx,
                    group_key,
                ), hint in banner_jump_hints.items()
                if kind == "banner" and panel_idx == occupancy_idx
            }
            if not local_banner_hints:
                local_banner_hints = None

        local_tribe_labels: list[str | None] | None = None
        if merge_tribe_panels:
            local_tribe_labels = [
                effective_tribes[gi]
                if 0 <= gi < len(effective_tribes) and effective_tribes[gi] is not None
                else None
                for gi in global_indices
            ]

        paint_key = _panel_paint_key(
            jump_hints=local_jump_hints,
            banner_jump_hints=local_banner_hints,
            marked=marked,
            unread=unread,
            marked_fold_keys=marked_fold_keys,
            fold_counts=fold_counts,
            attempt_number=attempt_number if is_focused else None,
            current_group_key=(
                current_group_key if is_focused and not selected_expanded else None
            ),
            tribe_labels=local_tribe_labels,
            panel_tribe=key if not merge_tribe_panels else None,
            visible_parent_keys=visible_parent_keys,
            fully_expanded_parent_keys=fully_expanded_parent_keys,
            fold_registry=panel_fold_registry(self, key),
        )
        content_unchanged = skip_content or self._panel_content_is_unchanged(
            widget,
            panel_agents,
            grouping_mode=grouping_mode,
            panel_collapsed=panel_collapsed,
            paint_key=paint_key,
        )
        if panel_collapsed:
            widget.add_class("-collapsed-panel")
            if not content_unchanged:
                widget.render_collapsed(grouping_mode=grouping_mode)
        else:
            widget.remove_class("-collapsed-panel")
            if not content_unchanged:
                widget.update_list(
                    panel_agents,
                    local_idx,
                    fold_counts=fold_counts,
                    marked_agents=marked,
                    unread_agents=unread,
                    fold_restore_marked_keys=marked_fold_keys,
                    jump_hints=local_jump_hints,
                    banner_jump_hints=local_banner_hints,
                    current_attempt_number=(attempt_number if is_focused else None),
                    fold_registry=panel_fold_registry(self, key),
                    current_group_key=(
                        current_group_key
                        if is_focused and not selected_expanded
                        else None
                    ),
                    grouping_mode=grouping_mode,
                    tribe_labels=local_tribe_labels,
                    panel_tribe=key if not merge_tribe_panels else None,
                    parents_with_visible_children=visible_parent_keys,
                    fully_expanded_parents=fully_expanded_parent_keys,
                )
                widget._panel_paint_key = paint_key

        if is_focused:
            widget.add_class("-focused-panel")
        else:
            widget.remove_class("-focused-panel")
        if selected_expanded:
            widget.add_class("-whole-panel-focus")
            widget.clear_highlight()
        else:
            widget.remove_class("-whole-panel-focus")

    def _panel_paint_context(
        self,
        *,
        jump_hints: dict[int, str] | None,
        banner_jump_hints: dict[BannerJumpTarget, str] | None,
        panel_jump_hints: dict[PanelJumpTarget, str] | None,
    ) -> dict[str, Any]:
        """Collect the per-refresh inputs shared by full and selective paints."""
        from ...widgets._agent_list_build import compute_visible_parents

        occupancy_keys = list(self._panel_group.panel_keys)
        occupancy_with_rows = self._occupancy_keys_with_rows()
        panel_keys = self._sorted_widget_panel_keys(
            occupancy_keys, occupancy_with_rows=occupancy_with_rows
        )
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        effective_tribes: list[str] = []
        if merge_tribe_panels:
            from ...models.agent_panels import effective_tribe_per_agent

            effective_tribes = effective_tribe_per_agent(self._agents)
        marked_keys_fn = getattr(self, "_panel_isolation_marked_keys", None)
        restore_marked_fn = getattr(self, "_panel_fold_restore_marked_keys", None)
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        visible_parent_keys, fully_expanded_parent_keys = compute_visible_parents(
            self._agents
        )
        return {
            "panel_keys": panel_keys,
            "panel_index": self._agent_panel_index(),
            "merge_tribe_panels": merge_tribe_panels,
            "effective_tribes": effective_tribes,
            "jump_hints": jump_hints,
            "banner_jump_hints": banner_jump_hints,
            "panel_jump_hints": panel_jump_hints,
            "marked": self._marked_agents,
            "unread": getattr(self, "_unread_completed_agent_ids", set()),
            "fold_counts": self._fold_counts,
            "visible_parent_keys": visible_parent_keys,
            "fully_expanded_parent_keys": fully_expanded_parent_keys,
            "attempt_number": self.current_attempt_number,
            "current_group_key": self._current_group_key,
            "global_idx": self.current_idx,
            "grouping_mode": getattr(self, "_grouping_mode", GroupingMode.STANDARD),
            "collapsed_keys": effective_panel_collapses(self, panel_keys),
            "panel_focus": resolve_panel() if callable(resolve_panel) else None,
            "isolation_marked_keys": (
                marked_keys_fn() if callable(marked_keys_fn) else set()
            ),
            "fold_restore_marked": (
                restore_marked_fn() if callable(restore_marked_fn) else {}
            ),
        }

    def _refresh_panel_widgets_impl(
        self,
        *,
        jump_hints: dict[int, str] | None,
        banner_jump_hints: dict[BannerJumpTarget, str] | None = None,
        panel_jump_hints: dict[PanelJumpTarget, str] | None = None,
    ) -> None:
        from textual.css.query import NoMatches

        try:
            container = self.query_one(  # type: ignore[attr-defined]
                "#agent-list-container"
            )
        except NoMatches:
            return

        ctx = self._panel_paint_context(
            jump_hints=jump_hints,
            banner_jump_hints=banner_jump_hints,
            panel_jump_hints=panel_jump_hints,
        )
        ordered = self._sync_mounted_panel_widgets(container, ctx["panel_keys"])
        if ordered is None:
            return
        for idx, (key, widget) in enumerate(
            zip(ctx["panel_keys"], ordered, strict=True)
        ):
            self._paint_panel_widget(
                widget,
                idx=idx,
                key=key,
                skip_content=False,
                **{name: value for name, value in ctx.items() if name != "panel_keys"},
            )
        self._apply_panel_heights(container, ordered)
        self._focus_focused_panel_widget()

    def _refresh_affected_panel_widgets(
        self,
        affected_keys: set[PanelKey],
    ) -> bool:
        """Rebuild only rendered panels whose membership/content changed."""
        if not affected_keys:
            return True

        from textual.css.query import NoMatches

        try:
            container = self.query_one(  # type: ignore[attr-defined]
                "#agent-list-container"
            )
        except NoMatches:
            return False

        jump_hints = (
            dict(getattr(self, "_entry_jump_index_to_hint", {}))
            if getattr(self, "_entry_jump_mode_active", False)
            else None
        )
        banner_jump_hints = (
            dict(getattr(self, "_entry_jump_banner_to_hint", {}))
            if getattr(self, "_entry_jump_mode_active", False)
            else None
        )
        panel_jump_hints = (
            dict(getattr(self, "_entry_jump_panel_to_hint", {}))
            if getattr(self, "_entry_jump_mode_active", False)
            else None
        )
        if not getattr(self, "_entry_jump_mode_active", False) and getattr(
            self, "_panel_fold_hint_mode_active", False
        ):
            (
                jump_hints,
                banner_jump_hints,
            ) = self._panel_fold_hint_display_maps()  # type: ignore[attr-defined]
            panel_jump_hints = self._panel_fold_hint_title_map() or None  # type: ignore[attr-defined]

        ctx = self._panel_paint_context(
            jump_hints=jump_hints,
            banner_jump_hints=banner_jump_hints,
            panel_jump_hints=panel_jump_hints,
        )
        ordered = self._sync_mounted_panel_widgets(
            container,
            ctx["panel_keys"],
            record_costs=True,
        )
        if ordered is None:
            return False
        paint_ctx = {name: value for name, value in ctx.items() if name != "panel_keys"}
        for idx, (key, widget) in enumerate(
            zip(ctx["panel_keys"], ordered, strict=True)
        ):
            self._paint_panel_widget(
                widget,
                idx=idx,
                key=key,
                skip_content=key not in affected_keys,
                **paint_ctx,
            )

        self._apply_panel_heights(container, ordered)
        self._focus_focused_panel_widget()
        return True
