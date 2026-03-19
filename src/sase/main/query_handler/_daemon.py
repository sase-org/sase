"""Daemon mode for sase run — launches prompt as a detached background agent."""

import sys

from sase.agent_launcher import launch_agent_from_cwd


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
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Agent started (PID {result.pid})")
    sys.exit(0)
