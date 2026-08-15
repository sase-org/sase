"""Grouping-banner folding helpers for the Agents tab."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ._fold_scope import focused_panel_fold_registry, panel_fold_registry
from ._folding_clans import AgentPanelClanFoldingMixin
from ._folding_sase_agents import (
    SaseAgentCollapseTarget,
    resolve_group_lane_collapse_target,
)
from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry, GroupKey
    from ...models.agent_groups import GroupingMode
    from ...models.agent_panels import PanelKey
    from ...models.group_fold import GroupFoldRegistry

_FOCUSED_PANEL = object()


class AgentGroupFoldingMixin(AgentPanelClanFoldingMixin):
    """Manage Agents-tab grouping-banner fold state."""

    _agents: list[Agent]
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None

    def _persist_group_fold_change(
        self,
        group_key: GroupKey,
        *,
        collapsed: bool,
        panel_key: PanelKey | object = _FOCUSED_PANEL,
    ) -> None:
        record = getattr(self, "_record_agents_group_fold_change", None)
        if callable(record):
            if panel_key is _FOCUSED_PANEL:
                record(group_key, collapsed=collapsed)
            else:
                record(
                    group_key,
                    collapsed=collapsed,
                    panel_key=cast("PanelKey", panel_key),
                )

    def _active_grouping_mode(self) -> GroupingMode:
        """Return the active grouping mode, defaulting to STANDARD.

        Most call sites read ``self._grouping_mode`` directly; this
        helper exists so legacy tests that exercise the folding mixin
        without going through ``StartupMixin._init_app_state`` (and so
        never set the attribute) still get sensible behavior.
        """
        from ...models.agent_groups import GroupingMode

        return getattr(self, "_grouping_mode", GroupingMode.STANDARD)

    def _focused_panel_fold_context(
        self,
    ) -> tuple[list[int], list[Agent], GroupFoldRegistry]:
        """Return global indices, agents, and registry for the focused panel."""
        panel_group = getattr(self, "_panel_group", None)
        panel_key = panel_group.focused_key if panel_group is not None else None
        global_indices, panel_agents = rendered_panel_slice(self, panel_key)
        return global_indices, panel_agents, panel_fold_registry(self, panel_key)

    def _focused_group_keys(self) -> tuple[GroupKey | None, GroupKey | None]:
        """Return ``(deep_key | None, l0_key | None)`` for the focused agent.

        Uses :func:`grouping_keys_for_agents` plus
        :func:`build_agent_tree` to mirror the same per-panel mode +
        singleton-suppression rules the renderer applies.  ``deep_key``
        is the deepest banner that contains the focused agent (a name-
        root banner if visible, otherwise a Patch banner in 3-level
        mode), and ``l0_key`` is its project banner.  Returns
        ``(None, None)`` when no agent is focused.
        """
        from ...models.agent_groups import (
            build_agent_tree,
            find_visible_ancestor_banner,
        )

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            return (None, None)
        global_indices, panel_agents, _registry = self._focused_panel_fold_context()
        try:
            focused_local_idx = global_indices.index(self.current_idx)
        except ValueError:
            return (None, None)
        # Build with an empty registry so collapsed banners don't
        # short-circuit the search — we want every enclosing banner
        # the renderer would emit at full expansion.
        from ...models.group_fold import GroupFoldRegistry

        entries = build_agent_tree(
            panel_agents,
            fold_registry=GroupFoldRegistry(),
            mode=self._active_grouping_mode(),
        )
        l0: GroupKey | None = None
        deep: GroupKey | None = None
        for entry in entries:
            if entry.kind != "group" or entry.group is None:
                continue
            if focused_local_idx not in entry.group.agent_indices:
                continue
            if entry.group.level == 0:
                l0 = entry.group.group_key
            if deep is None or entry.group.level > 0:
                deep = entry.group.group_key
        if deep == l0:
            deep = None
        if l0 is None:
            ancestor = find_visible_ancestor_banner(entries, focused_local_idx)
            if ancestor is not None:
                l0 = ancestor.group_key
        return (deep, l0)

    def _all_known_group_keys(self) -> list[GroupKey]:
        """Every L0 + L1 key the current agent list would render."""
        from ...models.agent_groups import enumerate_group_keys

        return enumerate_group_keys(self._agents, mode=self._active_grouping_mode())

    def _snap_focus_after_group_fold_change(self) -> None:
        """Reposition ``current_idx`` / ``_current_group_key`` after a fold change.

        After a per-group fold mutation the previously focused agent
        may no longer be visible.  When the enclosing group(s) are
        still expanded and the focused agent stays visible, clear the
        banner key so focus is on the agent.  Otherwise snap to the
        deepest collapsed ancestor banner via
        :func:`find_visible_ancestor_banner`.
        """
        from ...models.agent_groups import (
            build_agent_tree,
            find_visible_ancestor_banner,
        )

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self._current_group_key = None
            return
        global_indices, panel_agents, registry = self._focused_panel_fold_context()
        try:
            focused_local_idx = global_indices.index(self.current_idx)
        except ValueError:
            self._current_group_key = None
            return
        entries = build_agent_tree(
            panel_agents,
            fold_registry=registry,
            mode=self._active_grouping_mode(),
        )
        # If the focused agent's row is in the tree, focus stays on it.
        for entry in entries:
            if entry.kind == "agent" and entry.agent_idx == focused_local_idx:
                self._current_group_key = None
                return
        ancestor = find_visible_ancestor_banner(entries, focused_local_idx)
        if ancestor is not None:
            self._current_group_key = ancestor.group_key

    def _expand_fold(self) -> None:
        """Expand the fold for the focused row (one level).

        Per-group rules:

        * Banner focus → expand that group.
        * Agent focus → run the existing per-workflow expansion (the
          agent must already be inside an expanded group, since
          collapsed groups hide agents).
        * Other tabs preserve the original per-workflow behavior.
        """
        if self.current_tab == "agents":
            resolve_panel = getattr(self, "_resolve_focused_panel", None)
            panel_focus = resolve_panel() if callable(resolve_panel) else None
            if panel_focus is not None:
                if panel_focus.collapsed:
                    # First ``l`` expands a collapsed selected panel but keeps
                    # whole-panel focus; a second ``l`` descends into it.
                    self._expanded_panel_focus = True
                    if self._expand_agent_panel(panel_focus.panel_key):
                        self._refresh_agents_display(  # type: ignore[attr-defined]
                            list_changed=True
                        )
                    return
                exit_focus = getattr(self, "_exit_expanded_panel_focus", None)
                if callable(exit_focus):
                    exit_focus()
                return

            if self._current_group_key is not None:
                group_key: GroupKey = tuple(self._current_group_key)
                registry = focused_panel_fold_registry(self)
                if registry.expand(group_key):
                    # Re-anchor focus on the first visible agent of the
                    # expanded group (or the first remaining collapsed
                    # child banner) so the cursor doesn't sit on a row
                    # that is now disabled.
                    self._reanchor_after_banner_expansion(group_key)
                    self._refilter_agents()  # type: ignore[attr-defined]
                    self._persist_group_fold_change(group_key, collapsed=False)
                return

            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is None:
                return
            wf_key = self._get_workflow_key_for_agent(agent)
            if wf_key is None:
                return
            if agent.is_clan_container:
                from ...models.fold_state import FoldLevel

                if self._fold_manager.get(wf_key) != FoldLevel.COLLAPSED:
                    return
            if self._fold_manager.expand(wf_key):
                self._refilter_agents()  # type: ignore[attr-defined]
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return
        wf_key = self._get_workflow_key_for_agent(agent)
        if wf_key is None:
            return

        if self._fold_manager.expand(wf_key):
            self._refilter_agents()  # type: ignore[attr-defined]

    def _reanchor_after_banner_expansion(self, expanded_key: GroupKey) -> None:
        """Move focus off a banner that just stopped being selectable.

        Picks (in order): the first remaining collapsed child banner of
        the expanded group, then the first visible agent of the group,
        then leaves selection alone.
        """
        from ...models.agent_groups import build_agent_tree

        global_indices, panel_agents, registry = self._focused_panel_fold_context()
        entries = build_agent_tree(
            panel_agents,
            fold_registry=registry,
            mode=self._active_grouping_mode(),
        )
        # Find the agent_indices the expanded banner covers, so we can
        # match either by descendant-banner key prefix or by agent
        # membership without re-deriving the panel mode here.
        expanded_member_indices: tuple[int, ...] = ()
        for entry in entries:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.group_key == expanded_key:
                    expanded_member_indices = entry.group.agent_indices
                    break
        # Find first collapsed child banner under the expanded group.
        for entry in entries:
            if entry.kind != "group" or entry.group is None:
                continue
            g = entry.group
            if (
                len(g.group_key) > len(expanded_key)
                and g.group_key[: len(expanded_key)] == expanded_key
                and g.is_collapsed
            ):
                self._current_group_key = g.group_key
                return
        # Fall back to the first visible agent inside the group.
        for entry in entries:
            if entry.kind == "agent" and entry.agent_idx is not None:
                if entry.agent_idx in expanded_member_indices:
                    self._current_group_key = None
                    if 0 <= entry.agent_idx < len(global_indices):
                        self.current_idx = global_indices[entry.agent_idx]
                    return
        # Nothing better — clear group focus so j/k can rebind cleanly.
        self._current_group_key = None

    def _collapse_fold(self) -> None:
        """Navigate outward on Agents, or collapse one fold on other tabs.

        Agents keeps the explicit selected-panel collapse exception, but rows
        and grouping banners otherwise move to their immediate structural or
        tribe parent without changing any fold state.
        """
        if self.current_tab == "agents":
            resolve_panel = getattr(self, "_resolve_focused_panel", None)
            panel_focus = resolve_panel() if callable(resolve_panel) else None
            if panel_focus is not None:
                if panel_focus.collapsed:
                    focus_last_expanded = getattr(
                        self, "_focus_last_expanded_panel", None
                    )
                    if not (callable(focus_last_expanded) and focus_last_expanded()):
                        self.notify(  # type: ignore[attr-defined]
                            "Panel is already collapsed", timeout=1.5
                        )
                else:
                    self._collapse_focused_panel()
                return

            self._navigate_agent_left()
            return

        # Non-agents tabs: preserve original per-workflow behavior.
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return
        key = self._get_workflow_key_for_agent(agent)
        if key is None:
            return
        from ...models.fold_state import FoldLevel

        if agent.is_workflow_child and agent.parent_timestamp:
            if self._fold_manager.get(key) == FoldLevel.EXPANDED:
                for idx, candidate in enumerate(self._agents):
                    if (
                        candidate.raw_suffix == agent.parent_timestamp
                        and not candidate.is_workflow_child
                    ):
                        self.current_idx = idx
                        break

        if self._fold_manager.collapse(key):
            self._refilter_agents()  # type: ignore[attr-defined]

    def _resolve_sase_agent_collapse_target(
        self,
    ) -> SaseAgentCollapseTarget | None:
        """Resolve the group-wide lane step that follows selected-lane ``H``."""
        group_key = self._resolve_group_collapse_target()
        if group_key is None:
            return None
        return resolve_group_lane_collapse_target(self, group_key)

    def _restore_focused_panel_inner_fold_state(
        self,
        panel_key: PanelKey,
        *,
        current_idx: int,
        remembered_selection: tuple[str, int | tuple[str, ...]] | object,
    ) -> None:
        """Keep whole-panel focus and its dormant row state unchanged."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is not None and panel_key in panel_group.panel_keys:
            panel_group.focused_idx = panel_group.panel_keys.index(panel_key)
        self.current_idx = current_idx
        self._expanded_panel_focus = True  # type: ignore[attr-defined]
        self._current_group_key = None

        selection_memory = getattr(self, "_panel_selection_memory", None)
        if selection_memory is None:
            return
        if remembered_selection is _FOCUSED_PANEL:
            selection_memory.pop(panel_key, None)
        else:
            selection_memory[panel_key] = cast(
                "tuple[str, int | tuple[str, ...]]",
                remembered_selection,
            )

    def _refilter_focused_panel_inner_fold(self, panel_key: PanelKey) -> None:
        """Run one fold-only refilter without changing whole-panel intent."""
        current_idx = self.current_idx
        selection_memory = getattr(self, "_panel_selection_memory", {})
        remembered_selection: tuple[str, int | tuple[str, ...]] | object = (
            selection_memory.get(panel_key, _FOCUSED_PANEL)
        )
        self._refilter_agents(  # type: ignore[attr-defined]
            refresh_content_index=False
        )
        self._restore_focused_panel_inner_fold_state(
            panel_key,
            current_idx=current_idx,
            remembered_selection=remembered_selection,
        )

    def _collapse_sase_agent_folds(
        self,
        target: SaseAgentCollapseTarget | None = None,
    ) -> bool:
        """Fully collapse all open canonical lanes in one resolved scope."""
        if target is None:
            target = self._resolve_sase_agent_collapse_target()
        if target is None:
            return False

        if target.reanchor_index is not None:
            self.current_idx = target.reanchor_index
        changed = self._fold_manager.collapse_fully_all(list(target.fold_keys))
        if not changed:
            return False

        # A fold-only mutation neither changes the cached content corpus nor
        # needs one background content-index rebuild. Apply every fold state
        # first, then take the normal in-memory display path exactly once.
        self._refilter_agents(  # type: ignore[attr-defined]
            refresh_content_index=False
        )
        if target.reanchor_index is not None:
            remember = getattr(self, "_remember_focused_panel_selection", None)
            if callable(remember):
                remember()
        return True

    def _resolve_group_collapse_target(self) -> GroupKey | None:
        """Resolve the grouping-strategy fold reached after structural folds."""
        if self.current_tab != "agents":
            return None
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        if callable(resolve_panel) and resolve_panel() is not None:
            return None

        if self._current_group_key is not None:
            cur_key: GroupKey = tuple(self._current_group_key)
            registry = focused_panel_fold_registry(self)
            if len(cur_key) > 1 and registry.is_collapsed(cur_key):
                parent_key: GroupKey = cur_key[:-1]
                return None if registry.is_collapsed(parent_key) else parent_key
            return None if registry.is_collapsed(cur_key) else cur_key

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return None
        l1_key, l0_key = self._focused_group_keys()
        target = l1_key or l0_key
        registry = focused_panel_fold_registry(self)
        if target is None or registry.is_collapsed(target):
            return None
        return target

    def _collapse_group_fold(self) -> None:
        """Collapse the enclosing Agents grouping-strategy fold with ``H``."""
        target = self._resolve_group_collapse_target()
        if target is None:
            return
        registry = focused_panel_fold_registry(self)
        if registry.collapse(target):
            self._current_group_key = target
            self._snap_focus_after_group_fold_change()
            self._refilter_agents()  # type: ignore[attr-defined]
            self._persist_group_fold_change(target, collapsed=True)


__all__ = ["AgentGroupFoldingMixin"]
