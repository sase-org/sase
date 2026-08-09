"""Whole-panel folding helpers for the Agents tab."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ...models.agent_panels import PanelIsolationRevert
from ._navigation_order import rendered_panel_slice
from ._panel_fold_intent import (
    effective_panel_collapses,
    panel_is_collapsed,
    set_panel_fold_intent,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import PanelKey

TabName = Literal["artifacts", "agents", "axe"]


class AgentPanelFoldingMixin:
    """Manage collapse state for whole Agents-tab panels."""

    current_tab: TabName
    current_idx: int
    current_attempt_number: int | None
    _agents: list[Agent]
    _current_group_key: tuple[str, ...] | None
    _collapsed_panel_keys: set[PanelKey]
    _expanded_panel_keys: set[PanelKey]
    _panel_isolation_revert: PanelIsolationRevert | None

    def _persist_panel_fold_change(
        self,
        panel_key: PanelKey,
        *,
        collapsed: bool,
    ) -> None:
        revert = getattr(self, "_panel_isolation_revert", None)
        if revert is not None and panel_key != revert.target_key:
            self._disarm_panel_isolation_revert(additional_keys={panel_key})
        record = getattr(self, "_record_agents_panel_fold_change", None)
        if callable(record):
            record(panel_key, collapsed=collapsed)

    def _live_panel_keys(self) -> set[PanelKey]:
        """Return the current split-layout keys available for isolation."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None or getattr(self, "_agent_panels_grouped", False):
            return set()
        return set(panel_group.panel_keys)

    def _marked_keys_for_panel_isolation(
        self,
        revert: PanelIsolationRevert,
    ) -> set[PanelKey]:
        """Return live panels whose fold state the remembered layout changes."""
        live_keys = self._live_panel_keys()
        collapsed = effective_panel_collapses(self, live_keys)
        return (collapsed ^ set(revert.collapsed_before)) & live_keys

    def _panel_isolation_revert_record(
        self,
        *,
        repaint_expired: bool = False,
    ) -> PanelIsolationRevert | None:
        """Return the armed record, expiring it when its target vanished."""
        revert = getattr(self, "_panel_isolation_revert", None)
        if revert is None:
            return None
        if revert.target_key in self._live_panel_keys():
            return revert
        self._disarm_panel_isolation_revert(refresh=repaint_expired)
        return None

    def _panel_isolation_marked_keys(self) -> set[PanelKey]:
        """Return panels marked as changing on the next whole-panel zoom action."""
        revert = self._panel_isolation_revert_record()
        if revert is None:
            return set()
        return self._marked_keys_for_panel_isolation(revert)

    def _refresh_panel_isolation_ui(self, affected_keys: set[PanelKey]) -> None:
        """Selectively repaint isolation markers and the conditional footer."""
        refresh_panels = getattr(self, "_refresh_affected_panel_widgets", None)
        if affected_keys and callable(refresh_panels):
            refresh_panels(affected_keys)
        refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
        if callable(refresh_footer):
            refresh_footer()

    def _disarm_panel_isolation_revert(
        self,
        *,
        additional_keys: set[PanelKey] | None = None,
        refresh: bool = True,
    ) -> None:
        """Drop the remembered layout and remove its transient UI markers."""
        revert = getattr(self, "_panel_isolation_revert", None)
        if revert is None:
            return
        affected_keys = self._marked_keys_for_panel_isolation(revert)
        if additional_keys:
            affected_keys.update(additional_keys)
        self._panel_isolation_revert = None
        if refresh:
            self._refresh_panel_isolation_ui(affected_keys)

    def _apply_panel_fold_layout(
        self,
        live_keys: list[PanelKey],
        desired_collapsed: set[PanelKey],
    ) -> list[PanelKey]:
        """Apply and persist one complete live-panel fold layout."""
        collapsed_keys = effective_panel_collapses(self, live_keys)
        changed_keys = [
            panel_key
            for panel_key in live_keys
            if (panel_key in collapsed_keys) != (panel_key in desired_collapsed)
        ]
        if not changed_keys:
            return []

        for panel_key in changed_keys:
            set_panel_fold_intent(
                self,
                panel_key,
                collapsed=panel_key in desired_collapsed,
            )
            self._persist_panel_fold_change(
                panel_key,
                collapsed=panel_key in desired_collapsed,
            )
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        return changed_keys

    def _focus_whole_panel_after_layout(
        self,
        panel_key: PanelKey,
        *,
        collapsed: bool,
    ) -> None:
        """Keep whole-panel focus stable across an isolate or restore."""
        self._expanded_panel_focus = not collapsed
        self._current_group_key = None
        self.current_attempt_number = None
        if collapsed:
            global_indices, _panel_agents = rendered_panel_slice(self, panel_key)
            if global_indices:
                self.current_idx = global_indices[0]

    def _isolate_focused_panel(self) -> bool:
        """Toggle between a solo panel and its remembered split layout.

        Returns ``True`` when whole-panel focus owns the action, including an
        idempotent transition that does not change any panel folds. The first
        changing isolate arms one session-local restore; the next whole-panel
        zoom action applies it from whichever panel is currently focused.
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
        revert = self._panel_isolation_revert_record(repaint_expired=True)
        if revert is not None:
            desired_collapsed = set(revert.collapsed_before) & set(live_keys)
            affected_markers = self._marked_keys_for_panel_isolation(revert)
            # Disarm before persistence so the restore's own per-key intents
            # cannot invalidate a record that is already being consumed.
            self._panel_isolation_revert = None
            self._focus_whole_panel_after_layout(
                selected_key,
                collapsed=selected_key in desired_collapsed,
            )
            changed_keys = self._apply_panel_fold_layout(
                live_keys,
                desired_collapsed,
            )
            if not changed_keys:
                self._refresh_panel_isolation_ui(affected_markers)
            count = len(changed_keys)
            noun = "panel" if count == 1 else "panels"
            self.notify(  # type: ignore[attr-defined]
                f"Restored {count} {noun}", timeout=1.5
            )
            return True

        collapsed_before = frozenset(effective_panel_collapses(self, live_keys))
        desired_collapsed = set(live_keys)
        desired_collapsed.discard(selected_key)

        # Whole-panel focus stays on the chosen key.  Do not descend into its
        # remembered banner/row or replace that saved in-panel selection.
        self._focus_whole_panel_after_layout(selected_key, collapsed=False)
        changed_keys = self._apply_panel_fold_layout(live_keys, desired_collapsed)
        if not changed_keys:
            return True

        self._panel_isolation_revert = PanelIsolationRevert(
            target_key=selected_key,
            collapsed_before=collapsed_before,
        )
        # The fold repaint ran before arming so isolation's own persistence
        # calls could not trip invalidation. Repaint only the newly-marked
        # panels and the footer now that the record is visible.
        self._refresh_panel_isolation_ui(set(changed_keys))
        return True

    def _collapse_focused_panel(self) -> None:
        """Collapse the focused tribe panel while retaining its detail context."""
        if self.current_tab != "agents":
            return
        panel_group = getattr(self, "_panel_group", None)
        panel_keys = getattr(panel_group, "panel_keys", ())
        focused_idx = getattr(panel_group, "focused_idx", -1)
        if (
            panel_group is None
            or getattr(self, "_agent_panels_grouped", False)
            or not (0 <= focused_idx < len(panel_keys))
        ):
            return

        focused_key = panel_group.focused_key
        if panel_is_collapsed(self, focused_key):
            return

        set_panel_fold_intent(self, focused_key, collapsed=True)
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
        if (
            panel_group is None
            or getattr(self, "_agent_panels_grouped", False)
            or panel_key not in panel_group.panel_keys
            or not panel_is_collapsed(self, panel_key)
        ):
            return False

        set_panel_fold_intent(self, panel_key, collapsed=False)
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        self._persist_panel_fold_change(panel_key, collapsed=False)
        return True

    def _expand_focused_panel(self) -> None:
        """Expand the focused tribe panel and select its first rendered row."""
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
