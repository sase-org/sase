"""Agent execution loop for the run agent runner.

Contains the core while-loop that runs workflow steps with retry,
plan approval, and question-flow handling.
"""

import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.axe_run_agent_helpers import (
    create_followup_artifacts,
    extract_step_output_and_diff_path,
    format_qa_for_prompt,
    handle_questions_flow,
    normalize_handoff_interruption_state,
    read_and_delete_marker,
    update_meta_suffix,
)
from sase.axe_run_agent_phases import build_done_marker
from sase.axe_runner_utils import prepare_workspace, reset_killed, was_killed
from sase.chat_history import save_chat_history
from sase.chat_history_extras import format_extra_sections
from sase.llm_provider.retry_config import (
    RetryState,
    get_retry_config,
    get_wait_time,
    is_retryable_error,
    truncate_error_snippet,
)
from sase.shared_utils import convert_timestamp_to_artifacts_format


@dataclass
class AgentExecContext:
    """Immutable configuration the execution loop needs from the runner."""

    cl_name: str
    project_file: str
    workspace_dir: str
    output_path: str
    workspace_num: int
    timestamp: str
    update_target: str
    project_name: str
    is_home_mode: bool
    artifacts_dir: str
    artifacts_timestamp: str
    vcs_tag: str | None
    agent_name: str | None
    agent_model: str | None
    agent_llm_provider: str | None
    agent_vcs_provider: str | None
    agent_hidden: bool
    agent_meta: dict[str, Any]


@dataclass
class _AgentExecResult:
    """Result from the execution loop."""

    success: bool
    saved_path: str | None = None
    diff_path: str | None = None
    current_artifacts_dir: str = ""


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
    plan_path_file = Path(artifacts_dir) / "plan_path.json"
    try:
        with open(plan_path_file, "w", encoding="utf-8") as f:
            json.dump({"plan_path": plan_path}, f)
    except OSError:
        pass


def _get_embedded_workflow_refs(artifacts_dir: str, vcs_tag: str | None) -> str:
    """Reconstruct non-VCS embedded workflow refs from artifacts metadata.

    Reads embedded_workflows.json (written during workflow expansion before
    the agent is killed) and returns a string of workflow references
    (e.g., ``"#propose "``) to prepend to follow-up agent prompts so their
    post-steps run after the follow-up agent completes.
    """
    metadata_path = os.path.join(artifacts_dir, "embedded_workflows.json")
    try:
        with open(metadata_path, encoding="utf-8") as f:
            workflows = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""

    # Extract VCS workflow name from tag (e.g., "#hg:sase " -> "hg")
    vcs_name: str | None = None
    if vcs_tag:
        m = re.match(r"#(\w+)", vcs_tag)
        if m:
            vcs_name = m.group(1)

    refs: list[str] = []
    for wf in workflows:
        name = wf["name"]
        if name == vcs_name:
            continue
        args = wf.get("args", {})
        if not args:
            refs.append(f"#{name}")
        elif len(args) == 1:
            value = next(iter(args.values()))
            refs.append(f"#{name}:{value}")
        else:
            arg_parts = [f"{k}={v}" for k, v in args.items()]
            refs.append(f"#{name}({', '.join(arg_parts)})")

    if not refs:
        return ""
    return " ".join(refs) + " "


def run_execution_loop(ctx: AgentExecContext, prompt: str) -> _AgentExecResult:
    """Run the agent workflow loop with retry, plan approval, and question handling.

    Returns an _AgentExecResult with the outcome.
    """
    from sase.xprompt.models import create_anonymous_workflow
    from sase.xprompt.workflow_runner import execute_workflow

    # Retry configuration
    retry_cfg = (
        get_retry_config(ctx.agent_llm_provider) if ctx.agent_llm_provider else None
    )
    retry_errors: list[str] = []
    retry_count = 0
    using_fallback = False
    _allow_retry = True  # Only retry initial execute_workflow calls

    # Follow-up loop: handles plan approval and question flows
    result = None  # Set by execute_workflow on normal completion
    current_prompt = prompt
    current_role_suffix = ""
    current_artifacts_dir = ctx.artifacts_dir
    loop_outcome = "completed"
    sdd_spec_path: str | None = None  # Track spec for Q&A updates

    # Feedback tracking: accumulate feedback bullets across rounds
    _original_prompt = prompt
    _qa_sections: list[str] = []
    _feedback_bullets: list[str] = []
    _feedback_round = 0

    while True:
        reset_killed()
        os.environ["SASE_ARTIFACTS_DIR"] = current_artifacts_dir
        anon_workflow = create_anonymous_workflow(current_prompt)

        try:
            result = execute_workflow(
                anon_workflow.name,
                [],
                {"cl_name": ctx.cl_name, "workspace_num": ctx.workspace_num},
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
                        ).write_to(ctx.artifacts_dir)
                        from sase.notifications.senders import (
                            notify_agent_retry,
                        )

                        notify_agent_retry(
                            "agent-retry",
                            ctx.cl_name,
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
                        ).write_to(ctx.artifacts_dir)
                        if ctx.update_target and not ctx.is_home_mode:
                            prepare_workspace(
                                ctx.workspace_dir,
                                ctx.cl_name,
                                ctx.update_target,
                                backup_suffix="ace",
                                project_basename=ctx.project_name,
                            )
                        os.chdir(ctx.workspace_dir)
                        continue  # Retry
                    elif retry_cfg.fallback_model and not using_fallback:
                        # Fallback to alternate model
                        using_fallback = True
                        os.environ["SASE_MODEL_OVERRIDE"] = retry_cfg.fallback_model
                        RetryState(
                            status="running_fallback",
                            retry_count=retry_count,
                            max_retries=retry_cfg.max_retries,
                            fallback_model=retry_cfg.fallback_model,
                            using_fallback=True,
                            last_error_snippet=snippet,
                        ).write_to(ctx.artifacts_dir)
                        from sase.notifications.senders import (
                            notify_agent_fallback,
                        )

                        notify_agent_fallback(
                            "agent-retry",
                            ctx.cl_name,
                            retry_cfg.fallback_model,
                            retry_count,
                        )
                        if ctx.update_target and not ctx.is_home_mode:
                            prepare_workspace(
                                ctx.workspace_dir,
                                ctx.cl_name,
                                ctx.update_target,
                                backup_suffix="ace",
                                project_basename=ctx.project_name,
                            )
                        os.chdir(ctx.workspace_dir)
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
        plan_data = read_and_delete_marker(current_artifacts_dir, ".sase_plan_pending")
        q_data = read_and_delete_marker(
            current_artifacts_dir, ".sase_questions_pending"
        )

        if plan_data:
            normalize_handoff_interruption_state(current_artifacts_dir)
            # Only set the ".plan" suffix on the original workflow entry;
            # feedback round agents (suffix ".2", ".3", …) keep theirs.
            if _feedback_round == 0:
                update_meta_suffix(current_artifacts_dir, ".plan")
            from sase.llm_provider._plan_utils import handle_plan_approval

            # Clear the killed flag set by the plan command's SIGTERM
            # so the poll loop only exits on a NEW kill signal.
            reset_killed()
            plan_result = handle_plan_approval(
                plan_data.get("plan_file"),
                str(uuid.uuid4()),
                killed_check=was_killed,
            )
            if plan_result is None and was_killed():
                loop_outcome = "killed"
                break
            if plan_result is None:
                loop_outcome = "plan_rejected"
                break
            # Write plan_path.json so the TUI can show the plan
            # in the file panel for the .plan agent entry.
            _write_plan_path_artifact(current_artifacts_dir, plan_result.plan_file)

            # Feedback: spawn a new agent with the original prompt +
            # accumulated "Additional Requirements" section.
            if plan_result.action == "feedback":
                assert plan_result.feedback is not None
                _feedback_round += 1
                _feedback_bullets.append(plan_result.feedback)

                suffix = f".{_feedback_round + 1}"
                current_role_suffix = suffix
                current_artifacts_dir = create_followup_artifacts(
                    ctx.project_name,
                    ctx.agent_meta,
                    current_role_suffix,
                    convert_timestamp_to_artifacts_format(ctx.timestamp),
                    workspace_num=ctx.workspace_num,
                )

                # Reconstruct prompt: original + all Q&A + requirements
                base = _original_prompt
                for qa in _qa_sections:
                    base += "\n\n" + qa
                reqs = "\n".join(f"- {fb}" for fb in _feedback_bullets)
                current_prompt = f"{base}\n\n### Additional Requirements\n\n{reqs}"
                _allow_retry = False
                continue

            # Write SDD files (spec + plan) to project
            from sase.sdd import (
                commit_sdd_files,
                get_sdd_config,
                get_sdd_dir,
                write_sdd_files,
            )

            sdd_plan_name: str | None = None
            version_controlled = True  # safe default (VC path is the no-op path)
            sdd_dir = Path(ctx.workspace_dir)
            try:
                version_controlled = get_sdd_config()
                sdd_dir = get_sdd_dir(
                    ctx.workspace_dir, ctx.workspace_num, version_controlled
                )
                sdd_plan_name = os.path.splitext(
                    os.path.basename(plan_result.plan_file)
                )[0]
                sdd_spec_path_obj, _ = write_sdd_files(
                    sdd_dir, sdd_plan_name, prompt, plan_result.plan_file
                )
                sdd_spec_path = str(sdd_spec_path_obj)
                if not version_controlled:
                    commit_sdd_files(sdd_dir, f"Add SDD files for {sdd_plan_name}")
            except Exception:
                pass  # Best effort — don't block the workflow

            # VCS workflow tag prefix for follow-up agents
            vcs_prefix = ctx.vcs_tag or ""

            # Reconstruct non-VCS embedded workflow refs (e.g. #propose,
            # #commit) so their post-steps run after the follow-up agent.
            embedded_refs = _get_embedded_workflow_refs(
                current_artifacts_dir, ctx.vcs_tag
            )

            if plan_result.action == "epic":
                # Ensure beads are initialized before spawning epic agent
                from sase.sdd import ensure_beads_initialized

                ensure_beads_initialized(ctx.workspace_dir, ctx.workspace_num)

                # Commit SDD files so the #gh pre-step doesn't wipe them
                if sdd_plan_name:
                    if version_controlled:
                        _commit_sdd_files(ctx.workspace_dir, sdd_plan_name)
                    else:
                        commit_sdd_files(sdd_dir, f"Add SDD files for {sdd_plan_name}")
                # Epic: spawn epic agent to create beads
                current_role_suffix = ".epic"
                current_artifacts_dir = create_followup_artifacts(
                    ctx.project_name,
                    ctx.agent_meta,
                    current_role_suffix,
                    convert_timestamp_to_artifacts_format(ctx.timestamp),
                    workspace_num=ctx.workspace_num,
                )
                plan_ref = (
                    f".sase/sdd/plans/{sdd_plan_name}.md"
                    if sdd_plan_name and not version_controlled
                    else f"plans/{sdd_plan_name}.md"
                    if sdd_plan_name
                    else plan_data["plan_file"]
                )
                current_prompt = f"{vcs_prefix}{embedded_refs}#bd/new_epic:{plan_ref}"
            else:
                # Approve: spawn coder with plan as prompt
                current_role_suffix = ".code"
                current_artifacts_dir = create_followup_artifacts(
                    ctx.project_name,
                    ctx.agent_meta,
                    current_role_suffix,
                    convert_timestamp_to_artifacts_format(ctx.timestamp),
                    workspace_num=ctx.workspace_num,
                )
                current_prompt = (
                    f"{vcs_prefix}{embedded_refs}"
                    f"@{plan_data['plan_file']}\n\n"
                    "The above plan has been reviewed and approved. "
                    "Implement it now."
                )
            _allow_retry = False
            continue

        elif q_data:
            normalize_handoff_interruption_state(current_artifacts_dir)
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
                ctx.project_name,
                ctx.agent_meta,
                current_role_suffix,
                convert_timestamp_to_artifacts_format(ctx.timestamp),
                workspace_num=ctx.workspace_num,
            )
            qa_text = format_qa_for_prompt(response)
            _qa_sections.append(qa_text)
            current_prompt = current_prompt + "\n\n" + qa_text

            # Update SDD spec file with Q&A answers
            if sdd_spec_path is not None:
                try:
                    from sase.sdd import update_spec_with_qa

                    update_spec_with_qa(Path(sdd_spec_path), qa_text)
                except Exception:
                    pass  # Best effort
            _allow_retry = False
            continue

        else:
            # Killed by user (no marker)
            loop_outcome = "killed"
            break

    # Clean up retry state
    RetryState.delete_from(ctx.artifacts_dir)
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

    saved_path: str | None = None
    diff_path: str | None = None

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
            timestamp=ctx.timestamp,
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
            ctx.cl_name,
            ctx.project_file,
            ctx.timestamp,
            ctx.artifacts_timestamp,
            ctx.workspace_num,
            ctx.output_path,
            "completed",
            agent_name=ctx.agent_name,
            agent_model=ctx.agent_model,
            agent_llm_provider=ctx.agent_llm_provider,
            agent_vcs_provider=ctx.agent_vcs_provider,
            agent_hidden=ctx.agent_hidden,
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
            ctx.cl_name,
            ctx.project_file,
            ctx.timestamp,
            ctx.artifacts_timestamp,
            ctx.workspace_num,
            ctx.output_path,
            loop_outcome,
            agent_name=ctx.agent_name,
            agent_model=ctx.agent_model,
            agent_hidden=ctx.agent_hidden,
            retry_metadata=_retry_meta,
        )
        done_path = os.path.join(current_artifacts_dir, "done.json")
        with open(done_path, "w", encoding="utf-8") as f:
            json.dump(done_marker, f, indent=2)
        print(f"Done marker written to: {done_path} (outcome: {loop_outcome})")

    return _AgentExecResult(
        success=loop_outcome == "completed",
        saved_path=saved_path,
        diff_path=diff_path,
        current_artifacts_dir=current_artifacts_dir,
    )
