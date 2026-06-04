"""Daemon mode for sase run — launches prompt as a detached background agent."""

import sys

from sase.agent.launcher import launch_agent_from_cwd


def run_query_daemon(query: str) -> None:
    """Launch *query* as a detached background agent process.

    Replicates the TUI ``@`` keybinding behaviour without TUI dependencies.
    The spawned agent appears in the TUI Agents tab.

    For multi-prompt queries (containing ``---`` separators), all segments
    are launched sequentially before this function returns.
    """
    try:
        result = launch_agent_from_cwd(query)
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

    print(f"Agent started (PID {result.pid})")
    sys.exit(0)
