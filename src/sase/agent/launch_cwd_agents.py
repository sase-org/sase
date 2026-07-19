"""Generic CWD-based launch flow for background agents."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence

from sase.agent.launch_cwd_common import (
    internal_agent_name_bypass_for_launch,
    plan_single_agent_name,
    resolve_known_project_vcs_launch_ref,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.paths import sase_projects_dir


def launch_agents_from_cwd_impl(
    query: str,
    extra_env: dict[str, str] | None = None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
    timestamp: str | None = None,
    *,
    recursive_launch_agents_from_cwd: Callable[..., list[AgentLaunchResult]]
    | None = None,
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

    def record_failed_launch_prompt(text: str) -> None:
        from sase.axe.chop_agents import is_chop_launch_env

        launch_envs = (extra_env, *(segment_extra_env or ()))
        if any(is_chop_launch_env(env) for env in launch_envs):
            return
        from sase.history.prompt import (
            record_failed_launch_prompt as record_interactive_failed_launch,
        )

        record_interactive_failed_launch(text)

    from sase.agent.names import ensure_historical_auto_name_migration
    from sase.project_aliases import canonicalize_project_aliases_in_prompt

    ensure_historical_auto_name_migration()
    try:
        query = canonicalize_project_aliases_in_prompt(query)
    except Exception:
        # An alias-map conflict here escapes before the validation/spawn
        # branches below can record the failure; preserve the original
        # submitted query so it stays recoverable from the stash.
        record_failed_launch_prompt(query)
        raise
    submitted_query = query

    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )
    from sase.history.prompt import add_or_update_prompt
    from sase.main.utils import ensure_project_file_and_get_workspace_num
    from sase.running_field import get_workspace_directory
    from sase.workspace_provider import get_workflow_names

    # --- Resolve project context ---
    # Read-only lookup: a plain launch from a git checkout must not register
    # that checkout as a SASE project. Explicit VCS/known-project refs resolved
    # below still activate their real project, and bare prompts fall back to
    # home mode rather than bootstrapping a CWD ProjectSpec.
    project_file, workspace_num, project_name = (
        ensure_project_file_and_get_workspace_num(create_missing=False)
    )

    is_home_mode = project_file is None
    if is_home_mode:
        from sase.ace.changespec.project_spec_path import preferred_project_spec_path

        project_name = "home"
        home_dir = str(sase_projects_dir() / "home")
        project_file = preferred_project_spec_path(home_dir, "home")

    assert project_file is not None
    assert project_name is not None

    # --- Multi-prompt detection ---
    from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.xprompt._parsing import (
        normalize_default_vcs_workflow,
        normalize_default_vcs_workflow_segment,
    )

    multi = parse_multi_prompt(query)
    from sase.agent.launch_projects import (
        enable_known_project_vcs_refs_for_launch_prompt,
    )

    enable_known_project_vcs_refs_for_launch_prompt("\n---\n".join(multi.segments))
    expanded_segment_extra_env: list[dict[str, str] | None] | None = None
    expanded_segment_template_groups: list[str | None] = []
    if segment_extra_env is not None:
        if len(segment_extra_env) != len(multi.segments):
            raise ValueError(
                "segment_extra_env must have one entry per multi-prompt segment"
            )
        from itertools import count

        expanded_segments: list[str] = []
        expanded_segment_extra_env = []
        # Share one invocation counter across the per-segment calls so two
        # invocations of the same xprompt swarm get distinct template
        # groups, exactly as the single-call branch below allocates them.
        xprompt_group_counter = count()
        for segment, env in zip(multi.segments, segment_extra_env, strict=True):
            segment_expansions = expand_xprompt_swarms_with_metadata(
                [segment],
                multi.local_xprompts,
                group_counter=xprompt_group_counter,
            )
            expanded_segments.extend(record.prompt for record in segment_expansions)
            expanded_segment_extra_env.extend([env] * len(segment_expansions))
            expanded_segment_template_groups.extend(
                record.template_group for record in segment_expansions
            )
    else:
        expanded_records = expand_xprompt_swarms_with_metadata(
            multi.segments, multi.local_xprompts
        )
        expanded_segments = [record.prompt for record in expanded_records]
        expanded_segment_template_groups = [
            record.template_group for record in expanded_records
        ]

    if not expanded_segments:
        return []

    if len(expanded_segments) > 1:
        from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

        expanded_segments = [
            normalize_default_vcs_workflow_segment(segment)
            for segment in expanded_segments
        ]
        normalized_query = "\n---\n".join(expanded_segments)
        enable_known_project_vcs_refs_for_launch_prompt(normalized_query)

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
                AgentNameSyntaxError,
                validate_launch_name_requests,
            )

            validate_launch_name_requests(
                expanded_segments,
                allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                    extra_env,
                    expanded_segment_extra_env,
                ),
            )
        except (
            AgentNameLaunchCollisionError,
            AgentNameReuseConfirmationRequiredError,
            AgentNameSyntaxError,
        ):
            record_failed_launch_prompt(submitted_query)
            raise

        add_or_update_prompt(
            submitted_query,
            allow_short=True,
        )
        try:
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
                segment_template_groups=expanded_segment_template_groups,
                allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                    extra_env,
                    expanded_segment_extra_env,
                ),
                default_bare_segments_to_home=True,
                multi_agent_prompt_text=submitted_query,
            )
        except Exception:
            record_failed_launch_prompt(submitted_query)
            raise
        return results

    query = normalize_default_vcs_workflow(expanded_segments[0])
    enable_known_project_vcs_refs_for_launch_prompt(query)
    if expanded_segment_extra_env:
        segment_env = expanded_segment_extra_env[0] or {}
        extra_env = {**(extra_env or {}), **segment_env}

    # --- Repeat fan-out ---
    # When %r:N is present, spawn N independent agents before any further
    # dispatch.  Each spec's prompt has %r / %i stripped and %i:<base>.<k>
    # re-injected, so the recursive call resolves through the single-agent
    # path without re-triggering this branch.
    from sase.agent.repeat_launcher import (
        REPEAT_ITERATION_ENV,
        REPEAT_NAME_ENV,
        REPEAT_PREV_NAME_ENV,
        REPEAT_TOTAL_ENV,
        RepeatAgentSpec,
        extract_repeat_and_name,
        spawn_repeat_batch,
    )
    from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

    repeat_count, _, _ = extract_repeat_and_name(query)
    if repeat_count is not None and repeat_count > 1:
        slot_results: list[AgentLaunchResult] = []
        recursive_launch = (
            recursive_launch_agents_from_cwd or launch_agents_from_cwd_impl
        )
        try:
            repeat_timestamps = reserve_launch_timestamp_batch(repeat_count)
            repeat_specs: list[RepeatAgentSpec] = []

            spawn_repeat_batch(
                query,
                base_spawn_fn=repeat_specs.append,
                timestamps=repeat_timestamps,
            )

            from sase.agent.launch_validation import validate_launch_name_requests

            validate_launch_name_requests(
                [spec.prompt for spec in repeat_specs],
                allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                    extra_env,
                ),
            )

            def _spawn_repeat_slot(spec: RepeatAgentSpec) -> None:
                assert spec.timestamp is not None
                slot_env = {
                    REPEAT_NAME_ENV: spec.name,
                    REPEAT_ITERATION_ENV: str(spec.iteration),
                    REPEAT_TOTAL_ENV: str(spec.total),
                }
                if spec.prev_name is not None:
                    slot_env[REPEAT_PREV_NAME_ENV] = spec.prev_name
                if extra_env:
                    slot_env.update(extra_env)
                slot_results.extend(
                    recursive_launch(
                        spec.prompt,
                        extra_env=slot_env,
                        timestamp=spec.timestamp,
                    )
                )

            for spec in repeat_specs:
                _spawn_repeat_slot(spec)
        except Exception:
            record_failed_launch_prompt(query)
            raise
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

        enable_known_project_vcs_refs_for_launch_prompt(
            "\n---\n".join(slot.prompt for slot in alt_plan.slots)
        )
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

            validate_launch_name_requests(
                [slot.prompt for slot in alt_plan.slots],
                allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                    extra_env,
                ),
            )
        except RuntimeError:
            record_failed_launch_prompt(query)
            raise

        add_or_update_prompt(query)
        try:
            results = launch_multi_prompt_agents(
                segments=[query],
                local_xprompts=multi.local_xprompts,
                cl_name=alt_cl_name,
                project_file=project_file,
                project_name=project_name,
                is_home_mode=is_home_mode,
                vcs_ref=alt_vcs_ref,
                extra_env=extra_env,
                preplanned_fanout_plans=[alt_plan],
                allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                    extra_env
                ),
                default_bare_segments_to_home=True,
            )
        except Exception:
            record_failed_launch_prompt(query)
            raise
        return results

    # --- Detect VCS refs in prompt ---
    from sase.xprompt.directives import has_deferred_start_directive

    has_wait = has_deferred_start_directive(query)
    vcs_ref: tuple[str, str] | None = None
    workspace_dir: str | None = None

    # Resolve VCS metadata without reserving a numbered workspace for normal
    # VCS refs. The executor claims the final slot atomically just before
    # spawn; deferred %wait launches carry a workspace here.
    for wf_name in get_workflow_names():
        resolved = resolve_ref_from_prompt(
            query,
            wf_name,
            skip_workspace=True,
        )
        if resolved is not None:
            project_file, project_name, resolved_dir, ws_num, ref_value = resolved
            if has_wait:
                workspace_dir = resolved_dir
                workspace_num = ws_num
            else:
                workspace_dir = None
                workspace_num = None
            vcs_ref = (wf_name, ref_value)
            is_home_mode = False
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
        home_dir = str(sase_projects_dir() / "home")
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
        from sase.vcs_provider import VCS_DEFAULT_REVISION

        update_target = VCS_DEFAULT_REVISION
    else:
        cl_name = project_name
        history_sort_key = ""
        update_target = ""

    try:
        from sase.agent.launch_validation import validate_launch_name_requests

        validate_launch_name_requests(
            [query],
            allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                extra_env
            ),
        )
    except RuntimeError:
        record_failed_launch_prompt(query)
        raise

    # --- Save prompt to history ---
    add_or_update_prompt(query)

    from sase.agent.launch_executor import LaunchExecutionContext, execute_launch_plan
    from sase.core.agent_launch_facade import plan_fake_fanout

    extra_env, name_allocator = plan_single_agent_name(
        query,
        extra_env,
        project_name=project_name,
        timestamp=timestamp,
    )

    fixed_workspace = is_home_mode or has_wait
    try:
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
                use_preallocated_workspace=False,
            ),
            extra_env=extra_env,
            base_timestamp=timestamp,
            allow_reserved_family_separator_names=internal_agent_name_bypass_for_launch(
                extra_env
            ),
        )
    except Exception:
        if name_allocator is not None:
            name_allocator.release_uncommitted_template_reservations()
        record_failed_launch_prompt(query)
        raise
    return execution.results
