"""Pure helper functions for the agent list widget."""

from datetime import datetime

from ..models._agent_parallel_family import (
    parallel_family_members,
    parallel_family_summary_text,
)
from ..models.agent import Agent, AgentType


def short_model_name(model: str) -> str:
    """Extract short display name from a model string."""
    model_lower = model.lower()
    for keyword in ("flash", "fable", "opus", "sonnet", "haiku", "pro"):
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

    def collect(current: Agent, seen: set[int]) -> None:
        current_id = id(current)
        if current_id in seen:
            return
        candidates.append(current)
        child_seen = seen | {current_id}
        for child in getattr(current, "runtime_children", ()):
            collect(child, child_seen)

    collect(agent, set())

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
    """Check if an agent is a foldable parent (workflow)."""
    if agent.is_workflow_child:
        return False
    if agent.agent_type == AgentType.WORKFLOW or parallel_family_members(agent):
        return True
    return False


def _append_parallel_family_summary(annotation: str, summary: str) -> str:
    if not summary:
        return annotation
    if annotation:
        return f"{annotation} · {summary}"
    return f" {summary}"


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
    parallel_summary = parallel_family_summary_text(agent)

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
                        return _append_parallel_family_summary("", parallel_summary)
                    return _append_parallel_family_summary(
                        f" ×{total}{suffix}", parallel_summary
                    )
                is_fully_expanded = (
                    fully_expanded_parents is not None
                    and agent.raw_suffix in fully_expanded_parents
                )
                if hidden > 0 and is_fully_expanded:
                    return _append_parallel_family_summary(
                        f" ×{total} +{hidden}{suffix}", parallel_summary
                    )
                if hidden > 0:
                    return _append_parallel_family_summary(
                        f" ×{total} −{hidden}{suffix}", parallel_summary
                    )
                if attempts_count > 0:
                    return _append_parallel_family_summary(
                        f" ↻{attempts_count}", parallel_summary
                    )
                return _append_parallel_family_summary("", parallel_summary)

    if attempts_count > 0:
        return _append_parallel_family_summary(f" ↻{attempts_count}", parallel_summary)
    return _append_parallel_family_summary("", parallel_summary)
