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
        scan_query_for_unresolved_references,
    )

    for name in scan_query_for_unresolved_references(query):
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
            request = create_launch_approval_request_from_prompt(
                query,
                reason="Running agent requested a detached launch.",
                source_surface="agent_skill",
            )
        except LaunchRequestError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            outcome = wait_for_launch_approval(request)
        except KeyboardInterrupt:
            try:
                cancel_launch_approval_request(request)
            except LaunchRequestError:
                pass
            print("Launch request cancelled", file=sys.stderr)
            sys.exit(130)
        print(json.dumps(outcome.to_dict(), sort_keys=True))
        sys.exit(0)

    try:
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
    emit_run_launch_result(
        success=True,
        message=f"Started {len(results)} agent(s)",
        payload={"count": len(results), "pids": [result.pid for result in results]},
    )
    sys.exit(0)
