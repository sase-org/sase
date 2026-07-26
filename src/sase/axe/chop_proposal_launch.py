"""Launch planned chop proposals and record their results."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from sase.artifacts import convert_timestamp_to_artifacts_format

from .chop_agents import build_chop_launch_env
from .chop_proposal_models import (
    PlannedChopProposal,
    PreparedChopProposal,
    resolve_wait_name,
    scaffolded_prompt,
)
from .chop_proposal_planning import plan_chop_proposals


def _launch_descriptor(
    plan: PlannedChopProposal,
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
    plans: Sequence[PlannedChopProposal],
    results: Sequence[Any],
    launch_recorded_fn: Callable[[dict[str, Any]], None] | None,
) -> list[dict[str, Any]]:
    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    launches: list[dict[str, Any]] = []
    for plan, result in zip(plans, results, strict=False):
        proposal = plan.proposal
        wait_name = resolve_wait_name(
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
    proposals: list[PreparedChopProposal],
    launch_agent_from_cwd_fn: Callable[..., Any],
    launch_agents_from_cwd_fn: Callable[..., Any] | None = None,
    launch_plans: Sequence[PlannedChopProposal] | None = None,
    launch_recorded_fn: Callable[[dict[str, Any]], None] | None = None,
    proposal_skipped_fn: (
        Callable[[PreparedChopProposal, str, int | str | None], None] | None
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

        wait_name = resolve_wait_name(effective_wait, names_by_index, names_by_id)
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


__all__ = ["launch_chop_proposals"]
