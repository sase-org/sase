#!/usr/bin/env python3
"""Background mentor runner for sase axe.

This script is launched by the axe scheduler to run mentors in the background.
It handles workspace cleanup and status updates upon completion.
"""

import os
import sys
import time
import traceback as tb_mod
from pathlib import Path

from sase.ace.hooks import format_duration
from sase.ace.mentors import set_mentor_status
from sase.axe.runner_utils import (
    detect_and_write_agent_meta,
    install_sigterm_handler,
    read_agent_meta,
    write_done_marker,
    write_error_report,
)
from sase.workflows.mentor import MentorWorkflow
from sase.artifacts import create_artifacts_directory

install_sigterm_handler("mentor")


def main() -> None:
    """Run mentor workflow and update status on completion."""
    if len(sys.argv) != 8:
        print(
            f"Usage: {sys.argv[0]} <cl_name> <project_file> <mentor_name> "
            "<output_path> <entry_id> <profile_name> <timestamp>",
            file=sys.stderr,
        )
        sys.exit(1)

    cl_name = sys.argv[1]
    project_file = sys.argv[2]
    mentor_name = sys.argv[3]
    output_path = sys.argv[4]
    entry_id = sys.argv[5]
    profile_name = sys.argv[6]
    timestamp = sys.argv[7]

    start_time = time.time()
    success = False
    final_status = "FAILED"
    duration = "0s"
    response_path: str | None = None
    error_summary: str | None = None
    error_traceback_str: str | None = None

    # Create artifacts directory early so done.json can be written even on error
    # Note: MentorWorkflow also creates this same directory internally
    artifacts_dir = create_artifacts_directory(
        f"mentor-{mentor_name}",
        project_name=Path(project_file).parent.name,
        timestamp=timestamp,
    )

    # Write agent_meta.json early so Agents tab shows model/VCS while running
    detect_and_write_agent_meta(artifacts_dir, project_file)

    print(f"Starting mentor workflow: {mentor_name}")
    print(f"CL: {cl_name}")
    print(f"Profile: {profile_name}")
    print(f"Entry ID: {entry_id}")
    print()

    try:
        try:
            # Run the mentor workflow (#hg handles workspace management)
            workflow = MentorWorkflow(
                profile_name=profile_name,
                mentor_name=mentor_name,
                cl_name=cl_name,
                timestamp=timestamp,
            )
            success = workflow.run()
            response_path = workflow.response_path
            comment_count = workflow.comment_count
        except BaseException as e:
            # Catch BaseException (not just Exception) so that SystemExit from
            # the SIGTERM handler doesn't bypass the status update below.
            if isinstance(e, Exception):
                print(f"Error running mentor workflow: {e}", file=sys.stderr)
                error_summary = f"{type(e).__qualname__}: {e}"
                error_traceback_str = tb_mod.format_exc()
            success = False
            comment_count = 0

        end_time = time.time()
        elapsed_seconds = int(end_time - start_time)
        duration = format_duration(elapsed_seconds)

        # Determine final status:
        # - COMMENTED: mentor ran successfully and produced review comments
        # - PASSED: mentor ran successfully with no comments (no issues found)
        # - FAILED: mentor errored or produced invalid JSON
        if success and comment_count > 0:
            final_status = "COMMENTED"
        elif success:
            final_status = "PASSED"
        else:
            final_status = "FAILED"

        print()
        print(f"Mentor workflow completed with status: {final_status}")
        print(f"Duration: {duration}")
        if comment_count > 0:
            print(f"Comments: {comment_count}")

        # Update MENTORS field with result
        # When FAILED, include the output file path for debugging
        if final_status == "FAILED":
            # Shorten home directory to ~ for readability
            display_path = output_path.replace(os.path.expanduser("~"), "~")
            suffix = display_path
            suffix_type = "error"
        else:
            suffix = None
            suffix_type = None

        # Always attempt the status update. If the accept workflow already
        # marked the mentor as KILLED (suffix_type="killed_agent"),
        # set_mentor_status() will detect that and return early (no-op).
        try:
            set_mentor_status(
                project_file,
                cl_name,
                entry_id,
                profile_name,
                mentor_name,
                status=final_status,
                timestamp=timestamp,
                duration=duration if final_status != "FAILED" else None,
                suffix=suffix,
                suffix_type=suffix_type,
            )
        except Exception as e:
            print(f"Error updating mentor status: {e}", file=sys.stderr)

    finally:
        # Write done.json marker for Agents tab visibility
        exit_code = 0 if success else 1

        # Read output_path from env var (set by mentor starter)
        output_log_path = os.environ.get("SASE_AGENT_OUTPUT_PATH") or output_path

        write_done_marker(
            artifacts_dir,
            cl_name=cl_name,
            project_file=project_file,
            timestamp=timestamp,
            exit_code=exit_code,
            response_path=response_path,
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
                workflow_name=f"mentor-{mentor_name}",
                cl_name=cl_name,
                duration=duration,
                error_summary=error_summary,
                error_traceback=error_traceback_str,
            )

        # Write completion marker
        try:
            with open(output_path, "a") as f:
                f.write("\n=== MENTOR_WORKFLOW_COMPLETE ===\n")
                f.write(f"Status: {final_status}\n")
                f.write(f"Duration: {duration}\n")
        except Exception as e:
            print(f"Error writing completion marker: {e}", file=sys.stderr)

        # Send notification for mentor completion
        from sase.notifications.senders import notify_workflow_complete

        # Build notes with error summary for failures
        notes = [
            f"Mentor {mentor_name} {'completed' if success else 'failed'} for {cl_name}"
        ]
        if not success and error_summary:
            notes.append(error_summary)

        # Build file list — attach error report and output log for failures
        extra_files: list[str] = []
        if response_path:
            extra_files.append(response_path)
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
                "cl_name": cl_name,
            }
        else:
            action = "JumpToChangeSpec"
            action_data = {
                "changespec_name": cl_name,
                "project_file": project_file,
            }

        notify_workflow_complete(
            sender=f"mentor-{mentor_name}",
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
