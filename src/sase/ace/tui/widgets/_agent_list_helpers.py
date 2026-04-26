"""Pure helper functions for the agent list widget."""

from ..models.agent import Agent, AgentType


def short_model_name(model: str) -> str:
    """Extract short display name from a model string."""
    model_lower = model.lower()
    for keyword in ("flash", "opus", "sonnet", "haiku", "pro"):
        if keyword in model_lower:
            return keyword
    parts = model.split("-")
    return parts[0] if parts else model


def step_role_suffix(agent: Agent) -> str:
    """Return role suffix to include in step number, or empty string.

    Shows role_suffix (e.g., ".plan", ".code", ".q") as part of the step number
    only for agent-type workflow steps and follow-up agents.  Other step types
    (bash, python) and workflow parents do not display it.
    """
    if not agent.role_suffix:
        return ""
    if not agent.parent_workflow:
        return agent.role_suffix
    if agent.step_type == "agent":
        return agent.role_suffix
    return ""


def _is_foldable_parent(agent: Agent) -> bool:
    """Check if an agent is a foldable parent (workflow)."""
    if agent.is_workflow_child:
        return False
    if agent.agent_type == AgentType.WORKFLOW:
        return True
    return False


def _attempt_count_suffix(attempts_count: int) -> str:
    """Return `` ↻N`` fragment when attempts exist, else empty string."""
    if attempts_count <= 0:
        return ""
    return f" ↻{attempts_count}"


def compute_fold_annotation(
    agent: Agent,
    fold_counts: dict[str, tuple[int, int]] | None,
    parents_with_visible_children: set[str],
    fully_expanded_parents: set[str] | None = None,
) -> str:
    """Compute fold annotation for a workflow parent.

    Args:
        agent: The agent to annotate.
        fold_counts: Fold counts mapping raw_suffix -> (non_hidden, hidden).
        parents_with_visible_children: Set of parent raw_suffixes that have
            visible children in the current filtered list.
        fully_expanded_parents: Set of parent raw_suffixes that are in
            FULLY_EXPANDED state (hidden children are visible).

    Returns:
        Annotation string, or empty string if not applicable.
    """
    attempts_count = len(agent.attempt_history)

    if _is_foldable_parent(agent) and fold_counts and agent.raw_suffix:
        counts = fold_counts.get(agent.raw_suffix)
        if counts:
            non_hidden, hidden = counts
            total = non_hidden + hidden
            if total > 0:
                has_visible_children = agent.raw_suffix in parents_with_visible_children
                suffix = _attempt_count_suffix(attempts_count)
                if not has_visible_children:
                    if (
                        agent.is_anonymous
                        and agent.appears_as_agent
                        and total == 1
                        and attempts_count == 0
                    ):
                        return ""
                    return f" ×{total}{suffix}"
                is_fully_expanded = (
                    fully_expanded_parents is not None
                    and agent.raw_suffix in fully_expanded_parents
                )
                if hidden > 0 and is_fully_expanded:
                    return f" ×{total} +{hidden}{suffix}"
                if hidden > 0:
                    return f" ×{total} −{hidden}{suffix}"
                if attempts_count > 0:
                    return f" ↻{attempts_count}"
                return ""

    if attempts_count > 0:
        return f" ↻{attempts_count}"
    return ""
