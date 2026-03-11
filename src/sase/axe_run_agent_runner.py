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
from sase.axe_runner_utils import (
    all_steps_hidden,
    install_sigterm_handler,
    prepare_workspace,
    was_killed,
)
from sase.chat_history import save_chat_history
from sase.chat_history_extras import format_extra_sections
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

    # Track running marker path for cleanup (home mode only)
    running_marker_path: str | None = None

    # Compute artifacts early so error handler can write done.json
    if is_home_mode:
        project_name = "home"
    else:
        project_name = os.path.basename(os.path.dirname(project_file))
    artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
    artifacts_dir = create_artifacts_directory(
        "ace-run",
        project_name=project_name,
        timestamp=timestamp,
    )

    # Save raw xprompt for TUI display (before any preprocessing)
    raw_xprompt_path = os.path.join(artifacts_dir, "raw_xprompt.md")
    with open(raw_xprompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    # Defaults for agent metadata (populated later, but needed by error handler)
    agent_name: str | None = None
    agent_model: str | None = None
    agent_llm_provider: str | None = None
    agent_vcs_provider: str | None = None
    agent_hidden: bool = False
    attempt: int = 1

    try:
        try:
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
                    raise RuntimeError("Failed to prepare workspace")
                print("===========================")
                print()

            # Change to workspace directory
            os.chdir(workspace_dir)

            # Extract model directive and detect VCS before preprocessing
            from sase.llm_provider.registry import (
                get_default_provider_name,
                get_provider,
            )
            from sase.vcs_provider._registry import detect_vcs
            from sase.xprompt import process_xprompt_references
            from sase.xprompt.directives import extract_prompt_directives

            # Expand xprompts before extracting directives so that
            # directives embedded in xprompts (e.g. %model:#pro inside
            # #mentor) are discovered for agent metadata.
            expanded_for_directives = process_xprompt_references(prompt)
            _, directives = extract_prompt_directives(expanded_for_directives)
            agent_name = directives.name
            agent_wait_names = directives.wait
            agent_model = directives.model
            agent_llm_provider = get_default_provider_name()
            if not agent_model:
                provider = get_provider()
                agent_model = provider.resolve_model_name()

            vcs_name = detect_vcs(workspace_dir)
            if vcs_name:
                from sase.workspace_provider import get_display_name_by_vcs

                agent_vcs_provider = get_display_name_by_vcs(vcs_name)
            else:
                agent_vcs_provider = None

            # Persist model, provider, VCS, name, and wait_for to agent_meta.json
            agent_meta: dict[str, Any] = {"pid": os.getpid()}
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
            if directives.approve:
                agent_meta["approve"] = True
            if directives.hide:
                agent_meta["hidden"] = True
                agent_hidden = True
            if directives.plan:
                agent_meta["plan"] = True
            if agent_meta:
                meta_path = os.path.join(artifacts_dir, "agent_meta.json")
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(agent_meta, f, indent=2)

                if agent_name:
                    from sase.agent_names import claim_agent_name

                    claim_agent_name(agent_name, artifacts_dir)

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

                # Record actual run start time in agent_meta.json so the
                # thinking panel can filter out JSONL files from the wait period.
                from datetime import UTC, datetime

                agent_meta["run_started_at"] = datetime.now(UTC).isoformat()
                meta_path = os.path.join(artifacts_dir, "agent_meta.json")
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(agent_meta, f, indent=2)

                # Allocate real workspace now that dependencies are resolved
                if os.environ.get("SASE_AGENT_DEFERRED_WORKSPACE") and not is_home_mode:
                    from sase.running_field import (
                        claim_workspace as claim_ws,
                        get_workspace_directory_for_num,
                        get_first_available_axe_workspace,
                        release_workspace,
                    )

                    # Release the placeholder workspace_num=0 claim
                    release_workspace(project_file, 0, workflow_name, cl_name)

                    # Allocate a real workspace
                    vcs_wf_type = os.environ.get("SASE_AGENT_VCS_WORKFLOW_TYPE")
                    if vcs_wf_type:
                        from sase.workspace_provider import (
                            get_workspace_directory as ws_get_dir,
                            get_pre_allocated_env_prefix,
                        )

                        workspace_num = get_first_available_axe_workspace(project_file)
                        workspace_dir = ws_get_dir(
                            vcs_wf_type,
                            workspace_num,
                            project_name,
                            os.getcwd(),
                        )

                        # Set pre-allocation env vars for embedded workflows
                        prefix = get_pre_allocated_env_prefix(vcs_wf_type)
                        if prefix:
                            os.environ[f"{prefix}_PRE_ALLOCATED"] = "1"
                            os.environ[f"{prefix}_WORKSPACE_NUM"] = str(workspace_num)
                            os.environ[f"{prefix}_WORKSPACE_DIR"] = workspace_dir
                    else:
                        workspace_num = get_first_available_axe_workspace(project_file)
                        workspace_dir, _ = get_workspace_directory_for_num(
                            workspace_num, project_name
                        )

                    # Claim the real workspace
                    if not claim_ws(
                        project_file,
                        workspace_num,
                        workflow_name,
                        os.getpid(),
                        cl_name,
                        artifacts_timestamp=artifacts_timestamp,
                    ):
                        print(
                            f"Failed to claim workspace #{workspace_num}",
                            file=sys.stderr,
                        )
                        sys.exit(1)

                    os.chdir(workspace_dir)
                    print(f"Claimed workspace #{workspace_num}: {workspace_dir}")

            # Create anonymous workflow and execute through WorkflowExecutor
            from sase.xprompt.models import create_anonymous_workflow
            from sase.xprompt.workflow_runner import execute_workflow

            os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir
            if directives.approve:
                os.environ["SASE_AGENT_AUTO_APPROVE"] = "1"
            if directives.plan:
                os.environ["SASE_AGENT_PLAN_MODE"] = "1"

            # Load max retries from config
            from sase.axe.config import load_axe_config

            axe_cfg = load_axe_config()
            max_retries = axe_cfg.max_agent_retries

            anon_workflow = create_anonymous_workflow(prompt)

            # Patterns in response text that indicate transient/retriable failures.
            # These occur when invoke_agent() catches a subprocess error and returns
            # the error content as a "successful" AIMessage instead of raising.
            _RETRIABLE_PATTERNS = [
                "Error running LLM provider command",
                "exceeded your current quota",
                "RetryableQuotaError",
                "rate limit",
                "Per user memory limit reached",
                "RESOURCE_EXHAUSTED",
                "500 Internal Server Error",
                "503 Service Unavailable",
                "overloaded",
            ]

            def _is_retriable_response(response_text: str | None) -> bool:
                """Check if a workflow response indicates a transient failure."""
                if not response_text:
                    return False
                text_lower = response_text.lower()
                return any(p.lower() in text_lower for p in _RETRIABLE_PATTERNS)

            # Retry loop for transient failures
            result = None
            last_error: Exception | str | None = None
            for attempt in range(1, max_retries + 1):
                if attempt > 1:
                    # Update agent_meta.json with retry attempt number
                    agent_meta["retry_attempt"] = attempt
                    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(agent_meta, f, indent=2)
                    print(f"\n=== RETRY ATTEMPT {attempt}/{max_retries} ===\n")

                    # Re-create the anonymous workflow for a fresh execution
                    anon_workflow = create_anonymous_workflow(prompt)

                try:
                    result = execute_workflow(
                        anon_workflow.name,
                        [],
                        {"cl_name": cl_name},
                        artifacts_dir=artifacts_dir,
                        silent=True,
                        workflow_obj=anon_workflow,
                    )

                    # Check if the "successful" response actually contains
                    # a transient error (invoke_agent swallows exceptions)
                    if _is_retriable_response(result.response_text):
                        error_snippet = (result.response_text or "")[:200]
                        if attempt < max_retries:
                            print(
                                f"Attempt {attempt}/{max_retries} failed "
                                f"(retriable error in response): {error_snippet}",
                                file=sys.stderr,
                            )
                            last_error = error_snippet
                            time.sleep(5)
                            continue
                        else:
                            print(
                                f"Attempt {attempt}/{max_retries} failed "
                                f"(max retries reached): {error_snippet}",
                                file=sys.stderr,
                            )
                            last_error = error_snippet
                    else:
                        last_error = None
                        break

                except Exception as retry_exc:
                    last_error = retry_exc
                    if attempt < max_retries:
                        import traceback as tb_mod

                        print(
                            f"Attempt {attempt}/{max_retries} failed: {retry_exc}",
                            file=sys.stderr,
                        )
                        tb_mod.print_exc()
                        # Brief delay before retry
                        time.sleep(5)
                    else:
                        print(
                            f"Attempt {attempt}/{max_retries} failed "
                            f"(max retries reached): {retry_exc}",
                            file=sys.stderr,
                        )

            if last_error is not None:
                if isinstance(last_error, Exception):
                    raise last_error
                raise RuntimeError(last_error)
            assert result is not None

            # Extract response text for chat history
            response_content = result.response_text or ""

            # Prepare and save chat history
            extra = format_extra_sections(artifacts_dir)
            saved_path = save_chat_history(
                prompt=prompt,
                response=response_content,
                workflow="ace-run",
                timestamp=timestamp,
                extra_sections=extra,
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
                "output_path": output_path,
            }
            if agent_name:
                done_marker["name"] = agent_name
            if agent_model:
                done_marker["model"] = agent_model
            if agent_llm_provider:
                done_marker["llm_provider"] = agent_llm_provider
            if agent_vcs_provider:
                done_marker["vcs_provider"] = agent_vcs_provider
            if attempt > 1:
                done_marker["retry_attempt"] = attempt
            if agent_hidden:
                done_marker["hidden"] = True
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
                    "output_path": output_path,
                }
                if agent_name:
                    error_done["name"] = agent_name
                if agent_model:
                    error_done["model"] = agent_model
                if agent_llm_provider:
                    error_done["llm_provider"] = agent_llm_provider
                if agent_vcs_provider:
                    error_done["vcs_provider"] = agent_vcs_provider
                if attempt > 1:
                    error_done["retry_attempt"] = attempt
                if agent_hidden:
                    error_done["hidden"] = True
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
        # Also skip when every step in the workflow was hidden (e.g. for-loops
        # over empty lists) — there's nothing useful to report.
        if not was_killed() and not all_steps_hidden(artifacts_dir):
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
                action_data={
                    "cl_name": cl_name,
                    "raw_suffix": artifacts_timestamp,
                    **({"agent_name": agent_name} if agent_name else {}),
                    "prompt": prompt,
                },
                extra_files=extra_files,
            )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
