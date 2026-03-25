#!/usr/bin/env python3
"""Standalone fix-hook workflow runner for sase axe background execution.

This script runs the fix-hook workflow in the background and writes completion
markers to the output file for the axe scheduler to detect when finished.

Usage:
    python3 axe_fix_hook_runner.py <changespec_name> <project_file> <hook_command> \
        <hook_output_path> <output_file> <last_history_id> <timestamp>

Output file will contain:
    - Workflow output/logs
    - Completion marker: ===WORKFLOW_COMPLETE=== PROPOSAL_ID: <id> EXIT_CODE: <code>
"""

import os
import sys
import time
import traceback as tb_mod
from pathlib import Path

from sase.ace.changespec import ChangeSpec, parse_project_file
from sase.ace.hooks import (
    contract_test_target_command,
    format_duration,
    set_hook_suffix,
)
from sase.axe.runner_utils import (
    detect_and_write_agent_meta,
    finalize_axe_runner,
    read_agent_meta,
    write_done_marker,
    write_error_report,
)
from sase.history.chat import find_chat_by_timestamp
from sase.core.paths import shorten_path
from sase.core.shell import strip_hook_prefix
from sase.llm_provider import LLMInvocationError, invoke_agent
from sase.main.query_handler import (
    execute_standalone_steps,
    expand_embedded_workflows_in_query,
)
from sase.artifacts import create_artifacts_directory
from sase.content import ensure_str_content
from sase.xprompt import escape_for_xprompt, process_xprompt_references


def _update_hook_suffix(
    cs: ChangeSpec,
    project_file: str,
    proposal_id: str | None,
    exit_code: int,
    hook_command: str,
    entry_id: str,
    output_file: str,
) -> None:
    """Update the hook suffix based on workflow result."""
    # Find the current summary from the status line (to preserve it)
    # Note: cs.hooks may be slightly stale but summary is unlikely to change
    current_summary: str | None = None
    if cs.hooks:
        for hook in cs.hooks:
            if hook.command == hook_command:
                sl = hook.get_status_line_for_commit_entry(entry_id)
                if sl:
                    current_summary = sl.summary
                break

    if exit_code == 0 and proposal_id:
        # Success - proposal ID suffix (not an error), preserve summary
        # Pass hooks=None to let set_hook_suffix do a safe read inside the lock
        # (avoids race condition when multiple fix-hook agents run in parallel)
        set_hook_suffix(
            project_file,
            cs.name,
            hook_command,
            proposal_id,
            hooks=None,
            entry_id=entry_id,
            suffix_type="plain",
            summary=current_summary,
        )
    else:
        # Failure - "!" suffix (is an error), preserve summary
        # Prepend output file path to summary for easy access to fix-hook logs
        shortened_output = shorten_path(output_file)
        if current_summary:
            current_summary = f"{shortened_output} | {current_summary}"
        else:
            current_summary = shortened_output
        set_hook_suffix(
            project_file,
            cs.name,
            hook_command,
            "fix-hook Failed",
            hooks=None,
            entry_id=entry_id,
            suffix_type="error",
            summary=current_summary,
        )


def main() -> int:
    """Run the fix-hook workflow and write completion marker."""
    if len(sys.argv) != 8:
        print(
            f"Usage: {sys.argv[0]} <changespec_name> <project_file> <hook_command> "
            "<hook_output_path> <output_file> <last_history_id> <timestamp>"
        )
        return 1

    changespec_name = sys.argv[1]
    project_file = sys.argv[2]
    hook_command = sys.argv[3]
    hook_output_path = sys.argv[4]
    output_file = sys.argv[5]
    last_history_id = sys.argv[6]
    timestamp = sys.argv[7]  # Same timestamp used in agent suffix

    proposal_id: str | None = None
    exit_code = 1
    error_summary: str | None = None
    error_traceback_str: str | None = None
    start_time = time.time()

    # Get the command to run (strip "!" prefix)
    run_hook_command = strip_hook_prefix(hook_command)

    # Detect VCS type for the project
    from sase.workspace_provider import detect_workflow_type

    vcs_type = detect_workflow_type(project_file)

    # Create artifacts directory early so done.json can be written even on error
    artifacts_dir = create_artifacts_directory(
        "fix-hook",
        project_name=Path(project_file).parent.name,
        timestamp=timestamp,
    )

    # Write agent_meta.json early so Agents tab shows model/VCS while running
    detect_and_write_agent_meta(artifacts_dir, project_file)

    try:
        print(f"Running fix-hook workflow for {changespec_name}")
        print(f"Hook command: {run_hook_command}")
        print(f"Hook output: {hook_output_path}")
        print()

        # Build the prompt using xprompt reference (tag-based lookup with fallback)
        from sase.xprompt.tags import XPromptTag, get_by_tag

        fh_wf = get_by_tag(XPromptTag.fix_hook)
        fh_name = fh_wf.name if fh_wf else "fix_hook"

        escaped_cmd = escape_for_xprompt(run_hook_command)
        escaped_output = escape_for_xprompt(hook_output_path)
        escaped_cl = escape_for_xprompt(changespec_name)
        prompt_ref = (
            f'#{fh_name}(hook_command="{escaped_cmd}", '
            f'output_file="{escaped_output}", '
            f'cl_name="{escaped_cl}", vcs_type="{vcs_type}")'
        )
        prompt = process_xprompt_references(prompt_ref)

        # Expand embedded workflows (#propose from fix_hook.md)

        expanded_prompt, post_workflows = expand_embedded_workflows_in_query(
            prompt, artifacts_dir
        )

        # Set SASE_ARTIFACTS_DIR before invoking the agent so that the
        # commit_stop_hook path (agent commits during response) can write
        # commit_result.json to the correct location.
        os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir

        # Run the agent
        print("Running fix-hook agent...")
        print(f"Command: {run_hook_command}")
        print()

        try:
            response = invoke_agent(
                expanded_prompt,
                agent_type="fix-hook",
                model_tier="large",
                workflow="fix-hook",
                artifacts_dir=artifacts_dir,
                timestamp=timestamp,
            )
            response_content = ensure_str_content(response.content)
        except LLMInvocationError as e:
            response_content = str(e)
            error_summary = f"LLMInvocationError: {e}"
            error_traceback_str = tb_mod.format_exc()
        print(f"\nAgent Response:\n{response_content}\n")

        # Build who identifier for proposal
        history_ref = f"({last_history_id})" if last_history_id else ""
        display_command = contract_test_target_command(run_hook_command)
        who = f"fix-hook {history_ref} {display_command}"

        # Inject remaining environment variables for post-steps.
        os.environ["SASE_COMMIT_METHOD"] = "create_proposal"

        # Execute post-steps from embedded workflows (proposal creation via #propose)
        for ewf_result in post_workflows:
            ewf_result.context["_prompt"] = expanded_prompt
            ewf_result.context["_response"] = response_content
            ewf_result.context["who"] = who
            ewf_result.context["_start_timestamp"] = timestamp
            try:
                execute_standalone_steps(
                    ewf_result.post_steps,
                    ewf_result.context,
                    "fix-hook-embedded",
                    artifacts_dir,
                )
            except Exception as step_error:
                print(f"Warning: Some embedded workflow steps failed: {step_error}")
                import traceback

                traceback.print_exc()

            # Always check for proposal_id (even if later steps failed)
            create_result = ewf_result.context.get("propose", {})
            if isinstance(create_result, dict) and create_result.get("success") in (
                True,
                "true",
            ):
                proposal_id = create_result.get("proposal_id")
                exit_code = 0

        # Fallback: if context extraction failed, check ChangeSpec directly
        # (the propose step may have written the entry to disk even
        # though embedded_context didn't capture the result properly)
        if not proposal_id:
            try:
                base_num = int(last_history_id)
                for cs in parse_project_file(project_file):
                    if cs.name == changespec_name:
                        for commit in cs.commits or []:
                            if (
                                commit.number == base_num
                                and commit.is_proposed
                                and commit.note.startswith("[fix-hook")
                            ):
                                proposal_id = commit.display_number
                                exit_code = 0
                                print(
                                    f"Fallback: found proposal ({proposal_id}) "
                                    f"in ChangeSpec despite context extraction failure"
                                )
                                break
                        break
            except (ValueError, Exception) as e:
                print(f"Warning: fallback proposal check failed: {e}")

    except Exception as e:
        print(f"Error running fix-hook workflow: {e}")
        tb_mod.print_exc()
        exit_code = 1
        error_summary = f"{type(e).__qualname__}: {e}"
        error_traceback_str = tb_mod.format_exc()

    finally:
        duration = format_duration(int(time.time() - start_time))
        success = exit_code == 0 and proposal_id is not None

        # Read output_path from env var (set by starter.py)
        output_log_path = os.environ.get("SASE_AGENT_OUTPUT_PATH")

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
                workflow_name="fix-hook",
                cl_name=changespec_name,
                duration=duration,
                error_summary=error_summary,
                error_traceback=error_traceback_str,
            )

        # Finalize: update suffix, release workspace, write completion marker
        finalize_axe_runner(
            project_file=project_file,
            changespec_name=changespec_name,
            proposal_id=proposal_id,
            exit_code=exit_code,
            update_suffix_fn=lambda cs, pf, pid, ec: _update_hook_suffix(
                cs, pf, pid, ec, hook_command, last_history_id, output_file
            ),
        )

        from sase.notifications.senders import notify_workflow_complete

        # Build notes with error summary for failures
        notes = [
            f"Fix-hook {'completed' if success else 'failed'} for {changespec_name}"
        ]
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
            sender="fix-hook",
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
