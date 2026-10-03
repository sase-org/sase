"""Launch ``sase run`` prompts as detached background agents."""

import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sase.agent.launcher import launch_agents_from_cwd
from sase.history.prompt_store import PromptOrigin

#: Process marker set on every monitor-supervised command.
MONITOR_ID_ENV = "SASE_MONITOR_ID"

#: Marker set on every ToolRun child command. Mirrors
#: ``sase.tool.executor_process.TOOL_RUN_ID_ENV`` locally to avoid an import cycle.
TOOL_RUN_ID_ENV = "SASE_TOOL_RUN_ID"


def _sase_run_ingress_origin() -> PromptOrigin:
    """Return the history origin for one ``sase run`` ingress launch.

    Monitor commands, gate commands, and nested ToolRun child commands reach
    ``sase run`` as automation, so they classify as ``generated`` (which the
    history writers drop). Every other terminal invocation classifies as
    ``typed``. A blank ToolRun marker counts as absent so it never suppresses
    human history.
    """
    from sase.notification_gates.command_runner import GATE_COMMAND_ENV

    if os.environ.get(MONITOR_ID_ENV):
        return "generated"
    if os.environ.get(GATE_COMMAND_ENV):
        return "generated"
    if os.environ.get(TOOL_RUN_ID_ENV):
        return "generated"
    return "typed"


def _payload_history_text(payload: Mapping[str, Any]) -> str | None:
    """Return the submitter's canonical text from a ``sase run`` payload.

    Only a non-empty string counts: it is the pre-rewrite text when the
    submitter rewrote the prompt before ``sase run`` (the TUI provider
    guard). Anything else means the launcher records the query itself.
    """
    value = payload.get("history_text")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _payload_history_origin(
    payload: Mapping[str, Any], ingress_origin: PromptOrigin
) -> PromptOrigin:
    """Downgrade the ingress origin from a ``sase run`` payload, if asked.

    Only ``"generated"`` is honored, and it overrides the ingress origin;
    every other value (including ``"typed"``) is ignored so a payload can
    never upgrade automation back to human history.
    """
    if payload.get("history_origin") == "generated":
        return "generated"
    return ingress_origin


def _expand_history_text_best_effort(history_text: str) -> str:
    """Expand project tags in history text, keeping the literal on error."""
    if "+" not in history_text:
        return history_text
    try:
        from sase.project_tags import (
            expand_project_tags,
            validate_project_tags_for_launch,
        )

        validate_project_tags_for_launch(history_text)
        return expand_project_tags(history_text)
    except Exception:  # noqa: BLE001 - tags stay literal when catalog is cold.
        return history_text


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
    ingress_origin = _sase_run_ingress_origin()
    # The payload origin is downgrade-only; the payload text is the
    # submitter's canonical text when it rewrote the prompt before `sase run`.
    resolved_origin = _payload_history_origin(payload, ingress_origin)
    history_text = _payload_history_text(payload)
    from sase.agent.prompt_inputs import missing_required_input_names

    missing_inputs = missing_required_input_names(query)
    if missing_inputs:
        from sase.output import print_status
        from sase.ops.commands.run import emit_run_launch_result

        names = ", ".join(missing_inputs)
        message = (
            f"Prompt declares required input(s) without defaults: {names}. "
            "Interactive input collection is only available in `sase tui`; "
            "add a default to each input or launch from the TUI."
        )
        print_status(message, "error")
        emit_run_launch_result(success=False, message=message)
        sys.exit(1)

    from sase.output import print_status
    from sase.macro.unresolved import (
        format_unresolved_reference_warning,
        format_unresolved_references_toast,
        scan_query_for_unresolved_references,
    )

    unresolved_names = scan_query_for_unresolved_references(query)
    for name in unresolved_names:
        print_status(format_unresolved_reference_warning(name), "warning")

    if not _confirm_hold_arm(query):
        message = "Hold not armed; launch cancelled."
        _emit_failed_launch_result(message)
        sys.exit(1)

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

    from sase.dispatch.launch import (
        RemoteDispatchLaunchError,
        maybe_dispatch_launch,
    )

    try:
        dispatch_result = maybe_dispatch_launch(
            query,
            payload=payload,
            unresolved_names=tuple(unresolved_names),
        )
    except RemoteDispatchLaunchError as exc:
        from sase.history.prompt import record_failed_launch_prompt

        # The forwarded prompt is recorded verbatim: remote dispatch sends it
        # before project-tag expansion, which happens on the target machine.
        record_failed_launch_prompt(
            history_text if history_text is not None else query,
            origin=resolved_origin,
        )
        _emit_failed_launch_result(str(exc))
        sys.exit(1)
    if dispatch_result is not None:
        from sase.history.prompt import add_or_update_prompt
        from sase.ops.commands.run import emit_run_launch_result

        add_or_update_prompt(
            history_text if history_text is not None else query,
            allow_short=True,
            origin=resolved_origin,
        )
        print(dispatch_result.message)
        emit_run_launch_result(
            success=True,
            message=dispatch_result.message,
            payload=dispatch_result.payload,
        )
        sys.exit(0)

    # Project tags resolve against this machine's projects: remote-dispatch
    # already returned above with the prompt forwarded verbatim, so validate
    # and expand here, before force-reuse, typed dispatch, MRU, and spawn.
    if "+" in query:
        from sase.history.prompt import record_failed_launch_prompt
        from sase.ops.commands.run import emit_run_launch_result
        from sase.project_tags import (
            ProjectTagError,
            expand_project_tags,
            validate_project_tags_for_launch,
        )

        try:
            validate_project_tags_for_launch(query)
        except ProjectTagError as exc:
            message = str(exc)
            record_failed_launch_prompt(
                history_text if history_text is not None else query,
                origin=resolved_origin,
            )
            print(f"Error: {message}", file=sys.stderr)
            emit_run_launch_result(success=False, message=message)
            sys.exit(1)
        try:
            query = expand_project_tags(query)
        except ProjectTagError as exc:
            message = str(exc)
            record_failed_launch_prompt(
                history_text if history_text is not None else query,
                origin=resolved_origin,
            )
            print(f"Error: {message}", file=sys.stderr)
            emit_run_launch_result(success=False, message=message)
            sys.exit(1)
        except Exception:  # noqa: BLE001 - tags stay literal when catalog is cold.
            pass

    # The payload text gets the same project-tag expansion the query gets;
    # best-effort, so a cold catalog keeps the literal text.
    if history_text is not None:
        history_text = _expand_history_text_best_effort(history_text)

    # The launcher sees the force-reuse rewritten prompt below; history keeps
    # what the human submitted (after project-tag expansion).
    history_query = query
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
            record_failed_launch_prompt(
                history_text if history_text is not None else query,
                origin=resolved_origin,
            )
            print(f"Error: {message}", file=sys.stderr)
            emit_run_launch_result(success=False, message=message)
            sys.exit(1)
        if force_reuse_plan is not None:
            try:
                apply_force_reuse_launch(force_reuse_plan)
            except Exception as exc:
                message = f"Agent name reuse failed: {exc}"
                record_failed_launch_prompt(
                    history_text if history_text is not None else query,
                    origin=resolved_origin,
                )
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
            history_query=(history_text if history_text is not None else history_query),
            history_origin=resolved_origin,
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

    # The launcher records the submitter's canonical text: the payload text
    # when the submitter rewrote the prompt first, else the pre-rewrite
    # query when force-reuse rewrote it, else the query itself.
    launch_history_text = history_text
    if launch_history_text is None and force_reuse_applied:
        launch_history_text = history_query
    try:
        if launch_units is not None:
            results = launch_agents_from_cwd(
                query,
                segment_extra_env=segment_extra_env,
                launch_units=launch_units,
                origin=resolved_origin,
                history_text=launch_history_text,
            )
        elif segment_extra_env is not None:
            results = launch_agents_from_cwd(
                query,
                segment_extra_env=segment_extra_env,
                origin=resolved_origin,
                history_text=launch_history_text,
            )
        else:
            results = launch_agents_from_cwd(
                query, origin=resolved_origin, history_text=launch_history_text
            )
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
    history_query: str | None = None,
    history_origin: PromptOrigin | None = "typed",
) -> None:
    """Admit a direct typed launch, or return so the legacy path can run.

    *history_query* is the pre-rewrite root prompt the human submitted; it is
    what history records, since these launches bypass the launcher that would
    otherwise record it (and would only see the rewritten prompt).
    """
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
    recorded_query = history_query if history_query is not None else query
    try:
        dispatched = dispatch_direct_typed_launch(
            query,
            source_surface=source_surface,
            safe_inputs=safe_inputs,
        )
    except LaunchRequestError as exc:
        from sase.history.prompt import record_failed_launch_prompt

        record_failed_launch_prompt(recorded_query, origin=history_origin)
        _emit_failed_launch_result(str(exc))
        sys.exit(1)
    if dispatched is None:
        return
    result, bundle_dir = dispatched
    from sase.history.prompt import add_or_update_prompt

    add_or_update_prompt(recorded_query, allow_short=True, origin=history_origin)
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


def _confirm_hold_arm(
    query: str,
    *,
    is_tty_fn: Callable[[], bool] | None = None,
    confirm_fn: Callable[[str], bool] | None = None,
) -> bool:
    """Return whether the launch should proceed, prompting when needed.

    Declines only when *query* arms a broad ``%hold`` on an interactive TTY
    session that is neither a running agent nor a durable proc. Every other
    launch proceeds unconditionally: the arm notification and the
    LaunchApproval preview already list the capture.
    """
    from sase.ops.models import PROC_ID_ENV

    if os.environ.get("SASE_AGENT") or os.environ.get(PROC_ID_ENV):
        return True
    is_tty = is_tty_fn or _stdin_stdout_are_tty
    if not is_tty():
        return True
    from sase.agent.launch_hold_preview import hold_confirmation_body

    body = hold_confirmation_body(query)
    if body is None:
        return True
    confirm = confirm_fn or _confirm_hold_interactively
    return confirm(body)


def _stdin_stdout_are_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _confirm_hold_interactively(body: str) -> bool:
    print(body)
    try:
        answer = input("Arm this hold? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


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
    from sase.history.vcs_macro_mru import record_vcs_xprompt_usage

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
    from sase.macro._parsing import (
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
