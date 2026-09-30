"""Panel-index cache for the agent display mixin."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panel_index import AgentPanelIndex

from ._loading import DISMISSABLE_STATUSES


class AgentDisplayCacheMixin:
    """Memoized panel index and panel-derived cache invalidation."""

    _agents: list[Agent]
    _agent_panels_grouped: bool
    _agent_panel_index_cache: tuple[Any, bool, str, AgentPanelIndex] | None
    _panel_keys_cache: tuple[Any, ...] | None
    _nav_stops_cache: tuple[Any, ...] | None
    _agent_neighbor_index_cache: tuple[Any, ...] | None
    _unread_jump_candidates_cache: tuple[Any, Any] | None
    _agent_info_metrics_cache: tuple[Any, ...] | None

    def _invalidate_agent_panel_cache(self) -> None:
        """Clear panel-derived caches after in-place agent mutations."""
        if hasattr(self, "_agent_panel_index_cache"):
            self._agent_panel_index_cache = None
        if hasattr(self, "_agent_neighbor_index_cache"):
            self._agent_neighbor_index_cache = None
        if hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None
        if hasattr(self, "_panel_keys_cache"):
            self._panel_keys_cache = None
        if hasattr(self, "_nav_stops_cache"):
            self._nav_stops_cache = None
        if hasattr(self, "_unread_jump_candidates_cache"):
            self._unread_jump_candidates_cache = None

    def _snap_focus_after_agents_fold_restore(self) -> None:
        """Re-anchor once after restored folds hide the selected agent row."""
        if not getattr(self, "_agents_fold_restore_needs_focus_snap", False):
            return
        self._agents_fold_restore_needs_focus_snap = False  # type: ignore[attr-defined]
        snap = getattr(self, "_snap_focus_after_group_fold_change", None)
        if callable(snap):
            snap()

    def _agent_panel_index(self) -> AgentPanelIndex:
        """Memoized :class:`AgentPanelIndex` keyed on the agents-list ref.

        ``self._agents`` is replaced wholesale by the loading / refilter
        paths so ``is`` identity is a sufficient invalidation signal.
        Every panel-aware refresh path (highlights, widgets, info panel,
        single-row patch) reads from this index so the agents list is
        scanned at most once per refresh cycle.
        """
        from ...models.agent_panel_index import build_agent_panel_index
        from ._tab_scope import current_agent_tab_scope_token

        cached = getattr(self, "_agent_panel_index_cache", None)
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        tab_scope = current_agent_tab_scope_token(self)
        if (
            cached is not None
            and cached[0] is self._agents
            and cached[1] == merge_tribe_panels
            and cached[2] == tab_scope
        ):
            return cached[3]
        index = build_agent_panel_index(
            self._agents,
            dismissable_statuses=DISMISSABLE_STATUSES,
            merge_tribe_panels=merge_tribe_panels,
        )
        self._agent_panel_index_cache = (
            self._agents,
            merge_tribe_panels,
            tab_scope,
            index,
        )
        # Keep the legacy ``_panel_keys_cache`` populated so callers that
        # still go through ``_panel_keys_per_agent`` (tree builder, banner
        # math) share the same per-agent key list as the panel index.
        self._panel_keys_cache = (
            self._agents,
            merge_tribe_panels,
            index.keys_per_agent,
        )
        return index

    def _panel_keys_per_agent(self) -> list:
        """Memoized :func:`panel_key_per_agent` keyed on the agents list."""
        return self._agent_panel_index().keys_per_agent


__all__ = ["AgentDisplayCacheMixin"]
