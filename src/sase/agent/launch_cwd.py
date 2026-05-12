"""High-level launch entry points that resolve context from the current CWD."""

import os
from collections.abc import Sequence
from dataclasses import dataclass

from sase.agent.launch_types import AgentLaunchResult


@dataclass(frozen=True)
class _KnownProjectVcsLaunchRef:
    workflow_type: str
    ref: str
    workspace_dir: str
    project_file: str


def resolve_known_project_vcs_launch_ref(
    prompt: str,
) -> _KnownProjectVcsLaunchRef | None:
    """Resolve a generic VCS ref that points at a known project checkout."""
    from pathlib import Path

    from sase.xprompt._parsing import extract_known_project_vcs_ref
    from sase.xprompt.loader import get_known_project_workspaces

    known_ref = extract_known_project_vcs_ref(prompt)
    if known_ref is None:
        return None

    workflow_type, ref = known_ref
    workspace_dir = get_known_project_workspaces().get(ref)
    if workspace_dir is None:
        return None

    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

    project_dir = Path.home() / ".sase" / "projects" / ref
    project_file = Path(preferred_project_spec_path(str(project_dir), ref))
    return _KnownProjectVcsLaunchRef(
        workflow_type=workflow_type,
        ref=ref,
        workspace_dir=str(workspace_dir),
        project_file=str(project_file),
    )


def launch_agents_from_cwd(
    query: str,
    extra_env: dict[str, str] | None = None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
    timestamp: str | None = None,
) -> list[AgentLaunchResult]:
    """Resolve project context from CWD and launch one or more background agents.

    This is the high-level entry point used by mobile launch surfaces that need
    every slot from multi-prompt, multi-model, alt, and repeat fan-out.

    For multi-prompt queries (containing ``---`` separators), all segments
    are launched sequentially.

    Args:
        query: The prompt/xprompt string to run as an agent.
        timestamp: Optional preallocated launch timestamp for fan-out callers.

    Returns:
        AgentLaunchResult records for every spawned slot.

    Raises:
        RuntimeError: If workspace allocation or claiming fails.
    """
    from sase.agent.names import ensure_historical_auto_name_migration

    ensure_historical_auto_name_migration()

    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        is_non_workspace_workflow,
        resolve_ref_from_prompt,
    )
    from sase.history.prompt import add_or_update_prompt
    from sase.main.utils import ensure_project_file_and_get_workspace_num
    from sase.running_field import get_workspace_directory
    from sase.workspace_provider import get_workflow_names

    # --- Resolve project context ---
    project_file, workspace_num, project_name = (
        ensure_project_file_and_get_workspace_num()
    )

    is_home_mode = project_file is None
    if is_home_mode:
        from sase.ace.changespec.project_spec_path import preferred_project_spec_path

        project_name = "home"
        home_dir = os.path.expanduser("~/.sase/projects/home")
        project_file = preferred_project_spec_path(home_dir, "home")

    assert project_file is not None
    assert project_name is not None

    # --- Multi-prompt detection ---
    from sase.agent.multi_agent_xprompt import expand_multi_agent_xprompts
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.xprompt._parsing import (
        normalize_default_vcs_workflow,
        normalize_default_vcs_workflow_segment,
    )

    multi = parse_multi_prompt(query)
    expanded_segment_extra_env: list[dict[str, str] | None] | None = None
    if segment_extra_env is not None:
        if len(segment_extra_env) != len(multi.segments):
            raise ValueError(
                "segment_extra_env must have one entry per multi-prompt segment"
            )
        expanded_segments = []
        expanded_segment_extra_env = []
        for segment, env in zip(multi.segments, segment_extra_env, strict=True):
            segment_expansions = expand_multi_agent_xprompts(
                [segment], multi.local_xprompts
            )
            expanded_segments.extend(segment_expansions)
            expanded_segment_extra_env.extend([env] * len(segment_expansions))
    else:
        expanded_segments = expand_multi_agent_xprompts(
            multi.segments, multi.local_xprompts
        )

    if not expanded_segments:
        return []

    if len(expanded_segments) > 1:
        from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

        expanded_segments = [
            normalize_default_vcs_workflow_segment(segment)
            for segment in expanded_segments
        ]
        normalized_query = "\n---\n".join(expanded_segments)

        # Determine cl_name from VCS refs (lightweight pattern check).
        from sase.workspace_provider import get_ref_patterns

        mp_cl_name = project_name
        mp_vcs_ref: tuple[str, str] | None = None
        for wf_name, pattern in get_ref_patterns().items():
            match = pattern.search(normalized_query)
            if match is not None:
                ref_value = match.group(1) or match.group(2)
                if ref_value:
                    mp_cl_name = ref_value
                    mp_vcs_ref = (wf_name, ref_value)
                    break

        try:
            from sase.agent.launch_validation import (
                AgentNameLaunchCollisionError,
                AgentNameReuseConfirmationRequiredError,
                validate_launch_name_requests,
            )

            validate_launch_name_requests(expanded_segments)
        except (
            AgentNameLaunchCollisionError,
            AgentNameReuseConfirmationRequiredError,
        ):
            add_or_update_prompt(
                normalized_query,
                project_name=project_name,
                branch_or_workspace=(
                    mp_cl_name if mp_cl_name != project_name else None
                ),
                cancelled=True,
            )
            raise

        add_or_update_prompt(
            normalized_query,
            project_name=project_name,
            branch_or_workspace=mp_cl_name if mp_cl_name != project_name else None,
        )
        results = launch_multi_prompt_agents(
            segments=expanded_segments,
            local_xprompts=multi.local_xprompts,
            cl_name=mp_cl_name,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=is_home_mode,
            vcs_ref=mp_vcs_ref,
            extra_env=extra_env,
            segment_extra_env=expanded_segment_extra_env,
            default_bare_segments_to_home=True,
        )
        return results

    query = normalize_default_vcs_workflow(expanded_segments[0])
    if expanded_segment_extra_env:
        segment_env = expanded_segment_extra_env[0] or {}
        extra_env = {**(extra_env or {}), **segment_env}

    # --- Repeat fan-out ---
    # When %r:N is present, spawn N independent agents before any further
    # dispatch.  Each spec's prompt has %r / %n stripped and %n:<base>.<k>
    # re-injected, so the recursive call resolves through the single-agent
    # path without re-triggering this branch.
    from sase.agent.repeat_launcher import (
        REPEAT_ITERATION_ENV,
        REPEAT_NAME_ENV,
        REPEAT_TOTAL_ENV,
        RepeatAgentSpec,
        extract_repeat_and_name,
        spawn_repeat_batch,
    )
    from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

    repeat_count, _, _ = extract_repeat_and_name(query)
    if repeat_count is not None and repeat_count > 1:
        slot_results: list[AgentLaunchResult] = []
        repeat_timestamps = reserve_launch_timestamp_batch(repeat_count)
        repeat_specs: list[RepeatAgentSpec] = []

        spawn_repeat_batch(
            query,
            base_spawn_fn=repeat_specs.append,
            timestamps=repeat_timestamps,
        )
        try:
            from sase.agent.launch_validation import validate_launch_name_requests

            validate_launch_name_requests([spec.prompt for spec in repeat_specs])
        except RuntimeError:
            add_or_update_prompt(query, project_name=project_name, cancelled=True)
            raise

        def _spawn_repeat_slot(spec: RepeatAgentSpec) -> None:
            assert spec.timestamp is not None
            slot_env = {
                REPEAT_NAME_ENV: spec.name,
                REPEAT_ITERATION_ENV: str(spec.iteration),
                REPEAT_TOTAL_ENV: str(spec.total),
            }
            if extra_env:
                slot_env.update(extra_env)
            slot_results.extend(
                launch_agents_from_cwd(
                    spec.prompt,
                    extra_env=slot_env,
                    timestamp=spec.timestamp,
                )
            )

        for spec in repeat_specs:
            _spawn_repeat_slot(spec)
        return slot_results

    # --- Alt-split detection ---
    from sase.xprompt.directives import plan_prompt_fanout_variants

    alt_plan = plan_prompt_fanout_variants(query)
    if alt_plan is None and "#" in query:
        from sase.xprompt.processor import (
            process_xprompt_references,
            prompt_may_reference_xprompt,
        )

        if prompt_may_reference_xprompt(query):
            expanded = process_xprompt_references(query)
            alt_plan = plan_prompt_fanout_variants(expanded)
    if alt_plan is not None:
        from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
        from sase.workspace_provider import get_ref_patterns

        alt_cl_name = project_name
        alt_vcs_ref: tuple[str, str] | None = None
        for wf_name, pattern in get_ref_patterns().items():
            match = pattern.search(query)
            if match is not None:
                ref_value = match.group(1) or match.group(2)
                if ref_value:
                    alt_cl_name = ref_value
                    alt_vcs_ref = (wf_name, ref_value)
                    break

        try:
            from sase.agent.launch_validation import validate_launch_name_requests

            validate_launch_name_requests([slot.prompt for slot in alt_plan.slots])
        except RuntimeError:
            add_or_update_prompt(
                query,
                project_name=project_name,
                branch_or_workspace=(
                    alt_cl_name if alt_cl_name != project_name else None
                ),
                cancelled=True,
            )
            raise

        add_or_update_prompt(
            query,
            project_name=project_name,
            branch_or_workspace=alt_cl_name if alt_cl_name != project_name else None,
        )
        results = launch_multi_prompt_agents(
            segments=[slot.prompt for slot in alt_plan.slots],
            local_xprompts={},
            cl_name=alt_cl_name,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=is_home_mode,
            vcs_ref=alt_vcs_ref,
            extra_env=extra_env,
            default_bare_segments_to_home=True,
        )
        return results

    # --- Detect VCS refs in prompt ---
    from sase.xprompt.directives import has_deferred_start_directive

    has_wait = has_deferred_start_directive(query)
    vcs_ref: tuple[str, str] | None = None
    workspace_dir: str | None = None
    use_preallocated_workspace = False

    # Try full VCS ref resolution -- this updates project_file, workspace_dir,
    # etc. when the prompt contains an explicit ref like #gh:sase.  Must run
    # in both home and non-home mode so xprompt chops launched from CWDs that
    # resolve to a different project still target the correct one.
    # When %wait is detected, skip workspace allocation (deferred until
    # dependencies resolve).
    for wf_name in get_workflow_names():
        resolved = resolve_ref_from_prompt(query, wf_name, skip_workspace=has_wait)
        if resolved is not None:
            project_file, project_name, workspace_dir, ws_num, ref_value = resolved
            workspace_num = ws_num
            vcs_ref = (wf_name, ref_value)
            is_home_mode = is_non_workspace_workflow(wf_name)
            use_preallocated_workspace = not is_home_mode and not has_wait
            break

    if vcs_ref is None:
        known_ref = resolve_known_project_vcs_launch_ref(query)
        if known_ref is not None:
            project_file = known_ref.project_file
            project_name = known_ref.ref
            workspace_dir = known_ref.workspace_dir if has_wait else None
            workspace_num = 0
            vcs_ref = (known_ref.workflow_type, known_ref.ref)
            is_home_mode = False

    if vcs_ref is None and not is_home_mode:
        from sase.workspace_provider import get_ref_patterns

        for wf_name, pattern in get_ref_patterns().items():
            match = pattern.search(query)
            if match is not None:
                ref_value = match.group(1) or match.group(2)
                if ref_value:
                    vcs_ref = (wf_name, ref_value)
                    break

    # If no workspace ref is found and we're not already in home mode, fall
    # back to direct home mode. Bare prompts normally gain the default
    # workspace ref before this point; this branch covers disabled/missing
    # workspace providers and explicit non-workspace contexts.
    if vcs_ref is None and not is_home_mode:
        from sase.ace.changespec.project_spec_path import preferred_project_spec_path

        is_home_mode = True
        project_name = "home"
        home_dir = os.path.expanduser("~/.sase/projects/home")
        project_file = preferred_project_spec_path(home_dir, "home")

    # --- Resolve fixed workspace contexts ---
    if timestamp is None:
        timestamp = reserve_launch_timestamp_batch(1)[0]

    if not workspace_dir:
        if is_home_mode:
            workspace_dir = os.path.expanduser("~")
            workspace_num = 0
        elif has_wait:
            # Deferred workspace: use main workspace dir as CWD during wait
            workspace_num = 0
            workspace_dir = get_workspace_directory(project_name, 1)

    # --- Determine display name / sort key ---
    if vcs_ref is not None:
        cl_name = vcs_ref[1]
        history_sort_key = vcs_ref[1]
        if is_non_workspace_workflow(vcs_ref[0]):
            update_target = ""
        else:
            from sase.vcs_provider import VCS_DEFAULT_REVISION

            update_target = VCS_DEFAULT_REVISION
    else:
        cl_name = project_name
        history_sort_key = ""
        update_target = ""

    try:
        from sase.agent.launch_validation import validate_launch_name_requests

        validate_launch_name_requests([query])
    except RuntimeError:
        add_or_update_prompt(
            query,
            project_name=project_name,
            branch_or_workspace=history_sort_key or None,
            cancelled=True,
        )
        raise

    # --- Save prompt to history ---
    add_or_update_prompt(
        query,
        project_name=project_name,
        branch_or_workspace=history_sort_key or None,
    )

    from sase.agent.launch_executor import LaunchExecutionContext, execute_launch_plan
    from sase.core.agent_launch_facade import plan_fake_fanout

    fixed_workspace = is_home_mode or has_wait or use_preallocated_workspace
    execution = execute_launch_plan(
        plan_fake_fanout("single", [query]),
        LaunchExecutionContext(
            cl_name=cl_name,
            project_file=project_file,
            project_name=project_name,
            update_target=update_target,
            history_sort_key=history_sort_key,
            is_home_mode=is_home_mode,
            vcs_ref=vcs_ref,
            deferred_workspace=has_wait,
            workspace_num=workspace_num if fixed_workspace else None,
            workspace_dir=workspace_dir if fixed_workspace else None,
            use_preallocated_workspace=use_preallocated_workspace,
        ),
        extra_env=extra_env,
        base_timestamp=timestamp,
    )
    return execution.results


def launch_agent_from_cwd(
    query: str,
    extra_env: dict[str, str] | None = None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
    timestamp: str | None = None,
) -> AgentLaunchResult:
    """Resolve project context from CWD and launch a background agent.

    This compatibility wrapper keeps the historical API returning the first
    launch result while ``launch_agents_from_cwd()`` exposes full fan-out.
    """
    results = launch_agents_from_cwd(
        query,
        extra_env=extra_env,
        segment_extra_env=segment_extra_env,
        timestamp=timestamp,
    )
    if not results:
        raise RuntimeError("agent launch produced no results")
    return results[0]
