#!/usr/bin/env python3
"""Standalone CRS workflow runner for sase axe background execution.

This script runs the CRS workflow in the background and writes completion
markers to the output file for the axe scheduler to detect when finished.

Usage:
    python3 axe_crs_runner.py <changespec_name> <project_file> <comments_file> \
        <reviewer_type> <timestamp>

Output file will contain:
    - Workflow output/logs
    - Completion marker: ===WORKFLOW_COMPLETE=== PROPOSAL_ID: <id> EXIT_CODE: <code>
"""

import os
import sys
import time
import traceback as tb_mod

from sase.ace.changespec import ChangeSpec
from sase.ace.comments import set_comment_suffix
from sase.ace.hooks import format_duration
from sase.axe.runner_utils import (
    detect_and_write_agent_meta,
    finalize_axe_runner,
    read_agent_meta,
    write_done_marker,
    write_error_report,
)
from sase.history.chat import find_chat_by_timestamp
from sase.workflows.crs import CrsWorkflow
from sase.core.paths import shorten_path
from sase.artifacts import create_artifacts_directory


def _update_comment_suffix(
    cs: ChangeSpec,
    project_file: str,
    proposal_id: str | None,
    exit_code: int,
    reviewer_type: str,
) -> None:
    """Update the comment suffix based on workflow result."""
    if not cs.comments:
        return
    if exit_code == 0 and proposal_id:
        set_comment_suffix(
            project_file, cs.name, reviewer_type, proposal_id, cs.comments
        )
    else:
        set_comment_suffix(
            project_file,
            cs.name,
            reviewer_type,
            "Unresolved Critique Comments",
            cs.comments,
            suffix_type="error",
        )


def main() -> int:
    """Run the CRS workflow and write completion marker."""
    if len(sys.argv) != 6:
        print(
            f"Usage: {sys.argv[0]} <changespec_name> <project_file> <comments_file> "
            "<reviewer_type> <timestamp>"
        )
        return 1

    changespec_name = sys.argv[1]
    project_file = sys.argv[2]
    comments_file = sys.argv[3] if sys.argv[3] else None
    reviewer_type = sys.argv[4]
    timestamp = sys.argv[5]  # Same timestamp used in agent suffix

    proposal_id: str | None = None
    exit_code = 1
    error_summary: str | None = None
    error_traceback_str: str | None = None
    start_time = time.time()

    # Detect VCS type for the project
    from sase.workspace_provider import detect_workflow_type

    vcs_type = detect_workflow_type(project_file)

    # Create artifacts directory early so done.json can be written even on error
    project_basename = os.path.splitext(os.path.basename(project_file))[0]
    artifacts_dir = create_artifacts_directory(
        "crs",
        project_name=project_basename,
        timestamp=timestamp,
    )

    # Write agent_meta.json early so Agents tab shows model/VCS while running
    detect_and_write_agent_meta(artifacts_dir, project_file)

    # Read output_path from env var (set by starter.py)
    output_log_path = os.environ.get("SASE_AGENT_OUTPUT_PATH")

    try:
        print(f"Running CRS workflow for {changespec_name}")
        print(f"Comments file: {comments_file}")
        print(f"Reviewer type: {reviewer_type}")
        print()

        # Build who identifier for proposal
        comments_ref = shorten_path(comments_file) if comments_file else "comments"
        who = f"crs ({comments_ref})"

        # Run the CRS workflow with timestamp for consistent artifacts directory
        workflow = CrsWorkflow(
            comments_file=comments_file,
            timestamp=timestamp,
            who=who,
            project_name=project_basename,
            cl_name=changespec_name,
            vcs_type=vcs_type,
        )
        workflow_succeeded = workflow.run()

        if not workflow_succeeded:
            print("CRS workflow failed")
            error_summary = "Workflow returned failure status (no exception raised)"
            exit_code = 1
        else:
            # Get proposal_id from workflow
            proposal_id = workflow.proposal_id
            exit_code = 0 if proposal_id else 1

    except Exception as e:
        print(f"Error running CRS workflow: {e}")
        tb_mod.print_exc()
        exit_code = 1
        error_summary = f"{type(e).__qualname__}: {e}"
        error_traceback_str = tb_mod.format_exc()

    finally:
        duration = format_duration(int(time.time() - start_time))
        success = exit_code == 0 and proposal_id is not None

        # Find chat file for response_path (written by invoke_agent during execution)
        chat_path = find_chat_by_timestamp(timestamp)

        # Write done.json marker for Agents tab visibility
        write_done_marker(
            artifacts_dir,
            cl_name=changespec_name,
            project_file=project_file,
            timestamp=timestamp,
            exit_code=exit_code,
            response_path=chat_path,
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
                workflow_name="crs",
                cl_name=changespec_name,
                duration=duration,
                error_summary=error_summary,
                error_traceback=error_traceback_str,
            )

        # Finalize: update suffix, write completion marker
        # Workspace release is handled by the scheduler's completer
        finalize_axe_runner(
            project_file=project_file,
            changespec_name=changespec_name,
            proposal_id=proposal_id,
            exit_code=exit_code,
            update_suffix_fn=lambda cs, pf, pid, ec: _update_comment_suffix(
                cs, pf, pid, ec, reviewer_type
            ),
        )

        from sase.notifications.senders import notify_workflow_complete

        # Build notes with error summary for failures
        notes = [f"CRS {'completed' if success else 'failed'} for {changespec_name}"]
        if not success and error_summary:
            notes.append(error_summary)

        # Build file list — attach error report and output log for failures
        extra_files = [chat_path] if chat_path else []
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
            sender="crs",
            cl_name=changespec_name,
            success=success,
            notes=notes,
            action=action,
            action_data=action_data,
            extra_files=extra_files,
        )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
