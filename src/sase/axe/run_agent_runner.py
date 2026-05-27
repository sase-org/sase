#!/usr/bin/env python3
"""Background run agent runner for sase ace TUI.

This script is launched by the ace TUI to run custom agents in the background.
It handles workspace cleanup and releases the workspace upon completion.

The core execution loop (retry, plan approval, question handling) lives in
``axe.run_agent_exec``. Pre-execution setup helpers live in
``axe.run_agent_runner_setup`` and post-execution helpers in
``axe.run_agent_runner_finalize``.
"""

import os
import signal
import sys
import time
from datetime import UTC, datetime
from typing import Any

from sase.ace.hooks import format_duration
from sase.axe.run_agent_exec import AgentExecContext, run_execution_loop
from sase.axe.run_agent_phases import (
    claim_deferred_workspace,
    extract_directives_and_write_meta,
    record_run_started_at,
    resolve_agent_refs_in_prompt,
    resolve_wait_chat_paths,
    wait_for_dependencies,
)
from sase.axe.run_agent_runtime import format_agent_run_runtime
from sase.axe.run_agent_runner_finalize import (
    classify_exec_success,
    record_completion_metrics,
    send_completion_notification,
    write_error_done_marker,
)
from sase.axe.run_agent_runner_setup import (
    apply_dynamic_memory,
    apply_retry_chain_to_meta,
    bump_spawn_telemetry,
    load_retry_handoff_from_env,
    prepare_workspace_if_needed,
    preprocess_prompt_xprompts,
    refresh_sibling_repos_for_workspace,
    setup_artifacts_directory,
    write_submitted_xprompt_artifact,
    write_home_running_marker,
)
from sase.axe.runner_utils import (
    all_steps_hidden,
    install_sigterm_handler,
    was_killed,
    write_error_report,
)
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
    update_agent_artifact_index_for_marker_mutation,
)
from sase.telemetry import init_telemetry, register_push_on_exit
from sase.telemetry.metrics import AGENT_KILLS

install_sigterm_handler("agent", soft=True)


def _system_exit_code(exc: SystemExit) -> int | None:
    """Return the integer exit code for ``SystemExit`` when one is available."""
    return exc.code if isinstance(exc.code, int) else None


def _is_user_kill_exit(exc: SystemExit) -> bool:
    """Return whether ``SystemExit`` represents an explicit user kill."""
    return was_killed() or _system_exit_code(exc) == 128 + signal.SIGTERM


def _auto_dismiss_completed_agent(cl_name: str, artifacts_timestamp: str) -> None:
    """Persist auto-dismiss identities for a completed background run."""
    try:
        from sase.ace.dismissed_agents import (
            load_dismissed_agents,
            save_dismissed_agents,
        )
        from sase.ace.tui.models.agent import AgentType

        dismissed = load_dismissed_agents()
        # Dismiss both RUNNING and WORKFLOW identities -- dedup may pick
        # either depending on whether workflow_state.json exists.
        identities = {
            (AgentType.RUNNING, cl_name, artifacts_timestamp),
            (AgentType.WORKFLOW, cl_name, artifacts_timestamp),
        }
        dismissed.update(identities)
        if save_dismissed_agents(dismissed):
            sync_dismissed_agent_artifact_index(dismissed, added=identities)
    except Exception:
        pass  # Best effort


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
        submitted_xprompt = prompt
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
    register_push_on_exit(
        job="agent_runner", workflow=workflow_name, instance=timestamp
    )

    start_time = time.time()
    success = False
    duration = "0s"
    runtime: str | None = None
    saved_path: str | None = None
    diff_path: str | None = None
    markdown_pdf_paths: list[str] = []
    markdown_source_count = 0
    image_paths: list[str] = []
    step_output: dict[str, Any] | None = None
    exec_outcome = ""
    error_summary: str | None = None
    error_traceback_str: str | None = None
    run_started_at: str | None = None
    suppress_completion_notification = False

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

    project_name, artifacts_timestamp, artifacts_dir = setup_artifacts_directory(
        timestamp=timestamp,
        project_file=project_file,
        cl_name=cl_name,
        is_home_mode=is_home_mode,
    )
    try:
        write_submitted_xprompt_artifact(artifacts_dir, submitted_xprompt)
    except OSError as e:
        print(f"Warning: Failed to write submitted_xprompt.md: {e}", file=sys.stderr)

    prompt, vcs_tag, raw_resolved_prompt = preprocess_prompt_xprompts(
        prompt, artifacts_dir
    )

    # Defaults for agent metadata (populated later, but needed by error handler)
    agent_name: str | None = None
    agent_model: str | None = None
    agent_llm_provider: str | None = None
    agent_vcs_provider: str | None = None
    agent_hidden: bool = False
    # Initialize current_artifacts_dir so it's always defined for cleanup
    current_artifacts_dir = artifacts_dir

    # Spawn-on-retry: detect the retry handoff env var. When set, this
    # process is a retry child whose workspace was transferred from the
    # failing parent; we must NOT call prepare_workspace (which would
    # wipe the parent's in-progress file edits) and must record the
    # retry-chain pointers into agent_meta.json so the TUI loader can
    # build the chain.
    retry_handoff = load_retry_handoff_from_env()

    try:
        try:
            deferred_workspace = bool(os.environ.get("SASE_AGENT_DEFERRED_WORKSPACE"))

            # Change to the allocated workspace before prompt-derived metadata
            # is published. Workspace preparation runs after metadata so launch
            # surfaces can resolve the claimed agent name while prep is busy.
            os.chdir(workspace_dir)
            os.environ["SASE_ACTIVE_PROJECT_DIR"] = workspace_dir

            # Keep ``.sase/`` untracked in this clone so embedded ``#git``
            # pre-steps that run ``git clean -fd`` do not wipe dynamic-memory
            # files written below. ``.git/info/exclude`` is git's per-clone,
            # untracked ignore file and is honored by ``git clean`` identically
            # to ``.gitignore`` entries.
            from sase.workspace_provider.git_exclude import (
                ensure_git_info_exclude_entry,
            )

            ensure_git_info_exclude_entry(workspace_dir, ".sase/")

            # Generate dynamic memory before agent starts. The on-disk files
            # written here may be wiped by embedded-workflow pre-steps (e.g.
            # `hg clean`); preprocess_prompt_late() re-writes them via
            # rewrite_dynamic_memory_for_prompt() before file-reference
            # validation.
            prompt = apply_dynamic_memory(prompt, project_name, artifacts_dir)

            # Extract directives and write agent metadata
            info = extract_directives_and_write_meta(
                prompt,
                workspace_dir,
                artifacts_dir,
                cl_name=cl_name,
                raw_resolved_prompt=raw_resolved_prompt,
            )
            agent_name = info.name
            agent_model = info.model
            agent_llm_provider = info.llm_provider
            agent_vcs_provider = info.vcs_provider
            agent_hidden = info.hidden
            agent_meta = info.meta

            agent_meta = apply_retry_chain_to_meta(
                retry_handoff=retry_handoff,
                agent_meta=agent_meta,
                artifacts_dir=artifacts_dir,
            )

            # Prepare normal workspaces before running the agent.  Deferred
            # %wait agents still have only their placeholder workspace here;
            # their real workspace is claimed and prepared after the wait.
            if deferred_workspace and not is_home_mode:
                print(
                    "=== Skipping workspace prep "
                    "(deferred workspace; waiting for dependencies) ==="
                )
                print()
            else:
                prepare_workspace_if_needed(
                    workspace_dir=workspace_dir,
                    cl_name=cl_name,
                    update_target=update_target,
                    project_name=project_name,
                    is_home_mode=is_home_mode,
                    retry_handoff=retry_handoff,
                )

            bump_spawn_telemetry(
                agent_llm_provider=agent_llm_provider,
                project_name=project_name,
                is_home_mode=is_home_mode,
                workflow_name=workflow_name,
                timestamp=timestamp,
            )

            # Write running marker for home mode (no workspace tracking available)
            if is_home_mode:
                running_marker_path = write_home_running_marker(
                    artifacts_dir=artifacts_dir,
                    cl_name=cl_name,
                    timestamp=timestamp,
                    prompt=prompt,
                    agent_model=agent_model,
                    agent_llm_provider=agent_llm_provider,
                    agent_vcs_provider=agent_vcs_provider,
                    workspace_dir=workspace_dir,
                )

            # Wait for dependencies if %wait directives are present
            has_wait = (
                bool(info.wait_names)
                or info.wait_duration is not None
                or info.wait_until is not None
            )
            if deferred_workspace and not is_home_mode and not has_wait:
                raise RuntimeError(
                    "SASE_AGENT_DEFERRED_WORKSPACE=1 but extracted wait metadata "
                    "is empty; refusing to continue in the placeholder workspace"
                )
            wait_chats: list[str] = []
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

                if info.wait_names:
                    wait_chats = resolve_wait_chat_paths(info.wait_names)

                # Allocate real workspace now that dependencies are resolved
                if os.environ.get("SASE_AGENT_DEFERRED_WORKSPACE") and not is_home_mode:
                    workspace_num, workspace_dir = claim_deferred_workspace(
                        project_file,
                        project_name,
                        workflow_name,
                        cl_name,
                        artifacts_timestamp,
                    )
                    prepare_workspace_if_needed(
                        workspace_dir=workspace_dir,
                        cl_name=cl_name,
                        update_target=update_target,
                        project_name=project_name,
                        is_home_mode=is_home_mode,
                        retry_handoff=retry_handoff,
                    )
                    prompt = refresh_sibling_repos_for_workspace(
                        project_file=project_file,
                        workspace_dir=workspace_dir,
                        workspace_num=workspace_num,
                        artifacts_dir=artifacts_dir,
                        agent_meta=agent_meta,
                        prompt=prompt,
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
                wait_chats=wait_chats,
            )

            run_started_at = record_run_started_at(artifacts_dir, agent_meta)
            exec_result = run_execution_loop(ctx, prompt)
            exec_outcome = exec_result.outcome
            success = classify_exec_success(
                success=exec_result.success,
                outcome=exec_outcome,
            )
            saved_path = exec_result.saved_path
            diff_path = exec_result.diff_path
            markdown_pdf_paths = exec_result.markdown_pdf_paths
            markdown_source_count = exec_result.markdown_source_count
            image_paths = exec_result.image_paths
            current_artifacts_dir = exec_result.current_artifacts_dir
            step_output = exec_result.step_output

        except Exception as e:
            print(f"Error running agent: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            success = False
            error_summary = f"{type(e).__qualname__}: {e}"
            error_traceback_str = traceback.format_exc()
            AGENT_KILLS.labels(reason="error").inc()
            write_error_done_marker(
                current_artifacts_dir=current_artifacts_dir,
                cl_name=cl_name,
                project_file=project_file,
                timestamp=timestamp,
                artifacts_timestamp=artifacts_timestamp,
                workspace_num=workspace_num,
                workspace_dir=workspace_dir,
                output_path=output_path,
                agent_name=agent_name,
                agent_model=agent_model,
                agent_llm_provider=agent_llm_provider,
                agent_vcs_provider=agent_vcs_provider,
                agent_hidden=agent_hidden,
                error=error_summary,
                traceback_str=error_traceback_str,
            )
        except SystemExit as e:
            if _is_user_kill_exit(e):
                exec_outcome = "killed"
                suppress_completion_notification = True
                raise

            print(f"Agent exited before completion: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            success = False
            error_summary = f"{type(e).__qualname__}: {_system_exit_code(e)}"
            error_traceback_str = traceback.format_exc()
            AGENT_KILLS.labels(reason="error").inc()
            write_error_done_marker(
                current_artifacts_dir=current_artifacts_dir,
                cl_name=cl_name,
                project_file=project_file,
                timestamp=timestamp,
                artifacts_timestamp=artifacts_timestamp,
                workspace_num=workspace_num,
                workspace_dir=workspace_dir,
                output_path=output_path,
                agent_name=agent_name,
                agent_model=agent_model,
                agent_llm_provider=agent_llm_provider,
                agent_vcs_provider=agent_vcs_provider,
                agent_hidden=agent_hidden,
                error=error_summary,
                traceback_str=error_traceback_str,
            )

        completion_time = datetime.now(UTC)
        end_time = completion_time.timestamp()
        elapsed_seconds = int(end_time - start_time)
        duration = format_duration(elapsed_seconds)

        record_completion_metrics(
            success=success,
            duration_seconds=end_time - start_time,
            agent_llm_provider=agent_llm_provider,
            agent_model=agent_model,
            workflow_name=workflow_name,
            project_name=project_name,
            cl_name=cl_name,
            workspace_num=workspace_num,
            artifacts_dir=artifacts_dir,
            current_artifacts_dir=current_artifacts_dir,
            prompt=prompt,
            completion_time=completion_time,
        )
        runtime = format_agent_run_runtime(
            launch_timestamp_suffix=artifacts_timestamp,
            run_started_at=run_started_at,
            completion_time=completion_time,
        )

        print()
        print(f"Agent completed with status: {'SUCCESS' if success else 'FAILED'}")
        print(f"Duration: {duration}")

    finally:
        # Clean up running marker for home mode (done.json replaces it)
        if running_marker_path and os.path.exists(running_marker_path):
            try:
                os.unlink(running_marker_path)
                update_agent_artifact_index_for_marker_mutation(artifacts_dir)
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
            _auto_dismiss_completed_agent(cl_name, artifacts_timestamp)

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
                submitted_xprompt=submitted_xprompt,
                workspace_dir=workspace_dir,
                output_path=output_path,
                agent_name=agent_name,
            )

        # Skip notification if the agent was killed by the user (SIGTERM).
        # The user already knows it died because they killed it from the TUI.
        # Also skip when every step in the workflow was hidden (e.g. for-loops
        # over empty lists) — there's nothing useful to report.
        if (
            not suppress_completion_notification
            and not was_killed()
            and not all_steps_hidden(current_artifacts_dir)
        ):
            send_completion_notification(
                cl_name=cl_name,
                artifacts_timestamp=artifacts_timestamp,
                workflow_name=workflow_name,
                success=success,
                agent_hidden=agent_hidden,
                agent_name=agent_name,
                agent_model=agent_model,
                agent_llm_provider=agent_llm_provider,
                error_summary=error_summary,
                error_report_path=error_report_path,
                saved_path=saved_path,
                diff_path=diff_path,
                current_artifacts_dir=current_artifacts_dir,
                markdown_pdf_paths=markdown_pdf_paths,
                markdown_source_count=markdown_source_count,
                image_paths=image_paths,
                output_path=output_path,
                step_output=step_output,
                prompt=prompt,
                outcome=exec_outcome,
                runtime=runtime,
            )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
