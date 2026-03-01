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
class _AgentLaunchResult:
    """Result returned after successfully spawning a background agent."""

    pid: int
    workspace_num: int
    workspace_dir: str
    output_path: str


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
) -> _AgentLaunchResult:
    """Spawn a detached background agent process.

    This is the low-level entry point: all parameters must already be
    resolved by the caller.  The TUI uses this directly.

    Raises:
        RuntimeError: If workspace claiming fails (process is terminated
            before the error is raised).
    """
    from sase.running_field import claim_workspace
    from sase.sase_utils import ensure_sase_directory
    from sase.shared_utils import convert_timestamp_to_artifacts_format

    # Write prompt to temp file (runner will read and delete)
    fd, prompt_file = tempfile.mkstemp(suffix=".md", prefix="sase_ace_prompt_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(prompt)

    # Build output file path
    workflows_dir = ensure_sase_directory("workflows")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in cl_name)
    output_path = os.path.join(workflows_dir, f"{safe_name}_ace-run-{timestamp}.txt")

    # Resolve runner script path
    import sase.axe_run_agent_runner as runner_mod

    runner_script = os.path.abspath(runner_mod.__file__)

    # Build subprocess environment (copy to avoid mutating os.environ)
    subprocess_env = dict(os.environ)
    subprocess_env["SASE_AGENT"] = "1"
    subprocess_env["SASE_AGENT_CL_NAME"] = cl_name
    subprocess_env["SASE_AGENT_PROJECT_FILE"] = project_file
    subprocess_env["SASE_AGENT_TIMESTAMP"] = timestamp
    if vcs_ref is not None:
        from sase.workspace_provider import get_pre_allocated_env_prefix

        prefix = get_pre_allocated_env_prefix(vcs_ref[0])
        if prefix:
            subprocess_env[f"{prefix}_PRE_ALLOCATED"] = "1"
            subprocess_env[f"{prefix}_WORKSPACE_NUM"] = str(workspace_num)
            subprocess_env[f"{prefix}_WORKSPACE_DIR"] = workspace_dir

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
            stdout=output_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=subprocess_env,
        )

    # Claim workspace so agent appears in Agents tab while running
    if not is_home_mode:
        artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
        if not claim_workspace(
            project_file,
            workspace_num,
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
            raise RuntimeError(f"Failed to claim workspace #{workspace_num}")
    else:
        # Ensure home project directory and file exist
        home_project_dir = os.path.expanduser("~/.sase/projects/home")
        home_project_file = os.path.join(home_project_dir, "home.gp")
        os.makedirs(home_project_dir, exist_ok=True)
        if not os.path.exists(home_project_file):
            with open(home_project_file, "w", encoding="utf-8") as f:
                f.write("")

    return _AgentLaunchResult(
        pid=process.pid,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        output_path=output_path,
    )


def launch_agent_from_cwd(query: str) -> _AgentLaunchResult:
    """Resolve project context from CWD and launch a background agent.

    This is the high-level entry point used by ``sase run --daemon``
    and xprompt chop handlers.

    Args:
        query: The prompt/xprompt string to run as an agent.

    Returns:
        _AgentLaunchResult with process info.

    Raises:
        RuntimeError: If workspace allocation or claiming fails.
    """
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )
    from sase.main.utils import ensure_project_file_and_get_workspace_num
    from sase.prompt_history import add_or_update_prompt
    from sase.running_field import (
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
    )
    from sase.sase_utils import generate_timestamp
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

    # --- Detect VCS refs in prompt ---
    vcs_ref: tuple[str, str] | None = None
    workspace_dir: str | None = None

    # Try full VCS ref resolution — this updates project_file, workspace_dir,
    # etc. when the prompt contains an explicit ref like #gh:sase.  Must run
    # in both home and non-home mode so xprompt chops launched from CWDs that
    # resolve to a different project still target the correct one.
    for wf_name in get_workflow_names():
        resolved = resolve_ref_from_prompt(query, wf_name)
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

    if workspace_dir is None:
        if is_home_mode:
            workspace_dir = os.path.expanduser("~")
            workspace_num = 0
        else:
            workspace_num = get_first_available_axe_workspace(project_file)
            workspace_dir, _ = get_workspace_directory_for_num(
                workspace_num, project_name
            )

    # --- Determine display name / sort key ---
    if vcs_ref is not None:
        cl_name = vcs_ref[1]
        history_sort_key = vcs_ref[1]
        update_target = ""
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
    )
