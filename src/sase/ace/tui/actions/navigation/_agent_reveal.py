"""Shared in-memory reveal contract for Agents-tab navigation targets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey
    from ...models.fold_state import FoldLevel

type AgentIdentity = tuple["AgentType", str, str | None]


class AgentRevealFailure(Enum):
    """Reason a navigation target could not be revealed safely."""

    TARGET_MISSING = "target_missing"
    TARGET_AMBIGUOUS = "target_ambiguous"
    TARGET_NOT_CURRENT = "target_not_current"
    ANCESTRY_INVALID = "ancestry_invalid"
    REFILTER_UNAVAILABLE = "refilter_unavailable"
    TARGET_FILTERED = "target_filtered"
    PANEL_MISSING = "panel_missing"
    TARGET_NOT_VISIBLE = "target_not_visible"


@dataclass(frozen=True)
class _AncestorRequirement:
    fold_key: str
    level: FoldLevel


@dataclass(frozen=True)
class _AgentRevealPlan:
    """Validated target and ancestry captured before any fold mutation."""

    target_identity: AgentIdentity
    ancestor_requirements: tuple[_AncestorRequirement, ...]


@dataclass(frozen=True)
class _AgentRevealResult:
    """Current target location plus the structural changes used to reveal it."""

    target_identity: AgentIdentity
    target_idx: int
    target_agent: Agent
    panel_idx: int
    panel_key: PanelKey
    tree_changed: bool = False
    groups_changed: bool = False
    panel_changed: bool = False

    @property
    def structural_changed(self) -> bool:
        """Whether the rendered Agents list needs one structural rebuild."""
        return self.tree_changed or self.groups_changed or self.panel_changed


@dataclass(frozen=True)
class _AgentRevealOutcome:
    """Success or failure from preflighting/applying a reveal."""

    result: _AgentRevealResult | None = None
    failure: AgentRevealFailure | None = None

    @property
    def succeeded(self) -> bool:
        return self.result is not None


def _agents_matching_identity(
    agents: list[Agent],
    target_identity: AgentIdentity,
) -> list[Agent]:
    return [agent for agent in agents if agent.identity == target_identity]


def _target_index(owner: Any, target_identity: AgentIdentity) -> int | None:
    matches = [
        idx
        for idx, agent in enumerate(getattr(owner, "_agents", ()))
        if agent.identity == target_identity
    ]
    return matches[0] if len(matches) == 1 else None


def _ancestor_requirements(
    complete: list[Agent],
    target: Agent,
) -> tuple[_AncestorRequirement, ...] | None:
    """Return a bounded, fully validated immediate-parent chain."""
    from ...models._agent_tree import agent_parent_fold_key, tree_parent_lookup
    from ...models.fold_state import FoldLevel

    parents = tree_parent_lookup(complete)
    requirements: list[_AncestorRequirement] = []
    current = target
    visited: set[int] = set()
    for _ in range(len(complete) + 1):
        current_id = id(current)
        if current_id in visited:
            return None
        visited.add(current_id)
        parent_key = agent_parent_fold_key(current)
        if parent_key is None:
            return tuple(requirements)
        parent = parents.get(parent_key)
        if parent is None:
            return None
        requirements.append(
            _AncestorRequirement(
                fold_key=parent_key,
                level=(
                    FoldLevel.FULLY_EXPANDED
                    if current.is_hidden_step and not parent_key.startswith("clan:")
                    else FoldLevel.EXPANDED
                ),
            )
        )
        current = parent
    return None


def prepare_agent_navigation_target(
    owner: Any,
    target_identity: AgentIdentity,
    *,
    require_current: bool,
) -> tuple[_AgentRevealPlan | None, AgentRevealFailure | None]:
    """Validate one stable target identity without mutating navigation state."""
    complete = list(
        getattr(owner, "_agents_with_children", None)
        or getattr(owner, "_agents", None)
        or ()
    )
    matches = _agents_matching_identity(complete, target_identity)
    if not matches:
        return None, AgentRevealFailure.TARGET_MISSING
    if len(matches) != 1:
        return None, AgentRevealFailure.TARGET_AMBIGUOUS

    if require_current:
        current_matches = _agents_matching_identity(
            list(getattr(owner, "_agents", None) or ()),
            target_identity,
        )
        if len(current_matches) != 1:
            return None, AgentRevealFailure.TARGET_NOT_CURRENT

    requirements = _ancestor_requirements(complete, matches[0])
    if requirements is None:
        return None, AgentRevealFailure.ANCESTRY_INVALID
    return (
        _AgentRevealPlan(
            target_identity=target_identity,
            ancestor_requirements=requirements,
        ),
        None,
    )


def _fold_requirement_is_met(current: FoldLevel, required: FoldLevel) -> bool:
    from ...models.fold_state import FoldLevel

    if required is FoldLevel.FULLY_EXPANDED:
        return current is FoldLevel.FULLY_EXPANDED
    return current is not FoldLevel.COLLAPSED


def _expand_tree_ancestors(owner: Any, plan: _AgentRevealPlan) -> tuple[bool, bool]:
    """Apply a prevalidated ancestor path, returning ``(ok, changed)``."""
    fold_manager = getattr(owner, "_fold_manager", None)
    if fold_manager is None:
        return (not plan.ancestor_requirements, False)

    changed = False
    for requirement in plan.ancestor_requirements:
        while not _fold_requirement_is_met(
            fold_manager.get(requirement.fold_key),
            requirement.level,
        ):
            if not fold_manager.expand(requirement.fold_key):
                return False, changed
            changed = True
    return True, changed


def _refilter_after_tree_reveal(owner: Any) -> bool:
    """Rebuild the folded projection without painting or content-index work."""
    invalidate = getattr(owner, "_invalidate_agent_panel_cache", None)
    if callable(invalidate):
        invalidate()
    refilter = getattr(owner, "_refilter_agents", None)
    if not callable(refilter):
        return False
    try:
        refilter(refresh_content_index=False, refresh_display=False)
    except TypeError:
        # Compatibility for focused embedding tests with the legacy signature.
        try:
            refilter(refresh_content_index=False)
        except TypeError:
            refilter()
    sync_panels = getattr(owner, "_sync_panel_group", None)
    if callable(sync_panels):
        sync_panels()
    return True


def _target_panel_context(
    owner: Any,
    target_idx: int,
) -> tuple[int, PanelKey] | None:
    panel_group = getattr(owner, "_panel_group", None)
    if panel_group is None:
        return (0, None)

    keys_getter = getattr(owner, "_panel_keys_per_agent", None)
    if callable(keys_getter):
        keys_per_agent = keys_getter()
    else:
        from ...models.agent_panels import panel_key_per_agent

        keys_per_agent = panel_key_per_agent(
            owner._agents,
            merge_tag_panels=getattr(owner, "_agent_panels_grouped", False),
        )
    if not (0 <= target_idx < len(keys_per_agent)):
        return None
    panel_key = keys_per_agent[target_idx]
    try:
        return (panel_group.panel_keys.index(panel_key), panel_key)
    except ValueError:
        return None


def _expand_target_groups(
    owner: Any,
    target_idx: int,
    panel_key: PanelKey,
) -> tuple[bool, bool]:
    """Expand only grouping banners that contain the stable target row."""
    from ...models.agent_groups import GroupingMode, build_agent_tree
    from ...models.group_fold import GroupFoldRegistry
    from ..agents._fold_scope import panel_fold_registry
    from ..agents._navigation_order import rendered_panel_slice

    global_indices, panel_agents = rendered_panel_slice(owner, panel_key)
    try:
        local_idx = global_indices.index(target_idx)
    except ValueError:
        return False, False

    complete_tree = build_agent_tree(
        panel_agents,
        fold_registry=GroupFoldRegistry(),
        mode=getattr(owner, "_grouping_mode", GroupingMode.STANDARD),
    )
    enclosing_keys = [
        entry.group.group_key
        for entry in complete_tree
        if entry.kind == "group"
        and entry.group is not None
        and local_idx in entry.group.agent_indices
    ]
    registry = panel_fold_registry(owner, panel_key)
    changed = False
    for group_key in enclosing_keys:
        if registry is not None and registry.expand(group_key):
            changed = True
            persist = getattr(owner, "_persist_group_fold_change", None)
            if callable(persist):
                try:
                    persist(
                        group_key,
                        collapsed=False,
                        panel_key=panel_key,
                    )
                except TypeError:
                    # Compatibility for focused harnesses with the old hook.
                    persist(group_key, collapsed=False)
    return True, changed


def _target_is_visible_in_panel(
    owner: Any,
    target_idx: int,
    panel_key: PanelKey,
) -> bool:
    from ...models.agent_groups import GroupingMode, build_agent_tree
    from ..agents._fold_scope import panel_fold_registry
    from ..agents._navigation_order import rendered_panel_slice

    global_indices, panel_agents = rendered_panel_slice(owner, panel_key)
    try:
        local_idx = global_indices.index(target_idx)
    except ValueError:
        return False
    tree = build_agent_tree(
        panel_agents,
        fold_registry=panel_fold_registry(owner, panel_key),
        mode=getattr(owner, "_grouping_mode", GroupingMode.STANDARD),
    )
    return any(entry.kind == "agent" and entry.agent_idx == local_idx for entry in tree)


def reveal_agent_navigation_target(
    owner: Any,
    plan: _AgentRevealPlan,
) -> _AgentRevealOutcome:
    """Reveal a preflighted target and resolve its current panel/index once."""
    ancestors_ok, tree_changed = _expand_tree_ancestors(owner, plan)
    if not ancestors_ok:
        return _AgentRevealOutcome(failure=AgentRevealFailure.ANCESTRY_INVALID)
    if tree_changed and not _refilter_after_tree_reveal(owner):
        return _AgentRevealOutcome(failure=AgentRevealFailure.REFILTER_UNAVAILABLE)

    target_idx = _target_index(owner, plan.target_identity)
    if target_idx is None:
        return _AgentRevealOutcome(failure=AgentRevealFailure.TARGET_FILTERED)
    panel_context = _target_panel_context(owner, target_idx)
    if panel_context is None:
        return _AgentRevealOutcome(failure=AgentRevealFailure.PANEL_MISSING)
    panel_idx, panel_key = panel_context

    target_in_panel, groups_changed = _expand_target_groups(
        owner,
        target_idx,
        panel_key,
    )
    if not target_in_panel or not _target_is_visible_in_panel(
        owner,
        target_idx,
        panel_key,
    ):
        return _AgentRevealOutcome(failure=AgentRevealFailure.TARGET_NOT_VISIBLE)

    expand_panel = getattr(owner, "_expand_agent_panel", None)
    panel_changed = bool(callable(expand_panel) and expand_panel(panel_key))
    return _AgentRevealOutcome(
        result=_AgentRevealResult(
            target_identity=plan.target_identity,
            target_idx=target_idx,
            target_agent=owner._agents[target_idx],
            panel_idx=panel_idx,
            panel_key=panel_key,
            tree_changed=tree_changed,
            groups_changed=groups_changed,
            panel_changed=panel_changed,
        )
    )


__all__ = [
    "AgentIdentity",
    "AgentRevealFailure",
    "prepare_agent_navigation_target",
    "reveal_agent_navigation_target",
]
