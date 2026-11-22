"""Pure helper functions for the agent list widget."""

from datetime import datetime

from ..models._agent_clan import clan_members
from ..models._agent_tree import agent_fold_key
from ..models.agent import Agent, AgentType


def short_model_name(model: str) -> str:
    """Extract short display name from a model string."""
    model_lower = model.lower()
    for keyword in (
        "wonder-full",
        "wonder",
        "neon",
        "argon",
        "hydrogen",
        "flash",
        "fable",
        "opus",
        "sonnet",
        "haiku",
        "pro",
    ):
        if keyword in model_lower:
            return keyword
    parts = model.split("-")
    return parts[0] if parts else model


def _normalized_provider(provider: str | None) -> str | None:
    if provider is None:
        return None
    normalized = provider.strip().lower()
    return normalized or None


def _row_launch_time(agent: Agent) -> datetime:
    return agent.run_start_time or agent.start_time or datetime.min


def ordered_row_providers(agent: Agent) -> tuple[str, ...]:
    """Return distinct row provider names in first-launch order."""
    candidates: list[Agent] = []
    # Depth-first preorder with an explicit stack. Each entry carries only its
    # ancestors, so a row reachable through two parents is still listed twice
    # (as before) while a loop back to an ancestor terminates. A self-recursive
    # local function would close a cell cycle that pins every row until the
    # cyclic collector runs.
    pending: list[tuple[Agent, frozenset[int]]] = [(agent, frozenset())]
    while pending:
        current, seen = pending.pop()
        current_id = id(current)
        if current_id in seen:
            continue
        candidates.append(current)
        child_seen = seen | {current_id}
        pending.extend(
            (child, child_seen)
            for child in reversed(getattr(current, "runtime_children", ()))
        )

    providers: list[str] = []
    seen_providers: set[str] = set()
    for candidate in sorted(candidates, key=_row_launch_time):
        provider = _normalized_provider(candidate.llm_provider)
        if provider is None or provider in seen_providers:
            continue
        providers.append(provider)
        seen_providers.add(provider)
    return tuple(providers)


def _is_foldable_parent(agent: Agent) -> bool:
    """Return whether structural fold counts belong on this row."""
    if agent.is_child_row:
        return False
    return bool(
        agent.is_clan_container
        or agent.is_agent_session_container_row
        or agent.tree_depth == 1
        or agent.agent_type == AgentType.WORKFLOW
        or clan_members(agent)
    )


def _attempt_count_suffix(attempts_count: int) -> str:
    """Return `` ↻N`` fragment when attempts exist, else empty string."""
    if attempts_count <= 0:
        return ""
    return f" ↻{attempts_count}"


def folded_member_total(
    agent: Agent,
    fold_counts: dict[str, tuple[int, int]] | None,
    parents_with_visible_children: set[str],
) -> int | None:
    """Return the folded ``×N`` total exactly when it renders, else ``None``.

    Mirrors the folded branch of :func:`compute_fold_annotation`,
    honoring the anonymous-single-child exception. Derived from the same
    inputs as the prompt so prompt identity stays a sound validator.
    """
    fold_key = agent_fold_key(agent)
    if _is_foldable_parent(agent) and fold_counts and fold_key:
        counts = fold_counts.get(fold_key)
        if counts:
            non_hidden, hidden = counts
            total = non_hidden + hidden
            if total > 0 and fold_key not in parents_with_visible_children:
                attempts_count = len(agent.attempt_history)
                if (
                    agent.is_anonymous
                    and agent.appears_as_agent
                    and total == 1
                    and attempts_count == 0
                ):
                    return None
                return total
    return None


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
    fold_key = agent_fold_key(agent)
    if _is_foldable_parent(agent) and fold_counts and fold_key:
        counts = fold_counts.get(fold_key)
        if counts:
            non_hidden, hidden = counts
            total = non_hidden + hidden
            if total > 0:
                has_visible_children = fold_key in parents_with_visible_children
                suffix = _attempt_count_suffix(attempts_count)
                if not has_visible_children:
                    folded_total = folded_member_total(
                        agent, fold_counts, parents_with_visible_children
                    )
                    if folded_total is None:
                        return ""
                    return f" ×{folded_total}{suffix}"
                is_fully_expanded = (
                    fully_expanded_parents is not None
                    and fold_key in fully_expanded_parents
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
