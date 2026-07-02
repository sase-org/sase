"""Launch ``sase run`` prompts as detached background agents."""

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

        names = ", ".join(missing_inputs)
        print_status(
            f"Prompt declares required input(s) without defaults: {names}. "
            "Interactive input collection is only available in `sase ace`; "
            "add a default to each input or launch from the TUI.",
            "error",
        )
        sys.exit(1)

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
        print("Error: agent launch produced no results", file=sys.stderr)
        sys.exit(1)

    for result in results:
        print(f"Agent started (PID {result.pid})")
    sys.exit(0)
