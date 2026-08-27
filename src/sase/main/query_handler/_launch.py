"""Launch ``sase run`` prompts as detached background agents."""

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any

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
        create_launch_approval_request_from_prompt,
        maybe_handoff_launch_approval_from_agent,
        running_agent_context_requires_launch_approval,
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
        print(json.dumps(approval_request.to_dict(), sort_keys=True))
        sys.stdout.flush()
        maybe_handoff_launch_approval_from_agent(approval_request)
        sys.exit(0)

    segment_extra_env = None
    force_reuse_applied = False
    if allow_force_reuse:
        from sase.agent.force_reuse_launch import (
            apply_force_reuse_launch,
            plan_force_reuse_launch,
        )
        from sase.history.prompt import record_failed_launch_prompt
        from sase.ops.commands.run import emit_run_launch_result

        try:
            force_reuse_plan = plan_force_reuse_launch(query)
        except Exception as exc:
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
            force_reuse_applied = True

    if "%if" in query or "%proc" in query:
        _dispatch_direct_typed_launch_if_active(
            query,
            payload=payload,
            allow_force_reuse=allow_force_reuse,
            unresolved_names=tuple(unresolved_names),
        )

    launch_units = None
    if not force_reuse_applied and payload.get("launch_units") is not None:
        from sase.agent.launch_guard import (
            LaunchUnitsPayloadError,
            parse_launch_units_payload,
        )
        from sase.ops.commands.run import emit_run_launch_result

        try:
            launch_units = parse_launch_units_payload(payload.get("launch_units"))
        except LaunchUnitsPayloadError as exc:
            message = str(exc)
            print(f"Error: {message}", file=sys.stderr)
            emit_run_launch_result(success=False, message=message)
            sys.exit(1)

    try:
        if launch_units is not None:
            results = launch_agents_from_cwd(
                query,
                segment_extra_env=segment_extra_env,
                launch_units=launch_units,
            )
        elif segment_extra_env is not None:
            results = launch_agents_from_cwd(query, segment_extra_env=segment_extra_env)
        else:
            results = launch_agents_from_cwd(query)
    except RuntimeError as e:
        from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError

        if isinstance(e, MultiPromptPartialLaunchError):
            from sase.agent.partial_launch import rollback_partial_launch_results

            rollback = rollback_partial_launch_results(e.results)
            message = (
                "partial multi-prompt launch failed after spawning "
                f"{len(e.results)} child agent(s); terminated "
                f"{len(rollback.terminated_pids)} and released "
                f"{len(rollback.released_workspaces)} workspace claim(s). "
                f"Cause: {e.cause}"
            )
            _emit_failed_launch_result(message)
            sys.exit(1)
        _emit_failed_launch_result(str(e))
        sys.exit(1)
    except Exception as e:
        _emit_failed_launch_result(_exception_summary(e))
        raise

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
    _record_launched_vcs_xprompt_usage(query)
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


def _dispatch_direct_typed_launch_if_active(
    query: str,
    *,
    payload: Mapping[str, Any],
    allow_force_reuse: bool,
    unresolved_names: Sequence[str],
) -> None:
    """Admit a direct typed launch, or return so the legacy path can run."""
    from sase.agent.direct_typed_launch import (
        dispatch_direct_typed_launch,
        typed_launch_run_message,
        typed_launch_run_payload,
    )
    from sase.agent.launch_request import LaunchRequestError

    source_surface = str(payload.get("source_surface") or "")
    if not source_surface:
        source_surface = "ace" if allow_force_reuse else "cli"
    raw_inputs = payload.get("inputs")
    safe_inputs = raw_inputs if isinstance(raw_inputs, dict) else None
    try:
        dispatched = dispatch_direct_typed_launch(
            query,
            source_surface=source_surface,
            safe_inputs=safe_inputs,
        )
    except LaunchRequestError as exc:
        _emit_failed_launch_result(str(exc))
        sys.exit(1)
    if dispatched is None:
        return
    result, bundle_dir = dispatched
    message = typed_launch_run_message(result)
    result_payload = typed_launch_run_payload(
        result,
        bundle_dir,
        unresolved_names=tuple(unresolved_names),
    )
    print(message)
    for item in result.results:
        print(f"Agent started (PID {item.pid})")
    _record_launched_vcs_xprompt_usage(query)
    from sase.ops.commands.run import emit_run_launch_result

    emit_run_launch_result(success=True, message=message, payload=result_payload)
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


def _emit_failed_launch_result(message: str) -> None:
    """Print and publish a typed failed ``sase run`` launch result."""
    from sase.ops.commands.run import emit_run_launch_result

    print(f"Error: {message}", file=sys.stderr)
    emit_run_launch_result(success=False, message=message)


def _exception_summary(exc: BaseException) -> str:
    """Return a concise exception type and message for typed launch failures."""
    detail = str(exc)
    if detail:
        return f"{type(exc).__name__}: {detail}"
    return type(exc).__name__


def _record_launched_vcs_xprompt_usage(query: str) -> None:
    """Record one VCS MRU entry per launched multi-prompt segment.

    Entries are recorded in launch order so the last-launched segment ends up
    at the MRU head; a single-segment query keeps today's behavior.
    """
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.history.vcs_xprompt_mru import record_vcs_xprompt_usage

    segments = parse_multi_prompt(query).segments
    for segment in segments:
        prefix = _launched_vcs_xprompt_prefix(segment)
        if prefix is not None:
            record_vcs_xprompt_usage(prefix)


def _launched_vcs_xprompt_prefix(segment: str) -> str | None:
    """Return ``#<workflow>:<ref>`` for *segment*'s leading VCS tag, if any.

    Uses the launcher's own leading-tag semantics (skips a ``%directive``
    prefix, matches only at the start of the segment) instead of a
    registry-ordered search, so this agrees with what actually launched.
    """
    from sase.xprompt._parsing import (
        extract_project_from_vcs_tag,
        extract_vcs_workflow_tag,
    )

    tag = extract_vcs_workflow_tag(segment.strip() + " ")
    if tag is None:
        return None
    ref = extract_project_from_vcs_tag(tag)
    if not ref:
        return None
    workflow_type = _vcs_workflow_type_from_tag(tag)
    if not workflow_type:
        return None
    return f"#{workflow_type}:{ref}"


def _vcs_workflow_type_from_tag(tag: str) -> str | None:
    """Return the workflow-type prefix (e.g. ``"gh"``) of a leading VCS tag."""
    body = tag.strip()
    if not body.startswith("#"):
        return None
    body = body[1:]

    for suffix in ("!!", "??"):
        idx = body.find(suffix)
        if idx != -1:
            body = body[:idx] + body[idx + len(suffix) :]
            break

    for sep in ("(", ":", "_", "+"):
        idx = body.find(sep)
        if idx != -1:
            return body[:idx] or None
    return body or None
