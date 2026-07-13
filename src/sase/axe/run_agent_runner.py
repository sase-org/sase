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
import sys
import time
from datetime import UTC, datetime
from typing import Any

from sase.ace.hooks import format_duration
from sase.axe.run_agent_exec import AgentExecContext, run_execution_loop
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.axe.run_agent_phases import (
    claim_deferred_workspace,
    extract_directives_and_write_meta,
    record_run_started_at,
    resolve_agent_refs_in_prompt,
    resolve_wait_chat_paths,
    wait_for_dependencies,
    wait_for_runner_slot,
)
from sase.axe.run_agent_repeat_stop import RepeatStopDecision, detect_repeat_stop
from sase.axe.run_agent_runtime import format_agent_run_runtime
from sase.axe.run_agent_runner_cli import parse_runner_args, read_prompt_file
from sase.axe.run_agent_runner_errors import (
    RunnerErrorContext,
    record_runner_error,
)
from sase.axe.run_agent_runner_finalize import (
    classify_exec_success,
    record_completion_metrics,
    send_completion_notification,
    write_error_done_marker,
)
from sase.axe.run_agent_runner_lifecycle import (
    RunnerShutdownContext,
    RunnerShutdownDeps,
    RunnerShutdownState,
    auto_dismiss_completed_agent,
    finalize_runner_shutdown,
)
from sase.axe.run_agent_runner_repeat import finalize_repeat_stop
from sase.axe.run_agent_runner_signals import (
    install_workspace_release_sigterm_handler,
    is_user_kill_exit,
    system_exit_code,
)
from sase.axe.run_agent_runner_setup import (
    apply_retry_chain_to_meta,
    bump_spawn_telemetry,
    build_output_variable_namespaces,
    capture_sdd_base_sha,
    enter_agent_workspace,
    load_retry_handoff_from_env,
    prepare_linked_repo_workspaces_if_needed,
    prepare_workspace_if_needed,
    preprocess_prompt_xprompts,
    print_agent_start_banner,
    refresh_linked_repos_for_workspace,
    setup_artifacts_directory,
    write_submitted_xprompt_artifact,
    write_agent_meta,
    write_home_running_marker,
)
from sase.axe.runner_utils import (
    all_steps_hidden,
    install_sigterm_handler,
    was_killed,
    write_error_report,
)
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_output_variables import set_agent_output_variables
from sase.history.multi_agent_prompt import MULTI_AGENT_PROMPT_FILE_ENV
from sase.telemetry import init_telemetry, register_push_on_exit
from sase.telemetry.metrics import AGENT_KILLS

install_sigterm_handler("agent", soft=True)


def main() -> None:
    """Run agent workflow and release workspace on completion."""
    args = parse_runner_args(sys.argv)
    cl_name = args.cl_name
    project_file = args.project_file
    workspace_dir = args.workspace_dir
    output_path = args.output_path
    workspace_num = args.workspace_num
    workflow_name = args.workflow_name
    timestamp = args.timestamp
    update_target = args.update_target
    is_home_mode = args.is_home_mode
    signal_fallback_artifacts_dir: str | None = None

    def _signal_fallback_artifacts_dir() -> str | None:
        return signal_fallback_artifacts_dir

    install_workspace_release_sigterm_handler(
        project_file=project_file,
        workspace_num=workspace_num,
        workflow_name=workflow_name,
        cl_name=cl_name,
        is_home_mode=is_home_mode,
        artifacts_dir_getter=_signal_fallback_artifacts_dir,
    )

    prompt = read_prompt_file(args.prompt_file)
    submitted_xprompt = prompt

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
    video_paths: list[str] = []
    step_output: dict[str, Any] | None = None
    exec_outcome = ""
    error_summary: str | None = None
    error_traceback_str: str | None = None
    run_started_at: str | None = None
    suppress_completion_notification = False

    print_agent_start_banner(
        cl_name=cl_name,
        workspace_dir=workspace_dir,
        workflow_name=workflow_name,
        prompt=prompt,
    )

    running_marker_path: str | None = None

    project_name, artifacts_timestamp, artifacts_dir = setup_artifacts_directory(
        timestamp=timestamp,
        project_file=project_file,
        cl_name=cl_name,
        is_home_mode=is_home_mode,
    )
    signal_fallback_artifacts_dir = artifacts_dir
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

    def _error_context() -> RunnerErrorContext:
        return RunnerErrorContext(
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
        )

    retry_handoff = load_retry_handoff_from_env()

    try:
        try:
            deferred_workspace = bool(os.environ.get("SASE_AGENT_DEFERRED_WORKSPACE"))

            enter_agent_workspace(workspace_dir, workspace_num)

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

            has_dependency_wait = (
                bool(info.wait_names)
                or bool(info.wait_identity_deps)
                or info.wait_duration is not None
                or info.wait_until is not None
            )
            has_wait = has_dependency_wait or info.wait_runners is not None
            if deferred_workspace and not is_home_mode and not has_wait:
                raise RuntimeError(
                    "SASE_AGENT_DEFERRED_WORKSPACE=1 but extracted wait metadata "
                    "is empty; refusing to continue in the placeholder workspace"
                )
            wait_chats: list[str] = []
            repeat_stop: RepeatStopDecision | None = None
            if has_dependency_wait:
                wait_for_dependencies(
                    info.wait_names,
                    artifacts_dir,
                    cl_name,
                    timestamp,
                    agent_meta,
                    project_name=project_name,
                    wait_identity_deps=info.wait_identity_deps,
                    duration=info.wait_duration,
                    wait_until=info.wait_until,
                )
                repeat_stop = detect_repeat_stop()

            if repeat_stop is not None:
                bump_spawn_telemetry(
                    agent_llm_provider=agent_llm_provider,
                    project_name=project_name,
                    is_home_mode=is_home_mode,
                    workflow_name=workflow_name,
                    timestamp=timestamp,
                )
                finalize_repeat_stop(
                    decision=repeat_stop,
                    artifacts_dir=artifacts_dir,
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
                    set_output_variables=set_agent_output_variables,
                    write_done_marker=write_done_marker_and_update_index,
                )
                current_artifacts_dir = artifacts_dir
                success = True
                exec_outcome = "completed"
                suppress_completion_notification = True
            else:
                run_started_at = wait_for_runner_slot(
                    artifacts_dir,
                    cl_name,
                    timestamp,
                    agent_meta,
                    wait_runners=info.wait_runners,
                    claim=lambda: record_run_started_at(artifacts_dir, agent_meta),
                )

                bump_spawn_telemetry(
                    agent_llm_provider=agent_llm_provider,
                    project_name=project_name,
                    is_home_mode=is_home_mode,
                    workflow_name=workflow_name,
                    timestamp=timestamp,
                )

                if deferred_workspace and not is_home_mode:
                    workspace_num, workspace_dir = claim_deferred_workspace(
                        project_file,
                        project_name,
                        workflow_name,
                        cl_name,
                        artifacts_timestamp,
                    )

                prepare_workspace_if_needed(
                    workspace_dir=workspace_dir,
                    workspace_num=workspace_num,
                    cl_name=cl_name,
                    update_target=update_target,
                    project_name=project_name,
                    is_home_mode=is_home_mode,
                    retry_handoff=retry_handoff,
                )

                if deferred_workspace and not is_home_mode:
                    linked_repo_resolution = refresh_linked_repos_for_workspace(
                        project_file=project_file,
                        workspace_dir=workspace_dir,
                        workspace_num=workspace_num,
                        artifacts_dir=artifacts_dir,
                        agent_meta=agent_meta,
                    )
                    if update_target and retry_handoff is None:
                        prepare_linked_repo_workspaces_if_needed(
                            resolution=linked_repo_resolution,
                            cl_name=cl_name,
                        )
                elif update_target and not is_home_mode and retry_handoff is None:
                    linked_repo_resolution = refresh_linked_repos_for_workspace(
                        project_file=project_file,
                        workspace_dir=workspace_dir,
                        workspace_num=workspace_num,
                        artifacts_dir=artifacts_dir,
                        agent_meta=agent_meta,
                    )
                    prepare_linked_repo_workspaces_if_needed(
                        resolution=linked_repo_resolution,
                        cl_name=cl_name,
                    )

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

                if has_dependency_wait and info.wait_names:
                    wait_chats = resolve_wait_chat_paths(info.wait_names)

                prompt, vcs_tag = resolve_agent_refs_in_prompt(prompt)

                if info.approve:
                    os.environ["SASE_AGENT_AUTO_APPROVE"] = "1"

                output_variable_namespaces = build_output_variable_namespaces(
                    info.wait_names
                )

                sdd_base_sha = capture_sdd_base_sha(workspace_dir, workspace_num)
                if sdd_base_sha:
                    agent_meta["sdd_base_sha"] = sdd_base_sha
                    write_agent_meta(artifacts_dir, agent_meta)

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
                    multi_agent_prompt_file=os.environ.get(MULTI_AGENT_PROMPT_FILE_ENV),
                    wait_chats=wait_chats,
                    output_variable_namespaces=output_variable_namespaces,
                )

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
                video_paths = exec_result.video_paths
                current_artifacts_dir = exec_result.current_artifacts_dir
                step_output = exec_result.step_output

        except Exception as e:
            success = False
            error_summary, error_traceback_str = record_runner_error(
                e,
                context=_error_context(),
                write_error_done_marker=write_error_done_marker,
                agent_kills=AGENT_KILLS,
                message_prefix="Error running agent",
            )
        except SystemExit as e:
            if is_user_kill_exit(e):
                exec_outcome = "killed"
                suppress_completion_notification = True
                raise

            success = False
            error_summary, error_traceback_str = record_runner_error(
                e,
                context=_error_context(),
                write_error_done_marker=write_error_done_marker,
                agent_kills=AGENT_KILLS,
                message_prefix="Agent exited before completion",
                error_summary=f"{type(e).__qualname__}: {system_exit_code(e)}",
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
        finalize_runner_shutdown(
            context=RunnerShutdownContext(
                project_file=project_file,
                workflow_name=workflow_name,
                cl_name=cl_name,
                artifacts_timestamp=artifacts_timestamp,
                artifacts_dir=artifacts_dir,
                output_path=output_path,
                submitted_xprompt=submitted_xprompt,
                prompt=prompt,
                is_home_mode=is_home_mode,
            ),
            state=RunnerShutdownState(
                success=success,
                duration=duration,
                workspace_num=workspace_num,
                workspace_dir=workspace_dir,
                current_artifacts_dir=current_artifacts_dir,
                running_marker_path=running_marker_path,
                agent_name=agent_name,
                agent_model=agent_model,
                agent_llm_provider=agent_llm_provider,
                agent_hidden=agent_hidden,
                saved_path=saved_path,
                diff_path=diff_path,
                markdown_pdf_paths=markdown_pdf_paths,
                markdown_source_count=markdown_source_count,
                image_paths=image_paths,
                video_paths=video_paths,
                step_output=step_output,
                exec_outcome=exec_outcome,
                error_summary=error_summary,
                error_traceback_str=error_traceback_str,
                suppress_completion_notification=suppress_completion_notification,
                runtime=runtime,
            ),
            deps=RunnerShutdownDeps(
                update_artifact_index=update_agent_artifact_index_for_marker_mutation,
                was_killed=was_killed,
                all_steps_hidden=all_steps_hidden,
                write_error_report=write_error_report,
                send_completion_notification=send_completion_notification,
                auto_dismiss_completed_agent=auto_dismiss_completed_agent,
            ),
        )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
