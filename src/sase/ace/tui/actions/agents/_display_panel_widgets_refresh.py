"""Full and selective panel-widget refresh orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...models.agent_groups import GroupingMode
from ...util.trace import tui_trace
from ._display_helpers import panel_widget_id_for_key
from ._display_panel_state import PanelRefreshStateMixin
from ._panel_fold_intent import effective_panel_collapses

if TYPE_CHECKING:
    from ...models.agent_panels import PanelKey
    from ..navigation.jump_hints import BannerJumpTarget, PanelJumpTarget


class PanelWidgetRefreshOrchestrationMixin(PanelRefreshStateMixin):
    """Collect shared paint inputs and run full/selective panel refreshes."""

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
        ordered = self._sync_mounted_panel_widgets(  # type: ignore[attr-defined]
            container, ctx["panel_keys"]
        )
        if ordered is None:
            return
        for idx, (key, widget) in enumerate(
            zip(ctx["panel_keys"], ordered, strict=True)
        ):
            self._paint_panel_widget(  # type: ignore[attr-defined]
                widget,
                idx=idx,
                key=key,
                skip_content=False,
                **{name: value for name, value in ctx.items() if name != "panel_keys"},
            )
        self._settle_agent_list_container_width(container, ordered)
        self._apply_panel_heights(container, ordered)
        self._focus_focused_panel_widget()

    def _refresh_affected_panel_widgets(
        self,
        affected_keys: set[PanelKey],
        *,
        inserted_keys: set[PanelKey] | None = None,
        rebuild_only_keys: set[PanelKey] | None = None,
    ) -> bool:
        """Rebuild only rendered panels whose membership/content changed.

        When *inserted_keys* is given, an affected panel whose rows only gained
        plain nodes takes the in-place row insert instead of a rebuild, and its
        key is added to *inserted_keys*. A panel in *rebuild_only_keys* is one a
        caller already knows is structurally unsafe to insert into, so it skips
        the attempt and is rebuilt.
        """
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
        ordered = self._sync_mounted_panel_widgets(  # type: ignore[attr-defined]
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
            inserted = self._paint_panel_widget(  # type: ignore[attr-defined]
                widget,
                idx=idx,
                key=key,
                skip_content=key not in affected_keys,
                row_insert=inserted_keys is not None
                and key not in (rebuild_only_keys or ()),
                **paint_ctx,
            )
            if inserted and inserted_keys is not None:
                inserted_keys.add(key)

        self._settle_agent_list_container_width(container, ordered)
        self._apply_panel_heights(container, ordered)
        self._focus_focused_panel_widget()
        return True
