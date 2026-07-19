"""Execution of preflighted multi-prompt agent launch segments."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from sase.agent.clan_membership import CLAN_MEMBERSHIP_ENV
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.multi_prompt_launch_plan import (
    assign_missing_slot_timestamps,
    empty_clan_prepass,
    future_agent_artifacts_dir,
    plan_segment_fanout,
    prepare_clan_launches,
)
from sase.agent.multi_prompt_references import (
    _GENERATED_AGENT_NAME_ENV,
    _PLANNED_AGENT_NAME_ENV,
    PlannedNameAllocator,
    extract_static_name_directive,
    has_bare_resume_reference,
    has_bare_wait_directive,
    rewrite_bare_resume_references,
    rewrite_bare_wait_directives,
)
from sase.agent.multi_prompt_vcs import resolve_segment_vcs_context
from sase.agent.multi_prompt_xprompts import (
    local_xprompts_for_segment,
    serialize_local_xprompts,
)
from sase.agent.output_variable_context import (
    SASE_AGENT_VAR_UPSTREAMS_ENV,
    build_agent_var_upstream_record,
    encode_agent_var_upstreams,
)
from sase.core.agent_launch_facade import LaunchTimestampBatchAllocator
from sase.core.agent_launch_wire import LaunchFanoutPlanWire
from sase.history.multi_agent_prompt import (
    MULTI_AGENT_PROMPT_FILE_ENV,
    save_multi_agent_prompt_file,
)
from sase.xprompt.models import XPrompt


def spawn_segments_into(
    *,
    segments: list[str],
    local_xprompts: dict[str, XPrompt],
    cl_name: str,
    project_file: str,
    project_name: str,
    is_home_mode: bool,
    vcs_ref: tuple[str, str] | None,
    on_agent_spawned: Callable[[], None] | None,
    extra_env: dict[str, str] | None,
    segment_extra_env: Sequence[dict[str, str] | None] | None,
    segment_template_groups: Sequence[str | None] | None,
    preplanned_fanout_plans: Sequence[LaunchFanoutPlanWire | None] | None,
    allow_reserved_family_separator_names: bool,
    default_bare_segments_to_home: bool,
    multi_agent_prompt_text: str | None,
    timestamp_allocator: LaunchTimestampBatchAllocator,
    results: list[AgentLaunchResult],
    wait_for_agent_naming: Callable[[str], str | None],
) -> None:
    from sase.agent.launch_executor import (
        LaunchExecutionContext,
        LaunchExecutionRecord,
        execute_launch_plan,
    )
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.artifacts import create_artifacts_directory
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.xprompt._parsing import normalize_default_vcs_workflow_segment
    from sase.xprompt.directives import has_deferred_start_directive

    timer = LaunchTimingRecorder(
        "agent_launch_multi_prompt",
        {
            "segment_count": len(segments),
            "project_name": project_name,
            "home_mode": is_home_mode,
        },
    )
    if segment_extra_env is not None and len(segment_extra_env) != len(segments):
        raise ValueError(
            "segment_extra_env must have one entry per multi-prompt segment"
        )
    if preplanned_fanout_plans is not None and len(preplanned_fanout_plans) != len(
        segments
    ):
        raise ValueError(
            "preplanned_fanout_plans must have one entry per multi-prompt segment"
        )
    if segment_template_groups is not None and len(segment_template_groups) != len(
        segments
    ):
        raise ValueError(
            "segment_template_groups must have one entry per multi-prompt segment"
        )
    name_allocator = PlannedNameAllocator()
    clan_prepass = empty_clan_prepass()
    try:
        clan_prepass = prepare_clan_launches(
            segments=segments,
            local_xprompts=local_xprompts,
            cl_name=cl_name,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=is_home_mode,
            vcs_ref=vcs_ref,
            segment_template_groups=segment_template_groups,
            preplanned_fanout_plans=preplanned_fanout_plans,
            default_bare_segments_to_home=default_bare_segments_to_home,
            timestamp_allocator=timestamp_allocator,
            name_allocator=name_allocator,
        )
        from sase.agent.launch_validation import validate_launch_name_requests

        validate_launch_name_requests(
            segments,
            allow_reserved_family_separator_names=(
                allow_reserved_family_separator_names
            ),
        )
    except Exception:
        clan_prepass.release_uncommitted_clan_reservations()
        name_allocator.release_uncommitted_template_reservations()
        raise
    previous_agent_name: str | None = None
    upstreams: list[dict[str, Any]] = []
    pending_family_parents: list[Any] = []
    multi_agent_prompt_file: str | None = None
    for i, segment in enumerate(segments):
        segment = canonicalize_project_aliases_in_prompt(segment)
        segment_template_group = (
            None if segment_template_groups is None else segment_template_groups[i]
        )
        segment_env = (
            dict(segment_extra_env[i] or {}) if segment_extra_env is not None else {}
        )
        upstreams_json = encode_agent_var_upstreams(upstreams) if upstreams else None
        if default_bare_segments_to_home:
            with timer.stage("prompt_normalize", segment_index=i):
                segment = normalize_default_vcs_workflow_segment(segment)
        with timer.stage("wait_resume_rewrite", segment_index=i):
            segment = name_allocator.rewrite_template_references(segment)
            segment_has_bare_wait = has_bare_wait_directive(segment)
            segment_has_bare_resume = has_bare_resume_reference(segment)
            if previous_agent_name:
                if segment_has_bare_wait:
                    segment = rewrite_bare_wait_directives(segment, previous_agent_name)
                if segment_has_bare_resume:
                    segment = rewrite_bare_resume_references(
                        segment, previous_agent_name
                    )
        segment_explicit_name = extract_static_name_directive(segment)
        with timer.stage("prompt_parse", segment_index=i):
            has_wait = has_deferred_start_directive(segment)
            segment_local_xprompts = local_xprompts_for_segment(segment, local_xprompts)
        next_segment_needs_name = i < len(segments) - 1 and (
            has_bare_wait_directive(segments[i + 1])
            or has_bare_resume_reference(segments[i + 1])
        )

        # Check for launch fan-out directives (e.g.,
        # %{%m:opus | %m:sonnet}, %alt(a,b), or %{a | b}).
        # Try the raw segment first; if no match and the segment contains
        # xprompt references, expand them and re-check.
        preplanned_fanout_plan = (
            None if preplanned_fanout_plans is None else preplanned_fanout_plans[i]
        )
        with timer.stage("fanout_plan", segment_index=i, fanout_kind="prompt"):
            prepass_plan = clan_prepass.plans_by_segment.get(i)
            if prepass_plan is not None:
                plan = prepass_plan
                is_fanout = len(plan.slots) > 1
            else:
                plan, is_fanout = plan_segment_fanout(
                    segment,
                    segment_local_xprompts=segment_local_xprompts,
                    preplanned_fanout_plan=preplanned_fanout_plan,
                )
        plan = assign_missing_slot_timestamps(plan, timestamp_allocator)
        if (
            multi_agent_prompt_text is not None
            and multi_agent_prompt_file is None
            and plan.slots
        ):
            assert plan.slots[0].timestamp is not None
            multi_agent_prompt_file = save_multi_agent_prompt_file(
                multi_agent_prompt_text,
                cl_name=cl_name,
                timestamp=plan.slots[0].timestamp,
            )

        slot_contexts: dict[int, LaunchExecutionContext] = {}
        slot_artifacts_dirs: dict[int, Path] = {}
        slot_planned_env: dict[int, dict[str, str]] = {}
        slot_local_xprompts_files: dict[int, str | None] = {}
        planned_names: dict[int, str | None] = {}
        planned_env_names: dict[int, str | None] = {}
        for slot in plan.slots:
            key = (i, slot.slot_index)
            if key in clan_prepass.planned_names_by_slot:
                planned_names[slot.slot_index] = clan_prepass.planned_names_by_slot[key]
                planned_env_names[slot.slot_index] = (
                    clan_prepass.planned_env_names_by_slot[key]
                )
        explicit_templates: dict[int, str | None] = {}
        try:
            for slot in plan.slots:
                j = slot.slot_index
                sub_prompt = slot.prompt
                assert slot.timestamp is not None
                with timer.stage("vcs_resolution", segment_index=i, slot_index=j):
                    segment_ctx = clan_prepass.contexts_by_slot.get((i, j))
                    if segment_ctx is None:
                        segment_ctx = resolve_segment_vcs_context(
                            prompt=sub_prompt,
                            fallback_cl_name=cl_name,
                            fallback_project_file=project_file,
                            fallback_project_name=project_name,
                            fallback_is_home_mode=is_home_mode,
                            fallback_vcs_ref=vcs_ref,
                            has_wait=has_wait,
                        )
                    slot_contexts[j] = LaunchExecutionContext(
                        cl_name=segment_ctx.cl_name,
                        project_file=segment_ctx.project_file,
                        update_target=segment_ctx.update_target,
                        project_name=segment_ctx.project_name,
                        history_sort_key=segment_ctx.history_sort_key,
                        is_home_mode=segment_ctx.is_home_mode,
                        vcs_ref=segment_ctx.vcs_ref,
                        deferred_workspace=has_wait,
                        workspace_num=segment_ctx.workspace_num,
                        workspace_dir=segment_ctx.workspace_dir,
                        use_preallocated_workspace=False,
                    )
                    slot_artifacts_dirs[j] = future_agent_artifacts_dir(
                        project_name=segment_ctx.project_name,
                        timestamp=slot.timestamp,
                    )

                # Each sub-prompt gets its own copy of the local xprompts file
                # (the agent runner deletes it after reading).
                with timer.stage(
                    "local_xprompts_serialize", segment_index=i, slot_index=j
                ):
                    slot_local_xprompts_files[j] = (
                        serialize_local_xprompts(segment_local_xprompts)
                        if segment_local_xprompts
                        else None
                    )

                explicit_templates[j] = extract_static_name_directive(sub_prompt)

            from sase.agent.names import is_agent_name_template

            grouped_template_slots: list[tuple[int, str]] = []
            if is_fanout and len(plan.slots) > 1:
                for slot in plan.slots:
                    template = explicit_templates.get(slot.slot_index)
                    if template and is_agent_name_template(template):
                        grouped_template_slots.append((slot.slot_index, template))

            if len(grouped_template_slots) > 1:
                with timer.stage("name_plan", segment_index=i, slot_index=-1):
                    template_names = [
                        template for _, template in grouped_template_slots
                    ]
                    artifacts_dirs = [
                        slot_artifacts_dirs[slot_index]
                        for slot_index, _ in grouped_template_slots
                    ]
                    grouped_names = name_allocator.planned_names_for_template_group(
                        template_names,
                        artifacts_dirs=artifacts_dirs,
                        template_group=segment_template_group or f"fanout:{i}",
                    )
                for (slot_index, _), planned_name in zip(
                    grouped_template_slots,
                    grouped_names,
                    strict=True,
                ):
                    planned_names[slot_index] = planned_name
                    planned_env_names[slot_index] = planned_name

            for slot in plan.slots:
                j = slot.slot_index
                if j not in planned_names:
                    sub_prompt = slot.prompt
                    with timer.stage("name_plan", segment_index=i, slot_index=j):
                        slot_planned_name, slot_planned_env_name = (
                            name_allocator.planned_name_for_prompt(
                                sub_prompt,
                                artifacts_dir=slot_artifacts_dirs[j],
                                template_group=segment_template_group,
                            )
                        )
                    planned_names[j] = slot_planned_name
                    planned_env_names[j] = slot_planned_env_name

                # Inject SASE_AGENT_PLANNED_NAME whenever a planned name is
                # known so the launch result carries it synchronously and
                # template-originated names can use the parent allocation.
                slot_planned_name = planned_names[j]
                slot_planned_env_name = planned_env_names.get(j)
                env_name_to_inject = (
                    slot_planned_env_name
                    if slot_planned_env_name is not None
                    else slot_planned_name
                )
                slot_env = dict(segment_env)
                if upstreams_json is not None:
                    slot_env[SASE_AGENT_VAR_UPSTREAMS_ENV] = upstreams_json
                if env_name_to_inject is not None:
                    slot_env[_PLANNED_AGENT_NAME_ENV] = env_name_to_inject
                if slot.name_generated:
                    slot_env[_GENERATED_AGENT_NAME_ENV] = "1"
                if multi_agent_prompt_file is not None:
                    slot_env[MULTI_AGENT_PROMPT_FILE_ENV] = multi_agent_prompt_file
                clan_payload = clan_prepass.membership_env_by_segment.get(i)
                if clan_payload is not None:
                    slot_env[CLAN_MEMBERSHIP_ENV] = clan_payload
                slot_planned_env[j] = slot_env

            with timer.stage(
                "execute_launch_plan",
                segment_index=i,
                slot_count=len(plan.slots),
            ):

                def _slot_context(
                    slot: object,
                    _context: LaunchExecutionContext,
                    contexts: dict[int, LaunchExecutionContext] = slot_contexts,
                ) -> LaunchExecutionContext:
                    return contexts[slot.slot_index]  # type: ignore[attr-defined]

                def _slot_extra_env(
                    slot: object,
                    env_by_slot: dict[int, dict[str, str]] = slot_planned_env,
                ) -> dict[str, str]:
                    return env_by_slot[slot.slot_index]  # type: ignore[attr-defined]

                def _slot_local_xprompts_file(
                    slot: object,
                    files_by_slot: dict[int, str | None] = slot_local_xprompts_files,
                ) -> str | None:
                    return files_by_slot[slot.slot_index]  # type: ignore[attr-defined]

                def _on_slot_executed(
                    record: LaunchExecutionRecord,
                    planned_names_by_slot: dict[int, str | None] = planned_names,
                    artifact_dirs_by_slot: dict[int, Path] = slot_artifacts_dirs,
                    segment_index: int = i,
                ) -> None:
                    slot_index = record.slot.slot_index
                    name_allocator.mark_template_reservation_committed(
                        planned_names_by_slot.get(slot_index),
                        artifact_dirs_by_slot.get(slot_index),
                    )
                    membership = clan_prepass.membership_by_segment.get(segment_index)
                    if membership is not None:
                        from sase.agent.names import claim_registered_clan_name

                        claim_registered_clan_name(
                            membership.clan_name,
                            membership.generation,
                            artifact_dirs_by_slot[slot_index],
                        )
                    if on_agent_spawned is not None:
                        on_agent_spawned()

                execution = execute_launch_plan(
                    plan,
                    slot_contexts[0],
                    slot_context=_slot_context,
                    slot_extra_env=_slot_extra_env,
                    slot_local_xprompts_file=_slot_local_xprompts_file,
                    extra_env=extra_env,
                    timestamp_allocator=timestamp_allocator,
                    on_slot_executed=_on_slot_executed,
                    allow_reserved_family_separator_names=(
                        allow_reserved_family_separator_names
                    ),
                    pending_family_parents=pending_family_parents,
                )
        except Exception:
            clan_prepass.release_uncommitted_clan_reservations()
            name_allocator.release_uncommitted_template_reservations()
            raise

        results.extend(execution.results)
        for record in execution.records:
            record_planned_name = planned_names.get(record.slot.slot_index)
            explicit_template = explicit_templates.get(record.slot.slot_index)
            if (
                record_planned_name is None
                or explicit_template is None
                or segment_explicit_name is None
            ):
                continue
            from sase.agent.names import is_agent_name_template

            upstreams.append(
                build_agent_var_upstream_record(
                    agent_name=record_planned_name,
                    agent_name_template=(
                        explicit_template
                        if is_agent_name_template(explicit_template)
                        else None
                    ),
                    project_name=record.request.project_name,
                    workflow_timestamp=record.request.timestamp,
                )
            )
        last_record = execution.records[-1]
        last_timestamp = last_record.request.timestamp
        last_project_name = last_record.request.project_name
        last_planned_name = planned_names.get(last_record.slot.slot_index)

        previous_agent_name = last_planned_name
        # Fall back to the legacy naming poll only when the next segment has
        # a bare %wait and the previous agent name could not be planned.
        if next_segment_needs_name and previous_agent_name is None:
            assert last_timestamp is not None
            assert last_project_name is not None
            artifacts_dir = create_artifacts_directory(
                "ace-run",
                project_name=last_project_name,
                timestamp=last_timestamp,
            )
            # The artifacts dir is already created by the runner; we just
            # need the path to poll agent_meta.json.
            with timer.stage("multi_prompt_naming_wait", segment_index=i):
                agent_name = wait_for_agent_naming(artifacts_dir)
            if agent_name:
                previous_agent_name = agent_name
                print(f"  Agent {i + 1}/{len(segments)} named '{agent_name}'")
            else:
                print(f"  Agent {i + 1}/{len(segments)} naming timed out, continuing")
    timer.finish(outcome="ok", launched=len(results))
