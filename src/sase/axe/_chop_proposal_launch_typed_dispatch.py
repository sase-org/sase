"""Typed-dispatch path for chop proposal launches."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from sase.core.agent_launch_wire import launch_plan_from_dict

from .chop_proposal_launch import ChopProposalLaunches
from .chop_proposal_models import PlannedChopProposal
from .chop_typed_admission import (
    AXE_CHOP_SOURCE_SURFACE,
    make_axe_chop_agent_dispatcher,
)
from ._chop_proposal_launch_shared import (
    ordinary_batch_manifest,
    query_for_plans,
)
from ._chop_proposal_launch_typed_metadata import (
    typed_admission_record,
    unit_dispatch_metadata,
    unit_dispatch_metadata_from_payload,
)


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


def _persist_typed_outer_batch(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    bundle_id: str,
    bundle_digest: str,
    run_started_at: datetime,
    preflight: Any,
    plans: Sequence[PlannedChopProposal],
    batch_created_fn: Callable[[str], None] | None,
) -> tuple[str, bool]:
    from . import chop_batch_store

    manifest = ordinary_batch_manifest(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        run_id=run_id,
        run_started_at=run_started_at.isoformat(),
        preflight=preflight,
        plans=plans,
    )
    manifest["typed_bundle"] = {
        "bundle_id": bundle_id,
        "bundle_digest": bundle_digest,
    }
    ownership_acquired = False
    try:
        chop_batch_store.create_chop_batch(
            lumberjack_name,
            chop_name,
            manifest,
            owner="typed-admission-first-run",
        )
        ownership_acquired = True
    except chop_batch_store.ChopBatchExistsError as exc:
        existing = chop_batch_store.load_chop_batch(lumberjack_name, chop_name, run_id)
        if existing.get("typed_bundle") != manifest["typed_bundle"]:
            from sase.agent.launch_request_types import LaunchRequestError

            raise LaunchRequestError(
                "invalid_request",
                run_id,
                "an existing chop batch refers to a different typed bundle",
            ) from exc
    if batch_created_fn is not None:
        try:
            batch_created_fn(run_id)
        except BaseException:
            if ownership_acquired:
                chop_batch_store.release_chop_batch_ownership(
                    lumberjack_name, chop_name, run_id
                )
            raise
    return run_id, ownership_acquired


def maybe_dispatch_typed_chop_proposals(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    plans: Sequence[PlannedChopProposal],
    launch_agents_from_cwd_fn: Callable[..., Any] | None,
    launch_recorded_fn: Callable[[dict[str, Any]], None] | None,
    run_started_at: datetime | None,
    preflight: Any | None,
    batch_created_fn: Callable[[str], None] | None,
    pause_requested_fn: Callable[[], bool] | None,
) -> ChopProposalLaunches | None:
    from . import chop_batch_store
    from .chop_typed_admission import resume_typed_chop_batch

    durable_batch = run_started_at is not None and preflight is not None
    bundle_id = f"axe-chop-{run_id}"
    if durable_batch:
        assert run_started_at is not None and preflight is not None
        try:
            existing = chop_batch_store.load_chop_batch(
                lumberjack_name, chop_name, run_id
            )
        except chop_batch_store.ChopBatchNotFoundError:
            existing = None
        if existing is not None:
            if existing.get("typed_bundle") is None:
                from sase.agent.launch_request_types import LaunchRequestError

                raise LaunchRequestError(
                    "invalid_request",
                    run_id,
                    "the chop run already has a non-typed batch manifest",
                )
            resumed = resume_typed_chop_batch(
                lumberjack_name,
                chop_name,
                run_id,
                launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
                launch_recorded_fn=launch_recorded_fn,
                pause_requested_fn=pause_requested_fn,
            )
            return ChopProposalLaunches(
                resumed.launches,
                typed_admission=resumed.typed_admission,
                admission_result=resumed.admission_result,
                paused=resumed.paused,
                batch_id=run_id,
            )

        from sase.agent.direct_typed_launch import typed_launch_bundle_dir
        from sase.agent.launch_admission_request_data import typed_plan_from_request
        from sase.agent.launch_request_response import read_launch_request
        from sase.notification_gates.paths import REQUEST_FILENAME

        bundle_dir = typed_launch_bundle_dir(bundle_id)
        if (bundle_dir / REQUEST_FILENAME).is_file():
            payload = read_launch_request(bundle_dir)
            typed_plan = typed_plan_from_request(payload)
            if (
                str(payload.get("request_id") or "") != bundle_id
                or str(payload.get("source_surface") or "") != AXE_CHOP_SOURCE_SURFACE
            ):
                from sase.agent.launch_request_types import LaunchRequestError

                raise LaunchRequestError(
                    "invalid_request",
                    str(bundle_dir),
                    "an existing typed bundle does not belong to this chop run",
                )
            metadata = unit_dispatch_metadata_from_payload(payload)
            expected_metadata = unit_dispatch_metadata(
                typed_plan=typed_plan,
                plans=plans,
                lumberjack_name=lumberjack_name,
                chop_name=chop_name,
                run_id=run_id,
            )
            if metadata != expected_metadata:
                from sase.agent.launch_request_types import LaunchRequestError

                raise LaunchRequestError(
                    "invalid_request",
                    str(bundle_dir),
                    "an interrupted typed bundle has different chop dispatch metadata",
                )
            recovered_batch_id, ownership_acquired = _persist_typed_outer_batch(
                lumberjack_name=lumberjack_name,
                chop_name=chop_name,
                run_id=run_id,
                bundle_id=bundle_id,
                bundle_digest=typed_plan.content_digest,
                run_started_at=run_started_at,
                preflight=preflight,
                plans=plans,
                batch_created_fn=batch_created_fn,
            )
            try:
                resumed = resume_typed_chop_batch(
                    lumberjack_name,
                    chop_name,
                    recovered_batch_id,
                    launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
                    launch_recorded_fn=launch_recorded_fn,
                    pause_requested_fn=pause_requested_fn,
                    ownership_acquired=ownership_acquired,
                )
            finally:
                if ownership_acquired:
                    chop_batch_store.release_chop_batch_ownership(
                        lumberjack_name, chop_name, recovered_batch_id
                    )
            return ChopProposalLaunches(
                resumed.launches,
                typed_admission=resumed.typed_admission,
                admission_result=resumed.admission_result,
                paused=resumed.paused,
                batch_id=recovered_batch_id,
            )

    from sase.agent.direct_typed_launch import write_typed_launch_bundle
    from sase.agent.launch_admission import dispatch_typed_launch_request
    from sase.agent.launch_request_planning import (
        expand_prompt_for_typed_launch,
        prepare_typed_launch_plan,
    )
    from sase.agent.launch_request_types import LaunchRequestError
    from sase.macro.directives import DirectiveError, has_typed_launch_directive

    query = query_for_plans(plans)
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
    planned_metadata = unit_dispatch_metadata(
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
        unit_dispatch_metadata=planned_metadata,
        request_id=bundle_id,
    )
    typed_plan = launch_plan_from_dict(payload.get("typed_plan") or {})
    metadata = unit_dispatch_metadata_from_payload(payload)
    if metadata != planned_metadata:
        raise LaunchRequestError(
            "invalid_request",
            str(bundle_dir),
            "an existing typed launch bundle has different chop dispatch metadata",
        )
    typed_admission = typed_admission_record(
        bundle_dir=bundle_dir,
        payload=payload,
        typed_plan=typed_plan,
        metadata=metadata,
    )

    if durable_batch:
        assert run_started_at is not None and preflight is not None
        batch_id, ownership_acquired = _persist_typed_outer_batch(
            lumberjack_name=lumberjack_name,
            chop_name=chop_name,
            run_id=run_id,
            bundle_id=bundle_id,
            bundle_digest=typed_plan.content_digest,
            run_started_at=run_started_at,
            preflight=preflight,
            plans=plans,
            batch_created_fn=batch_created_fn,
        )
        try:
            resumed = resume_typed_chop_batch(
                lumberjack_name,
                chop_name,
                batch_id,
                launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
                launch_recorded_fn=launch_recorded_fn,
                pause_requested_fn=pause_requested_fn,
                ownership_acquired=ownership_acquired,
            )
        finally:
            if ownership_acquired:
                chop_batch_store.release_chop_batch_ownership(
                    lumberjack_name, chop_name, batch_id
                )
        return ChopProposalLaunches(
            resumed.launches,
            typed_admission=resumed.typed_admission,
            admission_result=resumed.admission_result,
            paused=resumed.paused,
            batch_id=batch_id,
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
        pause_requested=pause_requested_fn,
    )
    return ChopProposalLaunches(
        recorded,
        typed_admission=typed_admission,
        admission_result=result,
        paused=bool(result.paused),
    )


__all__ = ["maybe_dispatch_typed_chop_proposals"]
