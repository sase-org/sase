"""Multi-prompt sequential launch orchestration.

When a prompt splits into multiple segments (via ``---`` separators),
launch each segment as a separate agent. Bare ``%wait`` in segment N+1 is
rewritten to the planned name of agent N when that name is knowable; otherwise
the launcher falls back to the legacy naming poll.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sase.agent.family_membership import FAMILY_MEMBERSHIP_ENV
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.multi_prompt_references import (
    _GENERATED_AGENT_NAME_ENV,
    _PLANNED_AGENT_NAME_ENV,
    PlannedNameAllocator as _PlannedNameAllocator,
    StaticFamilyDirective as _StaticFamilyDirective,
    extract_static_family_directive as _extract_static_family_directive,
    extract_static_name_directive as _extract_static_name_directive,
    has_bare_resume_reference as _has_bare_resume_reference,
    has_bare_wait_directive as _has_bare_wait_directive,
    rewrite_bare_resume_references as _rewrite_bare_resume_references,
    rewrite_bare_wait_directives as _rewrite_bare_wait_directives,
    wait_for_agent_naming as _wait_for_agent_naming,
)
from sase.agent.multi_prompt_vcs import (
    SegmentVcsContext as _SegmentVcsContext,
    extract_vcs_ref as _extract_vcs_ref,
    resolve_segment_vcs_context as _resolve_segment_vcs_context,
)
from sase.agent.multi_prompt_xprompts import (
    deserialize_local_xprompts as deserialize_local_xprompts,
    extract_called_xprompt_names as _extract_called_xprompt_names,
    local_xprompts_for_segment as _local_xprompts_for_segment,
    serialize_local_xprompts as _serialize_local_xprompts,
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

__all__ = [
    "MultiPromptPartialLaunchError",
    "_MultiPromptPartialLaunchError",
    "_SegmentVcsContext",
    "_extract_called_xprompt_names",
    "_extract_static_name_directive",
    "_extract_vcs_ref",
    "_has_bare_resume_reference",
    "_has_bare_wait_directive",
    "_local_xprompts_for_segment",
    "_rewrite_bare_resume_references",
    "_rewrite_bare_wait_directives",
    "_serialize_local_xprompts",
    "_wait_for_agent_naming",
    "deserialize_local_xprompts",
    "launch_multi_prompt_agents",
]


class _MultiPromptPartialLaunchError(RuntimeError):
    """Raised when one segment of a multi-prompt launch fails after others succeeded.

    ``results`` holds the agents that were spawned before the failure, so
    callers can roll back (e.g. terminate the leaked PIDs).
    """

    def __init__(self, results: list[AgentLaunchResult], cause: BaseException) -> None:
        super().__init__(f"partial multi-prompt launch failed: {cause}")
        self.results = results
        self.cause = cause


MultiPromptPartialLaunchError = _MultiPromptPartialLaunchError


def _future_agent_artifacts_dir(*, project_name: str, timestamp: str) -> Path:
    from sase.artifacts import convert_timestamp_to_artifacts_format
    from sase.core.agent_artifact_paths import canonical_agent_artifact_path

    return canonical_agent_artifact_path(
        project_name,
        "ace-run",
        convert_timestamp_to_artifacts_format(timestamp),
    )


def _assign_missing_slot_timestamps(
    plan: LaunchFanoutPlanWire,
    timestamp_allocator: LaunchTimestampBatchAllocator,
) -> LaunchFanoutPlanWire:
    missing_count = sum(1 for slot in plan.slots if slot.timestamp is None)
    if missing_count == 0:
        return plan
    allocated = iter(timestamp_allocator.allocate(missing_count))
    return replace(
        plan,
        slots=[
            slot
            if slot.timestamp is not None
            else replace(slot, timestamp=next(allocated))
            for slot in plan.slots
        ],
    )


def _plan_segment_fanout(
    segment: str,
    *,
    segment_local_xprompts: dict[str, XPrompt],
    preplanned_fanout_plan: LaunchFanoutPlanWire | None,
) -> tuple[LaunchFanoutPlanWire, bool]:
    """Return one segment's launch plan and whether it is a real fan-out."""
    from sase.core.agent_launch_facade import plan_fake_fanout
    from sase.xprompt.directives import plan_prompt_fanout_variants

    fanout_plan = (
        preplanned_fanout_plan
        if preplanned_fanout_plan is not None
        else plan_prompt_fanout_variants(
            segment,
            extra_xprompts=segment_local_xprompts or None,
        )
    )
    if fanout_plan is None and preplanned_fanout_plan is None and "#" in segment:
        from sase.xprompt.processor import process_xprompt_references

        expanded = process_xprompt_references(
            segment,
            extra_xprompts=segment_local_xprompts or None,
        )
        fanout_plan = plan_prompt_fanout_variants(
            expanded,
            extra_xprompts=segment_local_xprompts or None,
        )
    if fanout_plan is not None:
        return fanout_plan, True
    return plan_fake_fanout("multi_prompt", [segment]), False


@dataclass
class _ParallelFamilyPrepass:
    """Launch values pinned before any parallel-family member can spawn."""

    root_timestamps: dict[int, str]
    root_contexts: dict[int, _SegmentVcsContext]
    root_planned_names: dict[int, tuple[str, str | None]]
    membership_env_by_segment: dict[int, str]


def _prepare_parallel_family_launches(
    *,
    segments: list[str],
    local_xprompts: dict[str, XPrompt],
    cl_name: str,
    project_file: str,
    project_name: str,
    is_home_mode: bool,
    vcs_ref: tuple[str, str] | None,
    segment_template_groups: Sequence[str | None] | None,
    preplanned_fanout_plans: Sequence[LaunchFanoutPlanWire | None] | None,
    default_bare_segments_to_home: bool,
    timestamp_allocator: LaunchTimestampBatchAllocator,
    name_allocator: _PlannedNameAllocator,
) -> _ParallelFamilyPrepass:
    """Resolve in-launch family roots before the first segment is spawned."""
    from sase.agent.family_membership import (
        FamilyMembershipPlan,
        encode_family_membership_plan,
    )
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.xprompt._exceptions import DirectiveError
    from sase.xprompt._parsing import normalize_default_vcs_workflow_segment
    from sase.xprompt.directives import has_deferred_start_directive

    directives: list[_StaticFamilyDirective | None] = [
        _extract_static_family_directive(segment) for segment in segments
    ]
    if not any(directive is not None for directive in directives):
        return _ParallelFamilyPrepass({}, {}, {}, {})

    names = [_extract_static_name_directive(segment) for segment in segments]
    members_by_target: dict[str, list[int]] = {}
    for index, directive in enumerate(directives):
        if directive is None:
            continue
        if names[index] == directive.target:
            raise DirectiveError(
                f"Multi-prompt segment {index + 1} cannot target itself with "
                f"%family:{directive.target}"
            )
        members_by_target.setdefault(directive.target, []).append(index)

    root_timestamps: dict[int, str] = {}
    root_contexts: dict[int, _SegmentVcsContext] = {}
    root_planned_names: dict[int, tuple[str, str | None]] = {}
    membership_env_by_segment: dict[int, str] = {}

    def set_membership(index: int, payload: str) -> None:
        if index in membership_env_by_segment:
            raise DirectiveError(
                f"Multi-prompt segment {index + 1} belongs to more than one "
                "parallel family"
            )
        membership_env_by_segment[index] = payload

    for target, member_indexes in members_by_target.items():
        root_indexes = [index for index, name in enumerate(names) if name == target]
        if len(root_indexes) > 1:
            raise DirectiveError(
                f"%family target '{target}' matches more than one sibling root segment"
            )
        if not root_indexes:
            # A directive-only launch or retry resolves the root in the runner.
            continue

        root_index = root_indexes[0]
        root_segment = canonicalize_project_aliases_in_prompt(segments[root_index])
        if default_bare_segments_to_home:
            root_segment = normalize_default_vcs_workflow_segment(root_segment)
        root_local_xprompts = _local_xprompts_for_segment(
            root_segment,
            local_xprompts,
        )
        preplanned = (
            None
            if preplanned_fanout_plans is None
            else preplanned_fanout_plans[root_index]
        )
        root_plan, _ = _plan_segment_fanout(
            root_segment,
            segment_local_xprompts=root_local_xprompts,
            preplanned_fanout_plan=preplanned,
        )
        root_plan = _assign_missing_slot_timestamps(root_plan, timestamp_allocator)
        if len(root_plan.slots) != 1:
            raise DirectiveError(
                f"%family root segment for '{target}' must resolve to exactly "
                "one launch slot"
            )
        root_slot = root_plan.slots[0]
        assert root_slot.timestamp is not None
        root_timestamp = root_slot.timestamp
        has_wait = has_deferred_start_directive(root_segment)
        root_context = _resolve_segment_vcs_context(
            prompt=root_slot.prompt,
            fallback_cl_name=cl_name,
            fallback_project_file=project_file,
            fallback_project_name=project_name,
            fallback_is_home_mode=is_home_mode,
            fallback_vcs_ref=vcs_ref,
            has_wait=has_wait,
        )
        root_artifacts_dir = _future_agent_artifacts_dir(
            project_name=root_context.project_name,
            timestamp=root_timestamp,
        )
        template_group = (
            None
            if segment_template_groups is None
            else segment_template_groups[root_index]
        )
        root_name, root_env_name = name_allocator.planned_name_for_prompt(
            root_slot.prompt,
            artifacts_dir=root_artifacts_dir,
            template_group=template_group,
        )
        if root_name is None:
            raise DirectiveError(
                f"%family root segment for '{target}' has no plannable %name"
            )

        from sase.artifacts import convert_timestamp_to_artifacts_format

        root_identity_timestamp = convert_timestamp_to_artifacts_format(root_timestamp)
        root_payload = encode_family_membership_plan(
            FamilyMembershipPlan(
                family_base=root_name,
                root_timestamp=root_identity_timestamp,
                root_artifacts_dir=str(root_artifacts_dir),
                root_project_name=root_context.project_name,
                role="root",
                is_root=True,
            )
        )
        set_membership(root_index, root_payload)
        for member_index in member_indexes:
            directive = directives[member_index]
            assert directive is not None
            member_payload = encode_family_membership_plan(
                FamilyMembershipPlan(
                    family_base=root_name,
                    root_timestamp=root_identity_timestamp,
                    root_artifacts_dir=str(root_artifacts_dir),
                    root_project_name=root_context.project_name,
                    role=directive.role,
                    is_root=False,
                )
            )
            set_membership(member_index, member_payload)

        root_timestamps[root_index] = root_timestamp
        root_contexts[root_index] = root_context
        root_planned_names[root_index] = (root_name, root_env_name)

    return _ParallelFamilyPrepass(
        root_timestamps=root_timestamps,
        root_contexts=root_contexts,
        root_planned_names=root_planned_names,
        membership_env_by_segment=membership_env_by_segment,
    )


def launch_multi_prompt_agents(
    *,
    segments: list[str],
    local_xprompts: dict[str, XPrompt],
    cl_name: str,
    project_file: str,
    project_name: str,
    is_home_mode: bool,
    vcs_ref: tuple[str, str] | None,
    on_agent_spawned: Callable[[], None] | None = None,
    extra_env: dict[str, str] | None = None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
    segment_template_groups: Sequence[str | None] | None = None,
    preplanned_fanout_plans: Sequence[LaunchFanoutPlanWire | None] | None = None,
    allow_reserved_family_separator_names: bool = False,
    allow_hyphenated_names: bool | None = None,
    default_bare_segments_to_home: bool = False,
    multi_agent_prompt_text: str | None = None,
) -> list[AgentLaunchResult]:
    """Launch each segment as a separate agent.

    For each segment:
    1. Serialize only segment-referenced local xprompts (if any) to a temp JSON file.
    2. Allocate a workspace and timestamp.
    3. Spawn the agent subprocess.
    4. Poll for the predecessor name only when a following bare ``%wait`` cannot
       be rewritten from the launch plan.

    Returns a list of ``AgentLaunchResult`` for all launched agents.

    On partial failure (one segment raises after others succeeded), raises
    :class:`_MultiPromptPartialLaunchError` with the already-spawned results
    so callers can roll back.
    """
    if allow_hyphenated_names is not None:
        allow_reserved_family_separator_names = allow_hyphenated_names

    results: list[AgentLaunchResult] = []
    timestamp_allocator = LaunchTimestampBatchAllocator()

    try:
        _spawn_segments_into(
            segments=segments,
            local_xprompts=local_xprompts,
            cl_name=cl_name,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=is_home_mode,
            vcs_ref=vcs_ref,
            on_agent_spawned=on_agent_spawned,
            extra_env=extra_env,
            segment_extra_env=segment_extra_env,
            segment_template_groups=segment_template_groups,
            preplanned_fanout_plans=preplanned_fanout_plans,
            allow_reserved_family_separator_names=allow_reserved_family_separator_names,
            default_bare_segments_to_home=default_bare_segments_to_home,
            multi_agent_prompt_text=multi_agent_prompt_text,
            timestamp_allocator=timestamp_allocator,
            results=results,
        )
    except Exception as exc:
        if results:
            raise _MultiPromptPartialLaunchError(results, exc) from exc
        raise
    return results


def _spawn_segments_into(
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
) -> None:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.agent.launch_executor import (
        LaunchExecutionContext,
        LaunchExecutionRecord,
        execute_launch_plan,
    )
    from sase.artifacts import create_artifacts_directory
    from sase.xprompt.directives import has_deferred_start_directive
    from sase.xprompt._parsing import normalize_default_vcs_workflow_segment
    from sase.project_aliases import canonicalize_project_aliases_in_prompt

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
    name_allocator = _PlannedNameAllocator()
    try:
        family_prepass = _prepare_parallel_family_launches(
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
            segment_has_bare_wait = _has_bare_wait_directive(segment)
            segment_has_bare_resume = _has_bare_resume_reference(segment)
            if previous_agent_name:
                if segment_has_bare_wait:
                    segment = _rewrite_bare_wait_directives(
                        segment, previous_agent_name
                    )
                if segment_has_bare_resume:
                    segment = _rewrite_bare_resume_references(
                        segment, previous_agent_name
                    )
        segment_explicit_name = _extract_static_name_directive(segment)
        with timer.stage("prompt_parse", segment_index=i):
            has_wait = has_deferred_start_directive(segment)
            segment_local_xprompts = _local_xprompts_for_segment(
                segment, local_xprompts
            )
        next_segment_needs_name = i < len(segments) - 1 and (
            _has_bare_wait_directive(segments[i + 1])
            or _has_bare_resume_reference(segments[i + 1])
        )

        # Check for launch fan-out directives (e.g.,
        # %{%m:opus | %m:sonnet}, %alt(a,b), or %{a | b}).
        # Try the raw segment first; if no match and the segment contains
        # xprompt references, expand them and re-check.
        preplanned_fanout_plan = (
            None if preplanned_fanout_plans is None else preplanned_fanout_plans[i]
        )
        with timer.stage("fanout_plan", segment_index=i, fanout_kind="prompt"):
            plan, is_fanout = _plan_segment_fanout(
                segment,
                segment_local_xprompts=segment_local_xprompts,
                preplanned_fanout_plan=preplanned_fanout_plan,
            )
        root_timestamp = family_prepass.root_timestamps.get(i)
        if root_timestamp is not None:
            if len(plan.slots) != 1:
                from sase.xprompt._exceptions import DirectiveError

                raise DirectiveError(
                    "Parallel-family root segment changed to a multi-slot fan-out "
                    "after launch pre-planning"
                )
            plan = replace(
                plan,
                slots=[replace(plan.slots[0], timestamp=root_timestamp)],
            )
        plan = _assign_missing_slot_timestamps(plan, timestamp_allocator)
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
        pinned_root_name = family_prepass.root_planned_names.get(i)
        if pinned_root_name is not None:
            planned_names[0], planned_env_names[0] = pinned_root_name
        explicit_templates: dict[int, str | None] = {}
        try:
            for slot in plan.slots:
                j = slot.slot_index
                sub_prompt = slot.prompt
                assert slot.timestamp is not None
                with timer.stage("vcs_resolution", segment_index=i, slot_index=j):
                    segment_ctx = family_prepass.root_contexts.get(i)
                    if segment_ctx is None or j != 0:
                        segment_ctx = _resolve_segment_vcs_context(
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
                    slot_artifacts_dirs[j] = _future_agent_artifacts_dir(
                        project_name=segment_ctx.project_name,
                        timestamp=slot.timestamp,
                    )

                # Each sub-prompt gets its own copy of the local xprompts file
                # (the agent runner deletes it after reading).
                with timer.stage(
                    "local_xprompts_serialize", segment_index=i, slot_index=j
                ):
                    slot_local_xprompts_files[j] = (
                        _serialize_local_xprompts(segment_local_xprompts)
                        if segment_local_xprompts
                        else None
                    )

                explicit_templates[j] = _extract_static_name_directive(sub_prompt)

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
                family_payload = family_prepass.membership_env_by_segment.get(i)
                if family_payload is not None:
                    slot_env[FAMILY_MEMBERSHIP_ENV] = family_payload
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
                ) -> None:
                    slot_index = record.slot.slot_index
                    name_allocator.mark_template_reservation_committed(
                        planned_names_by_slot.get(slot_index),
                        artifact_dirs_by_slot.get(slot_index),
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
                    allow_reserved_family_separator_names=allow_reserved_family_separator_names,
                    pending_family_parents=pending_family_parents,
                )
        except Exception:
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
                agent_name = _wait_for_agent_naming(artifacts_dir)
            if agent_name:
                previous_agent_name = agent_name
                print(f"  Agent {i + 1}/{len(segments)} named '{agent_name}'")
            else:
                print(f"  Agent {i + 1}/{len(segments)} naming timed out, continuing")
    timer.finish(outcome="ok", launched=len(results))
