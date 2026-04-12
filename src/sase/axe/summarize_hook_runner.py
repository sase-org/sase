#!/usr/bin/env python3
"""Standalone summarize-hook workflow runner for sase axe background execution.

This script runs the summarize workflow in the background and writes the summary
suffix back to the hook status line. Unlike fix-hook, this workflow does NOT
require a workspace since it only reads the hook output file and calls the
summarize agent.

Usage:
    python3 axe_summarize_hook_runner.py <changespec_name> <project_file> \
        <hook_command> <hook_output_path> <output_file> <entry_id> <timestamp>

Output file will contain:
    - Workflow output/logs
    - Completion marker: ===WORKFLOW_COMPLETE=== PROPOSAL_ID: None EXIT_CODE: <code>
"""

import os
import subprocess
import sys
import time
import traceback as tb_mod
from pathlib import Path

from sase.ace.hooks import format_duration, set_hook_suffix
from sase.axe.runner_utils import (
    detect_and_write_agent_meta,
    read_agent_meta,
    write_done_marker,
    write_error_report,
)
from sase.config.metahook import MetahookConfig, find_matching_metahook
from sase.telemetry import init_telemetry, register_push_on_exit
from sase.telemetry.metrics import WORKFLOW_DURATION, WORKFLOW_EXECUTIONS
from sase.artifacts import create_artifacts_directory
from sase.ace.hooks.summarize_utils import get_file_summary

# Workflow completion marker (same pattern as other axe runners)
WORKFLOW_COMPLETE_MARKER = "===WORKFLOW_COMPLETE=== PROPOSAL_ID: "


def main() -> int:
    """Run the summarize-hook workflow and write completion marker."""
    if len(sys.argv) != 8:
        print(
            f"Usage: {sys.argv[0]} <changespec_name> <project_file> <hook_command> "
            "<hook_output_path> <output_file> <entry_id> <timestamp>"
        )
        return 1

    changespec_name = sys.argv[1]
    project_file = sys.argv[2]
    hook_command = sys.argv[3]
    hook_output_path = sys.argv[4]
    # output_file = sys.argv[5]  # Not used directly - stdout goes there
    entry_id = sys.argv[6]
    timestamp = sys.argv[7]  # Same timestamp used in agent suffix

    # Initialize telemetry and push metrics on exit
    init_telemetry()
    register_push_on_exit(job="summarize-hook-runner", instance=timestamp)

    exit_code = 1
    error_summary: str | None = None
    error_traceback_str: str | None = None
    start_time = time.time()

    # Create artifacts directory early so done.json can be written even on error
    artifacts_dir = create_artifacts_directory(
        "summarize-hook",
        project_name=Path(project_file).parent.name,
        timestamp=timestamp,
    )

    # Write agent_meta.json early so Agents tab shows model/VCS while running
    detect_and_write_agent_meta(artifacts_dir, project_file)

    try:
        print(f"Running summarize-hook workflow for {changespec_name}")
        print(f"Hook command: {hook_command}")
        print(f"Hook output: {hook_output_path}")
        print(f"Entry ID: {entry_id}")
        print()

        # Check for matching metahook
        hook_output_content = Path(hook_output_path).read_text(encoding="utf-8")
        matching_metahook: MetahookConfig | None = find_matching_metahook(
            hook_command, hook_output_content
        )

        if matching_metahook:
            print(f"Found matching metahook: {matching_metahook.name}")
            metahook_script = f"sase_metahook_{matching_metahook.name}"

            try:
                result = subprocess.run(
                    [metahook_script, hook_output_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode != 0:
                    # Metahook returned non-zero - use its output as summary
                    summary = result.stdout.strip() or "Metahook failed"
                    print(f"Metahook completed with summary: {summary}")

                    success = set_hook_suffix(
                        project_file,
                        changespec_name,
                        hook_command,
                        summary,
                        hooks=None,
                        entry_id=entry_id,
                        suffix_type="metahook_complete",
                    )
                    if success:
                        print(
                            f"Updated hook suffix for entry ({entry_id}) to: {summary}"
                        )
                        exit_code = 0
                    else:
                        print(
                            f"Warning: Could not update hook suffix for {changespec_name}"
                        )
                        exit_code = 1

                    # Record workflow telemetry (metahook path)
                    elapsed = time.time() - start_time
                    wf_status = "passed" if exit_code == 0 else "failed"
                    WORKFLOW_EXECUTIONS.labels(
                        workflow="summarize-hook", status=wf_status
                    ).inc()
                    WORKFLOW_DURATION.labels(workflow="summarize-hook").observe(elapsed)

                    # Read output_path from env var (set by starter.py)
                    output_log_path = os.environ.get("SASE_AGENT_OUTPUT_PATH")

                    # Write done.json and completion marker, then return early
                    write_done_marker(
                        artifacts_dir,
                        cl_name=changespec_name,
                        project_file=project_file,
                        timestamp=timestamp,
                        exit_code=exit_code,
                        output_path=output_log_path,
                    )
                    print()
                    print(f"{WORKFLOW_COMPLETE_MARKER}None EXIT_CODE: {exit_code}")
                    return exit_code
                else:
                    print("Metahook returned 0, continuing with normal summarize flow")

            except FileNotFoundError:
                print(
                    f"Metahook script not found: {metahook_script}, continuing with normal flow"
                )
            except subprocess.TimeoutExpired:
                print(
                    f"Metahook script timed out: {metahook_script}, continuing with normal flow"
                )
            except Exception as e:
                print(f"Error running metahook: {e}, continuing with normal flow")

        # Get summary of the hook failure
        summary = get_file_summary(
            target_file=hook_output_path,
            usage="a hook failure suffix on a status line",
            fallback="Hook Command Failed",
            artifacts_dir=artifacts_dir,
        )

        print(f"Generated summary: {summary}")

        # Update the hook suffix with the summary
        # Use suffix_type="summarize_complete" to indicate ready for fix-hook
        # Pass hooks=None to let set_hook_suffix do a safe read inside the lock
        # (avoids race condition when multiple summarize agents run in parallel)
        success = set_hook_suffix(
            project_file,
            changespec_name,
            hook_command,
            summary,
            hooks=None,
            entry_id=entry_id,
            suffix_type="summarize_complete",
        )
        if success:
            print(f"Updated hook suffix for entry ({entry_id}) to: {summary}")
            exit_code = 0
        else:
            print(f"Warning: Could not update hook suffix for {changespec_name}")
            exit_code = 1

    except Exception as e:
        print(f"Error running summarize-hook workflow: {e}")
        tb_mod.print_exc()
        exit_code = 1
        error_summary = f"{type(e).__qualname__}: {e}"
        error_traceback_str = tb_mod.format_exc()

    elapsed = time.time() - start_time
    duration = format_duration(int(elapsed))
    success = exit_code == 0

    # Record workflow telemetry (normal path)
    wf_status = "passed" if success else "failed"
    WORKFLOW_EXECUTIONS.labels(workflow="summarize-hook", status=wf_status).inc()
    WORKFLOW_DURATION.labels(workflow="summarize-hook").observe(elapsed)

    # Read output_path from env var (set by starter.py)
    output_log_path = os.environ.get("SASE_AGENT_OUTPUT_PATH")

    # Write done.json marker for Agents tab visibility
    write_done_marker(
        artifacts_dir,
        cl_name=changespec_name,
        project_file=project_file,
        timestamp=timestamp,
        exit_code=exit_code,
        error=error_summary,
        traceback_str=error_traceback_str,
        output_path=output_log_path,
    )

    # Write error report for failed runs
    error_report_path: str | None = None
    if not success and error_summary:
        meta = read_agent_meta(artifacts_dir)
        error_report_path = write_error_report(
            artifacts_dir,
            agent_model=meta["model"],
            agent_llm_provider=meta["llm_provider"],
            workflow_name="summarize-hook",
            cl_name=changespec_name,
            duration=duration,
            error_summary=error_summary,
            error_traceback=error_traceback_str,
        )

    # Send notification for summarize-hook completion
    from sase.notifications.senders import notify_workflow_complete

    # Build notes with error summary for failures
    notes = [
        f"Summarize-hook {'completed' if success else 'failed'} for {changespec_name}"
    ]
    if not success and error_summary:
        notes.append(error_summary)

    # Build file list — attach error report and output log for failures
    extra_files: list[str] = []
    if not success:
        if error_report_path:
            extra_files.insert(0, error_report_path)
        if output_log_path and os.path.isfile(output_log_path):
            extra_files.append(output_log_path)

    # Use ViewErrorReport action for failures with error report
    if not success and error_report_path:
        action = "ViewErrorReport"
        action_data: dict[str, str] = {
            "error_report_path": error_report_path,
            "cl_name": changespec_name,
        }
    else:
        action = "JumpToChangeSpec"
        action_data = {
            "changespec_name": changespec_name,
            "project_file": project_file,
        }

    notify_workflow_complete(
        sender="summarize-hook",
        cl_name=changespec_name,
        success=success,
        notes=notes,
        action=action,
        action_data=action_data,
        extra_files=extra_files,
        silent=True,
    )

    # Write completion marker (no proposal ID for summarize workflows)
    print()
    print(f"{WORKFLOW_COMPLETE_MARKER}None EXIT_CODE: {exit_code}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
