"""Shared agent-launching library.

Extracts the common subprocess-spawning logic used by both
``sase run --daemon`` and the TUI ``@`` keymap into reusable functions.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache


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


def _remove_inherited_sase_codex_home(env: dict[str, str]) -> None:
    """Drop CODEX_HOME when it points at a SASE-managed temporary Codex home."""
    codex_home = env.get("CODEX_HOME")
    if not codex_home:
        return

    from sase.llm_provider.codex import is_sase_managed_codex_home

    if is_sase_managed_codex_home(codex_home):
        env.pop("CODEX_HOME", None)


@lru_cache(maxsize=1)
def _get_runner_script() -> str:
    import importlib.util

    _spec = importlib.util.find_spec("sase.axe.run_agent_runner")
    assert _spec is not None and _spec.origin is not None
    return os.path.abspath(_spec.origin)


def _preallocated_workspace_env(
    vcs_ref: tuple[str, str] | None,
    *,
    workspace_num: int,
    workspace_dir: str,
) -> dict[str, str]:
    if vcs_ref is None:
        return {}

    from sase.workspace_provider import get_pre_allocated_env_prefix

    prefix = get_pre_allocated_env_prefix(vcs_ref[0])
    if not prefix:
        return {}
    return {
        f"{prefix}_PRE_ALLOCATED": "1",
        f"{prefix}_WORKSPACE_NUM": str(workspace_num),
        f"{prefix}_WORKSPACE_DIR": workspace_dir,
    }


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
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.core.agent_launch_facade import prepare_agent_launch, safe_launch_name
    from sase.core.agent_launch_wire import (
        AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        AgentLaunchRequestWire,
    )
    from sase.running_field import claim_workspace, transfer_workspace_claim
    from sase.core.paths import sharded_path
    from sase.artifacts import convert_timestamp_to_artifacts_format
    from sase.axe.chop_agents import record_chop_agent_launch_from_env
    from sase.core.paths import get_sase_tmpdir

    timer = LaunchTimingRecorder(
        "agent_launch_spawn",
        {
            "project_name": project_name,
            "cl_name": cl_name,
            "workspace_num": workspace_num,
            "home_mode": is_home_mode,
            "deferred_workspace": deferred_workspace,
        },
    )

    # Resolve runner script path without importing the module (its top-level
    # code calls signal.signal() which fails from non-main threads).
    with timer.stage("runner_script_resolution"):
        runner_script = _get_runner_script()

    # Compute the output shard root in Python because sharding is still a
    # host-side policy. Rust owns the deterministic filename/path assembly.
    with timer.stage("output_path_derive"):
        output_filename = f"{safe_launch_name(cl_name)}_ace-run-{timestamp}.txt"
        output_path_hint = sharded_path("workflows", output_filename)
        output_root = os.path.dirname(output_path_hint)

    request = AgentLaunchRequestWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        cl_name=cl_name,
        project_file=project_file,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        workflow_name=workflow_name,
        prompt=prompt,
        timestamp=timestamp,
        update_target=update_target,
        project_name=project_name,
        history_sort_key=history_sort_key,
        is_home_mode=is_home_mode,
        vcs_workflow_type=None if vcs_ref is None else vcs_ref[0],
        vcs_ref=None if vcs_ref is None else vcs_ref[1],
        deferred_workspace=deferred_workspace,
        local_xprompts_file=local_xprompts_file,
        extra_env=extra_env or {},
        retry_transfer_from_pid=retry_transfer_from_pid,
    )

    with timer.stage("launch_prepare", prompt_len=len(prompt)):
        prepared = prepare_agent_launch(
            request,
            python_executable=sys.executable,
            runner_script=runner_script,
            sase_tmpdir=get_sase_tmpdir(),
            output_root=output_root,
            preallocated_env=_preallocated_workspace_env(
                vcs_ref,
                workspace_num=workspace_num,
                workspace_dir=workspace_dir,
            ),
        )

    # Build subprocess environment (copy to avoid mutating os.environ)
    with timer.stage("env_shape"):
        subprocess_env = dict(os.environ)
        _remove_inherited_sase_codex_home(subprocess_env)
        subprocess_env.update(prepared.env_delta)

    resolved_project_name = project_name or (
        "home" if is_home_mode else os.path.basename(os.path.dirname(project_file))
    )

    # Spawn detached subprocess
    with timer.stage("subprocess_spawn"):
        with open(prepared.output_path, "w") as output_file:
            process = subprocess.Popen(
                prepared.argv,
                cwd=prepared.cwd,
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
    with timer.stage("workspace_claim"):
        if prepared.claim_request is not None:
            artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
            claim_request = prepared.claim_request
            claim_num = claim_request.workspace_num
            if claim_request.transfer_from_pid is not None:
                transferred = transfer_workspace_claim(
                    claim_request.project_file,
                    claim_num,
                    from_pid=claim_request.transfer_from_pid,
                    to_pid=process.pid,
                    new_workflow=claim_request.workflow_name,
                    new_artifacts_timestamp=artifacts_timestamp,
                    cl_name=claim_request.cl_name,
                )
                if not transferred:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    timer.finish(outcome="claim_failed")
                    raise RuntimeError(
                        f"Failed to transfer workspace #{claim_num} from "
                        f"pid {claim_request.transfer_from_pid}"
                    )
            elif not claim_workspace(
                claim_request.project_file,
                claim_num,
                claim_request.workflow_name,
                process.pid,
                claim_request.cl_name,
                artifacts_timestamp=artifacts_timestamp,
            ):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                timer.finish(outcome="claim_failed")
                raise RuntimeError(f"Failed to claim workspace #{claim_num}")
        else:
            # Ensure home project directory and file exist
            home_project_dir = os.path.expanduser("~/.sase/projects/home")
            home_project_file = os.path.join(home_project_dir, "home.gp")
            os.makedirs(home_project_dir, exist_ok=True)
            if not os.path.exists(home_project_file):
                with open(home_project_file, "w", encoding="utf-8") as f:
                    f.write("")

    with timer.stage("chop_registry_record"):
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

    timer.finish(outcome="ok", pid=process.pid)
    return AgentLaunchResult(
        pid=process.pid,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        output_path=prepared.output_path,
        project_file=project_file,
        project_name=resolved_project_name,
        workflow_name=workflow_name,
        cl_name=cl_name,
        timestamp=timestamp,
    )


def launch_agent_from_cwd(
    query: str,
    extra_env: dict[str, str] | None = None,
    timestamp: str | None = None,
) -> AgentLaunchResult:
    """Resolve project context from CWD and launch a background agent.

    This is the high-level entry point used by ``sase run --daemon``
    and xprompt chop handlers.

    For multi-prompt queries (containing ``---`` separators), all segments
    are launched sequentially and the first result is returned.

    Args:
        query: The prompt/xprompt string to run as an agent.
        timestamp: Optional preallocated launch timestamp for fan-out callers.

    Returns:
        AgentLaunchResult with process info (first agent for multi-prompt).

    Raises:
        RuntimeError: If workspace allocation or claiming fails.
    """
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        is_non_workspace_workflow,
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
    from sase.xprompt._parsing import (
        normalize_default_vcs_workflow,
        normalize_default_vcs_workflow_segment,
    )

    multi = parse_multi_prompt(query)
    expanded_segments = expand_multi_agent_xprompts(
        multi.segments, multi.local_xprompts
    )

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
            default_bare_segments_to_home=True,
        )
        return results[0]

    query = normalize_default_vcs_workflow(query)

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
    from sase.core.agent_launch_facade import allocate_launch_timestamp_batch

    repeat_count, _, _ = extract_repeat_and_name(query)
    if repeat_count is not None and repeat_count > 1:
        slot_results: list[AgentLaunchResult] = []
        repeat_timestamps = allocate_launch_timestamp_batch(repeat_count)

        def _spawn_repeat_slot(spec: RepeatAgentSpec) -> None:
            assert spec.timestamp is not None
            slot_env = {
                REPEAT_NAME_ENV: spec.name,
                REPEAT_ITERATION_ENV: str(spec.iteration),
                REPEAT_TOTAL_ENV: str(spec.total),
            }
            if extra_env:
                slot_env.update(extra_env)
            slot_results.append(
                launch_agent_from_cwd(
                    spec.prompt,
                    extra_env=slot_env,
                    timestamp=spec.timestamp,
                )
            )

        spawn_repeat_batch(
            query,
            base_spawn_fn=_spawn_repeat_slot,
            timestamps=repeat_timestamps,
        )
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
            default_bare_segments_to_home=True,
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
            is_home_mode = is_non_workspace_workflow(wf_name)
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
    timestamp = timestamp or generate_timestamp()
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
