"""Ordinary launch orchestration for chop proposals."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from .chop_agents import build_chop_launch_env
from .chop_proposal_launch import ChopProposalLaunches
from .chop_proposal_models import (
    PlannedChopProposal,
    PreparedChopProposal,
    resolve_wait_name,
    scaffolded_prompt,
)
from .chop_proposal_planning import plan_chop_proposals
from ._chop_proposal_launch_journal import OrdinaryLaunchJournal
from ._chop_proposal_launch_shared import (
    ordinary_batch_manifest,
    query_for_plans,
)
from ._chop_proposal_launch_typed_dispatch import (
    maybe_dispatch_typed_chop_proposals,
)


def _call_with_supported_kwargs(
    function: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """Keep injected launch fakes compatible with additive progress hooks."""
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(*args, **kwargs)
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return function(*args, **kwargs)
    supported = {
        key: value for key, value in kwargs.items() if key in signature.parameters
    }
    return function(*args, **supported)


def launch_chop_proposals(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    proposals: list[PreparedChopProposal],
    launch_agent_from_cwd_fn: Callable[..., Any] | None,
    launch_agents_from_cwd_fn: Callable[..., Any] | None = None,
    launch_plans: Sequence[PlannedChopProposal] | None = None,
    launch_recorded_fn: Callable[[dict[str, Any]], None] | None = None,
    proposal_skipped_fn: (
        Callable[[PreparedChopProposal, str, int | str | None], None] | None
    ) = None,
    run_started_at: datetime | None = None,
    preflight: Any | None = None,
    batch_created_fn: Callable[[str], None] | None = None,
    pause_requested_fn: Callable[[], bool] | None = None,
) -> ChopProposalLaunches:
    """Launch proposals, batching clan members through multi-prompt preflight."""
    plans = list(launch_plans or plan_chop_proposals(proposals))
    typed_launches = maybe_dispatch_typed_chop_proposals(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        run_id=run_id,
        plans=plans,
        launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
        launch_recorded_fn=launch_recorded_fn,
        run_started_at=run_started_at,
        preflight=preflight,
        batch_created_fn=batch_created_fn,
        pause_requested_fn=pause_requested_fn,
    )
    if typed_launches is not None:
        return typed_launches

    batch_id: str | None = None
    if run_started_at is not None and preflight is not None:
        from .chop_batch_store import create_chop_batch

        manifest = ordinary_batch_manifest(
            lumberjack_name=lumberjack_name,
            chop_name=chop_name,
            run_id=run_id,
            run_started_at=run_started_at.isoformat(),
            preflight=preflight,
            plans=plans,
        )
        batch_id = str(
            create_chop_batch(lumberjack_name, chop_name, manifest)["batch_id"]
        )
        if batch_created_fn is not None:
            batch_created_fn(batch_id)

    journal = OrdinaryLaunchJournal(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        batch_id=batch_id,
        plans=plans,
        launch_recorded_fn=launch_recorded_fn,
        pause_requested_fn=pause_requested_fn,
    )

    if journal.has_clan:
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
                    proposal_index=plan.proposal.index,
                    proposal_id=plan.proposal.proposal_id,
                )
            )
            segment_env.append(extra_env)
        query = query_for_plans(plans)
        try:
            results = list(
                _call_with_supported_kwargs(
                    launch_agents_from_cwd_fn,
                    query,
                    segment_extra_env=segment_env,
                    origin="generated",
                    **journal.progress_kwargs(),
                )
            )
        except Exception as exc:
            partial_results = list(getattr(exc, "results", ()) or ())
            if partial_results and not journal.launches_by_member:
                for member_index, result in enumerate(partial_results[: len(plans)]):
                    journal.fallback_record(member_index, result)
            raise
        if journal.paused:
            batch_launches = [
                journal.launches_by_member[index]
                for index in range(len(plans))
                if index in journal.launches_by_member
            ]
            return ChopProposalLaunches(
                batch_launches,
                paused=True,
                batch_id=journal.batch_id,
            )
        if len(results) != len(plans):
            raise RuntimeError(
                "clan proposal batch returned "
                f"{len(results)} launch result(s) for {len(plans)} proposal(s)"
            )
        for member_index, result in enumerate(results):
            if member_index not in journal.launches_by_member:
                journal.fallback_record(member_index, result)
        batch_launches = [
            journal.launches_by_member[index]
            for index in range(len(plans))
            if index in journal.launches_by_member
        ]
        return ChopProposalLaunches(
            batch_launches, paused=journal.paused, batch_id=journal.batch_id
        )

    from sase.agent.launch_validation import AgentNameLaunchCollisionError

    for member_index, plan in enumerate(plans):
        if pause_requested_fn is not None and pause_requested_fn():
            journal.pause_batch()
            break
        journal.active_single_member = member_index
        proposal = plan.proposal
        dependency = proposal.wait_on
        dependency_index: int | None = None
        if isinstance(dependency, int):
            dependency_index = dependency
        elif isinstance(dependency, str):
            dependency_index = journal.proposal_indices_by_id.get(dependency)
        effective_wait = dependency
        if dependency_index in journal.skipped_indices:
            effective_wait = journal.resolved_waits[dependency_index]
        journal.resolved_waits[proposal.index] = effective_wait
        if proposal.proposal_id is not None:
            journal.proposal_indices_by_id[proposal.proposal_id] = proposal.index

        wait_name = resolve_wait_name(
            effective_wait, journal.names_by_index, journal.names_by_id
        )
        prompt = scaffolded_prompt(
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
                proposal_index=proposal.index,
                proposal_id=proposal.proposal_id,
            )
        )
        try:
            if launch_agent_from_cwd_fn is None:
                from sase.agent.launcher import launch_agent_from_cwd as launch_fn
            else:
                launch_fn = launch_agent_from_cwd_fn

            result = _call_with_supported_kwargs(
                launch_fn,
                prompt,
                extra_env=extra_env,
                origin="generated",
                **journal.progress_kwargs(),
            )
        except AgentNameLaunchCollisionError as exc:
            if not proposal.explicit_agent_name:
                raise
            journal.skipped_indices.add(proposal.index)
            journal.batch_event(
                "record_skip",
                member_index=member_index,
                reason=f"explicit agent name collision: {exc}",
            )
            reason = f"explicit agent name collision: {exc} Proposal skipped."
            if proposal_skipped_fn is not None:
                proposal_skipped_fn(proposal, reason, effective_wait)
            continue
        except Exception:
            if journal.paused:
                break
            raise
        if result is None and journal.paused:
            break
        launch = journal.launches_by_member.get(member_index)
        if launch is None:
            launch = journal.fallback_record(member_index, result)
        journal.names_by_index[proposal.index] = str(launch["agent_name"])
        if proposal.proposal_id is not None:
            journal.names_by_id[proposal.proposal_id] = str(launch["agent_name"])
    launches = [
        journal.launches_by_member[index]
        for index in range(len(plans))
        if index in journal.launches_by_member
    ]
    return ChopProposalLaunches(
        launches, paused=journal.paused, batch_id=journal.batch_id
    )


__all__ = ["launch_chop_proposals"]
