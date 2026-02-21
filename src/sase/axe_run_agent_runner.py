#!/usr/bin/env python3
"""Background run agent runner for sase ace TUI.

This script is launched by the ace TUI to run custom agents in the background.
It handles workspace cleanup and releases the workspace upon completion.
"""

import json
import os
import sys
import time
from typing import Any

from sase.ace.hooks import format_duration
from sase.axe_runner_utils import install_sigterm_handler, prepare_workspace, was_killed
from sase.chat_history import save_chat_history
from sase.shared_utils import (
    convert_timestamp_to_artifacts_format,
    create_artifacts_directory,
)

install_sigterm_handler("agent")


def _extract_step_output_and_diff_path(
    artifacts_dir: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract step_output and diff_path from workflow_state.json.

    Reads the workflow state written by execute_workflow() and extracts:
    - step_output: the last completed step's output dict
    - diff_path: path value from output_types with field_type=="path",
      or fallback to direct diff_path key in step outputs

    Args:
        artifacts_dir: Path to the artifacts directory containing workflow_state.json.

    Returns:
        Tuple of (step_output, diff_path).
    """
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, None

    # Extract step_output: last step with a dict output
    step_output: dict[str, Any] | None = None
    for step_data in reversed(data.get("steps", [])):
        output = step_data.get("output")
        if output and isinstance(output, dict):
            step_output = output
            break

    # Extract diff_path: last step's first path-typed output
    diff_path: str | None = None
    steps_list = data.get("steps", [])
    if steps_list:
        last_step = steps_list[-1]
        output_types = last_step.get("output_types") or {}
        step_out = last_step.get("output")
        if output_types and isinstance(step_out, dict):
            for field_name, field_type in output_types.items():
                if field_type == "path":
                    path_value = step_out.get(field_name)
                    if path_value:
                        diff_path = str(path_value)
                        break

    # Fallback: check for literal diff_path key in last step
    if not diff_path and steps_list:
        last_out = steps_list[-1].get("output")
        if isinstance(last_out, dict) and last_out.get("diff_path"):
            diff_path = str(last_out["diff_path"])

    # Expand tilde in diff_path to prevent path corruption when absolutized
    if diff_path:
        diff_path = os.path.expanduser(diff_path)

    return step_output, diff_path


def main() -> None:
    """Run agent workflow and release workspace on completion."""
    # Accept 13 args: cl_name, project_file, workspace_dir, output_path,
    # workspace_num, workflow_name, prompt_file, timestamp,
    # update_target, project_name, cl_name_for_history, is_home_mode
    if len(sys.argv) != 13:
        print(
            f"Usage: {sys.argv[0]} <cl_name> <project_file> <workspace_dir> "
            "<output_path> <workspace_num> <workflow_name> <prompt_file> <timestamp> "
            "<update_target> <project_name> "
            "<cl_name_for_history> <is_home_mode>",
            file=sys.stderr,
        )
        sys.exit(1)

    cl_name = sys.argv[1]
    project_file = sys.argv[2]
    workspace_dir = sys.argv[3]
    output_path = sys.argv[4]
    workspace_num = int(sys.argv[5])
    workflow_name = sys.argv[6]
    prompt_file = sys.argv[7]
    timestamp = sys.argv[8]

    # Optional parameters (empty string = not provided)
    update_target = sys.argv[9]
    project_name = sys.argv[10]
    # sys.argv[11] (cl_name_for_history) is no longer used here;
    # prompt history is saved by the TUI before launch.
    is_home_mode_arg = sys.argv[12]
    is_home_mode: bool = bool(is_home_mode_arg)

    # Read prompt from temp file
    try:
        with open(prompt_file, encoding="utf-8") as f:
            prompt = f.read()
    except Exception as e:
        print(f"Error reading prompt file: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Clean up temp prompt file
        try:
            os.unlink(prompt_file)
        except OSError:
            pass

    start_time = time.time()
    success = False
    duration = "0s"
    saved_path: str | None = None
    diff_path: str | None = None

    print("Starting agent run")
    print(f"CL: {cl_name}")
    print(f"Workspace: {workspace_dir}")
    print(f"Workflow: {workflow_name}")
    print()
    print("=== Prompt ===")
    print(prompt)
    print("==============")
    print()

    # Prepare workspace before running agent (skip for home mode)
    if update_target and not is_home_mode:
        print("=== Preparing Workspace ===")
        if not prepare_workspace(
            workspace_dir,
            cl_name,
            update_target,
            backup_suffix="ace",
            project_basename=project_name,
        ):
            print("Failed to prepare workspace", file=sys.stderr)
            sys.exit(1)
        print("===========================")
        print()

    # Track running marker path for cleanup (home mode only)
    running_marker_path: str | None = None

    try:
        try:
            # Change to workspace directory
            os.chdir(workspace_dir)

            # Get project name from project_file path (or use "home" for home mode)
            # Path format: ~/.sase/projects/<project>/<project>.gp
            if is_home_mode:
                project_name = "home"
            else:
                project_name = os.path.basename(os.path.dirname(project_file))

            # Create artifacts directory using shared timestamp
            artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
            artifacts_dir = create_artifacts_directory(
                "ace-run",
                project_name=project_name,
                timestamp=timestamp,
            )

            # Extract model directive and detect VCS before preprocessing
            from sase.llm_provider.registry import (
                get_default_provider_name,
                get_provider,
            )
            from sase.vcs_provider._registry import detect_vcs
            from sase.xprompt.directives import extract_prompt_directives

            _, directives = extract_prompt_directives(prompt)
            agent_name = directives.name
            agent_wait_names = directives.wait
            agent_model = directives.model
            agent_llm_provider = get_default_provider_name()
            if not agent_model:
                provider = get_provider()
                agent_model = provider.resolve_model_name()

            vcs_name = detect_vcs(workspace_dir)
            vcs_display_map = {"git": "GitHub", "hg": "Mercurial"}
            agent_vcs_provider = vcs_display_map.get(vcs_name) if vcs_name else None

            # Persist model, provider, VCS, name, and wait_for to agent_meta.json
            agent_meta: dict[str, Any] = {}
            if agent_name:
                agent_meta["name"] = agent_name
            if agent_wait_names:
                agent_meta["wait_for"] = agent_wait_names
            if agent_model:
                agent_meta["model"] = agent_model
            if agent_llm_provider:
                agent_meta["llm_provider"] = agent_llm_provider
            if agent_vcs_provider:
                agent_meta["vcs_provider"] = agent_vcs_provider
            if agent_meta:
                meta_path = os.path.join(artifacts_dir, "agent_meta.json")
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(agent_meta, f, indent=2)

            # Write running marker for home mode (no workspace tracking available)
            if is_home_mode:
                running_marker_path = os.path.join(artifacts_dir, "running.json")
                running_marker: dict[str, Any] = {
                    "cl_name": cl_name,
                    "pid": os.getpid(),
                    "timestamp": timestamp,
                    "prompt": prompt,
                }
                if agent_model:
                    running_marker["model"] = agent_model
                if agent_llm_provider:
                    running_marker["llm_provider"] = agent_llm_provider
                if agent_vcs_provider:
                    running_marker["vcs_provider"] = agent_vcs_provider
                with open(running_marker_path, "w", encoding="utf-8") as f:
                    json.dump(running_marker, f, indent=2)

            # Wait for dependencies if %wait directives are present
            if agent_wait_names:
                waiting_path = os.path.join(artifacts_dir, "waiting.json")
                waiting_data = {
                    "waiting_for": agent_wait_names,
                    "cl_name": cl_name,
                    "timestamp": timestamp,
                }
                with open(waiting_path, "w", encoding="utf-8") as f:
                    json.dump(waiting_data, f, indent=2)

                print(f"Waiting for agents: {', '.join(agent_wait_names)}")

                # Poll for ready.json (written by wait_checks lumberjack chop)
                ready_path = os.path.join(artifacts_dir, "ready.json")
                _WAIT_POLL_INTERVAL = 2  # seconds
                _WAIT_MAX_TIMEOUT = 86400  # 24 hours
                wait_elapsed = 0.0
                while not os.path.exists(ready_path):
                    if was_killed():
                        break
                    if wait_elapsed >= _WAIT_MAX_TIMEOUT:
                        print(
                            "Wait timeout exceeded, proceeding anyway",
                            file=sys.stderr,
                        )
                        break
                    time.sleep(_WAIT_POLL_INTERVAL)
                    wait_elapsed += _WAIT_POLL_INTERVAL

                # Clean up wait markers
                for path in (waiting_path, ready_path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

                if was_killed():
                    print("Agent killed while waiting", file=sys.stderr)
                    sys.exit(128 + 15)  # SIGTERM

                print("All dependencies satisfied, proceeding with workflow")

            # Create anonymous workflow and execute through WorkflowExecutor
            from sase.xprompt.models import create_anonymous_workflow
            from sase.xprompt.processor import execute_workflow

            os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir

            anon_workflow = create_anonymous_workflow(prompt)
            result = execute_workflow(
                anon_workflow.name,
                [],
                {"cl_name": cl_name},
                artifacts_dir=artifacts_dir,
                silent=True,
                workflow_obj=anon_workflow,
            )

            # Extract response text for chat history
            response_content = result.response_text or ""

            # Prepare and save chat history
            saved_path = save_chat_history(
                prompt=prompt,
                response=response_content,
                workflow="ace-run",
                timestamp=timestamp,
            )
            print(f"\nChat history saved to: {saved_path}")

            # Clean up SASE_ARTIFACTS_DIR env var
            os.environ.pop("SASE_ARTIFACTS_DIR", None)

            # Read plan_path from plan_path.json if written by claude.py
            plan_path: str | None = None
            plan_path_file = os.path.join(artifacts_dir, "plan_path.json")
            try:
                with open(plan_path_file, encoding="utf-8") as f:
                    plan_path = json.load(f).get("plan_path")
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass

            # Extract step_output and diff_path from workflow_state.json
            step_output, diff_path = _extract_step_output_and_diff_path(artifacts_dir)

            # Write done marker
            done_marker: dict[str, Any] = {
                "cl_name": cl_name,
                "project_file": project_file,
                "timestamp": timestamp,
                "artifacts_timestamp": artifacts_timestamp,
                "response_path": saved_path,
                "outcome": "completed",
                "workspace_num": workspace_num,
                "step_output": step_output,
                "diff_path": diff_path,
                "plan_path": plan_path,
            }
            if agent_name:
                done_marker["name"] = agent_name
            if agent_model:
                done_marker["model"] = agent_model
            if agent_llm_provider:
                done_marker["llm_provider"] = agent_llm_provider
            if agent_vcs_provider:
                done_marker["vcs_provider"] = agent_vcs_provider
            done_path = os.path.join(artifacts_dir, "done.json")
            with open(done_path, "w", encoding="utf-8") as f:
                json.dump(done_marker, f, indent=2)
            print(f"Done marker written to: {done_path}")

            success = True

        except Exception as e:
            print(f"Error running agent: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            success = False
            # Write error done marker so TUI can display the error
            try:
                error_done: dict[str, Any] = {
                    "cl_name": cl_name,
                    "project_file": project_file,
                    "timestamp": timestamp,
                    "artifacts_timestamp": artifacts_timestamp,
                    "outcome": "failed",
                    "error": f"{type(e).__qualname__}: {e}",
                    "traceback": traceback.format_exc(),
                    "workspace_num": workspace_num,
                }
                if agent_name:
                    error_done["name"] = agent_name
                if agent_model:
                    error_done["model"] = agent_model
                if agent_llm_provider:
                    error_done["llm_provider"] = agent_llm_provider
                if agent_vcs_provider:
                    error_done["vcs_provider"] = agent_vcs_provider
                done_path = os.path.join(artifacts_dir, "done.json")
                with open(done_path, "w", encoding="utf-8") as f:
                    json.dump(error_done, f, indent=2)
            except Exception:
                pass  # Best effort

        end_time = time.time()
        elapsed_seconds = int(end_time - start_time)
        duration = format_duration(elapsed_seconds)

        print()
        print(f"Agent completed with status: {'SUCCESS' if success else 'FAILED'}")
        print(f"Duration: {duration}")

    finally:
        # Clean up running marker for home mode (done.json replaces it)
        if running_marker_path and os.path.exists(running_marker_path):
            try:
                os.unlink(running_marker_path)
            except OSError:
                pass

        # Release workspace for non-home-mode agents
        if not is_home_mode:
            try:
                from sase.running_field import release_workspace

                release_workspace(project_file, workspace_num, workflow_name, cl_name)
                print("Workspace released")
            except Exception as e:
                print(f"Error releasing workspace: {e}", file=sys.stderr)

        # Write completion marker
        try:
            with open(output_path, "a") as f:
                f.write("\n=== AGENT_RUN_COMPLETE ===\n")
                f.write(f"Status: {'SUCCESS' if success else 'FAILED'}\n")
                f.write(f"Duration: {duration}\n")
        except Exception as e:
            print(f"Error writing completion marker: {e}", file=sys.stderr)

        # Skip notification if the agent was killed by the user (SIGTERM).
        # The user already knows it died because they killed it from the TUI.
        if not was_killed():
            from sase.notifications.senders import notify_workflow_complete

            extra_files = [p for p in [saved_path, diff_path] if p]
            notify_workflow_complete(
                sender="user-agent",
                cl_name=cl_name,
                success=success,
                notes=[
                    f"Agent {'completed' if success else 'failed'}: {workflow_name}"
                ],
                action="JumpToAgent",
                action_data={"cl_name": cl_name, "raw_suffix": artifacts_timestamp},
                extra_files=extra_files,
            )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
