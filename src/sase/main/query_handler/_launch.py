"""Launch ``sase run`` prompts as detached background agents."""

import json
import sys

from sase.agent.launcher import launch_agents_from_cwd


def launch_query(query: str) -> None:
    """Launch *query* as detached background agent process(es).

    Replicates the TUI ``@`` keybinding behaviour without TUI dependencies.
    The spawned agent appears in the TUI Agents tab.

    For multi-prompt queries (containing ``---`` separators), all segments
    are launched sequentially before this function returns.
    """
    from sase.ops.cli import load_request
    from sase.ops.names import RUN_LAUNCH

    request = load_request(RUN_LAUNCH)
    payload = dict(request.payload)
    if isinstance(payload.get("prompt"), str) and payload["prompt"]:
        query = payload["prompt"]
    allow_force_reuse = bool(payload.get("allow_force_reuse"))
    from sase.agent.prompt_inputs import missing_required_input_names

    missing_inputs = missing_required_input_names(query)
    if missing_inputs:
        from sase.output import print_status
        from sase.ops.commands.run import emit_run_launch_result

        names = ", ".join(missing_inputs)
        message = (
            f"Prompt declares required input(s) without defaults: {names}. "
            "Interactive input collection is only available in `sase ace`; "
            "add a default to each input or launch from the TUI."
        )
        print_status(message, "error")
        emit_run_launch_result(success=False, message=message)
        sys.exit(1)

    from sase.output import print_status
    from sase.xprompt.unresolved import (
        format_unresolved_reference_warning,
        format_unresolved_references_toast,
        scan_query_for_unresolved_references,
    )

    unresolved_names = scan_query_for_unresolved_references(query)
    for name in unresolved_names:
        print_status(format_unresolved_reference_warning(name), "warning")

    from sase.agent.launch_request import (
        LaunchRequestError,
        cancel_launch_approval_request,
        create_launch_approval_request_from_prompt,
        running_agent_context_requires_launch_approval,
        wait_for_launch_approval,
    )

    if running_agent_context_requires_launch_approval():
        try:
            approval_request = create_launch_approval_request_from_prompt(
                query,
                reason="Running agent requested a detached launch.",
                source_surface="agent_skill",
            )
        except LaunchRequestError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            outcome = wait_for_launch_approval(approval_request)
        except KeyboardInterrupt:
            try:
                cancel_launch_approval_request(approval_request)
            except LaunchRequestError:
                pass
            print("Launch request cancelled", file=sys.stderr)
            sys.exit(130)
        print(json.dumps(outcome.to_dict(), sort_keys=True))
        sys.exit(0)

    segment_extra_env = None
    if allow_force_reuse:
        from sase.agent.force_reuse_launch import (
            apply_force_reuse_launch,
            plan_force_reuse_launch,
        )
        from sase.history.prompt import record_failed_launch_prompt
        from sase.ops.commands.run import emit_run_launch_result

        try:
            force_reuse_plan = plan_force_reuse_launch(query)
        except RuntimeError as exc:
            message = str(exc)
            record_failed_launch_prompt(query)
            print(f"Error: {message}", file=sys.stderr)
            emit_run_launch_result(success=False, message=message)
            sys.exit(1)
        if force_reuse_plan is not None:
            try:
                apply_force_reuse_launch(force_reuse_plan)
            except Exception as exc:
                message = f"Agent name reuse failed: {exc}"
                record_failed_launch_prompt(query)
                print(f"Error: {message}", file=sys.stderr)
                emit_run_launch_result(success=False, message=message)
                sys.exit(1)
            query = force_reuse_plan.rewritten_prompt
            segment_extra_env = force_reuse_plan.segment_envs

    try:
        if segment_extra_env is not None:
            results = launch_agents_from_cwd(query, segment_extra_env=segment_extra_env)
        else:
            results = launch_agents_from_cwd(query)
    except RuntimeError as e:
        from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError

        if isinstance(e, MultiPromptPartialLaunchError):
            from sase.agent.partial_launch import rollback_partial_launch_results

            rollback = rollback_partial_launch_results(e.results)
            print(
                "Error: partial multi-prompt launch failed after spawning "
                f"{len(e.results)} child agent(s); terminated "
                f"{len(rollback.terminated_pids)} and released "
                f"{len(rollback.released_workspaces)} workspace claim(s). "
                f"Cause: {e.cause}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not results:
        from sase.ops.commands.run import emit_run_launch_result

        print("Error: agent launch produced no results", file=sys.stderr)
        emit_run_launch_result(
            success=False, message="agent launch produced no results"
        )
        sys.exit(1)

    from sase.ops.commands.run import emit_run_launch_result

    for result in results:
        print(f"Agent started (PID {result.pid})")
    _record_leading_vcs_xprompt_usage(query)
    result_payload: dict[str, object] = {
        "count": len(results),
        "pids": [result.pid for result in results],
        "results": [_serialize_launch_result(item) for item in results],
        "request_agents_refresh": True,
        "schedule_agents_refresh": True,
    }
    if unresolved_names:
        result_payload["warning_messages"] = [
            format_unresolved_references_toast(unresolved_names)
        ]
    emit_run_launch_result(
        success=True,
        message=f"Started {len(results)} agent(s)",
        payload=result_payload,
    )
    sys.exit(0)


def _serialize_launch_result(result: object) -> dict[str, object]:
    return {
        "agent_name": getattr(result, "agent_name", None),
        "artifacts_dir": getattr(result, "artifacts_dir", ""),
        "cl_name": getattr(result, "cl_name", ""),
        "output_path": getattr(result, "output_path", ""),
        "pid": getattr(result, "pid", 0),
        "project_file": getattr(result, "project_file", ""),
        "project_name": getattr(result, "project_name", ""),
        "timestamp": getattr(result, "timestamp", ""),
        "workflow_name": getattr(result, "workflow_name", ""),
        "workspace_dir": getattr(result, "workspace_dir", ""),
        "workspace_num": getattr(result, "workspace_num", 0),
    }


def _record_leading_vcs_xprompt_usage(query: str) -> None:
    """Record the leading VCS prefix from a successful launch query."""
    prefix = _leading_vcs_xprompt_prefix(query)
    if prefix is None:
        return
    from sase.history.vcs_xprompt_mru import record_vcs_xprompt_usage

    record_vcs_xprompt_usage(prefix)


def _leading_vcs_xprompt_prefix(query: str) -> str | None:
    """Return ``#<workflow>:<ref>`` for the first VCS tag in *query*, if any."""
    from sase.workspace_provider import get_ref_patterns

    for workflow_type, pattern in get_ref_patterns().items():
        match = pattern.search(query)
        if match is None:
            continue
        ref = match.group(1) or match.group(2)
        if ref:
            return f"#{workflow_type}:{ref}"
    return None
