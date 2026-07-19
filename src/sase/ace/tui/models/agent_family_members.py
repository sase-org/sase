"""Pure in-memory projection of concrete sequential family members."""

from __future__ import annotations

from collections.abc import Sequence

from .agent import Agent


def concrete_family_member_rows(agent: Agent) -> tuple[Agent, ...]:
    """Return the ordered real rows represented by a family container.

    Plan workflow roots are aggregate rows.  When their concrete main agent
    step is loaded, that step owns the planner phase; otherwise the root stays
    as the compatibility fallback.  Rename-on-attach roots remain real first
    members for families that do not have a concrete planner step.
    """
    planner = _concrete_planner_child(agent)
    candidates: list[Agent] = []
    if planner is not None:
        candidates.append(planner)
    elif _root_represents_member(agent):
        candidates.append(agent)

    candidates.extend(_concrete_continuations(agent.runtime_children, planner))
    candidates.extend(_concrete_continuations(agent.followup_agents, planner))
    return _dedupe_rows(candidates)


def _concrete_planner_child(agent: Agent) -> Agent | None:
    if not agent.is_plan_family_root_entry:
        return None
    return next(
        (
            child
            for child in agent.runtime_children
            if child.is_workflow_step_child
            and child.step_type == "agent"
            and child.parent_step_index is None
            and not child.is_synthetic_planner
            and not child.agent_family_parallel
        ),
        None,
    )


def _root_represents_member(agent: Agent) -> bool:
    if agent.is_plan_family_root_entry:
        return True
    family_name = agent.agent_family or agent.family_reference_name()
    return not bool(
        agent.agent_name and family_name and agent.agent_name == family_name
    )


def _concrete_continuations(
    rows: Sequence[Agent],
    planner: Agent | None,
) -> tuple[Agent, ...]:
    return tuple(
        row
        for row in rows
        if row is not planner
        and not row.is_workflow_step_child
        and not row.is_synthetic_planner
        and not row.agent_family_parallel
    )


def _dedupe_rows(rows: Sequence[Agent]) -> tuple[Agent, ...]:
    ordered: list[Agent] = []
    seen: set[int] = set()
    for row in rows:
        object_identity = id(row)
        if object_identity in seen:
            continue
        seen.add(object_identity)
        ordered.append(row)
    return tuple(ordered)


__all__ = ["concrete_family_member_rows"]
