"""Launch planned chop proposals and record their results."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.core.agent_launch_wire import LaunchPlanWire, launch_plan_from_dict

from .chop_agents import build_chop_launch_env
from .chop_proposal_models import (
    PlannedChopProposal,
    PreparedChopProposal,
    resolve_wait_name,
    scaffolded_prompt,
)
from .chop_proposal_planning import plan_chop_proposals
from .chop_typed_admission import (
    AXE_CHOP_SOURCE_SURFACE,
    UNIT_DISPATCH_METADATA_KEY,
    make_axe_chop_agent_dispatcher,
)


class _ChopProposalLaunches(list[dict[str, Any]]):
    """Launch rows plus optional durable typed-admission metadata."""

    def __init__(
        self,
        launches: Sequence[dict[str, Any]] = (),
        *,
        typed_admission: dict[str, Any] | None = None,
        admission_result: Any | None = None,
    ) -> None:
        super().__init__(launches)
        self.typed_admission = typed_admission
        self.admission_result = admission_result


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
        "patch_name": str(getattr(result, "cl_name", "") or ""),
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


def _query_for_plans(plans: Sequence[PlannedChopProposal]) -> str:
    return "\n---\n".join(plan.prompt.rstrip() for plan in plans) + "\n"


def _resolve_typed_batch_project(
    plans: Sequence[PlannedChopProposal],
) -> tuple[str, str]:
    """Resolve the only project/source cwd allowed for one typed chop batch."""
    from sase.agent.launch_cwd_common import resolve_known_project_vcs_launch_ref
    from sase.agent.launch_request_types import LaunchRequestError

    resolved: list[tuple[str, str, int, str]] = []
    for plan in plans:
        ref = resolve_known_project_vcs_launch_ref(plan.prompt)
        if ref is None:
            raise LaunchRequestError(
                "invalid_request",
                "workspace",
                (
                    "typed AXE chop proposal "
                    f"{plan.proposal.index + 1} workspace "
                    f"{plan.proposal.workspace!r} does not resolve to a known project"
                ),
            )
        resolved.append(
            (
                str(ref.ref),
                str(ref.workspace_dir),
                plan.proposal.index,
                plan.proposal.workspace,
            )
        )
    unique = {(project, cwd) for project, cwd, _index, _workspace in resolved}
    if len(unique) != 1:
        details = ", ".join(
            f"{workspace!r}->{project}" for project, _cwd, _index, workspace in resolved
        )
        raise LaunchRequestError(
            "invalid_request",
            "workspace",
            f"typed AXE chop proposal batch spans multiple projects: {details}",
        )
    selected_project, source_cwd = next(iter(unique))
    return selected_project, source_cwd


def _wait_names_by_proposal_index(
    plans: Sequence[PlannedChopProposal],
) -> dict[int, str | None]:
    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    result: dict[int, str | None] = {}
    for plan in plans:
        proposal = plan.proposal
        wait_name = resolve_wait_name(
            proposal.wait_on,
            names_by_index,
            names_by_id,
        )
        result[proposal.index] = wait_name
        names_by_index[proposal.index] = plan.agent_name
        if proposal.proposal_id is not None:
            names_by_id[proposal.proposal_id] = plan.agent_name
    return result


def _metadata_for_unit(
    *,
    plan: PlannedChopProposal,
    logical_id: str,
    source_order: int,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    wait_name: str | None,
) -> dict[str, Any]:
    proposal = plan.proposal
    return {
        "lumberjack_name": lumberjack_name,
        "chop_name": chop_name,
        "run_id": run_id,
        "logical_id": logical_id,
        "source_order": source_order,
        "proposal_index": proposal.index,
        "proposal_id": proposal.proposal_id,
        "agent_name": plan.agent_name,
        "clan": plan.clan,
        "member_id": plan.member_id,
        "workspace": proposal.workspace,
        "dedupe_key": proposal.dedupe_key,
        "wait_on": proposal.wait_on,
        "wait_name": wait_name,
        "env": dict(proposal.env),
    }


def _unit_dispatch_metadata(
    *,
    typed_plan: LaunchPlanWire,
    plans: Sequence[PlannedChopProposal],
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
) -> dict[str, dict[str, Any]]:
    wait_names = _wait_names_by_proposal_index(plans)
    metadata: dict[str, dict[str, Any]] = {}
    for unit in typed_plan.units:
        try:
            plan = plans[int(unit.source_order)]
        except (IndexError, ValueError) as exc:
            from sase.agent.launch_request_types import LaunchRequestError

            raise LaunchRequestError(
                "invalid_request",
                unit.logical_id,
                (
                    "typed AXE chop plan unit "
                    f"{unit.logical_id} has invalid source_order {unit.source_order}"
                ),
            ) from exc
        metadata[unit.logical_id] = _metadata_for_unit(
            plan=plan,
            logical_id=unit.logical_id,
            source_order=int(unit.source_order),
            lumberjack_name=lumberjack_name,
            chop_name=chop_name,
            run_id=run_id,
            wait_name=wait_names.get(plan.proposal.index),
        )
    return metadata


def _typed_admission_record(
    *,
    bundle_dir: Any,
    payload: Mapping[str, Any],
    typed_plan: LaunchPlanWire,
    metadata: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    for unit in typed_plan.units:
        unit_meta = metadata.get(unit.logical_id, {})
        units.append(
            {
                "logical_id": unit.logical_id,
                "source_order": int(unit.source_order),
                "proposal_index": unit_meta.get("proposal_index"),
                "proposal_id": unit_meta.get("proposal_id"),
                "dedupe_key": unit_meta.get("dedupe_key"),
            }
        )
    return {
        "request_id": str(payload.get("request_id") or ""),
        "bundle_dir": str(bundle_dir),
        "plan_digest": typed_plan.content_digest,
        "plan_schema_version": typed_plan.schema_version,
        "source_surface": AXE_CHOP_SOURCE_SURFACE,
        "units": units,
    }


def _maybe_dispatch_typed_chop_proposals(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    plans: Sequence[PlannedChopProposal],
    launch_agents_from_cwd_fn: Callable[..., Any] | None,
    launch_recorded_fn: Callable[[dict[str, Any]], None] | None,
) -> _ChopProposalLaunches | None:
    from sase.agent.direct_typed_launch import write_typed_launch_bundle
    from sase.agent.launch_admission import dispatch_typed_launch_request
    from sase.agent.launch_request_planning import (
        expand_prompt_for_typed_launch,
        prepare_typed_launch_plan,
    )
    from sase.agent.launch_request_types import LaunchRequestError
    from sase.xprompt.code_value import (
        TYPED_LAUNCH_UNITS_DISABLED_MESSAGE,
        typed_launch_units_enabled,
    )
    from sase.xprompt.directives import DirectiveError, has_typed_launch_directive

    query = _query_for_plans(plans)
    try:
        expanded_prompt = expand_prompt_for_typed_launch(query)
    except DirectiveError as exc:
        raise LaunchRequestError("invalid_request", "prompt", str(exc)) from exc
    if not has_typed_launch_directive(expanded_prompt):
        return None
    if not typed_launch_units_enabled():
        raise LaunchRequestError(
            "invalid_request",
            "prompt",
            TYPED_LAUNCH_UNITS_DISABLED_MESSAGE,
        )

    selected_project, source_cwd = _resolve_typed_batch_project(plans)
    typed_plan_dict = prepare_typed_launch_plan(
        expanded_prompt,
        selected_project=selected_project,
        launch_kind="multi_prompt",
    )
    typed_plan = launch_plan_from_dict(typed_plan_dict)
    metadata = _unit_dispatch_metadata(
        typed_plan=typed_plan,
        plans=plans,
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        run_id=run_id,
    )
    bundle_dir, payload = write_typed_launch_bundle(
        prompt=query,
        expanded_prompt=expanded_prompt,
        typed_plan=typed_plan_dict,
        source_cwd=source_cwd,
        source_surface=AXE_CHOP_SOURCE_SURFACE,
        selected_project=selected_project,
        unit_dispatch_metadata=metadata,
        request_id=f"axe-chop-{run_id}",
    )
    recorded: list[dict[str, Any]] = []

    def _record(launch: dict[str, Any]) -> None:
        recorded.append(launch)
        if launch_recorded_fn is not None:
            launch_recorded_fn(launch)

    dispatcher = make_axe_chop_agent_dispatcher(
        payload,
        launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
        launch_recorded_fn=_record,
    )
    result = dispatch_typed_launch_request(
        bundle_dir,
        payload,
        agent_dispatcher=dispatcher,
        spawn_coordinator=True,
    )
    return _ChopProposalLaunches(
        recorded,
        typed_admission=_typed_admission_record(
            bundle_dir=bundle_dir,
            payload=payload,
            typed_plan=typed_plan,
            metadata=metadata,
        ),
        admission_result=result,
    )


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
) -> _ChopProposalLaunches:
    """Launch proposals, batching clan members through multi-prompt preflight."""
    plans = list(launch_plans or plan_chop_proposals(proposals))
    typed_launches = _maybe_dispatch_typed_chop_proposals(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        run_id=run_id,
        plans=plans,
        launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
        launch_recorded_fn=launch_recorded_fn,
    )
    if typed_launches is not None:
        return typed_launches
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
        query = _query_for_plans(plans)
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
        return _ChopProposalLaunches(batch_launches)

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
    return _ChopProposalLaunches(launches)


__all__ = ["launch_chop_proposals"]
