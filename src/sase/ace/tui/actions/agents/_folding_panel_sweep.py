"""Panel-wide fold sweep (``-``) and its per-panel reverse."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...models.agent_panels import PanelFoldSweepRecord
from ._fold_scope import panel_fold_registry
from ._folding_agent_groups import (
    AgentGroupFoldingMixin,
    expanded_panel_level_zero_group_keys,
)
from ._folding_clans import (
    resolve_panel_clan_collapse_target,
    selected_enclosing_clan_fold_key,
)
from ._folding_lanes import resolve_panel_lane_collapse_target
from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models.agent_group_fold import GroupKey
    from ...models.agent_panels import PanelKey
    from ...models.fold_state import FoldLevel


def _panel_fold_sweep_records(owner: Any) -> dict[PanelKey, PanelFoldSweepRecord]:
    """Return the owner's per-panel sweep records, lazily initializing them."""
    records = getattr(owner, "_panel_fold_sweep_records", None)
    if records is None:
        records = {}
        owner._panel_fold_sweep_records = records
    return records


def _global_index_for_fold_owner(
    owner: Any,
    fold_key: str,
    panel_key: PanelKey,
) -> int | None:
    """Return the global row index of the row that owns *fold_key* in one panel."""
    from ...models._agent_tree import agent_fold_key

    global_indices, panel_agents = rendered_panel_slice(owner, panel_key)
    for local_idx, candidate in enumerate(panel_agents):
        if candidate.is_child_row or agent_fold_key(candidate) != fold_key:
            continue
        if local_idx < len(global_indices):
            return global_indices[local_idx]
    return None


def _panel_level_zero_group_keys(
    owner: Any,
    panel_key: PanelKey,
) -> tuple[GroupKey, ...]:
    """Return every level-0 banner key rendered in one panel, any fold state."""
    from ...models.agent_groups import build_agent_tree
    from ...models.group_fold import GroupFoldRegistry

    _global_indices, panel_agents = rendered_panel_slice(owner, panel_key)
    return tuple(
        entry.group.group_key
        for entry in build_agent_tree(
            panel_agents,
            fold_registry=GroupFoldRegistry(),
            mode=owner._active_grouping_mode(),
        )
        if entry.kind == "group" and entry.group is not None and entry.group.level == 0
    )


def _live_sweep_record_entries(
    owner: Any,
    panel_key: PanelKey,
    record: PanelFoldSweepRecord,
) -> tuple[tuple[tuple[str, FoldLevel], ...], tuple[GroupKey, ...]]:
    """Filter one sweep record to owners still live in the panel and collapsed."""
    from ...models._agent_tree import agent_fold_key
    from ...models.fold_state import FoldLevel

    live_fold_keys = {
        agent_fold_key(candidate)
        for candidate in rendered_panel_slice(owner, panel_key)[1]
        if not candidate.is_child_row and agent_fold_key(candidate) is not None
    }
    agent_levels = tuple(
        (key, level)
        for key, level in record.agent_levels
        if key in live_fold_keys and owner._fold_manager.get(key) == FoldLevel.COLLAPSED
    )

    live_group_keys = set(_panel_level_zero_group_keys(owner, panel_key))
    registry = panel_fold_registry(owner, panel_key)
    group_keys = tuple(
        key
        for key in record.group_keys
        if key in live_group_keys and registry.is_collapsed(key)
    )
    return agent_levels, group_keys


def retire_panel_fold_sweep_records(owner: Any, live_keys: Any) -> None:
    """Drop sweep records for panels that stopped being live."""
    records = getattr(owner, "_panel_fold_sweep_records", None)
    if not records:
        return

    from ...models.agent_panels import normalize_panel_key

    live = {normalize_panel_key(key) for key in live_keys}
    for stale_key in set(records) - live:
        del records[stale_key]


class AgentPanelFoldSweepMixin(AgentGroupFoldingMixin):
    """Sweep every open fold in one tribe panel closed, and reverse it."""

    def action_collapse_panel_folds(self) -> None:
        """Collapse every open fold in the focused tribe panel, or restore it."""
        if self.current_tab != "agents":
            return
        if getattr(self, "_panel_fold_hint_mode_active", False):
            self._teardown_panel_fold_hint_mode()  # type: ignore[attr-defined]

        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            self.notify(  # type: ignore[attr-defined]
                "No tribe panel to fold", severity="warning"
            )
            return

        panel_focus = self._resolve_focused_panel()  # type: ignore[attr-defined]
        whole_panel_focus = panel_focus is not None
        panel_key = (
            panel_focus.panel_key
            if panel_focus is not None
            else panel_group.focused_key
        )

        if whole_panel_focus and panel_focus.collapsed:
            self.notify("Panel is collapsed", severity="warning")  # type: ignore[attr-defined]
            return

        lane_target = resolve_panel_lane_collapse_target(self, panel_key)
        lane_keys = lane_target.fold_keys if lane_target is not None else ()
        clan_target = resolve_panel_clan_collapse_target(self, panel_key)
        clan_keys = clan_target.fold_keys if clan_target is not None else ()
        banner_keys = expanded_panel_level_zero_group_keys(self, panel_key)

        if lane_keys or clan_keys or banner_keys:
            self._sweep_panel_folds(
                panel_key,
                whole_panel_focus=whole_panel_focus,
                lane_keys=lane_keys,
                clan_keys=clan_keys,
                banner_keys=banner_keys,
            )
        else:
            self._restore_panel_fold_sweep(
                panel_key, whole_panel_focus=whole_panel_focus
            )

    def _sweep_panel_folds(
        self,
        panel_key: PanelKey,
        *,
        whole_panel_focus: bool,
        lane_keys: tuple[str, ...],
        clan_keys: tuple[str, ...],
        banner_keys: tuple[GroupKey, ...],
    ) -> None:
        """Collapse every resolved lane, clan, and banner in one panel."""
        agent_levels = tuple(
            (key, self._fold_manager.get(key)) for key in (*lane_keys, *clan_keys)
        )
        _panel_fold_sweep_records(self)[panel_key] = PanelFoldSweepRecord(
            panel_key=panel_key,
            agent_levels=agent_levels,
            group_keys=banner_keys,
        )

        if not whole_panel_focus:
            reanchor_index = self._panel_sweep_reanchor_index(
                panel_key, lane_keys=lane_keys, clan_keys=clan_keys
            )
            if reanchor_index is not None:
                self.current_idx = reanchor_index

        self._fold_manager.collapse_fully_all([*lane_keys, *clan_keys])
        registry = panel_fold_registry(self, panel_key)
        for key in banner_keys:
            registry.collapse(key)
            self._persist_group_fold_change(key, collapsed=True, panel_key=panel_key)

        self._repaint_after_panel_fold_sweep(
            panel_key, whole_panel_focus=whole_panel_focus
        )

        total = len(lane_keys) + len(clan_keys) + len(banner_keys)
        noun = "fold" if total == 1 else "folds"
        self.notify(f"Collapsed {total} {noun}", timeout=1.5)  # type: ignore[attr-defined]

    def _panel_sweep_reanchor_index(
        self,
        panel_key: PanelKey,
        *,
        lane_keys: tuple[str, ...],
        clan_keys: tuple[str, ...],
    ) -> int | None:
        """Resolve the row-focus sweep's re-anchor before any fold mutates."""
        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        if selected is None:
            return None

        from ...models._agent_tree import agent_parent_fold_key

        clan_key = selected_enclosing_clan_fold_key(self._agents, self.current_idx)
        if clan_key is not None and clan_key in clan_keys:
            return _global_index_for_fold_owner(self, clan_key, panel_key)

        lane_key = agent_parent_fold_key(selected)
        if lane_key is not None and lane_key in lane_keys:
            return _global_index_for_fold_owner(self, lane_key, panel_key)
        return None

    def _restore_panel_fold_sweep(
        self,
        panel_key: PanelKey,
        *,
        whole_panel_focus: bool,
    ) -> None:
        """Re-expand exactly what this panel's last sweep closed."""
        records = _panel_fold_sweep_records(self)
        record = records.get(panel_key)
        if record is None:
            self.notify(  # type: ignore[attr-defined]
                "No folds to collapse or restore", severity="warning"
            )
            return

        agent_levels, group_keys = _live_sweep_record_entries(self, panel_key, record)
        if not agent_levels and not group_keys:
            del records[panel_key]
            self.notify("No folds to restore", severity="warning")  # type: ignore[attr-defined]
            return

        self._fold_manager.restore_levels(dict(agent_levels))
        registry = panel_fold_registry(self, panel_key)
        for key in group_keys:
            registry.expand(key)
            self._persist_group_fold_change(key, collapsed=False, panel_key=panel_key)
        del records[panel_key]

        self._repaint_after_panel_fold_sweep(
            panel_key, whole_panel_focus=whole_panel_focus
        )

        total = len(agent_levels) + len(group_keys)
        noun = "fold" if total == 1 else "folds"
        self.notify(f"Restored {total} {noun}", timeout=1.5)  # type: ignore[attr-defined]

    def _repaint_after_panel_fold_sweep(
        self,
        panel_key: PanelKey,
        *,
        whole_panel_focus: bool,
    ) -> None:
        """Apply the sweep/restore's single repaint and refresh the footer."""
        if whole_panel_focus:
            self._refilter_focused_panel_inner_fold(panel_key)
        else:
            self._refilter_agents(refresh_content_index=False)  # type: ignore[attr-defined]
            self._snap_focus_after_group_fold_change()
            remember = getattr(self, "_remember_focused_panel_selection", None)
            if callable(remember):
                remember()

        refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
        if callable(refresh_footer):
            refresh_footer()

    def _panel_has_collapsible_folds(self, panel_key: PanelKey) -> bool:
        """Return whether ``-`` would sweep anything in *panel_key* right now."""
        if resolve_panel_lane_collapse_target(self, panel_key) is not None:
            return True
        if resolve_panel_clan_collapse_target(self, panel_key) is not None:
            return True
        return bool(expanded_panel_level_zero_group_keys(self, panel_key))

    def _panel_fold_sweep_restore_available(self, panel_key: PanelKey) -> bool:
        """Return whether ``-`` would restore anything in *panel_key* right now."""
        record = _panel_fold_sweep_records(self).get(panel_key)
        if record is None:
            return False
        agent_levels, group_keys = _live_sweep_record_entries(self, panel_key, record)
        return bool(agent_levels or group_keys)


__all__ = [
    "AgentPanelFoldSweepMixin",
    "retire_panel_fold_sweep_records",
]
