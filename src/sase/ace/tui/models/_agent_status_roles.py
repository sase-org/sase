"""Agent-family role predicates for TUI status overrides."""

from sase.plan_chain import agent_family_role_for_suffix, is_plan_feedback_suffix

from .agent import Agent


def is_feedback_suffix(
    suffix: str | None,
    *,
    agent_family_role: str | None = None,
) -> bool:
    """Check if a role suffix is a plan feedback round (e.g., "--2" or ".2")."""
    return is_plan_feedback_suffix(suffix, agent_family_role=agent_family_role)


def is_coder_followup_suffix(
    suffix: str | None,
    *,
    agent_family_role: str | None = None,
) -> bool:
    """Check if a role suffix is the coder follow-up suffix."""
    role = agent_family_role_for_suffix(
        suffix,
        agent_family_role=agent_family_role,
    )
    return role == "code"


def agent_family_role(agent: Agent) -> str | None:
    return agent_family_role_for_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )


def is_feedback_agent(agent: Agent) -> bool:
    return is_feedback_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )


def is_coder_agent(agent: Agent) -> bool:
    return is_coder_followup_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )
