#!/usr/bin/env python3
"""Background run agent runner for sase ace TUI.

This script is launched by the ace TUI to run custom agents in the background.
It handles workspace cleanup and releases the workspace upon completion.

``main`` owns admission control -- dependency waits, code refresh, repeat-stop
detection, and runner-slot queueing -- and delegates the phases around it:
pre-wait bootstrap to ``axe.run_agent_runner_bootstrap``, post-admission
workspace preparation and execution to ``axe.run_agent_runner_launch``, the
core execution loop to ``axe.run_agent_exec``, and completion/shutdown to
``axe.run_agent_runner_finalize`` and ``axe.run_agent_runner_lifecycle``. The
run state they all share lives in ``axe.run_agent_runner_state``.
"""

import os
import sys
from datetime import UTC, datetime

from sase.ace.hooks import format_duration
from sase.artifacts import convert_timestamp_to_artifacts_format, launch_artifacts_dir
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.axe.run_agent_phases import (
    record_run_started_at,
    wait_for_dependencies,
    wait_for_runner_slot,
)
from sase.axe.run_agent_repeat_stop import RepeatStopDecision, detect_repeat_stop
from sase.axe.run_agent_runtime import format_agent_run_runtime
from sase.axe.run_agent_runner_bootstrap import RunnerBootstrap, bootstrap_agent_run
from sase.axe.run_agent_runner_cli import parse_runner_args
from sase.axe.run_agent_runner_errors import record_runner_error
from sase.axe.run_agent_runner_finalize import (
    record_completion_metrics,
    send_completion_notification,
    write_error_done_marker,
)
from sase.axe.run_agent_runner_launch import launch_agent_run
from sase.axe.run_agent_runner_lifecycle import (
    RunnerShutdownDeps,
    auto_dismiss_completed_agent,
    finalize_runner_shutdown,
)
from sase.axe.run_agent_runner_repeat import finalize_repeat_stop
from sase.axe.run_agent_runner_refresh import (
    refresh_runner_code_after_wait,
    runner_code_identity,
)
from sase.axe.run_agent_runner_setup import (
    bump_spawn_telemetry,
    expand_deferred_launch_xprompts,
)
from sase.axe.run_agent_runner_signals import is_user_kill_exit, system_exit_code
from sase.axe.run_agent_runner_state import RunnerRunState
from sase.axe.runner_artifacts import all_steps_hidden
from sase.axe.runner_reporting import write_error_report
from sase.axe.runner_signals import install_sigterm_handler, was_killed
from sase.axe.source_skew import snapshot_source_revision
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_output_variables import set_agent_output_variables
from sase.telemetry.metrics import AGENT_KILLS

install_sigterm_handler("agent", soft=True)

# Editable sase installs can fast-forward while a detached runner spends hours
# waiting. Capture the imported code's checkout identity before that wait starts.
_STARTUP_CODE_IDENTITY = runner_code_identity()

# A `sase dev update` can also swap the source out from under a runner that is
# already past its wait, where re-exec is no longer an option. Record the boot
# revision so a later deferred-import failure can name the swap that caused it.
snapshot_source_revision()


def _build_run_state(argv: list[str]) -> RunnerRunState:
    """Derive the run's launch and artifact identity from argv.

    Parsing is the only operation that intentionally precedes error recording:
    malformed argv may not contain enough launch identity to locate artifacts.
    For valid argv, the artifact identity is derived up front so even a failure
    while creating/seeding the directory has a best-effort ``done.json``
    destination.
    """
    args = parse_runner_args(argv)
    project_name = (
        "home"
        if args.is_home_mode
        else os.path.basename(os.path.dirname(args.project_file))
    )
    return RunnerRunState(
        cl_name=args.cl_name,
        project_file=args.project_file,
        prompt_file=args.prompt_file,
        output_path=args.output_path,
        workflow_name=args.workflow_name,
        timestamp=args.timestamp,
        update_target=args.update_target,
        is_home_mode=args.is_home_mode,
        workspace_dir=args.workspace_dir,
        workspace_num=args.workspace_num,
        project_name=project_name,
        artifacts_timestamp=convert_timestamp_to_artifacts_format(args.timestamp),
        artifacts_dir=launch_artifacts_dir(project_name, args.timestamp),
    )


def _wait_for_dependencies_phase(
    state: RunnerRunState,
    bootstrap: RunnerBootstrap,
) -> bool:
    """Block on this run's declared dependencies; return whether it blocked."""
    if not bootstrap.has_dependency_wait:
        return False
    info = bootstrap.info
    return wait_for_dependencies(
        info.wait_names,
        state.artifacts_dir,
        state.cl_name,
        state.timestamp,
        bootstrap.agent_meta,
        project_name=state.project_name,
        wait_identity_deps=info.wait_identity_deps,
        wait_beads=info.wait_beads,
        duration=info.wait_duration,
        wait_until=info.wait_until,
    )


def _finalize_repeat_stop_slot(
    state: RunnerRunState,
    decision: RepeatStopDecision,
) -> None:
    """Close this repeat slot as a successful skipped STOP slot."""
    finalize_repeat_stop(
        decision=decision,
        artifacts_dir=state.artifacts_dir,
        cl_name=state.cl_name,
        project_file=state.project_file,
        timestamp=state.timestamp,
        artifacts_timestamp=state.artifacts_timestamp,
        workspace_num=state.workspace_num,
        workspace_dir=state.workspace_dir,
        output_path=state.output_path,
        agent_name=state.agent_name,
        agent_model=state.agent_model,
        agent_llm_provider=state.agent_llm_provider,
        agent_vcs_provider=state.agent_vcs_provider,
        agent_hidden=state.agent_hidden,
        set_output_variables=set_agent_output_variables,
        write_done_marker=write_done_marker_and_update_index,
    )
    state.current_artifacts_dir = state.artifacts_dir
    state.success = True
    state.exec_outcome = "completed"
    state.suppress_completion_notification = True


def _bump_spawn_telemetry(state: RunnerRunState) -> None:
    """Count this run as an active spawn once it has been admitted."""
    bump_spawn_telemetry(
        agent_llm_provider=state.agent_llm_provider,
        project_name=state.project_name,
        is_home_mode=state.is_home_mode,
        workflow_name=state.workflow_name,
        timestamp=state.timestamp,
    )


def _admit_and_launch(state: RunnerRunState, bootstrap: RunnerBootstrap) -> None:
    """Claim a runner slot for this run and hand off to the launch phase."""
    # Fork resolution reads mutable parent transcripts. Keep it behind
    # dependency admission, but run it before runner-slot admission or any real
    # workspace claim/preparation.
    state.prompt = expand_deferred_launch_xprompts(
        state.prompt,
        state.artifacts_dir,
        extra_xprompts=bootstrap.info.local_xprompts or None,
    )

    state.run_started_at = wait_for_runner_slot(
        state.artifacts_dir,
        state.cl_name,
        state.timestamp,
        bootstrap.agent_meta,
        wait_runners=bootstrap.info.wait_runners,
        wait_priority=bootstrap.info.wait_priority,
        claim=lambda: record_run_started_at(state.artifacts_dir, bootstrap.agent_meta),
    )

    state.active_agent_started = True
    _bump_spawn_telemetry(state)
    launch_agent_run(state, bootstrap)


def _run_agent(state: RunnerRunState) -> None:
    """Bootstrap, wait for admission, then either stop or launch the agent."""
    bootstrap = bootstrap_agent_run(state)
    blocking_wait_occurred = _wait_for_dependencies_phase(state, bootstrap)

    # Re-exec before repeat-stop detection, runner-slot claiming, or any
    # workspace mutation. The refreshed main pass intentionally resolves
    # xprompts again so post-wait work uses the current definitions.
    refresh_runner_code_after_wait(
        _STARTUP_CODE_IDENTITY,
        blocking_wait_occurred=blocking_wait_occurred,
        killed=was_killed(),
        prompt_file=state.prompt_file,
        submitted_xprompt=state.submitted_xprompt,
    )

    repeat_stop: RepeatStopDecision | None = None
    if bootstrap.has_dependency_wait:
        repeat_stop = detect_repeat_stop()

    if repeat_stop is not None:
        state.active_agent_started = True
        _bump_spawn_telemetry(state)
        _finalize_repeat_stop_slot(state, repeat_stop)
    else:
        _admit_and_launch(state, bootstrap)


def _record_completion(state: RunnerRunState) -> None:
    """Record duration/runtime metrics and print the run's closing summary."""
    completion_time = datetime.now(UTC)
    end_time = completion_time.timestamp()
    state.duration = format_duration(int(end_time - state.start_time))

    record_completion_metrics(
        success=state.success,
        duration_seconds=end_time - state.start_time,
        agent_llm_provider=state.agent_llm_provider,
        agent_model=state.agent_model,
        workflow_name=state.workflow_name,
        project_name=state.project_name,
        cl_name=state.cl_name,
        workspace_num=state.workspace_num,
        artifacts_dir=state.artifacts_dir,
        current_artifacts_dir=state.current_artifacts_dir,
        prompt=state.prompt,
        active_agent_started=state.active_agent_started,
        completion_time=completion_time,
    )
    state.runtime = format_agent_run_runtime(
        launch_timestamp_suffix=state.artifacts_timestamp,
        run_started_at=state.run_started_at,
        completion_time=completion_time,
    )

    print()
    print(f"Agent completed with status: {'SUCCESS' if state.success else 'FAILED'}")
    print(f"Duration: {state.duration}")


def main() -> None:
    """Run agent workflow and release workspace on completion."""
    state = _build_run_state(sys.argv)

    try:
        try:
            _run_agent(state)
        except Exception as e:
            state.success = False
            state.error_summary, state.error_traceback_str = record_runner_error(
                e,
                context=state.error_context(),
                write_error_done_marker=write_error_done_marker,
                agent_kills=AGENT_KILLS,
                message_prefix="Error running agent",
            )
        except SystemExit as e:
            if is_user_kill_exit(e):
                state.exec_outcome = "killed"
                state.suppress_completion_notification = True
                raise

            state.success = False
            state.error_summary, state.error_traceback_str = record_runner_error(
                e,
                context=state.error_context(),
                write_error_done_marker=write_error_done_marker,
                agent_kills=AGENT_KILLS,
                message_prefix="Agent exited before completion",
                error_summary=f"{type(e).__qualname__}: {system_exit_code(e)}",
            )

        _record_completion(state)

    finally:
        finalize_runner_shutdown(
            context=state.shutdown_context(),
            state=state.shutdown_state(),
            deps=RunnerShutdownDeps(
                update_artifact_index=update_agent_artifact_index_for_marker_mutation,
                was_killed=was_killed,
                all_steps_hidden=all_steps_hidden,
                write_error_report=write_error_report,
                send_completion_notification=send_completion_notification,
                auto_dismiss_completed_agent=auto_dismiss_completed_agent,
            ),
        )

    sys.exit(0 if state.success else 1)


if __name__ == "__main__":
    main()
