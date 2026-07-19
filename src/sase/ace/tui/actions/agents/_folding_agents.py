"""Agent-tree and grouping-banner folding helpers for the Agents tab."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from ._fold_scope import focused_panel_fold_registry, panel_fold_registry
from ._folding_panels import AgentPanelFoldingMixin
from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry, GroupKey
    from ...models.agent_groups import GroupingMode
    from ...models.agent_panels import PanelKey
    from ...models.fold_state import FoldStateManager
    from ...models.group_fold import GroupFoldRegistry

TabName = Literal["changespecs", "agents", "axe"]
_FOCUSED_PANEL = object()


class AgentTreeFoldingMixin(AgentPanelFoldingMixin):
    """Manage agent-tree and grouping-banner fold state."""

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _fold_manager: FoldStateManager
    _fold_counts: dict[str, tuple[int, int]]
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

    def _get_workflow_key_for_agent(self, agent: Agent) -> str | None:
        """Get the fold state key targeted by actions on an agent row.

        Args:
            agent: The agent to get the key for.

        Returns:
            The row's owned descendant key, its immediate parent's key when
            selected as a child, or ``None`` when neither edge is foldable.
        """
        from ...models._agent_tree import agent_fold_key, agent_parent_fold_key

        if agent.is_clan_container:
            return agent_fold_key(agent)
        fold_key = agent_fold_key(agent)
        if fold_key in self._fold_counts:
            return fold_key
        if agent.is_child_row:
            return agent_parent_fold_key(agent)
        return None

    def _reanchor_to_fold_owner(self, fold_key: str) -> None:
        """Move selection to the visible row that owns ``fold_key``."""
        from ...models._agent_tree import agent_fold_key

        for idx, candidate in enumerate(self._agents):
            if agent_fold_key(candidate) == fold_key:
                self.current_idx = idx
                return

    def _collapse_clan_fold(self, fold_key: str) -> bool:
        """Collapse a clan's binary outer fold in a single action."""
        from ...models.fold_state import FoldLevel

        changed = False
        while self._fold_manager.get(fold_key) != FoldLevel.COLLAPSED:
            if not self._fold_manager.collapse(fold_key):
                break
            changed = True
        return changed

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
        root banner if visible, otherwise a ChangeSpec banner in 3-level
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
        """Collapse the fold for the focused row (one level).

        On Agents, ``h`` walks only structural agent/family/clan folds. Once
        none remain (or a collapsed group banner is selected), it promotes
        focus to the enclosing tribe panel. Grouping-strategy folds belong to
        ``H`` and are handled by :meth:`_collapse_group_fold`.
        """
        if self.current_tab == "agents":
            from ...models._agent_tree import agent_parent_fold_key
            from ...models.fold_state import FoldLevel

            resolve_panel = getattr(self, "_resolve_focused_panel", None)
            panel_focus = resolve_panel() if callable(resolve_panel) else None
            if panel_focus is not None:
                if panel_focus.collapsed:
                    self.notify(  # type: ignore[attr-defined]
                        "Panel is already collapsed", timeout=1.5
                    )
                else:
                    self._collapse_focused_panel()
                return

            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is not None and self._current_group_key is None:
                key = self._get_workflow_key_for_agent(agent)
                if (
                    key is not None
                    and self._fold_manager.get(key) != FoldLevel.COLLAPSED
                ):
                    level = self._fold_manager.get(key)
                    selected_parent_key = agent_parent_fold_key(agent)
                    selected_is_child = (
                        selected_parent_key == key and agent.is_child_row
                    )
                    if selected_is_child and (
                        level == FoldLevel.EXPANDED
                        or (level == FoldLevel.FULLY_EXPANDED and agent.is_hidden_step)
                    ):
                        self._reanchor_to_fold_owner(key)

                    changed = (
                        self._collapse_clan_fold(key)
                        if agent.is_clan_container
                        else self._fold_manager.collapse(key)
                    )
                    if changed:
                        self._refilter_agents()  # type: ignore[attr-defined]
                        return

                # Once a direct member's own fold is collapsed, walk up to
                # the enclosing clan before falling through to group folds.
                clan_parent_key = agent_parent_fold_key(agent)
                if (
                    agent.tree_depth == 1
                    and clan_parent_key is not None
                    and clan_parent_key.startswith("clan:")
                    and self._fold_manager.get(clan_parent_key) != FoldLevel.COLLAPSED
                ):
                    self._reanchor_to_fold_owner(clan_parent_key)
                    if self._collapse_clan_fold(clan_parent_key):
                        self._refilter_agents()  # type: ignore[attr-defined]
                        return

            activate_panel = getattr(self, "_activate_focused_panel", None)
            if callable(activate_panel):
                activate_panel()
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

    def _collapse_group_fold(self) -> None:
        """Collapse the enclosing Agents grouping-strategy fold with ``H``."""
        if self.current_tab != "agents":
            return
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        if callable(resolve_panel) and resolve_panel() is not None:
            return

        if self._current_group_key is not None:
            cur_key: GroupKey = tuple(self._current_group_key)
            registry = focused_panel_fold_registry(self)
            if len(cur_key) > 1 and registry.is_collapsed(cur_key):
                parent_key: GroupKey = cur_key[:-1]
                if registry.collapse(parent_key):
                    self._current_group_key = parent_key
                    self._refilter_agents()  # type: ignore[attr-defined]
                    self._persist_group_fold_change(parent_key, collapsed=True)
                return
            if registry.collapse(cur_key):
                self._refilter_agents()  # type: ignore[attr-defined]
                self._persist_group_fold_change(cur_key, collapsed=True)
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return
        l1_key, l0_key = self._focused_group_keys()
        target = l1_key or l0_key
        registry = focused_panel_fold_registry(self)
        if target is not None and registry.collapse(target):
            self._current_group_key = target
            self._snap_focus_after_group_fold_change()
            self._refilter_agents()  # type: ignore[attr-defined]
            self._persist_group_fold_change(target, collapsed=True)


__all__ = ["AgentTreeFoldingMixin"]
