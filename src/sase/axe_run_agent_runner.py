#!/usr/bin/env python3
"""Background run agent runner for sase ace TUI.

This script is launched by the ace TUI to run custom agents in the background.
It handles workspace cleanup and releases the workspace upon completion.
"""

import json
import os
import subprocess
import sys
import time
import uuid
from typing import Any

from sase.ace.hooks import format_duration
from sase.axe_run_agent_helpers import (
    create_followup_artifacts,
    extract_step_output_and_diff_path,
    format_qa_for_prompt,
    handle_questions_flow,
    read_and_delete_marker,
    update_meta_suffix,
)
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
    reset_killed,
    was_killed,
)
from sase.llm_provider.retry_config import (
    RetryState,
    get_retry_config,
    get_wait_time,
    is_retryable_error,
    truncate_error_snippet,
)
from sase.chat_history import save_chat_history
from sase.chat_history_extras import format_extra_sections
from sase.shared_utils import (
    convert_timestamp_to_artifacts_format,
    create_artifacts_directory,
)

install_sigterm_handler("agent", soft=True)


def _commit_sdd_files(workspace_dir: str, plan_name: str) -> None:
    """Commit SDD spec and plan files via ccommit before launching the epic agent.

    The ``#gh`` workflow pre-step runs ``git checkout . && git clean -fd`` which
    wipes uncommitted files.  Committing (and pushing) the SDD files first
    ensures the epic agent can still read them.
    """
    spec_file = os.path.join(workspace_dir, "specs", f"{plan_name}.md")
    plan_file = os.path.join(workspace_dir, "plans", f"{plan_name}.md")
    files = [f for f in (spec_file, plan_file) if os.path.exists(f)]
    if not files:
        return
    subprocess.run(
        [
            "ccommit",
            "chore",
            f"Add SDD spec and plan for {plan_name}",
            *files,
        ],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_plan_path_artifact(artifacts_dir: str, plan_path: str) -> None:
    """Write plan_path.json to the artifacts directory.

    This allows the TUI workflow loader to find the plan file and display
    it in the file panel for the .plan agent entry.
    """
    from pathlib import Path

    plan_path_file = Path(artifacts_dir) / "plan_path.json"
    try:
        with open(plan_path_file, "w", encoding="utf-8") as f:
            json.dump({"plan_path": plan_path}, f)
    except OSError:
        pass


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

            # Create anonymous workflow and execute through WorkflowExecutor
            from sase.xprompt.models import create_anonymous_workflow
            from sase.xprompt.workflow_runner import execute_workflow

            if info.approve:
                os.environ["SASE_AGENT_AUTO_APPROVE"] = "1"

            # Retry configuration
            retry_cfg = (
                get_retry_config(agent_llm_provider) if agent_llm_provider else None
            )
            retry_errors: list[str] = []
            retry_count = 0
            using_fallback = False
            _allow_retry = True  # Only retry initial execute_workflow calls

            # Follow-up loop: handles plan approval and question flows
            current_prompt = prompt
            current_role_suffix = ""
            current_artifacts_dir = artifacts_dir
            loop_outcome = "completed"
            sdd_spec_path: str | None = None  # Track spec for Q&A updates

            while True:
                reset_killed()
                os.environ["SASE_ARTIFACTS_DIR"] = current_artifacts_dir
                anon_workflow = create_anonymous_workflow(current_prompt)

                try:
                    result = execute_workflow(
                        anon_workflow.name,
                        [],
                        {"cl_name": cl_name, "workspace_num": workspace_num},
                        artifacts_dir=current_artifacts_dir,
                        silent=True,
                        workflow_obj=anon_workflow,
                    )
                except Exception as wf_exc:
                    if not was_killed():
                        error_str = str(wf_exc)
                        if (
                            _allow_retry
                            and retry_cfg
                            and is_retryable_error(error_str, retry_cfg)
                        ):
                            snippet = truncate_error_snippet(error_str)
                            retry_errors.append(snippet)
                            if retry_count < retry_cfg.max_retries:
                                # Retry with wait
                                retry_count += 1
                                wait_time = get_wait_time(retry_count, retry_cfg)
                                RetryState(
                                    status="retrying",
                                    retry_count=retry_count,
                                    max_retries=retry_cfg.max_retries,
                                    wait_seconds=wait_time,
                                    next_retry_at_epoch=time.time() + wait_time,
                                    last_error_snippet=snippet,
                                ).write_to(artifacts_dir)
                                from sase.notifications.senders import (
                                    notify_agent_retry,
                                )

                                notify_agent_retry(
                                    "agent-retry",
                                    cl_name,
                                    retry_count,
                                    retry_cfg.max_retries,
                                    wait_time,
                                    snippet,
                                )
                                # Sleep in 1s increments
                                for _ in range(wait_time):
                                    if was_killed():
                                        break
                                    time.sleep(1)
                                if was_killed():
                                    loop_outcome = "killed"
                                    break
                                # Re-prepare workspace
                                RetryState(
                                    status="running_retry",
                                    retry_count=retry_count,
                                    max_retries=retry_cfg.max_retries,
                                    last_error_snippet=snippet,
                                ).write_to(artifacts_dir)
                                if update_target and not is_home_mode:
                                    prepare_workspace(
                                        workspace_dir,
                                        cl_name,
                                        update_target,
                                        backup_suffix="ace",
                                        project_basename=project_name,
                                    )
                                os.chdir(workspace_dir)
                                continue  # Retry
                            elif retry_cfg.fallback_model and not using_fallback:
                                # Fallback to alternate model
                                using_fallback = True
                                os.environ["SASE_MODEL_OVERRIDE"] = (
                                    retry_cfg.fallback_model
                                )
                                RetryState(
                                    status="running_fallback",
                                    retry_count=retry_count,
                                    max_retries=retry_cfg.max_retries,
                                    fallback_model=retry_cfg.fallback_model,
                                    using_fallback=True,
                                    last_error_snippet=snippet,
                                ).write_to(artifacts_dir)
                                from sase.notifications.senders import (
                                    notify_agent_fallback,
                                )

                                notify_agent_fallback(
                                    "agent-retry",
                                    cl_name,
                                    retry_cfg.fallback_model,
                                    retry_count,
                                )
                                if update_target and not is_home_mode:
                                    prepare_workspace(
                                        workspace_dir,
                                        cl_name,
                                        update_target,
                                        backup_suffix="ace",
                                        project_basename=project_name,
                                    )
                                os.chdir(workspace_dir)
                                continue  # Fallback attempt
                        raise  # Not retryable or no retries left
                    result = None

                # If the process wasn't killed, this is a normal completion.
                # When it WAS killed, invoke_agent() may have swallowed the
                # CalledProcessError and returned an error AIMessage instead
                # of raising, so we must check for markers in both paths.
                if not was_killed():
                    break  # Normal completion

                # Check for marker files left by `sase plan` / `sase questions`
                plan_data = read_and_delete_marker(
                    current_artifacts_dir, ".sase_plan_pending"
                )
                q_data = read_and_delete_marker(
                    current_artifacts_dir, ".sase_questions_pending"
                )

                if plan_data:
                    update_meta_suffix(current_artifacts_dir, ".plan")
                    from sase.llm_provider._plan_utils import handle_plan_approval

                    # Check if the Epic option should be offered
                    from sase.sdd import check_epic_available

                    epic_available = check_epic_available(workspace_dir, workspace_num)

                    # Clear the killed flag set by the plan command's SIGTERM
                    # so the poll loop only exits on a NEW kill signal.
                    reset_killed()
                    plan_result = handle_plan_approval(
                        plan_data.get("plan_file"),
                        str(uuid.uuid4()),
                        killed_check=was_killed,
                        epic_available=epic_available,
                    )
                    if plan_result is None and was_killed():
                        loop_outcome = "killed"
                        break
                    if plan_result is None:
                        loop_outcome = "plan_rejected"
                        break
                    # Write plan_path.json so the TUI can show the plan
                    # in the file panel for the .plan agent entry.
                    _write_plan_path_artifact(
                        current_artifacts_dir, plan_result.plan_file
                    )

                    # Write SDD files (spec + plan) to project
                    sdd_plan_name: str | None = None
                    try:
                        from sase.sdd import (
                            get_sdd_config,
                            get_sdd_dir,
                            write_sdd_files,
                        )

                        version_controlled = get_sdd_config()
                        sdd_dir = get_sdd_dir(
                            workspace_dir, workspace_num, version_controlled
                        )
                        sdd_plan_name = os.path.splitext(
                            os.path.basename(plan_result.plan_file)
                        )[0]
                        sdd_spec_path_obj, _ = write_sdd_files(
                            sdd_dir, sdd_plan_name, prompt, plan_result.plan_file
                        )
                        sdd_spec_path = str(sdd_spec_path_obj)
                    except Exception:
                        pass  # Best effort — don't block the workflow

                    # VCS workflow tag prefix for follow-up agents
                    vcs_prefix = vcs_tag or ""

                    if plan_result.action == "epic":
                        # Commit SDD files so the #gh pre-step doesn't wipe them
                        if sdd_plan_name:
                            _commit_sdd_files(workspace_dir, sdd_plan_name)
                        # Epic: spawn epic agent to create beads
                        current_role_suffix = ".epic"
                        current_artifacts_dir = create_followup_artifacts(
                            project_name,
                            agent_meta,
                            current_role_suffix,
                            convert_timestamp_to_artifacts_format(timestamp),
                            workspace_num=workspace_num,
                        )
                        plan_ref = (
                            f"plans/{sdd_plan_name}.md"
                            if sdd_plan_name
                            else plan_data["plan_file"]
                        )
                        current_prompt = f"{vcs_prefix}#bd/new_epic:{plan_ref}"
                    else:
                        # Approve: spawn coder with plan as prompt
                        current_role_suffix = ".code"
                        current_artifacts_dir = create_followup_artifacts(
                            project_name,
                            agent_meta,
                            current_role_suffix,
                            convert_timestamp_to_artifacts_format(timestamp),
                            workspace_num=workspace_num,
                        )
                        current_prompt = (
                            f"{vcs_prefix}"
                            f"@{plan_data['plan_file']}\n\n"
                            "The above plan has been reviewed and approved. "
                            "Implement it now."
                        )
                    _allow_retry = False
                    continue

                elif q_data:
                    current_role_suffix += ".q"
                    update_meta_suffix(
                        current_artifacts_dir,
                        current_role_suffix or ".q",
                    )
                    # Clear the killed flag set by the questions command's
                    # SIGTERM so the poll loop only exits on a NEW kill signal.
                    reset_killed()
                    response = handle_questions_flow(
                        q_data.get("questions", []),
                        current_artifacts_dir,
                    )
                    if response is None:
                        loop_outcome = "killed"
                        break
                    current_artifacts_dir = create_followup_artifacts(
                        project_name,
                        agent_meta,
                        current_role_suffix,
                        convert_timestamp_to_artifacts_format(timestamp),
                        workspace_num=workspace_num,
                    )
                    qa_text = format_qa_for_prompt(response)
                    current_prompt = current_prompt + "\n\n" + qa_text

                    # Update SDD spec file with Q&A answers
                    if sdd_spec_path is not None:
                        try:
                            from pathlib import Path as _Path

                            from sase.sdd import update_spec_with_qa

                            update_spec_with_qa(_Path(sdd_spec_path), qa_text)
                        except Exception:
                            pass  # Best effort
                    _allow_retry = False
                    continue

                else:
                    # Killed by user (no marker)
                    loop_outcome = "killed"
                    break

            # Clean up retry state
            RetryState.delete_from(artifacts_dir)
            if "SASE_MODEL_OVERRIDE" in os.environ:
                del os.environ["SASE_MODEL_OVERRIDE"]

            # Build retry metadata for done.json
            _retry_meta: dict[str, Any] | None = None
            if retry_count > 0 or using_fallback:
                _retry_meta = {
                    "retry_count": retry_count,
                    "retry_errors": retry_errors,
                    "used_fallback": using_fallback,
                }
                if using_fallback and retry_cfg:
                    _retry_meta["fallback_model"] = retry_cfg.fallback_model

            # Clean up SASE_ARTIFACTS_DIR env var
            os.environ.pop("SASE_ARTIFACTS_DIR", None)

            if loop_outcome == "completed":
                assert result is not None
                # Extract response text for chat history
                response_content = result.response_text or ""

                # Prepare and save chat history
                extra = format_extra_sections(current_artifacts_dir)
                saved_path = save_chat_history(
                    prompt=current_prompt,
                    response=response_content,
                    workflow="ace-run",
                    timestamp=timestamp,
                    extra_sections=extra,
                )
                print(f"\nChat history saved to: {saved_path}")

                # Read plan_path from plan_path.json if written by claude.py
                plan_path: str | None = None
                plan_path_file = os.path.join(current_artifacts_dir, "plan_path.json")
                try:
                    with open(plan_path_file, encoding="utf-8") as f:
                        plan_path = json.load(f).get("plan_path")
                except (FileNotFoundError, json.JSONDecodeError, OSError):
                    pass

                # Extract step_output and diff_path from workflow_state.json
                step_output, diff_path = extract_step_output_and_diff_path(
                    current_artifacts_dir
                )

                # Write done marker
                done_marker = build_done_marker(
                    cl_name,
                    project_file,
                    timestamp,
                    artifacts_timestamp,
                    workspace_num,
                    output_path,
                    "completed",
                    agent_name=agent_name,
                    agent_model=agent_model,
                    agent_llm_provider=agent_llm_provider,
                    agent_vcs_provider=agent_vcs_provider,
                    agent_hidden=agent_hidden,
                    response_path=saved_path,
                    step_output=step_output,
                    diff_path=diff_path,
                    plan_path=plan_path,
                    retry_metadata=_retry_meta,
                )
                done_path = os.path.join(current_artifacts_dir, "done.json")
                with open(done_path, "w", encoding="utf-8") as f:
                    json.dump(done_marker, f, indent=2)
                print(f"Done marker written to: {done_path}")
            else:
                # plan_rejected or killed
                done_marker = build_done_marker(
                    cl_name,
                    project_file,
                    timestamp,
                    artifacts_timestamp,
                    workspace_num,
                    output_path,
                    loop_outcome,
                    agent_name=agent_name,
                    agent_model=agent_model,
                    agent_hidden=agent_hidden,
                    retry_metadata=_retry_meta,
                )
                done_path = os.path.join(current_artifacts_dir, "done.json")
                with open(done_path, "w", encoding="utf-8") as f:
                    json.dump(done_marker, f, indent=2)
                print(f"Done marker written to: {done_path} (outcome: {loop_outcome})")

            success = loop_outcome == "completed"

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
