"""Shared helpers for agent wait and fork actions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    agent_prompt_name,
    build_agent_completion_candidates,
)
from sase.plan_chain import agent_family_role_for_suffix
from sase.xprompt.directive_edit import PromptWaitDirective

from ...models.agent_status import is_resumable_done_status
from ._fork_scope import (
    AgentPromptTargetScope,
    agent_prompt_target_scope,
    clan_prompt_target_scope,
    resolve_vcs_tag,
    tribe_prompt_target_scope,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...modals import WaitAgentCandidate, WaitModalResult

TabName = Literal["changespecs", "agents", "axe"]

# Post-plan handoff statuses where forking should pick up the coder
# follow-up's chat rather than the planner's. Symmetric with the
# DISMISSABLE_STATUSES set used by other consumers.
_PLAN_HANDOFF_DONE_STATUSES: frozenset[str] = frozenset({"PLAN DONE", "TALE DONE"})


def is_coder_followup_suffix(suffix: str | None) -> bool:
    """Return True for the coder follow-up suffix."""
    return agent_family_role_for_suffix(suffix) == "code"


def is_agent_family_root(agent: Agent) -> bool:
    return not agent.is_workflow_child and (
        agent.plan_chain_root or agent.agent_family_role == "root"
    )


def action_agent_prompt_name(agent: Agent) -> str | None:
    """Return the name wait/fork/copy prompts should use for a row."""
    return agent_prompt_name(agent)


def wait_spec_label(result: WaitModalResult) -> str:
    """Build a user-facing label for a wait spec."""
    dependency_parts: list[str] = []
    if result.agents:
        dependency_parts.append(", ".join(result.agents))
    if result.beads:
        dependency_parts.append("beads " + ", ".join(result.beads))
    if dependency_parts:
        label = f"waiting for {' and '.join(dependency_parts)}"
        if result.time_token:
            label = f"{label}, then {result.time_token}"
    elif result.time_token:
        label = f"waiting until {result.time_token}"
    elif result.runners is not None:
        label = f"waiting for runners ≤ {result.runners}"
    else:
        return "running now"
    if result.runners is not None and (
        result.agents or result.beads or result.time_token
    ):
        label = f"{label}, with runners ≤ {result.runners}"
    return label


def result_has_wait_spec(result: WaitModalResult) -> bool:
    """Return whether the result contains a wait dependency or time floor."""
    return bool(
        result.agents or result.beads or result.time_token or result.runners is not None
    )


def prompt_wait_spec(result: WaitModalResult) -> PromptWaitDirective | None:
    """Convert a modal result to a prompt directive edit payload."""
    if not result_has_wait_spec(result):
        return None
    return PromptWaitDirective(
        agents=tuple(result.agents),
        time_token=result.time_token,
        runners=result.runners,
        beads=tuple(result.beads),
    )


def wait_candidate_from_completion(
    candidate: AgentCompletionCandidate,
) -> WaitAgentCandidate:
    """Convert a shared completion candidate to the wait modal row shape."""
    from ...modals import WaitAgentCandidate

    return WaitAgentCandidate(
        wait_name=candidate.name,
        label=candidate.label,
        status=candidate.status,
        runtime=candidate.runtime,
        model=candidate.model,
        start_time=candidate.start_time,
        duration=candidate.duration,
        role=candidate.role,
        tribe=candidate.tribe,
        vcs_workflow=candidate.vcs_workflow,
        prompt_snippet=candidate.prompt_snippet,
    )


def wait_modal_candidates(
    selected_agent: Agent,
    visible_agents: list[Agent],
) -> list[WaitAgentCandidate]:
    """Return wait candidates from visible rows, excluding self and unnamed rows."""
    return [
        wait_candidate_from_completion(candidate)
        for candidate in build_agent_completion_candidates(
            visible_agents,
            exclude_identity=selected_agent.identity,
        )
        if candidate.kind in {"agent", "family"}
    ]


def resolve_agent_vcs_tag(
    agent: Agent,
    name: str,
    agents: Sequence[Agent] | None = None,
) -> str | None:
    """Resolve one agent's display-ready smart VCS launch tag."""
    return resolve_vcs_tag(agent, name, agents or ())


def fork_panel_keys(owner: Any) -> list[str | None]:
    """Return the cached effective panel key for every loaded agent."""
    index_resolver = getattr(owner, "_agent_panel_index", None)
    if callable(index_resolver):
        try:
            keys = list(index_resolver().keys_per_agent)
            if len(keys) == len(owner._agents):
                return keys
        except Exception:
            pass
    key_resolver = getattr(owner, "_panel_keys_per_agent", None)
    if callable(key_resolver):
        try:
            keys = list(key_resolver())
            if len(keys) == len(owner._agents):
                return keys
        except Exception:
            pass

    from ...models.agent_panels import panel_key_per_agent

    return panel_key_per_agent(owner._agents)


def resolve_agent_prompt_target_scope(
    owner: Any,
    *,
    action: Literal["fork", "wait"],
) -> tuple[AgentPromptTargetScope | None, str | None]:
    """Resolve the current selection into a reusable prompt target scope."""
    panel_resolver = getattr(owner, "_resolve_focused_panel", None)
    focus = panel_resolver() if callable(panel_resolver) else None
    if focus is not None:
        panel_key = getattr(focus, "panel_key", None)
        from ...models.agent_panels import is_reserved_default_panel

        if is_reserved_default_panel(panel_key):
            if action == "fork":
                return None, "The reserved @default panel cannot be forked"
            return None, "The reserved @default panel cannot be used as a wait target"
        scope = tribe_prompt_target_scope(
            panel_key,
            owner._agents,
            fork_panel_keys(owner),
        )
        if scope is None:
            return None, f"Tribe '@{panel_key}' has no agents"
        return scope, None

    if getattr(owner, "_current_group_key", None) is not None:
        return None, "No agent, clan, or tribe selected"

    agent = owner._get_selected_agent()
    if agent is None:
        return None, "No agent, clan, or tribe selected"

    if agent.is_clan_container:
        scope = clan_prompt_target_scope(agent, owner._agents)
        if scope is None:
            label = agent.agent_clan or agent.display_name
            return None, f"Clan '{label}' has no agents"
        return scope, None

    if not agent.is_agent_entry or agent.is_synthetic_planner:
        return None, "No agent, clan, or tribe selected"

    from ._core import DISMISSABLE_STATUSES

    prompt_name = action_agent_prompt_name(agent)
    if action == "wait":
        if not prompt_name:
            return None, "No agent name found"
        return (
            agent_prompt_target_scope(
                agent,
                prompt_name,
                history_fallback="wait",
            ),
            None,
        )

    if agent.status not in DISMISSABLE_STATUSES and prompt_name:
        return (
            agent_prompt_target_scope(
                agent,
                prompt_name,
                history_fallback="fork",
            ),
            None,
        )

    if agent.status in _PLAN_HANDOFF_DONE_STATUSES and not is_agent_family_root(agent):
        coder = next(
            (
                followup
                for followup in agent.followup_agents
                if is_coder_followup_suffix(followup.role_suffix)
            ),
            None,
        )
        if coder and coder.agent_name:
            return (
                agent_prompt_target_scope(
                    agent,
                    coder.agent_name,
                    vcs_prompt_name=coder.agent_name,
                    history_fallback="fork",
                ),
                None,
            )

    if not is_resumable_done_status(agent.status):
        return None, "Agent not finished yet"
    if not prompt_name:
        return None, "No agent name found"
    return (
        agent_prompt_target_scope(
            agent,
            prompt_name,
            history_fallback="fork",
        ),
        None,
    )


def resolve_agent_fork_scope(
    owner: Any,
) -> tuple[AgentPromptTargetScope | None, str | None]:
    """Compatibility wrapper for resolving a fork target."""
    return resolve_agent_prompt_target_scope(owner, action="fork")
