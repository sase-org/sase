"""Helpers for retaining bead ownership across confirmed agent replacement."""

from __future__ import annotations

from sase.bead.model import Issue, Status


def same_current_owner_agent_name(left: str, right: str) -> bool:
    """Return whether two spellings name the same current-owner agent."""
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_key,
    )

    identity = AgentIdentitySnapshot.current()
    return current_owner_agent_name_key(left, identity) == current_owner_agent_name_key(
        right, identity
    )


def issue_retains_force_reuse_owner(
    issue: Issue,
    *,
    agent_name: str,
    prior_owner: str,
) -> bool:
    """Return whether *issue* is the retained in-progress replacement target."""
    return (
        issue.status is Status.IN_PROGRESS
        and bool(issue.assignee)
        and same_current_owner_agent_name(prior_owner, agent_name)
        and same_current_owner_agent_name(issue.assignee, prior_owner)
    )


def issue_is_in_progress_for_another_agent(
    issue: Issue,
    *,
    agent_name: str,
) -> bool:
    """Return whether *issue* is actively assigned to a different agent."""
    return (
        issue.status is Status.IN_PROGRESS
        and bool(issue.assignee)
        and not same_current_owner_agent_name(issue.assignee, agent_name)
    )


__all__ = [
    "issue_is_in_progress_for_another_agent",
    "issue_retains_force_reuse_owner",
    "same_current_owner_agent_name",
]
