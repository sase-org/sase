"""Multi-prompt sequential launch orchestration.

When a prompt splits into multiple segments (via ``---`` separators),
launch each segment as a separate agent. Bare ``%wait`` in segment N+1 is
rewritten to the planned name of agent N when that name is knowable; otherwise
the launcher falls back to the legacy naming poll.
"""

from collections.abc import Callable

from sase.agent.launcher import AgentLaunchResult
from sase.agent.multi_prompt_references import (
    _PLANNED_AGENT_NAME_ENV,
    PlannedNameAllocator as _PlannedNameAllocator,
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
from sase.core.agent_launch_facade import LaunchTimestampBatchAllocator
from sase.xprompt.models import XPrompt

__all__ = [
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
    default_bare_segments_to_home: bool = False,
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
            default_bare_segments_to_home=default_bare_segments_to_home,
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
    default_bare_segments_to_home: bool,
    timestamp_allocator: LaunchTimestampBatchAllocator,
    results: list[AgentLaunchResult],
) -> None:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.agent.launch_executor import (
        LaunchExecutionContext,
        execute_launch_plan,
    )
    from sase.core.agent_launch_facade import plan_fake_fanout
    from sase.artifacts import create_artifacts_directory
    from sase.xprompt.directives import (
        has_wait_directive,
        plan_prompt_fanout_variants,
    )
    from sase.xprompt._parsing import normalize_default_vcs_workflow_segment

    timer = LaunchTimingRecorder(
        "agent_launch_multi_prompt",
        {
            "segment_count": len(segments),
            "project_name": project_name,
            "home_mode": is_home_mode,
        },
    )
    name_allocator = _PlannedNameAllocator()
    previous_agent_name: str | None = None
    for i, segment in enumerate(segments):
        if default_bare_segments_to_home:
            with timer.stage("prompt_normalize", segment_index=i):
                segment = normalize_default_vcs_workflow_segment(segment)
        with timer.stage("wait_resume_rewrite", segment_index=i):
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
        with timer.stage("prompt_parse", segment_index=i):
            has_wait = has_wait_directive(segment)
            segment_local_xprompts = _local_xprompts_for_segment(
                segment, local_xprompts
            )
        next_segment_needs_name = i < len(segments) - 1 and (
            _has_bare_wait_directive(segments[i + 1])
            or _has_bare_resume_reference(segments[i + 1])
        )

        # Check for launch fan-out directives (e.g., %m(opus,sonnet) or %alt(a,b)).
        # Try the raw segment first; if no match and the segment contains
        # xprompt references, expand them and re-check.
        with timer.stage("fanout_plan", segment_index=i, fanout_kind="prompt"):
            fanout_plan = plan_prompt_fanout_variants(
                segment,
                extra_xprompts=segment_local_xprompts or None,
            )
        if fanout_plan is None and "#" in segment:
            from sase.xprompt.processor import process_xprompt_references

            with timer.stage("xprompt_expand", segment_index=i):
                expanded = process_xprompt_references(
                    segment,
                    extra_xprompts=segment_local_xprompts or None,
                )
                fanout_plan = plan_prompt_fanout_variants(
                    expanded,
                    extra_xprompts=segment_local_xprompts or None,
                )

        plan = (
            fanout_plan
            if fanout_plan is not None
            else plan_fake_fanout("multi_prompt", [segment])
        )

        slot_contexts: dict[int, LaunchExecutionContext] = {}
        slot_planned_env: dict[int, dict[str, str]] = {}
        slot_local_xprompts_files: dict[int, str | None] = {}
        planned_names: dict[int, str | None] = {}
        for slot in plan.slots:
            j = slot.slot_index
            sub_prompt = slot.prompt
            with timer.stage("name_plan", segment_index=i, slot_index=j):
                if next_segment_needs_name:
                    planned_name, planned_env_name = (
                        name_allocator.planned_name_for_prompt(sub_prompt)
                    )
                else:
                    planned_name, planned_env_name = None, None
                planned_names[j] = planned_name
                slot_planned_env[j] = (
                    {_PLANNED_AGENT_NAME_ENV: planned_env_name}
                    if planned_env_name is not None
                    else {}
                )

            # Each sub-prompt gets its own copy of the local xprompts file
            # (the agent runner deletes it after reading).
            with timer.stage("local_xprompts_serialize", segment_index=i, slot_index=j):
                slot_local_xprompts_files[j] = (
                    _serialize_local_xprompts(segment_local_xprompts)
                    if segment_local_xprompts
                    else None
                )

            with timer.stage("vcs_resolution", segment_index=i, slot_index=j):
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
                    use_preallocated_workspace=segment_ctx.workspace_dir is not None,
                )

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

            execution = execute_launch_plan(
                plan,
                slot_contexts[0],
                slot_context=_slot_context,
                slot_extra_env=_slot_extra_env,
                slot_local_xprompts_file=_slot_local_xprompts_file,
                extra_env=extra_env,
                timestamp_allocator=timestamp_allocator,
                on_slot_executed=(
                    None
                    if on_agent_spawned is None
                    else lambda _record: on_agent_spawned()
                ),
            )

        results.extend(execution.results)
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
