"""Shared agent-launching library.

Extracts the common subprocess-spawning logic used by both
``sase run --daemon`` and the TUI ``@`` keymap into reusable functions.
"""

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass


@dataclass
class AgentLaunchResult:
    """Result returned after successfully spawning a background agent."""

    pid: int
    workspace_num: int
    workspace_dir: str
    output_path: str
    project_file: str = ""
    project_name: str = ""
    workflow_name: str = ""
    cl_name: str = ""
    timestamp: str = ""


def spawn_agent_subprocess(
    *,
    cl_name: str,
    project_file: str,
    workspace_dir: str,
    workspace_num: int,
    workflow_name: str,
    prompt: str,
    timestamp: str,
    update_target: str = "",
    project_name: str = "",
    history_sort_key: str = "",
    is_home_mode: bool = False,
    vcs_ref: tuple[str, str] | None = None,
    deferred_workspace: bool = False,
    local_xprompts_file: str | None = None,
    extra_env: dict[str, str] | None = None,
    retry_transfer_from_pid: int | None = None,
) -> AgentLaunchResult:
    """Spawn a detached background agent process.

    This is the low-level entry point: all parameters must already be
    resolved by the caller.  The TUI uses this directly.

    When ``retry_transfer_from_pid`` is set, the function transfers an
    existing workspace claim (held by the given PID) atomically to the new
    child instead of attempting a fresh ``claim_workspace`` — used by the
    spawn-on-retry flow so the workspace slot stays continuously held.

    Raises:
        RuntimeError: If workspace claiming/transfer fails (process is
            terminated before the error is raised).
    """
    from sase.running_field import claim_workspace, transfer_workspace_claim
    from sase.core.paths import sharded_path
    from sase.artifacts import convert_timestamp_to_artifacts_format
    from sase.axe.chop_agents import record_chop_agent_launch_from_env

    # Write prompt to temp file (runner will read and delete)
    from sase.core.paths import get_sase_tmpdir

    fd, prompt_file = tempfile.mkstemp(
        suffix=".md", prefix="sase_ace_prompt_", dir=get_sase_tmpdir()
    )
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(prompt)

    # Build output file path (sharded by YYYYMM).
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in cl_name)
    output_path = sharded_path("workflows", f"{safe_name}_ace-run-{timestamp}.txt")

    # Resolve runner script path without importing the module (its top-level
    # code calls signal.signal() which fails from non-main threads).
    import importlib.util

    _spec = importlib.util.find_spec("sase.axe.run_agent_runner")
    assert _spec is not None and _spec.origin is not None
    runner_script = os.path.abspath(_spec.origin)

    # Build subprocess environment (copy to avoid mutating os.environ)
    subprocess_env = dict(os.environ)
    if extra_env:
        subprocess_env.update(extra_env)
    subprocess_env["SASE_AGENT"] = "1"
    subprocess_env["SASE_AGENT_CL_NAME"] = cl_name
    subprocess_env["SASE_AGENT_PROJECT_FILE"] = project_file
    subprocess_env["SASE_AGENT_TIMESTAMP"] = timestamp
    if deferred_workspace:
        subprocess_env["SASE_AGENT_DEFERRED_WORKSPACE"] = "1"
        if vcs_ref is not None:
            subprocess_env["SASE_AGENT_VCS_WORKFLOW_TYPE"] = vcs_ref[0]
    elif vcs_ref is not None and not is_home_mode:
        from sase.workspace_provider import get_pre_allocated_env_prefix

        prefix = get_pre_allocated_env_prefix(vcs_ref[0])
        if prefix:
            subprocess_env[f"{prefix}_PRE_ALLOCATED"] = "1"
            subprocess_env[f"{prefix}_WORKSPACE_NUM"] = str(workspace_num)
            subprocess_env[f"{prefix}_WORKSPACE_DIR"] = workspace_dir

    if local_xprompts_file:
        subprocess_env["SASE_AGENT_LOCAL_XPROMPTS"] = local_xprompts_file

    resolved_project_name = project_name or (
        "home" if is_home_mode else os.path.basename(os.path.dirname(project_file))
    )

    # Spawn detached subprocess
    with open(output_path, "w") as output_file:
        process = subprocess.Popen(
            [
                sys.executable,
                runner_script,
                cl_name,
                project_file,
                workspace_dir,
                output_path,
                str(workspace_num),
                workflow_name,
                prompt_file,
                timestamp,
                update_target,
                project_name,
                history_sort_key,
                "1" if is_home_mode else "",
            ],
            cwd=workspace_dir,
            stdin=subprocess.DEVNULL,
            stdout=output_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=subprocess_env,
        )

    # Claim workspace so agent appears in Agents tab while running.
    # For deferred-workspace agents (%wait), claim with workspace_num=0
    # so the agent appears in the TUI but doesn't reserve a real workspace.
    # For retry spawns, transfer an existing claim atomically so the slot
    # stays continuously held across the parent→child handoff.
    if not is_home_mode:
        artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
        claim_num = 0 if deferred_workspace else workspace_num
        if retry_transfer_from_pid is not None:
            transferred = transfer_workspace_claim(
                project_file,
                claim_num,
                from_pid=retry_transfer_from_pid,
                to_pid=process.pid,
                new_workflow=workflow_name,
                new_artifacts_timestamp=artifacts_timestamp,
                cl_name=cl_name,
            )
            if not transferred:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise RuntimeError(
                    f"Failed to transfer workspace #{claim_num} from "
                    f"pid {retry_transfer_from_pid}"
                )
        elif not claim_workspace(
            project_file,
            claim_num,
            workflow_name,
            process.pid,
            cl_name,
            artifacts_timestamp=artifacts_timestamp,
        ):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise RuntimeError(f"Failed to claim workspace #{claim_num}")
    else:
        # Ensure home project directory and file exist
        home_project_dir = os.path.expanduser("~/.sase/projects/home")
        home_project_file = os.path.join(home_project_dir, "home.gp")
        os.makedirs(home_project_dir, exist_ok=True)
        if not os.path.exists(home_project_file):
            with open(home_project_file, "w", encoding="utf-8") as f:
                f.write("")

    record_chop_agent_launch_from_env(
        pid=process.pid,
        project_file=project_file,
        project_name=resolved_project_name,
        workspace_num=workspace_num,
        workflow_name=workflow_name,
        cl_name=cl_name,
        timestamp=timestamp,
        prompt=prompt,
        env=subprocess_env,
    )

    return AgentLaunchResult(
        pid=process.pid,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        output_path=output_path,
        project_file=project_file,
        project_name=resolved_project_name,
        workflow_name=workflow_name,
        cl_name=cl_name,
        timestamp=timestamp,
    )


def launch_agent_from_cwd(
    query: str,
    extra_env: dict[str, str] | None = None,
) -> AgentLaunchResult:
    """Resolve project context from CWD and launch a background agent.

    This is the high-level entry point used by ``sase run --daemon``
    and xprompt chop handlers.

    For multi-prompt queries (containing ``---`` separators), all segments
    are launched sequentially and the first result is returned.

    Args:
        query: The prompt/xprompt string to run as an agent.

    Returns:
        AgentLaunchResult with process info (first agent for multi-prompt).

    Raises:
        RuntimeError: If workspace allocation or claiming fails.
    """
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )
    from sase.main.utils import ensure_project_file_and_get_workspace_num
    from sase.history.prompt import add_or_update_prompt
    from sase.running_field import (
        get_first_available_axe_workspace,
        get_workspace_directory,
        get_workspace_directory_for_num,
    )
    from sase.core.time import generate_timestamp
    from sase.workspace_provider import get_workflow_names

    # --- Resolve project context ---
    project_file, workspace_num, project_name = (
        ensure_project_file_and_get_workspace_num()
    )

    is_home_mode = project_file is None
    if is_home_mode:
        project_name = "home"
        project_file = os.path.expanduser("~/.sase/projects/home/home.gp")

    assert project_file is not None
    assert project_name is not None

    # --- Multi-prompt detection ---
    from sase.agent.multi_agent_xprompt import expand_multi_agent_xprompts
    from sase.agent.multi_prompt import parse_multi_prompt

    multi = parse_multi_prompt(query)
    expanded_segments = expand_multi_agent_xprompts(
        multi.segments, multi.local_xprompts
    )

    if len(expanded_segments) > 1:
        from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

        # Determine cl_name from VCS refs (lightweight pattern check).
        from sase.workspace_provider import get_ref_patterns

        mp_cl_name = project_name
        mp_vcs_ref: tuple[str, str] | None = None
        for wf_name, pattern in get_ref_patterns().items():
            match = pattern.search(query)
            if match is not None:
                ref_value = match.group(1) or match.group(2)
                if ref_value:
                    mp_cl_name = ref_value
                    mp_vcs_ref = (wf_name, ref_value)
                    break

        add_or_update_prompt(
            query,
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
        )
        return results[0]

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

    repeat_count, _, _ = extract_repeat_and_name(query)
    if repeat_count is not None and repeat_count > 1:
        slot_results: list[AgentLaunchResult] = []

        def _spawn_repeat_slot(spec: RepeatAgentSpec) -> None:
            slot_env = {
                REPEAT_NAME_ENV: spec.name,
                REPEAT_ITERATION_ENV: str(spec.iteration),
                REPEAT_TOTAL_ENV: str(spec.total),
            }
            if extra_env:
                slot_env.update(extra_env)
            slot_results.append(launch_agent_from_cwd(spec.prompt, extra_env=slot_env))

        spawn_repeat_batch(query, base_spawn_fn=_spawn_repeat_slot)
        return slot_results[0]

    # --- Alt-split detection ---
    from sase.xprompt.directives import split_prompt_for_models

    alt_prompts = split_prompt_for_models(query)
    if alt_prompts is not None:
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

        add_or_update_prompt(
            query,
            project_name=project_name,
            branch_or_workspace=alt_cl_name if alt_cl_name != project_name else None,
        )
        results = launch_multi_prompt_agents(
            segments=alt_prompts,
            local_xprompts={},
            cl_name=alt_cl_name,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=is_home_mode,
            vcs_ref=alt_vcs_ref,
            extra_env=extra_env,
        )
        return results[0]

    # --- Detect VCS refs in prompt ---
    from sase.xprompt.directives import has_wait_directive

    has_wait = has_wait_directive(query)
    vcs_ref: tuple[str, str] | None = None
    workspace_dir: str | None = None

    # Try full VCS ref resolution — this updates project_file, workspace_dir,
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
            is_home_mode = False
            break

    if vcs_ref is None and not is_home_mode:
        from sase.workspace_provider import get_ref_patterns

        for wf_name, pattern in get_ref_patterns().items():
            match = pattern.search(query)
            if match is not None:
                ref_value = match.group(1) or match.group(2)
                if ref_value:
                    vcs_ref = (wf_name, ref_value)
                    break

    # If no VCS ref found and we're not already in home mode, fall back to
    # home mode — matches TUI behavior where prompts without VCS refs always
    # run from home.
    if vcs_ref is None and not is_home_mode:
        is_home_mode = True
        project_name = "home"
        project_file = os.path.expanduser("~/.sase/projects/home/home.gp")

    # --- Allocate axe workspace ---
    timestamp = generate_timestamp()
    workflow_name = f"ace(run)-{timestamp}"

    if not workspace_dir:
        if is_home_mode:
            workspace_dir = os.path.expanduser("~")
            workspace_num = 0
        elif has_wait:
            # Deferred workspace: use main workspace dir as CWD during wait
            workspace_num = 0
            workspace_dir = get_workspace_directory(project_name, 1)
        else:
            workspace_num = get_first_available_axe_workspace(project_file)
            workspace_dir, _ = get_workspace_directory_for_num(
                workspace_num, project_name
            )

    # --- Determine display name / sort key ---
    if vcs_ref is not None:
        from sase.vcs_provider import VCS_DEFAULT_REVISION

        cl_name = vcs_ref[1]
        history_sort_key = vcs_ref[1]
        update_target = VCS_DEFAULT_REVISION
    else:
        cl_name = project_name
        history_sort_key = ""
        update_target = ""

    # --- Save prompt to history ---
    add_or_update_prompt(
        query,
        project_name=project_name,
        branch_or_workspace=history_sort_key or None,
    )

    assert workspace_num is not None
    assert workspace_dir is not None
    return spawn_agent_subprocess(
        cl_name=cl_name,
        project_file=project_file,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        workflow_name=workflow_name,
        prompt=query,
        timestamp=timestamp,
        update_target=update_target,
        project_name=project_name,
        history_sort_key=history_sort_key,
        is_home_mode=is_home_mode,
        vcs_ref=vcs_ref,
        deferred_workspace=has_wait,
        extra_env=extra_env,
    )
