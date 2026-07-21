"""Agent-tree and grouping-banner folding helpers for the Agents tab."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _AgentLeftNavigationTarget:
    """Validated immediate target for an Agents-tab ``h`` navigation."""

    kind: Literal["family", "clan", "tribe"]
    index: int | None = None
    agent: Agent | None = None


@dataclass(frozen=True, slots=True)
class _AgentStructuralCollapseTarget:
    """The next workflow, family, or clan fold owned by Agents-tab ``H``."""

    fold_key: str
    kind: Literal["workflow", "family", "clan"]
    reanchor: bool = False
    binary: bool = False


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

    def _can_select_focused_tribe_panel(self) -> bool:
        """Return whether the focused split panel can become a whole selection."""
        panel_group = getattr(self, "_panel_group", None)
        return bool(
            self.current_tab == "agents"
            and panel_group is not None
            and not getattr(self, "_agent_panels_grouped", False)
            and len(panel_group.panel_keys) > 1
        )

    def _resolve_agent_left_navigation_target(
        self,
    ) -> _AgentLeftNavigationTarget | None:
        """Resolve the selected row/banner's validated immediate parent.

        The resolver stays entirely within the loaded Agents projection.  It
        accepts concrete agent -> sequential family, direct member -> clan, and
        sequential family -> clan edges. A row or grouping banner reaches its
        tribe panel only after proving that it has no structural parent.
        """
        if self.current_tab != "agents" or not (
            0 <= self.current_idx < len(self._agents)
        ):
            return None

        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        if callable(resolve_panel) and resolve_panel() is not None:
            return None

        if self._current_group_key is not None:
            if self._can_select_focused_tribe_panel():
                return _AgentLeftNavigationTarget("tribe")
            return None

        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        if selected is None:
            return None

        from ...models._agent_tree import (
            agent_fold_key,
            agent_parent_fold_key,
            tree_parent_lookup,
        )
        from ...models.agent_family_members import is_sequential_family_container

        parent_key = agent_parent_fold_key(selected)
        if parent_key is None:
            if (
                selected.is_child_row
                or selected.is_hidden_step
                or selected.tree_parent_key is not None
                or selected.tree_depth != 0
                or not (
                    selected.is_agent_entry
                    or selected.is_clan_container
                    or is_sequential_family_container(selected)
                )
            ):
                return None
            if self._can_select_focused_tribe_panel():
                return _AgentLeftNavigationTarget("tribe")
            return None
        parent = tree_parent_lookup(self._agents).get(parent_key)
        if parent is None or parent is selected:
            return None

        # The canonical lookup intentionally resolves legacy duplicate keys
        # deterministically for presentation.  A navigation edge must be
        # unambiguous, however, so require exactly one rendered owner.
        parent_matches = [
            (index, candidate)
            for index, candidate in enumerate(self._agents)
            if agent_fold_key(candidate) == parent_key
        ]
        if (
            len(parent_matches) != 1
            or parent_matches[0][1] is not parent
            or agent_fold_key(parent) != parent_key
        ):
            return None
        parent_index = parent_matches[0][0]

        if is_sequential_family_container(selected):
            if (
                not parent.is_clan_container
                or selected.tree_parent_key != parent_key
                or selected.tree_depth != 1
            ):
                return None
            return _AgentLeftNavigationTarget("clan", parent_index, parent)

        if (
            selected.is_clan_container
            or not selected.is_agent_entry
            or selected.is_hidden_step
        ):
            return None

        if parent.is_clan_container:
            if (
                selected.tree_parent_key != parent_key
                or selected.tree_depth != parent.tree_depth + 1
            ):
                return None
            return _AgentLeftNavigationTarget("clan", parent_index, parent)

        if not selected.is_child_row or not is_sequential_family_container(parent):
            return None
        if (
            selected.tree_parent_key is not None
            and selected.tree_depth != parent.tree_depth + 1
        ):
            return None
        return _AgentLeftNavigationTarget("family", parent_index, parent)

    def _navigate_agent_left(self) -> bool:
        """Move to the validated structural parent or containing tribe panel."""
        target = self._resolve_agent_left_navigation_target()
        if target is None:
            return False

        save_jump_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if callable(save_jump_anchor):
            save_jump_anchor()

        origin = self._agents[self.current_idx]
        if target.kind == "tribe":
            if self._current_group_key is None:
                arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
                if callable(arm_manual):
                    arm_manual(origin)
            activate_panel = getattr(self, "_activate_focused_panel", None)
            return bool(callable(activate_panel) and activate_panel())

        if target.index is None or target.agent is None:
            return False
        if origin.identity != target.agent.identity:
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(origin)

        self._current_group_key = None
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]
        self.current_idx = target.index

        remember = getattr(self, "_remember_focused_panel_selection", None)
        if callable(remember):
            remember(("agent", target.index))
        acknowledge = getattr(self, "_acknowledge_agent_unread", None)
        if callable(acknowledge):
            acknowledge(target.agent)
        return True

    def _structural_fold_kind(
        self, fold_key: str
    ) -> Literal["workflow", "family", "clan"]:
        """Classify a canonical structural fold key for contextual labels."""
        from ...models._agent_tree import agent_fold_key
        from ...models.agent_family_members import is_sequential_family_container

        owner = next(
            (
                candidate
                for candidate in self._agents
                if agent_fold_key(candidate) == fold_key
            ),
            None,
        )
        if owner is not None and owner.is_clan_container:
            return "clan"
        if owner is not None and is_sequential_family_container(owner):
            return "family"
        return "workflow"

    def _resolve_agent_structural_collapse_target(
        self,
    ) -> _AgentStructuralCollapseTarget | None:
        """Resolve the highest-priority open structural fold for ``H``."""
        if self.current_tab != "agents" or self._current_group_key is not None:
            return None
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        if callable(resolve_panel) and resolve_panel() is not None:
            return None

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return None

        from ...models._agent_tree import agent_parent_fold_key
        from ...models.fold_state import FoldLevel

        fold_key = self._get_workflow_key_for_agent(agent)
        if (
            fold_key is not None
            and self._fold_manager.get(fold_key) != FoldLevel.COLLAPSED
        ):
            level = self._fold_manager.get(fold_key)
            selected_is_child = (
                agent_parent_fold_key(agent) == fold_key and agent.is_child_row
            )
            reanchor = selected_is_child and (
                level == FoldLevel.EXPANDED
                or (level == FoldLevel.FULLY_EXPANDED and agent.is_hidden_step)
            )
            kind = self._structural_fold_kind(fold_key)
            return _AgentStructuralCollapseTarget(
                fold_key,
                kind,
                reanchor=reanchor,
                binary=kind == "clan",
            )

        clan_parent_key = agent_parent_fold_key(agent)
        if (
            agent.tree_depth == 1
            and clan_parent_key is not None
            and clan_parent_key.startswith("clan:")
            and self._fold_manager.get(clan_parent_key) != FoldLevel.COLLAPSED
        ):
            return _AgentStructuralCollapseTarget(
                clan_parent_key,
                "clan",
                reanchor=True,
                binary=True,
            )
        return None

    def _collapse_agent_structural_fold(self) -> bool:
        """Collapse one Agents workflow/family/clan target, if available."""
        target = self._resolve_agent_structural_collapse_target()
        if target is None:
            return False
        if target.reanchor:
            self._reanchor_to_fold_owner(target.fold_key)
        changed = (
            self._collapse_clan_fold(target.fold_key)
            if target.binary
            else self._fold_manager.collapse(target.fold_key)
        )
        if changed:
            self._refilter_agents()  # type: ignore[attr-defined]
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


__all__ = ["AgentTreeFoldingMixin"]
