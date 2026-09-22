"""Single-panel repaint helpers for AgentList panel widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...models.agent_groups import GroupingMode
from ._display_panel_state import PanelRefreshStateMixin
from ._display_panel_widgets_keys import (
    panel_agents_match,
    panel_fold_inputs,
    panel_paint_key,
    panel_row_signature,
)
from ._fold_scope import panel_fold_registry

if TYPE_CHECKING:
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey
    from ...widgets import AgentList
    from ..navigation.jump_hints import BannerJumpTarget, PanelJumpTarget


class PanelWidgetPaintMixin(PanelRefreshStateMixin):
    """Decide collapse/content staleness and repaint one panel widget."""

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
        if panel_row_signature(current, grouping_mode) != panel_row_signature(
            panel_agents, grouping_mode
        ):
            return False
        if not current:
            return True
        return panel_agents_match(current, panel_agents) and (
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
        row_insert: bool = False,
    ) -> bool:
        """Update chrome and, unless *skip_content*, rows for one panel.

        With *row_insert*, a panel whose rows only gained plain nodes takes an
        in-place insert instead of ``update_list``. Returns ``True`` when it did.
        """
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

        panel_fold_counts, panel_visible_parents, panel_fully_expanded = (
            panel_fold_inputs(
                panel_agents,
                fold_counts=fold_counts,
                visible_parent_keys=visible_parent_keys,
                fully_expanded_parent_keys=fully_expanded_parent_keys,
            )
        )
        paint_key = panel_paint_key(
            jump_hints=local_jump_hints,
            banner_jump_hints=local_banner_hints,
            marked=marked,
            unread=unread,
            marked_fold_keys=marked_fold_keys,
            fold_counts=panel_fold_counts,
            attempt_number=attempt_number if is_focused else None,
            current_group_key=(
                current_group_key if is_focused and not selected_expanded else None
            ),
            tribe_labels=local_tribe_labels,
            panel_tribe=key if not merge_tribe_panels else None,
            visible_parent_keys=panel_visible_parents,
            fully_expanded_parent_keys=panel_fully_expanded,
            fold_registry=panel_fold_registry(self, key),
        )
        content_unchanged = skip_content or self._panel_content_is_unchanged(
            widget,
            panel_agents,
            grouping_mode=grouping_mode,
            panel_collapsed=panel_collapsed,
            paint_key=paint_key,
        )
        inserted = False
        if panel_collapsed:
            widget.add_class("-collapsed-panel")
            if not content_unchanged:
                widget.render_collapsed(grouping_mode=grouping_mode)
        else:
            widget.remove_class("-collapsed-panel")
            if not content_unchanged:
                update_kwargs: dict[str, Any] = {
                    "fold_counts": fold_counts,
                    "marked_agents": marked,
                    "unread_agents": unread,
                    "fold_restore_marked_keys": marked_fold_keys,
                    "jump_hints": local_jump_hints,
                    "banner_jump_hints": local_banner_hints,
                    "current_attempt_number": attempt_number if is_focused else None,
                    "fold_registry": panel_fold_registry(self, key),
                    "current_group_key": (
                        current_group_key
                        if is_focused and not selected_expanded
                        else None
                    ),
                    "grouping_mode": grouping_mode,
                    "tribe_labels": local_tribe_labels,
                    "panel_tribe": key if not merge_tribe_panels else None,
                    "parents_with_visible_children": visible_parent_keys,
                    "fully_expanded_parents": fully_expanded_parent_keys,
                }
                inserted = row_insert and self._try_insert_panel_rows(  # type: ignore[attr-defined]
                    widget, panel_agents, local_idx, **update_kwargs
                )
                if not inserted:
                    widget.update_list(panel_agents, local_idx, **update_kwargs)
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
        return inserted
