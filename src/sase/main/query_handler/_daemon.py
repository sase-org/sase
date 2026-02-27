"""Daemon mode for sase run — launches prompt as a detached background agent."""

import os
import subprocess
import sys
import tempfile

from sase.ace.tui.actions.agent_workflow._ref_resolution import (
    resolve_ref_from_prompt,
)
from sase.main.utils import ensure_project_file_and_get_workspace_num
from sase.prompt_history import add_or_update_prompt
from sase.running_field import (
    claim_workspace,
    get_first_available_axe_workspace,
    get_workspace_directory_for_num,
)
from sase.sase_utils import ensure_sase_directory, generate_timestamp
from sase.shared_utils import convert_timestamp_to_artifacts_format
from sase.workspace_provider import get_workflow_names


def run_query_daemon(query: str) -> None:
    """Launch *query* as a detached background agent process.

    Replicates the TUI ``@`` keybinding behaviour without TUI dependencies.
    The spawned agent appears in the TUI Agents tab.
    """
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
    workspace_dir: str | None = None  # Set by VCS resolution in home mode

    if is_home_mode:
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

    # --- Allocate axe workspace ---
    timestamp = generate_timestamp()
    workflow_name = f"ace(run)-{timestamp}"

    # VCS resolution from home mode already set workspace_dir/workspace_num.
    # All other cases need a fresh axe workspace allocation.
    if workspace_dir is None:
        workspace_num = get_first_available_axe_workspace(project_file)
        workspace_dir, _ = get_workspace_directory_for_num(workspace_num, project_name)

    # --- Determine display name / sort key ---
    if vcs_ref is not None:
        cl_name = vcs_ref[1]
        history_sort_key = vcs_ref[1]
        update_target = ""  # VCS workflow .yml handles checkout
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

    # --- Write prompt to temp file ---
    fd, prompt_file = tempfile.mkstemp(suffix=".md", prefix="sase_ace_prompt_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(query)

    # --- Build output file ---
    workflows_dir = ensure_sase_directory("workflows")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in cl_name)
    output_path = os.path.join(workflows_dir, f"{safe_name}_ace-run-{timestamp}.txt")

    # --- Resolve runner script path ---
    import sase.axe_run_agent_runner as runner_mod

    runner_script = os.path.abspath(runner_mod.__file__)

    # --- Build subprocess env ---
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

    # --- Spawn detached subprocess ---
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

    # --- Claim workspace ---
    assert workspace_num is not None
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
            print(
                f"Warning: Failed to claim workspace #{workspace_num}", file=sys.stderr
            )
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            sys.exit(1)
    else:
        # Ensure home project directory and file exist
        home_project_dir = os.path.expanduser("~/.sase/projects/home")
        os.makedirs(home_project_dir, exist_ok=True)
        if not os.path.exists(project_file):
            with open(project_file, "w", encoding="utf-8") as f:
                f.write("")

    print(f"Agent started (PID {process.pid})")
    sys.exit(0)
