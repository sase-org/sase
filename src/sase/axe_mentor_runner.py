#!/usr/bin/env python3
"""Background mentor runner for sase axe.

This script is launched by the axe scheduler to run mentors in the background.
It handles workspace cleanup and status updates upon completion.
"""

import os
import sys
import time

from sase.ace.hooks import format_duration
from sase.ace.mentors import set_mentor_status
from sase.axe_runner_utils import install_sigterm_handler, was_killed
from sase.mentor_workflow import MentorWorkflow

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

    print(f"Starting mentor workflow: {mentor_name}")
    print(f"CL: {cl_name}")
    print(f"Profile: {profile_name}")
    print(f"Entry ID: {entry_id}")
    print()

    try:
        try:
            # Build who identifier for proposal
            who = f"mentor:{mentor_name}"

            # Run the mentor workflow (#hg handles workspace management)
            workflow = MentorWorkflow(
                profile_name=profile_name,
                mentor_name=mentor_name,
                cl_name=cl_name,
                timestamp=timestamp,
                who=who,
            )
            success = workflow.run()

            # Get proposal_id from workflow
            proposal_id: str | None = workflow.proposal_id
        except Exception as e:
            print(f"Error running mentor workflow: {e}", file=sys.stderr)
            success = False
            proposal_id = None

        end_time = time.time()
        elapsed_seconds = int(end_time - start_time)
        duration = format_duration(elapsed_seconds)

        # Determine final status
        # PASSED = mentor ran successfully and made no changes
        # FAILED = mentor ran and made changes (created a proposal)
        # Note: Currently, we mark as PASSED if the workflow succeeded
        # The mentor workflow itself handles creating proposals for changes
        final_status = "PASSED" if success else "FAILED"

        print()
        print(f"Mentor workflow completed with status: {final_status}")
        print(f"Duration: {duration}")

        if proposal_id:
            print(f"Associated proposal: {proposal_id}")

        # Determine final status:
        # - FAILED if a proposal was created (regardless of workflow success)
        # - PASSED if workflow succeeded with no proposal
        # - FAILED if workflow errored (no proposal, already set above)
        if proposal_id:
            final_status = "FAILED"

        # Update MENTORS field with result
        # When FAILED without a proposal, include the output file path for debugging
        if final_status == "FAILED" and not proposal_id:
            # Shorten home directory to ~ for readability
            display_path = output_path.replace(os.path.expanduser("~"), "~")
            suffix = display_path
            suffix_type = "error"
        elif proposal_id:
            suffix = proposal_id
            suffix_type = "entry_ref"
        else:
            suffix = None
            suffix_type = None

        # Skip status update if we were killed - the accept workflow already marked
        # the mentor as killed, and we don't want to overwrite that status
        if was_killed():
            print("Skipping status update - mentor was killed", file=sys.stderr)
        else:
            try:
                set_mentor_status(
                    project_file,
                    cl_name,
                    entry_id,
                    profile_name,
                    mentor_name,
                    status=final_status,
                    timestamp=timestamp,
                    duration=duration if final_status == "PASSED" else None,
                    suffix=suffix,
                    suffix_type=suffix_type,
                )
            except Exception as e:
                print(f"Error updating mentor status: {e}", file=sys.stderr)

    finally:
        # Write completion marker
        try:
            with open(output_path, "a") as f:
                f.write("\n=== MENTOR_WORKFLOW_COMPLETE ===\n")
                f.write(f"Status: {final_status}\n")
                f.write(f"Duration: {duration}\n")
        except Exception as e:
            print(f"Error writing completion marker: {e}", file=sys.stderr)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
