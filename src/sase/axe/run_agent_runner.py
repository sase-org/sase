#!/usr/bin/env python3
"""Background run agent runner for sase ace TUI.

This script is launched by the ace TUI to run custom agents in the background.
It handles workspace cleanup and releases the workspace upon completion.

The core execution loop (retry, plan approval, question handling) lives in
``axe.run_agent_exec``.
"""

import json
import os
import sys
import time
from typing import Any

from sase.ace.hooks import format_duration
from sase.axe.run_agent_exec import AgentExecContext, run_execution_loop
from sase.axe.run_agent_phases import (
    build_done_marker,
    claim_deferred_workspace,
    extract_directives_and_write_meta,
    record_stop_time,
    resolve_agent_refs_in_prompt,
    wait_for_dependencies,
)
from sase.axe.runner_utils import (
    all_steps_hidden,
    install_sigterm_handler,
    prepare_workspace,
    was_killed,
    write_error_report,
)
from sase.artifacts import (
    convert_timestamp_to_artifacts_format,
    create_artifacts_directory,
)
from sase.telemetry import init_telemetry, push_metrics, register_push_on_exit
from sase.telemetry.metrics import (
    AGENT_ACTIVE,
    AGENT_RUN_DURATION,
    AGENT_RUNS,
    WORKSPACE_ACTIVE,
)

install_sigterm_handler("agent", soft=True)


def _write_repeat_state(
    path: str,
    repeat_count: int,
    current_iteration: int,
    completed_iterations: int,
) -> None:
    """Write repeat_state.json for TUI polling."""
    state = {
        "repeat_count": repeat_count,
        "current_iteration": current_iteration,
        "completed_iterations": completed_iterations,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


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

    # Initialize telemetry and register push-on-exit for this agent process
    init_telemetry()
    register_push_on_exit(job="agent_runner", workflow=workflow_name)

    start_time = time.time()
    success = False
    duration = "0s"
    saved_path: str | None = None
    diff_path: str | None = None
    step_output: dict[str, Any] | None = None
    error_summary: str | None = None
    error_traceback_str: str | None = None

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

    # Write initial workflow_state.json so the TUI can merge this entry as a
    # WORKFLOW immediately, before WorkflowExecutor.execute() overwrites it.
    _initial_state: dict[str, object] = {
        "workflow_name": "run",
        "status": "running",
        "current_step_index": 0,
        "steps": [],
        "context": {"cl_name": cl_name},
        "artifacts_dir": artifacts_dir,
        "pid": os.getpid(),
        "appears_as_agent": True,
    }
    with open(
        os.path.join(artifacts_dir, "workflow_state.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(_initial_state, f, indent=2)

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

    # Expand xprompt references so directives from xprompts (e.g.,
    # #swarm expanding to %model:opus) are available for extraction.
    # This must happen after saving raw_xprompt.md above.
    from sase.xprompt.processor import process_xprompt_references

    prompt = process_xprompt_references(prompt)

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

            # Track active agent gauge
            AGENT_ACTIVE.labels(
                llm_provider=agent_llm_provider or "", project=project_name
            ).inc()
            # Track active workspace gauge here (not in claim_workspace which
            # runs in the launcher process where telemetry is not initialized).
            if not is_home_mode:
                WORKSPACE_ACTIVE.labels(project=project_name).inc()
            # Push immediately so the pushgateway reflects the active state
            # (the atexit push only fires after gauges are decremented to 0).
            push_metrics(
                job="agent_runner",
                grouping_key={"workflow": workflow_name},
            )

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
            has_wait = (
                bool(info.wait_names)
                or info.wait_duration is not None
                or info.wait_until is not None
            )
            if has_wait:
                wait_for_dependencies(
                    info.wait_names,
                    artifacts_dir,
                    cl_name,
                    timestamp,
                    agent_meta,
                    duration=info.wait_duration,
                    wait_until=info.wait_until,
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

            # Resolve @name agent references in VCS tags (e.g., #gh:@a -> #gh:branch_name).
            # This runs after wait_for_dependencies() so referenced agents are done.
            prompt, vcs_tag = resolve_agent_refs_in_prompt(prompt)

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
                local_xprompts=info.local_xprompts,
            )

            repeat_count = info.repeat_count or 1
            if repeat_count > 1:
                # Repeat loop: run execution loop N times sequentially
                repeat_state_path = os.path.join(artifacts_dir, "repeat_state.json")
                for iteration in range(1, repeat_count + 1):
                    # Write repeat state for TUI polling
                    _write_repeat_state(
                        repeat_state_path, repeat_count, iteration, iteration - 1
                    )

                    print(f"\n=== Repeat iteration {iteration}/{repeat_count} ===\n")
                    exec_result = run_execution_loop(
                        ctx, prompt, repeat_iteration=iteration
                    )
                    success = exec_result.success
                    saved_path = exec_result.saved_path
                    diff_path = exec_result.diff_path
                    current_artifacts_dir = exec_result.current_artifacts_dir
                    step_output = exec_result.step_output

                    # Update completed count
                    _write_repeat_state(
                        repeat_state_path, repeat_count, iteration, iteration
                    )

                    if not success or was_killed():
                        if was_killed():
                            print("Repeat loop stopped by user kill")
                        else:
                            print(f"Repeat loop stopped: iteration {iteration} failed")
                        break

                # Clean up repeat_state.json
                try:
                    os.unlink(repeat_state_path)
                except OSError:
                    pass
            else:
                exec_result = run_execution_loop(ctx, prompt)
                success = exec_result.success
                saved_path = exec_result.saved_path
                diff_path = exec_result.diff_path
                current_artifacts_dir = exec_result.current_artifacts_dir
                step_output = exec_result.step_output

        except Exception as e:
            print(f"Error running agent: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            success = False
            error_summary = f"{type(e).__qualname__}: {e}"
            error_traceback_str = traceback.format_exc()
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

        # Record Prometheus agent lifecycle metrics
        _provider = agent_llm_provider or ""
        AGENT_RUNS.labels(
            llm_provider=_provider,
            status="ok" if success else "error",
            workflow=workflow_name,
        ).inc()
        AGENT_RUN_DURATION.labels(
            llm_provider=_provider, workflow=workflow_name
        ).observe(end_time - start_time)
        AGENT_ACTIVE.labels(llm_provider=_provider, project=project_name).dec()

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

        # Write error report for failed agents (before notification so it
        # can be attached as a file).
        error_report_path: str | None = None
        if not success and error_summary:
            error_report_path = write_error_report(
                current_artifacts_dir,
                agent_model=agent_model,
                agent_llm_provider=agent_llm_provider,
                workflow_name=workflow_name,
                cl_name=cl_name,
                duration=duration,
                error_summary=error_summary,
                error_traceback=error_traceback_str,
            )

        # Skip notification if the agent was killed by the user (SIGTERM).
        # The user already knows it died because they killed it from the TUI.
        # Also skip when every step in the workflow was hidden (e.g. for-loops
        # over empty lists) — there's nothing useful to report.
        if not was_killed() and not all_steps_hidden(current_artifacts_dir):
            from sase.notifications.senders import notify_workflow_complete

            extra_files = [p for p in [saved_path, diff_path] if p]

            # For failures: attach error report (first) and output log
            if not success:
                if error_report_path:
                    extra_files.insert(0, error_report_path)
                if os.path.isfile(output_path):
                    extra_files.append(output_path)

            from sase.llm_provider.registry import format_provider_model_label

            agent_label = format_provider_model_label(agent_llm_provider, agent_model)

            # Build notes — include error summary for failures
            notes = [
                f"{agent_label} {'completed' if success else 'failed'}: {workflow_name}"
            ]
            if not success and error_summary:
                notes.append(error_summary)

            # For failures with an error report, use ViewErrorReport action
            # so <enter> opens the report in $EDITOR. Otherwise JumpToAgent.
            commit_message = (step_output or {}).get("meta_commit_message")
            pr_url = (step_output or {}).get("meta_pr_url")

            if not success and error_report_path:
                action = "ViewErrorReport"
                action_data: dict[str, str] = {
                    "error_report_path": error_report_path,
                    "cl_name": cl_name,
                    "raw_suffix": artifacts_timestamp,
                    **({"agent_name": agent_name} if agent_name else {}),
                    **({"commit_message": commit_message} if commit_message else {}),
                    **({"pr_url": pr_url} if pr_url else {}),
                }
            else:
                action = "JumpToAgent"
                action_data = {
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
                    **({"commit_message": commit_message} if commit_message else {}),
                    **({"pr_url": pr_url} if pr_url else {}),
                }

            notify_workflow_complete(
                sender="user-agent",
                cl_name=cl_name,
                success=success,
                notes=notes,
                action=action,
                action_data=action_data,
                extra_files=extra_files,
            )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
