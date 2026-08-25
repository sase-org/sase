"""Pure scope and VCS-consensus helpers for Agents-tab prompt targets."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sase.ace.tui.agent_completion import agent_prompt_name
from sase.project_display_names import humanize_vcs_refs_in_text

if TYPE_CHECKING:
    from ...models.agent import Agent, AgentType

type AgentIdentity = tuple["AgentType", str, str | None]
type PromptTargetKind = Literal["agent", "clan", "tribe", "proc"]


@dataclass(frozen=True, slots=True)
class _PromptTargetVcsMember:
    """One real agent whose launch context participates in VCS consensus."""

    agent: Agent
    prompt_name: str | None


@dataclass(frozen=True, slots=True)
class AgentPromptTargetScope:
    """Immutable agent, clan, or tribe target captured at keypress."""

    kind: PromptTargetKind
    prompt_reference: str
    label: str
    history_sort_key: str
    vcs_members: tuple[_PromptTargetVcsMember, ...]
    member_identities: tuple[AgentIdentity, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedVcsTag:
    """A display-ready tag plus its syntax-independent comparison key."""

    display_tag: str
    workflow: str
    ref: str

    @property
    def canonical_key(self) -> tuple[str, str]:
        return (self.workflow, self.ref)


def _is_real_prompt_target_agent(agent: Agent) -> bool:
    """Return whether *agent* represents a real chat-bearing agent row."""
    return (
        not agent.is_clan_container
        and not agent.is_synthetic_planner
        and agent.is_agent_entry
    )


def _stable_real_agents(agents: Iterable[Agent]) -> tuple[Agent, ...]:
    """Filter synthetic rows and de-duplicate identities in input order."""
    real: list[Agent] = []
    seen: set[AgentIdentity] = set()
    for agent in agents:
        if not _is_real_prompt_target_agent(agent) or agent.identity in seen:
            continue
        seen.add(agent.identity)
        real.append(agent)
    return tuple(real)


def _vcs_members(
    agents: Iterable[Agent],
    *,
    prompt_name: str | None = None,
) -> tuple[_PromptTargetVcsMember, ...]:
    return tuple(
        _PromptTargetVcsMember(
            agent=agent,
            prompt_name=(
                prompt_name if prompt_name is not None else agent_prompt_name(agent)
            ),
        )
        for agent in _stable_real_agents(agents)
    )


def agent_prompt_target_scope(
    agent: Agent,
    prompt_reference: str,
    *,
    vcs_prompt_name: str | None = None,
    history_fallback: str = "agent",
) -> AgentPromptTargetScope:
    """Build a single-agent or plan-family prompt target scope."""
    members = _vcs_members(
        (agent,),
        prompt_name=vcs_prompt_name or prompt_reference,
    )
    return AgentPromptTargetScope(
        kind="agent",
        prompt_reference=prompt_reference,
        label=prompt_reference,
        history_sort_key=agent.cl_name or history_fallback,
        vcs_members=members,
        member_identities=tuple(member.agent.identity for member in members),
    )


def clan_prompt_target_scope(
    container: Agent,
    agents: Sequence[Agent],
) -> AgentPromptTargetScope | None:
    """Build a clan scope using only the selected generation's real members."""
    clan = container.agent_clan
    if not clan:
        return None
    generation = container.agent_clan_generation
    members = _stable_real_agents(
        agent
        for agent in agents
        if agent.agent_clan == clan and agent.agent_clan_generation == generation
    )
    if not members:
        # Directly constructed test/compatibility containers may not be
        # accompanied by their projected member rows.
        members = _stable_real_agents(container.runtime_children)
    if not members:
        return None
    vcs_members = _vcs_members(members)
    return AgentPromptTargetScope(
        kind="clan",
        prompt_reference=clan,
        label=clan,
        history_sort_key=clan,
        vcs_members=vcs_members,
        member_identities=tuple(member.agent.identity for member in vcs_members),
    )


def tribe_prompt_target_scope(
    panel_key: str | None,
    agents: Sequence[Agent],
    panel_keys: Sequence[str | None],
) -> AgentPromptTargetScope | None:
    """Build a named-tribe scope from the already-loaded panel projection."""
    from ...models.agent_panels import is_reserved_default_panel

    if is_reserved_default_panel(panel_key) or len(agents) != len(panel_keys):
        return None
    members = _stable_real_agents(
        agent for agent, key in zip(agents, panel_keys, strict=True) if key == panel_key
    )
    if not members:
        return None
    reference = f"@{panel_key}"
    vcs_members = _vcs_members(members)
    return AgentPromptTargetScope(
        kind="tribe",
        prompt_reference=reference,
        label=reference,
        history_sort_key=reference,
        vcs_members=vcs_members,
        member_identities=tuple(member.agent.identity for member in vcs_members),
    )


def proc_prompt_target_scope(
    agent: Agent,
    proc_id: str,
    *,
    label: str,
    history_fallback: str = "fork",
) -> AgentPromptTargetScope:
    """Build a stand-alone proc-shell or monitor prompt target scope.

    The reference is the exact durable proc ID so name reuse can never drift
    the eventual fork/wait target; the label stays the friendly shell name.
    A proc shell has no launch xprompt, so it never contributes to VCS
    consensus (``vcs_members`` stays empty).
    """
    return AgentPromptTargetScope(
        kind="proc",
        prompt_reference=proc_id,
        label=label,
        history_sort_key=agent.cl_name or history_fallback,
        vcs_members=(),
        member_identities=(agent.identity,),
    )


def same_prompt_target_scope(
    left: AgentPromptTargetScope,
    right: AgentPromptTargetScope,
) -> bool:
    """Compare the selection-sensitive portion of two scope snapshots."""
    return (
        left.kind == right.kind
        and left.prompt_reference == right.prompt_reference
        and left.member_identities == right.member_identities
    )


def _raw_vcs_tag(
    agent: Agent,
    prompt_name: str | None,
    agents: Sequence[Agent],
) -> str | None:
    """Resolve one agent's smart VCS tag before display-name rewriting."""
    from sase.xprompt import (
        extract_vcs_workflow_tag,
        find_vcs_workflow_tag,
        replace_ref_in_vcs_tag,
    )

    raw_content = agent.get_raw_xprompt_content()
    if not raw_content and agent.parent_timestamp:
        for parent in agents:
            if parent.raw_suffix == agent.parent_timestamp:
                raw_content = parent.get_raw_xprompt_content()
                break
    if not raw_content:
        return None

    vcs_tag = extract_vcs_workflow_tag(raw_content) or find_vcs_workflow_tag(
        raw_content
    )
    if not vcs_tag:
        return None

    if not agent.is_project_agent:
        return replace_ref_in_vcs_tag(vcs_tag, agent.cl_name)

    from sase.xprompt.workflow_validator_extract import extract_xprompt_calls

    if any(call.name == "pr" for call in extract_xprompt_calls(raw_content)):
        if not prompt_name:
            return None
        return replace_ref_in_vcs_tag(vcs_tag, f"@{prompt_name}")

    return vcs_tag


def _canonical_vcs_key(tag: str) -> tuple[str, str] | None:
    """Parse colon/underscore/parenthesized tags into one workflow/ref pair."""
    from sase.workspace_provider import get_workflow_names

    value = tag.strip()
    for workflow in sorted(get_workflow_names(), key=len, reverse=True):
        prefix = f"#{workflow}"
        if not value.startswith(prefix):
            continue
        rest = value[len(prefix) :]
        if rest.startswith(("!!", "??")):
            rest = rest[2:]
        if rest.startswith("(") and rest.endswith(")"):
            ref = rest[1:-1]
        elif rest.startswith((":", "_")):
            ref = rest[1:]
        else:
            return None
        return (workflow, ref) if ref else None
    return None


def _resolve_vcs_tag_details(
    agent: Agent,
    prompt_name: str | None,
    agents: Sequence[Agent] = (),
) -> _ResolvedVcsTag | None:
    """Resolve one smart VCS tag with a canonical workflow/ref comparison key."""
    raw_tag = _raw_vcs_tag(agent, prompt_name, agents)
    if raw_tag is None:
        return None
    canonical_key = _canonical_vcs_key(raw_tag)
    if canonical_key is None:
        return None
    workflow, ref = canonical_key
    return _ResolvedVcsTag(
        display_tag=humanize_vcs_refs_in_text(raw_tag),
        workflow=workflow,
        ref=ref,
    )


def resolve_vcs_tag(
    agent: Agent,
    prompt_name: str,
    agents: Sequence[Agent] = (),
) -> str | None:
    """Compatibility wrapper returning only the display-ready smart tag."""
    raw_tag = _raw_vcs_tag(agent, prompt_name, agents)
    return humanize_vcs_refs_in_text(raw_tag) if raw_tag is not None else None


def _resolve_vcs_tag_consensus(
    members: Sequence[_PromptTargetVcsMember],
    agents: Sequence[Agent],
) -> str | None:
    """Return one representative tag only when every member resolves equally."""
    if not members:
        return None
    resolved: list[_ResolvedVcsTag] = []
    for member in members:
        try:
            tag = _resolve_vcs_tag_details(
                member.agent,
                member.prompt_name,
                agents,
            )
        except Exception:
            return None
        if tag is None:
            return None
        resolved.append(tag)
    first = resolved[0]
    if any(tag.canonical_key != first.canonical_key for tag in resolved[1:]):
        return None
    return first.display_tag


def resolve_prompt_target_scope_vcs_tag(
    scope: AgentPromptTargetScope,
    agents: Sequence[Agent],
) -> str | None:
    """Resolve a target prefix while preserving legacy single-agent behavior."""
    if scope.kind != "agent":
        return _resolve_vcs_tag_consensus(scope.vcs_members, agents)
    if not scope.vcs_members:
        return None
    member = scope.vcs_members[0]
    try:
        return resolve_vcs_tag(
            member.agent,
            member.prompt_name or scope.prompt_reference,
            agents,
        )
    except Exception:
        return None


AgentForkScope = AgentPromptTargetScope
_ForkVcsMember = _PromptTargetVcsMember
agent_fork_scope = agent_prompt_target_scope
clan_fork_scope = clan_prompt_target_scope
resolve_fork_scope_vcs_tag = resolve_prompt_target_scope_vcs_tag
same_fork_scope = same_prompt_target_scope
tribe_fork_scope = tribe_prompt_target_scope


__all__ = [
    "AgentPromptTargetScope",
    "agent_prompt_target_scope",
    "clan_prompt_target_scope",
    "proc_prompt_target_scope",
    "resolve_prompt_target_scope_vcs_tag",
    "resolve_vcs_tag",
    "same_prompt_target_scope",
    "tribe_prompt_target_scope",
]
