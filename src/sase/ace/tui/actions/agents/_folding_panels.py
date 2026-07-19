"""Whole-panel folding helpers for the Agents tab."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import PanelKey

TabName = Literal["changespecs", "agents", "axe"]


class AgentPanelFoldingMixin:
    """Manage collapse state for whole Agents-tab panels."""

    current_tab: TabName
    current_idx: int
    current_attempt_number: int | None
    _agents: list[Agent]
    _current_group_key: tuple[str, ...] | None
    _collapsed_panel_keys: set[PanelKey]

    def _persist_panel_fold_change(
        self,
        panel_key: PanelKey,
        *,
        collapsed: bool,
    ) -> None:
        record = getattr(self, "_record_agents_panel_fold_change", None)
        if callable(record):
            record(panel_key, collapsed=collapsed)

    def _isolate_focused_panel(self) -> bool:
        """Leave only the selected Agents tribe panel expanded.

        Returns ``True`` when whole-panel focus owns the action, including an
        idempotent transition that does not change any panel folds.  The
        collapse set is updated before persistence is recorded so every
        coalesced snapshot observes the complete final state.
        """
        if self.current_tab != "agents":
            return False
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        panel_focus = resolve_panel() if callable(resolve_panel) else None
        if panel_focus is None:
            return False

        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None or getattr(self, "_agent_panels_grouped", False):
            return False

        live_keys = list(panel_group.panel_keys)
        selected_key = panel_focus.panel_key
        desired_collapsed = set(live_keys)
        desired_collapsed.discard(selected_key)

        collapsed_keys: set[PanelKey] | None = getattr(
            self, "_collapsed_panel_keys", None
        )
        if collapsed_keys is None:
            collapsed_keys = set()
            self._collapsed_panel_keys = collapsed_keys
        changed_keys = [
            panel_key
            for panel_key in live_keys
            if (panel_key in collapsed_keys) != (panel_key in desired_collapsed)
        ]

        # Whole-panel focus stays on the chosen key.  Do not descend into its
        # remembered banner/row or replace that saved in-panel selection.
        self._expanded_panel_focus = True
        self._current_group_key = None
        self.current_attempt_number = None
        if not changed_keys:
            return True

        collapsed_keys.difference_update(live_keys)
        collapsed_keys.update(desired_collapsed)
        for panel_key in changed_keys:
            self._persist_panel_fold_change(
                panel_key,
                collapsed=panel_key in desired_collapsed,
            )
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        return True

    def _collapse_focused_panel(self) -> None:
        """Collapse the focused tag panel while retaining its detail context."""
        if self.current_tab != "agents":
            return
        panel_group = getattr(self, "_panel_group", None)
        if (
            panel_group is None
            or getattr(self, "_agent_panels_grouped", False)
            or len(panel_group.panel_keys) <= 1
        ):
            return

        collapsed_keys: set[PanelKey] | None = getattr(
            self, "_collapsed_panel_keys", None
        )
        if collapsed_keys is None:
            collapsed_keys = set()
            self._collapsed_panel_keys = collapsed_keys
        focused_key = panel_group.focused_key
        if focused_key in collapsed_keys:
            return

        collapsed_keys.add(focused_key)
        self._expanded_panel_focus = False
        self._current_group_key = None
        self.current_attempt_number = None
        global_indices, _panel_agents = rendered_panel_slice(self, focused_key)
        if global_indices:
            self.current_idx = global_indices[0]
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        self._persist_panel_fold_change(focused_key, collapsed=True)

    def _expand_agent_panel(self, panel_key: PanelKey) -> bool:
        """Expand one whole panel without selecting or refreshing it."""
        panel_group = getattr(self, "_panel_group", None)
        collapsed_keys: set[PanelKey] = getattr(self, "_collapsed_panel_keys", set())
        if (
            panel_group is None
            or getattr(self, "_agent_panels_grouped", False)
            or panel_key not in panel_group.panel_keys
            or panel_key not in collapsed_keys
        ):
            return False

        collapsed_keys.discard(panel_key)
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        self._persist_panel_fold_change(panel_key, collapsed=False)
        return True

    def _expand_focused_panel(self) -> None:
        """Expand the focused tag panel and select its first rendered row."""
        if self.current_tab != "agents":
            return
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return

        focused_key = panel_group.focused_key
        if not self._expand_agent_panel(focused_key):
            return
        self._expanded_panel_focus = False
        stops = self._panel_navigation_stops()  # type: ignore[attr-defined]
        if stops:
            self._focus_panel_navigation_stop(stops[0])  # type: ignore[attr-defined]
        else:
            self._current_group_key = None
            keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
            self._snap_current_idx_to_focused_panel(  # type: ignore[attr-defined]
                keys_per_agent,
                focused_key,
            )
        self.current_attempt_number = None
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]


__all__ = ["AgentPanelFoldingMixin"]
