"""Scaffold and launch validated agent proposals from chop results."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.core.axe_chop_facade import (
    derive_chop_agent_name,
    validate_chop_proposal,
)

from .chop_agents import build_chop_launch_env


@dataclass(frozen=True)
class _PreparedChopProposal:
    index: int
    proposal_id: str | None
    prompt: str
    workspace: str
    agent_name: str
    explicit_agent_name: bool
    clan: str | None
    clan_summary: str | None
    tribe: str
    model: str | None
    effort: str | None
    env: dict[str, str]
    dedupe_key: str | None
    wait_on: int | str | None


@dataclass(frozen=True)
class _PlannedChopProposal:
    """One side-effect-free proposal scaffold ready for preview or launch."""

    proposal: _PreparedChopProposal
    agent_name: str
    clan: str | None
    member_id: str | None
    declares_clan: bool
    clan_summary: str | None
    prompt: str


def _workspace_directive(workspace: str) -> str:
    return workspace if workspace.startswith("#") else f"#{workspace}"


def _full_name_template(proposal: _PreparedChopProposal) -> str:
    if proposal.clan is None:
        return proposal.agent_name
    return f"{proposal.clan}.{proposal.agent_name}"


def _clan_declaration_directive(clan: str, summary: str | None) -> str:
    if summary is None:
        return f"%clan({clan}, tribe=chop)"
    return f"%clan({clan}, tribe=chop, summary=[[{summary}]])"


def _scaffolded_prompt(
    proposal: _PreparedChopProposal,
    wait_name: str | None,
    *,
    agent_name: str | None = None,
    clan: str | None = None,
    member_id: str | None = None,
    declares_clan: bool = False,
    clan_summary: str | None = None,
) -> str:
    resolved_name = agent_name or _full_name_template(proposal)
    resolved_clan = clan if proposal.clan is not None else None
    lines = [_workspace_directive(proposal.workspace)]
    if resolved_clan is not None:
        resolved_member = member_id or proposal.agent_name
        if declares_clan:
            lines.extend(
                [
                    f"%id:{resolved_name}",
                    _clan_declaration_directive(resolved_clan, clan_summary),
                ]
            )
        else:
            lines.append(f"%id({resolved_member}, clan={resolved_clan})")
    else:
        lines.append(f"%id({resolved_name}, tribe={proposal.tribe})")
    if proposal.model:
        lines.append(f"%model:{proposal.model}")
    if proposal.effort:
        lines.append(f"%effort:{proposal.effort}")
    if wait_name:
        lines.append(f"%wait:{wait_name}")
    lines.append(proposal.prompt.strip())
    return "\n".join(lines) + "\n"


def prepare_chop_proposals(
    chop_name: str,
    result: Mapping[str, Any],
    *,
    target_key: str | None = None,
    run_id: str | None = None,
) -> list[_PreparedChopProposal]:
    """Normalize and validate all proposals in result order."""
    prepared: list[_PreparedChopProposal] = []
    prior_ids: list[str] = []
    raw_proposals = result.get("proposed_launches", [])
    if not isinstance(raw_proposals, list):
        raise ValueError("proposed_launches must be a list")
    for index, raw in enumerate(raw_proposals):
        if not isinstance(raw, dict):
            raise ValueError(f"proposed_launches[{index}] must be an object")
        normalized = validate_chop_proposal(
            raw,
            index=index,
            prior_ids=prior_ids,
        )
        proposal_id_value = normalized.get("id")
        proposal_id = str(proposal_id_value) if proposal_id_value is not None else None
        if proposal_id is not None:
            prior_ids.append(proposal_id)
        configured_name = normalized.get("agent_name")
        agent_name = (
            str(configured_name)
            if configured_name
            else derive_chop_agent_name(
                chop_name,
                target_key=target_key,
                proposal_index=index,
                run_token=run_id,
            )
        )
        prepared.append(
            _PreparedChopProposal(
                index=index,
                proposal_id=proposal_id,
                prompt=str(normalized["prompt"]),
                workspace=str(normalized["workspace"]),
                agent_name=agent_name,
                explicit_agent_name=bool(configured_name),
                clan=str(normalized["clan"]) if normalized.get("clan") else None,
                clan_summary=(
                    str(normalized["clan_summary"])
                    if normalized.get("clan_summary") is not None
                    else None
                ),
                tribe=str(normalized.get("tribe") or "chop"),
                model=str(normalized["model"]) if normalized.get("model") else None,
                effort=str(normalized["effort"]) if normalized.get("effort") else None,
                env={str(k): str(v) for k, v in dict(normalized["env"]).items()},
                dedupe_key=(
                    str(normalized["dedupe_key"])
                    if normalized.get("dedupe_key")
                    else None
                ),
                wait_on=normalized.get("wait_on"),
            )
        )
    summaries_by_clan: dict[str, str] = {}
    for proposal in prepared:
        if proposal.clan is None or proposal.clan_summary is None:
            continue
        agreed = summaries_by_clan.setdefault(
            proposal.clan,
            proposal.clan_summary,
        )
        if proposal.clan_summary != agreed:
            raise ValueError(
                f"conflicting clan_summary values for raw clan {proposal.clan!r}"
            )
    return [
        replace(
            proposal,
            clan_summary=(
                summaries_by_clan.get(proposal.clan)
                if proposal.clan is not None
                else None
            ),
        )
        for proposal in prepared
    ]


def _render_template_value(value: str, token: str | None) -> str:
    from sase.agent.names import is_agent_name_template, render_agent_name_template

    if not is_agent_name_template(value):
        return value
    assert token is not None
    return render_agent_name_template(value, token)


def _group_token_candidates(has_template: bool) -> Iterable[str | None]:
    if not has_template:
        return (None,)
    from sase.agent.names import iter_agent_name_template_tokens

    return iter_agent_name_template_tokens()


def _plan_clan_group(
    proposals: Sequence[_PreparedChopProposal],
    *,
    reserved_names: set[str],
    reservation_index: Any,
) -> tuple[str, dict[int, tuple[str, str]]]:
    """Choose one unreserved concrete clan/token for a proposal group."""
    from sase.agent.names import (
        agent_name_template_namespace_template,
        is_agent_name_template,
        render_agent_name_template,
    )

    raw_clan = proposals[0].clan
    assert raw_clan is not None
    full_templates = [_full_name_template(proposal) for proposal in proposals]
    has_template = any(is_agent_name_template(value) for value in full_templates)

    for token in _group_token_candidates(has_template):
        concrete_clan = _render_template_value(raw_clan, token)
        if concrete_clan in reserved_names:
            if not has_template:
                break
            continue

        members: dict[int, tuple[str, str]] = {}
        candidates: list[tuple[str, str]] = []
        for proposal, full_template in zip(proposals, full_templates, strict=True):
            concrete_member = _render_template_value(proposal.agent_name, token)
            concrete_name = _render_template_value(full_template, token)
            namespace = concrete_clan
            if is_agent_name_template(full_template):
                namespace = render_agent_name_template(
                    agent_name_template_namespace_template(full_template),
                    token or "",
                )
            members[proposal.index] = (concrete_name, concrete_member)
            candidates.append((concrete_name, namespace))

        candidate_names = [name for name, _ in candidates]
        if len(set(candidate_names)) != len(candidate_names):
            raise ValueError(f"clan {raw_clan!r} contains duplicate member identities")
        if not all(
            reservation_index.candidate_available(name, namespace)
            for name, namespace in candidates
        ):
            if not has_template:
                break
            continue

        reserved_names.add(concrete_clan)
        reservation_index.add_name(concrete_clan)
        for name, _ in candidates:
            reserved_names.add(name)
            reservation_index.add_name(name)
        return concrete_clan, members

    raise ValueError(
        f"clan {raw_clan!r} or one of its member identities is already reserved"
    )


def plan_chop_proposals(
    proposals: Sequence[_PreparedChopProposal],
) -> list[_PlannedChopProposal]:
    """Build the exact clan declaration/join plan without reserving names."""
    clan_groups: dict[str, list[_PreparedChopProposal]] = {}
    for proposal in proposals:
        if proposal.clan is not None:
            clan_groups.setdefault(proposal.clan, []).append(proposal)

    concrete_by_index: dict[int, tuple[str, str, str]] = {}
    if clan_groups:
        from sase.agent.names import (
            AgentNameNamespaceReservationIndex,
            get_reserved_agent_names,
            get_reserved_clan_names,
            is_agent_name_template,
        )

        reserved_names = get_reserved_agent_names()
        reservation_index = AgentNameNamespaceReservationIndex.from_registry_names(
            reserved_names,
            namespace_containers=get_reserved_clan_names(),
        )
        # Concrete clan declarations are immovable, so account for them before
        # allocating template clans regardless of proposal ordering.
        ordered_groups = sorted(
            clan_groups.values(),
            key=lambda group: is_agent_name_template(group[0].clan or ""),
        )
        for group in ordered_groups:
            concrete_clan, members = _plan_clan_group(
                group,
                reserved_names=reserved_names,
                reservation_index=reservation_index,
            )
            for index, (agent_name, member_id) in members.items():
                concrete_by_index[index] = (concrete_clan, agent_name, member_id)

    first_by_clan: dict[str, int] = {}
    for proposal in proposals:
        concrete = concrete_by_index.get(proposal.index)
        if concrete is not None:
            first_by_clan.setdefault(concrete[0], proposal.index)

    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    planned: list[_PlannedChopProposal] = []
    for proposal in proposals:
        plan_clan: str | None
        plan_member_id: str | None
        concrete = concrete_by_index.get(proposal.index)
        if concrete is None:
            agent_name = proposal.agent_name
            plan_clan = None
            plan_member_id = None
            declares_clan = False
        else:
            plan_clan, agent_name, plan_member_id = concrete
            declares_clan = first_by_clan[plan_clan] == proposal.index
        clan_summary = proposal.clan_summary if declares_clan else None
        wait_name = _resolve_wait_name(
            proposal.wait_on,
            names_by_index,
            names_by_id,
        )
        prompt = _scaffolded_prompt(
            proposal,
            wait_name,
            agent_name=agent_name,
            clan=plan_clan,
            member_id=plan_member_id,
            declares_clan=declares_clan,
            clan_summary=clan_summary,
        )
        planned.append(
            _PlannedChopProposal(
                proposal=proposal,
                agent_name=agent_name,
                clan=plan_clan,
                member_id=plan_member_id,
                declares_clan=declares_clan,
                clan_summary=clan_summary,
                prompt=prompt,
            )
        )
        names_by_index[proposal.index] = agent_name
        if proposal.proposal_id is not None:
            names_by_id[proposal.proposal_id] = agent_name

    if clan_groups:
        from sase.agent.launch_validation import validate_launch_name_requests

        validate_launch_name_requests([item.prompt for item in planned])
    return planned


def _fallback_plan(proposal: _PreparedChopProposal) -> _PlannedChopProposal:
    agent_name = _full_name_template(proposal)
    return _PlannedChopProposal(
        proposal=proposal,
        agent_name=agent_name,
        clan=proposal.clan,
        member_id=proposal.agent_name if proposal.clan is not None else None,
        declares_clan=False,
        clan_summary=None,
        prompt=_scaffolded_prompt(
            proposal,
            None,
            agent_name=agent_name,
            clan=proposal.clan,
            member_id=proposal.agent_name,
        ),
    )


def proposal_previews(
    proposals: list[_PreparedChopProposal],
    *,
    once_per_decisions: Mapping[int, Mapping[str, str]] | None = None,
    effective_waits: Mapping[int, int | str | None] | None = None,
    launch_plans: Sequence[_PlannedChopProposal] | None = None,
) -> list[dict[str, Any]]:
    """Return JSON-safe launch previews with planned clan and wait metadata."""
    if launch_plans is None:
        launch_plans = plan_chop_proposals(proposals)
    plans_by_index = {plan.proposal.index: plan for plan in launch_plans}
    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    previews: list[dict[str, Any]] = []
    for proposal in proposals:
        plan = plans_by_index.get(proposal.index) or _fallback_plan(proposal)
        wait_on = proposal.wait_on
        if effective_waits is not None and proposal.index in effective_waits:
            wait_on = effective_waits[proposal.index]
        wait_name = _resolve_wait_name(wait_on, names_by_index, names_by_id)
        once_per = (once_per_decisions or {}).get(proposal.index, {})
        decision_outcome = once_per.get("outcome")
        validation = (
            decision_outcome
            if decision_outcome in {"duplicate", "name_collision"}
            else "valid"
        )
        prompt = _scaffolded_prompt(
            proposal,
            wait_name,
            agent_name=plan.agent_name,
            clan=plan.clan,
            member_id=plan.member_id,
            declares_clan=plan.declares_clan,
            clan_summary=plan.clan_summary,
        )
        previews.append(
            {
                "index": proposal.index,
                "id": proposal.proposal_id,
                "agent_name": plan.agent_name,
                "clan": plan.clan,
                "member_id": plan.member_id,
                "clan_role": ("declare" if plan.declares_clan else "join")
                if plan.clan is not None
                else None,
                "clan_summary": plan.clan_summary,
                "tribe": proposal.tribe,
                "workspace": proposal.workspace,
                "model": proposal.model,
                "effort": proposal.effort,
                "wait_on": wait_on,
                "wait_name": wait_name,
                "env_names": sorted(proposal.env),
                "dedupe_key": once_per.get("key") or proposal.dedupe_key,
                "dedupe_reason": (
                    None
                    if decision_outcome == "name_collision"
                    else once_per.get("reason")
                ),
                "skip_reason": (
                    once_per.get("reason")
                    if decision_outcome in {"duplicate", "name_collision"}
                    else None
                ),
                "prompt": prompt,
                "validation": validation,
            }
        )
        names_by_index[proposal.index] = plan.agent_name
        if proposal.proposal_id is not None:
            names_by_id[proposal.proposal_id] = plan.agent_name
    return previews


def _resolve_wait_name(
    wait_on: int | str | None,
    names_by_index: Mapping[int, str],
    names_by_id: Mapping[str, str],
) -> str | None:
    if wait_on is None:
        return None
    if isinstance(wait_on, int):
        return names_by_index[wait_on]
    return names_by_id[wait_on]


def _launch_descriptor(
    plan: _PlannedChopProposal,
    result: Any,
    *,
    wait_on: int | str | None,
    wait_name: str | None,
) -> dict[str, Any]:
    proposal = plan.proposal
    actual_name = str(getattr(result, "agent_name", "") or plan.agent_name)
    timestamp = str(getattr(result, "timestamp", "") or "")
    artifacts_timestamp = (
        convert_timestamp_to_artifacts_format(timestamp) if timestamp else ""
    )
    return {
        "index": proposal.index,
        "id": proposal.proposal_id,
        "agent_name": actual_name,
        "clan": plan.clan,
        "member_id": plan.member_id,
        "pid": int(result.pid),
        "workspace": proposal.workspace,
        "workspace_num": int(getattr(result, "workspace_num", 0) or 0),
        "workspace_dir": str(getattr(result, "workspace_dir", "") or ""),
        "project_name": str(getattr(result, "project_name", "") or ""),
        "workflow_name": str(getattr(result, "workflow_name", "") or ""),
        "cl_name": str(getattr(result, "cl_name", "") or ""),
        "timestamp": timestamp,
        "artifacts_timestamp": artifacts_timestamp,
        "artifacts_dir": str(getattr(result, "artifacts_dir", "") or ""),
        "dedupe_key": proposal.dedupe_key,
        "wait_on": wait_on,
        "wait_name": wait_name,
    }


def _record_batch_results(
    plans: Sequence[_PlannedChopProposal],
    results: Sequence[Any],
    launch_recorded_fn: Callable[[dict[str, Any]], None] | None,
) -> list[dict[str, Any]]:
    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    launches: list[dict[str, Any]] = []
    for plan, result in zip(plans, results, strict=False):
        proposal = plan.proposal
        wait_name = _resolve_wait_name(
            proposal.wait_on,
            names_by_index,
            names_by_id,
        )
        launch = _launch_descriptor(
            plan,
            result,
            wait_on=proposal.wait_on,
            wait_name=wait_name,
        )
        launches.append(launch)
        names_by_index[proposal.index] = str(launch["agent_name"])
        if proposal.proposal_id is not None:
            names_by_id[proposal.proposal_id] = str(launch["agent_name"])
        if launch_recorded_fn is not None:
            launch_recorded_fn(launch)
    return launches


def launch_chop_proposals(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    proposals: list[_PreparedChopProposal],
    launch_agent_from_cwd_fn: Callable[..., Any],
    launch_agents_from_cwd_fn: Callable[..., Any] | None = None,
    launch_plans: Sequence[_PlannedChopProposal] | None = None,
    launch_recorded_fn: Callable[[dict[str, Any]], None] | None = None,
    proposal_skipped_fn: (
        Callable[[_PreparedChopProposal, str, int | str | None], None] | None
    ) = None,
) -> list[dict[str, Any]]:
    """Launch proposals, batching clan members through multi-prompt preflight."""
    plans = list(launch_plans or plan_chop_proposals(proposals))
    if any(plan.clan is not None for plan in plans):
        if launch_agents_from_cwd_fn is None:
            from sase.agent.launcher import launch_agents_from_cwd

            launch_agents_from_cwd_fn = launch_agents_from_cwd
        segment_env: list[dict[str, str]] = []
        for plan in plans:
            extra_env = dict(plan.proposal.env)
            extra_env.update(
                build_chop_launch_env(
                    lumberjack_name=lumberjack_name,
                    chop_name=chop_name,
                    prompt=plan.prompt,
                    run_id=run_id,
                )
            )
            segment_env.append(extra_env)
        query = "\n---\n".join(plan.prompt.rstrip() for plan in plans) + "\n"
        try:
            results = list(
                launch_agents_from_cwd_fn(
                    query,
                    segment_extra_env=segment_env,
                )
            )
        except Exception as exc:
            partial_results = list(getattr(exc, "results", ()) or ())
            if partial_results:
                _record_batch_results(plans, partial_results, launch_recorded_fn)
            raise
        batch_launches = _record_batch_results(plans, results, launch_recorded_fn)
        if len(results) != len(plans):
            raise RuntimeError(
                "clan proposal batch returned "
                f"{len(results)} launch result(s) for {len(plans)} proposal(s)"
            )
        return batch_launches

    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    proposal_indices_by_id: dict[str, int] = {}
    resolved_waits: dict[int, int | str | None] = {}
    skipped_indices: set[int] = set()
    launches: list[dict[str, Any]] = []
    from sase.agent.launch_validation import AgentNameLaunchCollisionError

    for plan in plans:
        proposal = plan.proposal
        dependency = proposal.wait_on
        dependency_index: int | None = None
        if isinstance(dependency, int):
            dependency_index = dependency
        elif isinstance(dependency, str):
            dependency_index = proposal_indices_by_id.get(dependency)
        effective_wait = dependency
        if dependency_index in skipped_indices:
            effective_wait = resolved_waits[dependency_index]
        resolved_waits[proposal.index] = effective_wait
        if proposal.proposal_id is not None:
            proposal_indices_by_id[proposal.proposal_id] = proposal.index

        wait_name = _resolve_wait_name(effective_wait, names_by_index, names_by_id)
        prompt = _scaffolded_prompt(
            proposal,
            wait_name,
            agent_name=plan.agent_name,
        )
        extra_env = dict(proposal.env)
        extra_env.update(
            build_chop_launch_env(
                lumberjack_name=lumberjack_name,
                chop_name=chop_name,
                prompt=prompt,
                run_id=run_id,
            )
        )
        try:
            result = launch_agent_from_cwd_fn(prompt, extra_env=extra_env)
        except AgentNameLaunchCollisionError as exc:
            if not proposal.explicit_agent_name:
                raise
            skipped_indices.add(proposal.index)
            reason = f"explicit agent name collision: {exc} Proposal skipped."
            if proposal_skipped_fn is not None:
                proposal_skipped_fn(proposal, reason, effective_wait)
            continue
        launch = _launch_descriptor(
            plan,
            result,
            wait_on=effective_wait,
            wait_name=wait_name,
        )
        names_by_index[proposal.index] = str(launch["agent_name"])
        if proposal.proposal_id is not None:
            names_by_id[proposal.proposal_id] = str(launch["agent_name"])
        launches.append(launch)
        if launch_recorded_fn is not None:
            launch_recorded_fn(launch)
    return launches


__all__ = [
    "launch_chop_proposals",
    "plan_chop_proposals",
    "prepare_chop_proposals",
    "proposal_previews",
]
