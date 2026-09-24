"""Single-agent resolution and execution for CWD-based launches."""

from __future__ import annotations

import os
from collections.abc import Callable

from sase.agent.launch_cwd_common import (
    internal_agent_name_bypass_for_launch,
    plan_single_agent_name,
    resolve_known_project_vcs_launch_ref,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.paths import sase_projects_dir


def launch_single_agent(
    query: str,
    *,
    project_file: str,
    project_name: str,
    is_home_mode: bool,
    workspace_num: int | None,
    extra_env: dict[str, str] | None,
    timestamp: str | None,
    record_failed_launch_prompt: Callable[[str], None],
) -> list[AgentLaunchResult]:
    """Resolve the VCS/workspace context for one prompt and spawn it."""
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )
    from sase.history.prompt import add_or_update_prompt
    from sase.workspace_provider import get_workflow_names
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
        from sase.ace.patch.project_spec_path import preferred_project_spec_path

        is_home_mode = True
        project_name = "home"
        home_dir = str(sase_projects_dir() / "home")
        project_file = preferred_project_spec_path(home_dir, "home")

    # --- Resolve fixed workspace contexts ---
    if timestamp is None:
        from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

        timestamp = reserve_launch_timestamp_batch(1)[0]

    if not workspace_dir:
        if is_home_mode:
            workspace_dir = os.path.expanduser("~")
            workspace_num = 0
        elif has_wait:
            # Deferred workspace: use main workspace dir as CWD during wait
            from sase.running_field import get_workspace_directory

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
            allow_reserved_agent_session_separator_names=internal_agent_name_bypass_for_launch(
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
            allow_reserved_agent_session_separator_names=internal_agent_name_bypass_for_launch(
                extra_env
            ),
        )
    except Exception:
        if name_allocator is not None:
            name_allocator.release_uncommitted_template_reservations()
        record_failed_launch_prompt(query)
        raise
    return execution.results
