"""Attribution helpers for agent-family SASE CONTEXT events.

This is display attribution over the agent-family relationships already
computed by the TUI loaders (``followup_agents``, role suffixes, artifact
dirs). It deliberately does *not* scan agents by shared name prefix and it
does *not* move any audit-log reading into the Rust core; it only decides
which already-loaded agents make up a row's context and how to label each
producer when its audited events are rendered.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sase.ace.tui.models.agent import Agent
from sase.plan_chain import (
    AGENT_FAMILY_SEPARATOR,
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_role_for_suffix,
    agent_family_suffix_token,
    canonical_plan_chain_suffix,
    plan_chain_feedback_round,
)

# Canonical prefix shared by phase-feedback suffixes (``--plan-0``, ``--plan-1``).
_PLAN_FEEDBACK_SUFFIX_PREFIX = f"{PLAN_CHAIN_PLAN_SUFFIX}-"

# Compact labels for canonical plan-chain role suffixes.
_SUFFIX_LABELS = {
    PLAN_CHAIN_PLAN_SUFFIX: "plan",
    PLAN_CHAIN_CODER_SUFFIX: "coder",
    PLAN_CHAIN_EPIC_SUFFIX: "epic",
    PLAN_CHAIN_COMMIT_SUFFIX: "commit",
}

# Fallback labels for ``agent_family_role`` values when no suffix is present.
_FAMILY_ROLE_LABELS = {
    "plan": "plan",
    "code": "coder",
    "epic": "epic",
    "commit": "commit",
    "feedback": "fb",
}


@dataclass(frozen=True)
class _ContextMember:
    """One agent that contributes audited context to a family row."""

    label: str
    cache_key: str
    artifacts_dir: str | None
    agent_name: str | None


def _normalize_artifacts_dir(value: str | None) -> str | None:
    """Return a realpath-normalized artifacts dir, mirroring the loaders."""
    if not value:
        return None
    try:
        return os.path.realpath(value)
    except (OSError, ValueError):
        return value


def _compact_suffix_label(suffix: str) -> str:
    """Return a compact suffix label by stripping the leading ``--``."""
    if suffix.startswith(AGENT_FAMILY_SEPARATOR):
        return suffix[len(AGENT_FAMILY_SEPARATOR) :]
    return suffix


def compact_role_label(agent: Agent) -> str:
    """Return a compact role label for *agent* within its family.

    Recognized plan-chain suffixes map to ``plan``/``q``/``coder``/``epic``/
    ``commit``. Phase-feedback members carry a concrete suffix name
    such as ``--plan-0`` and render as ``plan-0``; only legacy numeric feedback
    rounds (``.2``/``-2``/``--2``) map to ``fbN``. Otherwise we fall back to the
    family role, ``@agent_name``, the step name, or the display name. The
    renderer is responsible for truncating long labels.
    """
    suffix = canonical_plan_chain_suffix(agent.role_suffix)
    role = agent_family_role_for_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )
    if agent.agent_family_role == "root" and not agent.plan_chain_root:
        token = agent_family_suffix_token(agent.role_suffix)
        if token is not None:
            return token
    if role == "code":
        return "coder"
    if role in {"epic", "commit"}:
        return role
    if suffix is not None:
        if suffix.startswith(_PLAN_FEEDBACK_SUFFIX_PREFIX):
            return _compact_suffix_label(suffix)
        feedback_round = plan_chain_feedback_round(
            suffix,
            agent_family_role=agent.agent_family_role,
        )
        if feedback_round is not None:
            return f"fb{feedback_round}"
        label = _SUFFIX_LABELS.get(suffix)
        if label is not None:
            return label
        return _compact_suffix_label(suffix)
    if agent.plan_chain_root:
        return "plan"
    family_role = agent.agent_family_role
    if family_role:
        return _FAMILY_ROLE_LABELS.get(family_role, family_role)
    if agent.presented_agent_name:
        return f"@{agent.presented_agent_name}"
    if agent.step_name:
        return agent.step_name
    return agent.display_name


def _member_cache_key(agent: Agent) -> str:
    from sase.ace.tui.tools.cache import get_cache_key

    return get_cache_key(agent)


def build_context_members(agent: Agent) -> list[_ContextMember]:
    """Return ordered, de-duplicated context members for *agent*.

    The selected agent comes first, followed by its ``followup_agents``.
    Members are de-duplicated by stable cache key and by normalized artifacts
    dir so synthetic rows that share the root artifacts dir do not appear
    twice; the earliest (closest to the selected row) member wins.
    """
    members: list[_ContextMember] = []
    seen_keys: set[str] = set()
    seen_dirs: set[str] = set()
    for member_agent in (agent, *agent.followup_agents):
        cache_key = _member_cache_key(member_agent)
        if cache_key in seen_keys:
            continue
        artifacts_dir = _normalize_artifacts_dir(member_agent.get_artifacts_dir())
        if artifacts_dir is not None and artifacts_dir in seen_dirs:
            continue
        seen_keys.add(cache_key)
        if artifacts_dir is not None:
            seen_dirs.add(artifacts_dir)
        members.append(
            _ContextMember(
                label=compact_role_label(member_agent),
                cache_key=cache_key,
                artifacts_dir=artifacts_dir,
                agent_name=member_agent.agent_name,
            )
        )
    return members


def context_cache_key(members: list[_ContextMember]) -> tuple[str, ...]:
    """Return a stable cache-key fragment for an ordered member list."""
    return tuple(member.cache_key for member in members)


def match_event_label(
    members: list[_ContextMember],
    *,
    artifacts_dir: str | None,
    agent_name: str | None,
) -> str | None:
    """Return the family label for an event, or ``None`` when no member matches.

    Artifact-dir matching wins when the event has an artifacts dir; matching
    by agent name is only a fallback for events that lack one. This preserves
    the existing per-agent matching semantics across the whole family.
    """
    normalized = _normalize_artifacts_dir(artifacts_dir)
    if normalized is not None:
        for member in members:
            if member.artifacts_dir is not None and member.artifacts_dir == normalized:
                return member.label
        return None
    if agent_name:
        for member in members:
            if member.agent_name and member.agent_name == agent_name:
                return member.label
    return None
