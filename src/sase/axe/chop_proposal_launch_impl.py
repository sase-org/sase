"""Launch planned chop proposals and record their results."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.core.agent_launch_wire import LaunchPlanWire, launch_plan_from_dict
from sase.core.axe_chop_facade import (
    CHOP_BATCH_SCHEMA_VERSION,
    apply_chop_batch_transition,
)
from sase.core.process_identity import process_identity_token
from sase.core.time import get_timezone

from .chop_agents import build_chop_launch_env
from .chop_proposal_launch import ChopProposalLaunches
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


def _ordinary_batch_manifest(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    run_started_at: str,
    preflight: Any,
    plans: Sequence[PlannedChopProposal],
) -> dict[str, Any]:
    decision = getattr(preflight, "decision", None)
    preflight_digest = None
    checkpoint_scope = None
    if isinstance(decision, Mapping):
        encoded = json.dumps(
            decision,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        preflight_digest = hashlib.sha256(encoded).hexdigest()
        checkpoint_scope_value = decision.get("checkpoint_key")
        if checkpoint_scope_value:
            checkpoint_scope = str(checkpoint_scope_value)
    members: list[dict[str, Any]] = []
    position_by_source_index = {
        plan.proposal.index: position for position, plan in enumerate(plans)
    }
    accepted_ids = {
        plan.proposal.proposal_id
        for plan in plans
        if plan.proposal.proposal_id is not None
    }
    for plan in plans:
        proposal = plan.proposal
        member: dict[str, Any] = {
            "source_index": proposal.index,
            "agent_name": plan.agent_name,
            "prompt": plan.prompt,
            "workspace": proposal.workspace,
            "env": dict(proposal.env),
            "launch_role": ("declare" if plan.declares_clan else "join")
            if plan.clan is not None
            else "standalone",
        }
        wait_on = proposal.wait_on
        if isinstance(wait_on, int):
            mapped_wait = position_by_source_index.get(wait_on)
            if mapped_wait is not None:
                member["wait_on"] = mapped_wait
        elif isinstance(wait_on, str) and wait_on in accepted_ids:
            member["wait_on"] = wait_on
        if proposal.proposal_id is not None:
            member["proposal_id"] = proposal.proposal_id
        if plan.clan is not None:
            member["clan"] = plan.clan
        if proposal.model is not None:
            member["model"] = proposal.model
        if proposal.effort is not None:
            member["effort"] = proposal.effort
        if proposal.dedupe_key is not None:
            member["dedupe_key"] = proposal.dedupe_key
        if proposal.tribe:
            member["tribe"] = proposal.tribe
        members.append(member)
    manifest: dict[str, Any] = {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": run_id,
        "run": {
            "routine": lumberjack_name,
            "job": chop_name,
            "run_id": run_id,
            "run_started_at": run_started_at,
        },
        "created_at": datetime.now(get_timezone()).isoformat(),
        "members": members,
    }
    if preflight_digest is not None:
        manifest["run"]["preflight_digest"] = preflight_digest
    if checkpoint_scope is not None:
        manifest["run"]["checkpoint_scope"] = checkpoint_scope
    return manifest


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
    pid = int(result.pid)
    return {
        "index": proposal.index,
        "id": proposal.proposal_id,
        "agent_name": actual_name,
        "clan": plan.clan,
        "member_id": plan.member_id,
        "pid": pid,
        "process_identity": process_identity_token(pid),
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


def _query_for_plans(plans: Sequence[PlannedChopProposal]) -> str:
    return "\n---\n".join(plan.prompt.rstrip() for plan in plans) + "\n"


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _resolve_typed_batch_project(
    plans: Sequence[PlannedChopProposal],
) -> tuple[str, str, str | None]:
    """Resolve the only project/source cwd allowed for one typed chop batch."""
    from sase.agent.launch_cwd_common import resolve_known_project_vcs_launch_ref
    from sase.agent.launch_request_types import LaunchRequestError

    resolved: list[tuple[str, str, str | None, int, str]] = []
    for plan in plans:
        ref = resolve_known_project_vcs_launch_ref(plan.prompt)
        if ref is None:
            raise LaunchRequestError(
                "invalid_request",
                "workspace",
                (
                    "typed AXE job proposal "
                    f"{plan.proposal.index + 1} workspace "
                    f"{plan.proposal.workspace!r} does not resolve to a known project"
                ),
            )
        resolved.append(
            (
                str(ref.ref),
                str(ref.workspace_dir),
                _str_or_none(getattr(ref, "project_file", None)),
                plan.proposal.index,
                plan.proposal.workspace,
            )
        )
    unique = {
        (project, cwd, project_file)
        for project, cwd, project_file, _index, _workspace in resolved
    }
    if len(unique) != 1:
        details = ", ".join(
            f"{workspace!r}->{project}"
            for project, _cwd, _project_file, _index, workspace in resolved
        )
        raise LaunchRequestError(
            "invalid_request",
            "workspace",
            f"typed AXE job proposal batch spans multiple projects: {details}",
        )
    selected_project, source_cwd, project_file = next(iter(unique))
    return selected_project, source_cwd, project_file


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
    wait_logical_id: str | None,
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
        # The statically planned role, from before admission-time `%if`
        # filtering. Dispatch promotes whichever eligible member reaches the
        # clan first, so this is informational rather than authoritative.
        "declares_clan": plan.declares_clan,
        # Every member of a clan repeats its raw proposal's intended tribe
        # and summary, so a promoted declarer can recover them without
        # re-deriving anything from mutable prompt prose.
        "clan_tribe": proposal.tribe,
        "clan_summary": proposal.clan_summary,
        "workspace": proposal.workspace,
        "dedupe_key": proposal.dedupe_key,
        "wait_on": proposal.wait_on,
        "wait_name": wait_name,
        "wait_logical_id": wait_logical_id,
        "env": dict(proposal.env),
    }


def _plan_for_unit(
    unit: Any,
    plans: Sequence[PlannedChopProposal],
) -> PlannedChopProposal:
    try:
        return plans[int(unit.source_order)]
    except (IndexError, ValueError) as exc:
        from sase.agent.launch_request_types import LaunchRequestError

        raise LaunchRequestError(
            "invalid_request",
            unit.logical_id,
            (
                "typed AXE job plan unit "
                f"{unit.logical_id} has invalid source_order {unit.source_order}"
            ),
        ) from exc


def _proposal_logical_id_maps(
    *,
    typed_plan: LaunchPlanWire,
    plans: Sequence[PlannedChopProposal],
) -> tuple[dict[int, str], dict[str, str]]:
    logical_by_index: dict[int, str] = {}
    logical_by_id: dict[str, str] = {}
    for unit in typed_plan.units:
        plan = _plan_for_unit(unit, plans)
        proposal = plan.proposal
        logical_by_index[proposal.index] = unit.logical_id
        if proposal.proposal_id is not None:
            logical_by_id[proposal.proposal_id] = unit.logical_id
    return logical_by_index, logical_by_id


def _wait_logical_id(
    wait_on: int | str | None,
    *,
    logical_by_index: Mapping[int, str],
    logical_by_id: Mapping[str, str],
) -> str | None:
    if wait_on is None:
        return None
    if isinstance(wait_on, int):
        return logical_by_index.get(wait_on)
    return logical_by_id.get(wait_on)


def _unit_dispatch_metadata(
    *,
    typed_plan: LaunchPlanWire,
    plans: Sequence[PlannedChopProposal],
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
) -> dict[str, dict[str, Any]]:
    wait_names = _wait_names_by_proposal_index(plans)
    logical_by_index, logical_by_id = _proposal_logical_id_maps(
        typed_plan=typed_plan,
        plans=plans,
    )
    metadata: dict[str, dict[str, Any]] = {}
    for unit in typed_plan.units:
        plan = _plan_for_unit(unit, plans)
        metadata[unit.logical_id] = _metadata_for_unit(
            plan=plan,
            logical_id=unit.logical_id,
            source_order=int(unit.source_order),
            lumberjack_name=lumberjack_name,
            chop_name=chop_name,
            run_id=run_id,
            wait_name=wait_names.get(plan.proposal.index),
            wait_logical_id=_wait_logical_id(
                plan.proposal.wait_on,
                logical_by_index=logical_by_index,
                logical_by_id=logical_by_id,
            ),
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
                "wait_logical_id": unit_meta.get("wait_logical_id"),
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
) -> ChopProposalLaunches | None:
    from sase.agent.direct_typed_launch import write_typed_launch_bundle
    from sase.agent.launch_admission import dispatch_typed_launch_request
    from sase.agent.launch_request_planning import (
        expand_prompt_for_typed_launch,
        prepare_typed_launch_plan,
    )
    from sase.agent.launch_request_types import LaunchRequestError
    from sase.macro.directives import DirectiveError, has_typed_launch_directive

    query = _query_for_plans(plans)
    try:
        expanded_prompt = expand_prompt_for_typed_launch(query)
    except DirectiveError as exc:
        raise LaunchRequestError("invalid_request", "prompt", str(exc)) from exc
    if not has_typed_launch_directive(expanded_prompt):
        return None

    selected_project, source_cwd, project_file = _resolve_typed_batch_project(plans)
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
        project_file=project_file,
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
        bundle_dir=bundle_dir,
    )
    result = dispatch_typed_launch_request(
        bundle_dir,
        payload,
        agent_dispatcher=dispatcher,
        spawn_coordinator=True,
    )
    return ChopProposalLaunches(
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

    batch_id: str | None = None
    if run_started_at is not None and preflight is not None:
        from .chop_batch_store import create_chop_batch

        manifest = _ordinary_batch_manifest(
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

    from .chop_batch_store import (
        apply_chop_batch_event,
        load_chop_batch,
        update_chop_batch,
    )

    wait_names = _wait_names_by_proposal_index(plans)
    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    proposal_indices_by_id: dict[str, int] = {}
    resolved_waits: dict[int, int | str | None] = {}
    skipped_indices: set[int] = set()
    launches_by_member: dict[int, dict[str, Any]] = {}
    published_launches: set[tuple[int, str, int]] = set()
    paused = False

    def _batch_event(
        event: str,
        *,
        member_index: int | None = None,
        reason: str | None = None,
    ) -> None:
        if batch_id is None:
            return
        apply_chop_batch_event(
            lumberjack_name,
            chop_name,
            batch_id,
            event,
            member_index=member_index,
            reason=reason,
        )

    def _prepare_member(
        member_index: int,
        *,
        request: Any | None = None,
        membership: Any | None = None,
        actual_name: str | None = None,
    ) -> None:
        if batch_id is None:
            return
        evidence = getattr(request, "name_reservation", None)
        evidence_name = str(getattr(evidence, "agent_name", "") or "")
        planned_env = getattr(request, "extra_env", None) or {}
        if not actual_name:
            actual_name = evidence_name or str(
                planned_env.get("SASE_AGENT_PLANNED_NAME") or ""
            )
        generation = str(getattr(membership, "generation", "") or "")
        clan_name = str(getattr(membership, "clan_name", "") or "")

        def _update(manifest: dict[str, Any]) -> dict[str, Any]:
            member = manifest["members"][member_index]
            if evidence_name and actual_name and evidence_name != actual_name:
                raise RuntimeError(
                    "reserved agent name differs from the accepted chop plan: "
                    f"{evidence_name!r} != {actual_name!r}"
                )
            if actual_name:
                member["agent_name"] = actual_name
            if generation:
                if member.get("clan") and clan_name != member["clan"]:
                    raise RuntimeError(
                        "clan reservation differs from accepted chop plan: "
                        f"{clan_name!r} != {member['clan']!r}"
                    )
                stored_generation = str(member.get("clan_generation") or "")
                if stored_generation and stored_generation != generation:
                    raise RuntimeError(
                        "clan generation differs from the persisted chop plan: "
                        f"{stored_generation!r} != {generation!r}"
                    )
                member["clan_generation"] = generation
                generations = {
                    str(item.get("clan_generation") or "")
                    for item in manifest["members"]
                    if item.get("clan")
                }
                if generations == {generation}:
                    manifest["clan_generation"] = generation
            return apply_chop_batch_transition(
                {
                    "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                    "manifest": manifest,
                    "event": "begin_dispatch",
                    "member_index": member_index,
                }
            )

        update_chop_batch(lumberjack_name, chop_name, batch_id, _update)

    def _journal_launch(
        member_index: int,
        plan: PlannedChopProposal,
        result: Any,
        *,
        request: Any | None = None,
        membership: Any | None = None,
    ) -> dict[str, Any]:
        effective_wait = resolved_waits.get(
            plan.proposal.index,
            plan.proposal.wait_on,
        )
        try:
            wait_name = resolve_wait_name(effective_wait, names_by_index, names_by_id)
        except KeyError:
            wait_name = None
        launch = _launch_descriptor(
            plan,
            result,
            wait_on=effective_wait,
            wait_name=wait_name or wait_names.get(plan.proposal.index),
        )
        if batch_id is not None:
            manifest = load_chop_batch(lumberjack_name, chop_name, batch_id)
            status = str(manifest["members"][member_index]["status"])
            if status == "pending":
                _prepare_member(
                    member_index,
                    request=request,
                    membership=membership,
                    actual_name=str(launch["agent_name"]),
                )
                status = "dispatching"
            if status == "dispatching":
                _batch_event("acknowledge_launch", member_index=member_index)
            elif status != "launched":
                raise RuntimeError(
                    f"cannot record launch for batch member in {status!r} state"
                )
        launches_by_member[member_index] = launch
        names_by_index[plan.proposal.index] = str(launch["agent_name"])
        if plan.proposal.proposal_id is not None:
            names_by_id[plan.proposal.proposal_id] = str(launch["agent_name"])
        key = (
            int(launch["index"]),
            str(launch["agent_name"]),
            int(launch["pid"]),
        )
        if key not in published_launches:
            published_launches.add(key)
            if launch_recorded_fn is not None:
                launch_recorded_fn(launch)
        return launch

    active_single_member: int | None = None

    def _before_agent_spawn(
        segment_index: int,
        slot_index: int,
        request: Any,
        membership: Any | None = None,
    ) -> None:
        if slot_index != 0:
            raise RuntimeError(
                "one chop proposal expanded into multiple launch slots; "
                "proposal fan-out is not supported by the batch journal"
            )
        member_index = (
            segment_index
            if any(plan.clan is not None for plan in plans)
            else active_single_member
        )
        if member_index is None or not 0 <= member_index < len(plans):
            raise RuntimeError(f"invalid chop launch source slot {segment_index}")
        _prepare_member(
            member_index,
            request=request,
            membership=membership,
        )

    def _plan_prepared(
        segment_index: int,
        slot_index: int,
        agent_name: str,
        membership: Any | None = None,
    ) -> None:
        if slot_index != 0:
            raise RuntimeError(
                "one chop proposal expanded into multiple launch slots; "
                "proposal fan-out is not supported by the batch journal"
            )
        if not any(plan.clan is not None for plan in plans):
            return
        if not 0 <= segment_index < len(plans):
            raise RuntimeError(f"invalid chop launch source slot {segment_index}")
        if batch_id is None:
            return
        generation = str(getattr(membership, "generation", "") or "")
        clan_name = str(getattr(membership, "clan_name", "") or "")

        def _update(manifest: dict[str, Any]) -> dict[str, Any]:
            member = manifest["members"][segment_index]
            if member.get("clan") and clan_name != member["clan"]:
                raise RuntimeError(
                    "clan preflight differs from accepted chop plan: "
                    f"{clan_name!r} != {member['clan']!r}"
                )
            stored_generation = str(member.get("clan_generation") or "")
            if generation and stored_generation and stored_generation != generation:
                raise RuntimeError(
                    "clan generation differs from the persisted chop plan: "
                    f"{stored_generation!r} != {generation!r}"
                )
            member["agent_name"] = agent_name
            if generation:
                member["clan_generation"] = generation
            clan_names = {
                str(item.get("clan") or "")
                for item in manifest["members"]
                if item.get("clan")
            }
            generations = {
                str(item.get("clan_generation") or "")
                for item in manifest["members"]
                if item.get("clan")
            }
            if len(clan_names) == 1 and len(generations) == 1 and "" not in generations:
                manifest["clan"] = next(iter(clan_names))
                manifest["clan_generation"] = next(iter(generations))
            return manifest

        update_chop_batch(lumberjack_name, chop_name, batch_id, _update)

    def _record_agent_spawn(
        segment_index: int,
        slot_index: int,
        record: Any,
        membership: Any | None = None,
    ) -> None:
        if slot_index != 0:
            raise RuntimeError(
                "one chop proposal expanded into multiple launch slots; "
                "proposal fan-out is not supported by the batch journal"
            )
        member_index = (
            segment_index
            if any(plan.clan is not None for plan in plans)
            else active_single_member
        )
        if member_index is None or not 0 <= member_index < len(plans):
            raise RuntimeError(f"invalid chop launch source slot {segment_index}")
        result = getattr(record, "result", None)
        if result is None:
            return
        _journal_launch(
            member_index,
            plans[member_index],
            result,
            request=getattr(record, "request", None),
            membership=membership,
        )

    def _pause_batch() -> None:
        nonlocal paused
        if paused:
            return
        paused = True
        _batch_event("request_pause", reason="cooperative stop requested")

    def _progress_kwargs() -> dict[str, Any]:
        return {
            "before_agent_spawn": _before_agent_spawn,
            "on_agent_plan_prepared": _plan_prepared,
            "on_agent_launch_recorded": _record_agent_spawn,
            "pause_requested_fn": pause_requested_fn,
            "on_launch_paused": _pause_batch,
        }

    def _fallback_record(
        member_index: int,
        result: Any,
    ) -> dict[str, Any]:
        return _journal_launch(
            member_index,
            plans[member_index],
            result,
        )

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
                    proposal_index=plan.proposal.index,
                    proposal_id=plan.proposal.proposal_id,
                )
            )
            segment_env.append(extra_env)
        query = _query_for_plans(plans)
        try:
            results = list(
                _call_with_supported_kwargs(
                    launch_agents_from_cwd_fn,
                    query,
                    segment_extra_env=segment_env,
                    origin="generated",
                    **_progress_kwargs(),
                )
            )
        except Exception as exc:
            partial_results = list(getattr(exc, "results", ()) or ())
            if partial_results and not launches_by_member:
                for member_index, result in enumerate(partial_results[: len(plans)]):
                    _fallback_record(member_index, result)
            raise
        if paused:
            batch_launches = [
                launches_by_member[index]
                for index in range(len(plans))
                if index in launches_by_member
            ]
            return ChopProposalLaunches(
                batch_launches,
                paused=True,
                batch_id=batch_id,
            )
        if len(results) != len(plans):
            raise RuntimeError(
                "clan proposal batch returned "
                f"{len(results)} launch result(s) for {len(plans)} proposal(s)"
            )
        for member_index, result in enumerate(results):
            if member_index not in launches_by_member:
                _fallback_record(member_index, result)
        batch_launches = [
            launches_by_member[index]
            for index in range(len(plans))
            if index in launches_by_member
        ]
        return ChopProposalLaunches(batch_launches, paused=paused, batch_id=batch_id)

    from sase.agent.launch_validation import AgentNameLaunchCollisionError

    for member_index, plan in enumerate(plans):
        if pause_requested_fn is not None and pause_requested_fn():
            _pause_batch()
            break
        active_single_member = member_index
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
                **_progress_kwargs(),
            )
        except AgentNameLaunchCollisionError as exc:
            if not proposal.explicit_agent_name:
                raise
            skipped_indices.add(proposal.index)
            _batch_event(
                "record_skip",
                member_index=member_index,
                reason=f"explicit agent name collision: {exc}",
            )
            reason = f"explicit agent name collision: {exc} Proposal skipped."
            if proposal_skipped_fn is not None:
                proposal_skipped_fn(proposal, reason, effective_wait)
            continue
        except Exception:
            if paused:
                break
            raise
        if result is None and paused:
            break
        launch = launches_by_member.get(member_index)
        if launch is None:
            launch = _fallback_record(member_index, result)
        names_by_index[proposal.index] = str(launch["agent_name"])
        if proposal.proposal_id is not None:
            names_by_id[proposal.proposal_id] = str(launch["agent_name"])
    launches = [
        launches_by_member[index]
        for index in range(len(plans))
        if index in launches_by_member
    ]
    return ChopProposalLaunches(launches, paused=paused, batch_id=batch_id)


__all__ = ["launch_chop_proposals"]
