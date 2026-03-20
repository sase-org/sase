#!/usr/bin/env python3
"""Background run agent runner for sase ace TUI.

This script is launched by the ace TUI to run custom agents in the background.
It handles workspace cleanup and releases the workspace upon completion.

The core execution loop (retry, plan approval, question handling) lives in
``axe_run_agent_exec``.
"""

import json
import os
import sys
import time
from typing import Any

from sase.ace.hooks import format_duration
from sase.axe_run_agent_exec import AgentExecContext, run_execution_loop
from sase.axe_run_agent_phases import (
    build_done_marker,
    claim_deferred_workspace,
    extract_directives_and_write_meta,
    record_stop_time,
    wait_for_dependencies,
)
from sase.axe_runner_utils import (
    all_steps_hidden,
    install_sigterm_handler,
    prepare_workspace,
    was_killed,
)
from sase.shared_utils import (
    convert_timestamp_to_artifacts_format,
    create_artifacts_directory,
)

install_sigterm_handler("agent", soft=True)


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

    # Resolve aliases before saving so the TUI shows canonical names
    from sase.xprompt import resolve_xprompt_aliases

    prompt = resolve_xprompt_aliases(prompt)

    # Extract VCS workflow tag from the raw prompt before xprompt expansion.
    # This is needed to prepend the tag to follow-up agents (.code, .epic).
    from sase.xprompt._parsing import extract_vcs_workflow_tag

    vcs_tag = extract_vcs_workflow_tag(prompt)

    # Save raw xprompt for TUI display (before any preprocessing)
    raw_xprompt_path = os.path.join(artifacts_dir, "raw_xprompt.md")
    with open(raw_xprompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    # Load local xprompts from env var (set by multi-prompt launcher)
    # before expanding, so local xprompts like #_docs:telegram are expanded.
    from sase.xprompt.models import XPrompt

    local_xprompts: dict[str, XPrompt] = {}
    env_xprompts_path = os.environ.pop("SASE_AGENT_LOCAL_XPROMPTS", None)
    if env_xprompts_path:
        try:
            from sase.multi_prompt_launcher import deserialize_local_xprompts

            local_xprompts = deserialize_local_xprompts(env_xprompts_path)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    # Expand xprompt references so directives from xprompts (e.g.,
    # #swarm expanding to %model:opus) are available for extraction.
    # This must happen after saving raw_xprompt.md above.
    from sase.xprompt.processor import process_xprompt_references

    prompt = process_xprompt_references(prompt, extra_xprompts=local_xprompts or None)

    # Defaults for agent metadata (populated later, but needed by error handler)
    agent_name: str | None = None
    agent_model: str | None = None
    agent_llm_provider: str | None = None
    agent_vcs_provider: str | None = None
    agent_hidden: bool = False
    # Initialize current_artifacts_dir so it's always defined for cleanup
    current_artifacts_dir = artifacts_dir

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

            # Extract directives and write agent metadata
            info = extract_directives_and_write_meta(
                prompt, workspace_dir, artifacts_dir
            )
            agent_name = info.name
            agent_model = info.model
            agent_llm_provider = info.llm_provider
            agent_vcs_provider = info.vcs_provider
            agent_hidden = info.hidden
            agent_meta = info.meta

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
            if info.wait_names:
                wait_for_dependencies(
                    info.wait_names, artifacts_dir, cl_name, timestamp, agent_meta
                )

                # Allocate real workspace now that dependencies are resolved
                if os.environ.get("SASE_AGENT_DEFERRED_WORKSPACE") and not is_home_mode:
                    workspace_num, workspace_dir = claim_deferred_workspace(
                        project_file,
                        project_name,
                        workflow_name,
                        cl_name,
                        artifacts_timestamp,
                    )

            if info.approve:
                os.environ["SASE_AGENT_AUTO_APPROVE"] = "1"

            ctx = AgentExecContext(
                cl_name=cl_name,
                project_file=project_file,
                workspace_dir=workspace_dir,
                output_path=output_path,
                workspace_num=workspace_num,
                timestamp=timestamp,
                update_target=update_target,
                project_name=project_name,
                is_home_mode=is_home_mode,
                artifacts_dir=artifacts_dir,
                artifacts_timestamp=artifacts_timestamp,
                vcs_tag=vcs_tag,
                agent_name=agent_name,
                agent_model=agent_model,
                agent_llm_provider=agent_llm_provider,
                agent_vcs_provider=agent_vcs_provider,
                agent_hidden=agent_hidden,
                agent_meta=agent_meta,
            )
            exec_result = run_execution_loop(ctx, prompt)
            success = exec_result.success
            saved_path = exec_result.saved_path
            diff_path = exec_result.diff_path
            current_artifacts_dir = exec_result.current_artifacts_dir

        except Exception as e:
            print(f"Error running agent: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            success = False
            # Write error done marker so TUI can display the error
            try:
                error_done = build_done_marker(
                    cl_name,
                    project_file,
                    timestamp,
                    artifacts_timestamp,
                    workspace_num,
                    output_path,
                    "failed",
                    agent_name=agent_name,
                    agent_model=agent_model,
                    agent_llm_provider=agent_llm_provider,
                    agent_vcs_provider=agent_vcs_provider,
                    agent_hidden=agent_hidden,
                    error=f"{type(e).__qualname__}: {e}",
                    traceback_str=traceback.format_exc(),
                )
                done_path = os.path.join(current_artifacts_dir, "done.json")
                with open(done_path, "w", encoding="utf-8") as f:
                    json.dump(error_done, f, indent=2)
            except Exception:
                pass  # Best effort

        end_time = time.time()
        elapsed_seconds = int(end_time - start_time)
        duration = format_duration(elapsed_seconds)

        # Record stop time in agent_meta.json for TUI timestamp display
        record_stop_time(artifacts_dir, current_artifacts_dir)

        # Log structured agent run record
        try:
            from sase.logs.run_log import log_agent_run

            log_agent_run(
                workflow=workflow_name,
                project=project_name,
                branch_or_workspace=cl_name,
                workspace_num=workspace_num,
                model=agent_model,
                llm_provider=agent_llm_provider,
                duration_seconds=end_time - start_time,
                status="success" if success else "failed",
                artifacts_dir=current_artifacts_dir,
                prompt_preview=prompt[:100] if prompt else None,
            )
        except Exception:
            pass  # Best effort

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

        # Auto-dismiss if launched by a run_every lumberjack chop, so
        # recurring infrastructure agents don't accumulate as "done" entries.
        if os.environ.get("SASE_AGENT_AUTO_DISMISS"):
            try:
                from sase.ace.dismissed_agents import (
                    load_dismissed_agents,
                    save_dismissed_agents,
                )
                from sase.ace.tui.models.agent import AgentType

                dismissed = load_dismissed_agents()
                # Dismiss both RUNNING and WORKFLOW identities — dedup may
                # pick either depending on whether workflow_state.json exists.
                dismissed.add((AgentType.RUNNING, cl_name, artifacts_timestamp))
                dismissed.add((AgentType.WORKFLOW, cl_name, artifacts_timestamp))
                save_dismissed_agents(dismissed)
            except Exception:
                pass  # Best effort

        # Skip notification if the agent was killed by the user (SIGTERM).
        # The user already knows it died because they killed it from the TUI.
        # Also skip when every step in the workflow was hidden (e.g. for-loops
        # over empty lists) — there's nothing useful to report.
        if not was_killed() and not all_steps_hidden(current_artifacts_dir):
            from sase.notifications.senders import notify_workflow_complete

            extra_files = [p for p in [saved_path, diff_path] if p]
            from sase.llm_provider.registry import format_provider_model_label

            agent_label = format_provider_model_label(agent_llm_provider, agent_model)
            notify_workflow_complete(
                sender="user-agent",
                cl_name=cl_name,
                success=success,
                notes=[
                    f"{agent_label} {'completed' if success else 'failed'}: {workflow_name}"
                ],
                action="JumpToAgent",
                action_data={
                    "cl_name": cl_name,
                    "raw_suffix": artifacts_timestamp,
                    **({"agent_name": agent_name} if agent_name else {}),
                    **({"model": agent_model} if agent_model else {}),
                    **(
                        {"llm_provider": agent_llm_provider}
                        if agent_llm_provider
                        else {}
                    ),
                    "prompt": prompt,
                },
                extra_files=extra_files,
            )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
