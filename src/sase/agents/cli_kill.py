"""``sase agent kill`` — terminate a running agent by name."""

from __future__ import annotations

import argparse
import sys

from sase.agent.hijack.custody import held_record_for_agent
from sase.agent.running import kill_named_agent


def handle_agents_kill(args: argparse.Namespace) -> None:
    """SIGTERM the named agent, echoing the outcome."""
    name: str = args.name
    # An explicit `x` release abandons a stop_blocked hold (the only path
    # that unpins) before the normal kill releases the workspace.
    try:
        from sase.agent.hijack.custody import abandon_stop_blocked_for_workspace
        from sase.agent.hijack.ledger import load_record_by_agent_name

        _blocked = load_record_by_agent_name(name)
        if (
            isinstance(_blocked, dict)
            and str(_blocked.get("state") or "") == "stop_blocked"
        ):
            _project = _blocked.get("project_file")
            _workspace = _blocked.get("workspace_num")
            if isinstance(_project, str) and _project and isinstance(_workspace, int):
                abandon_stop_blocked_for_workspace(_project, _workspace)
    except Exception:
        pass
    if held_record_for_agent(name) is not None:
        print(
            f"Agent '{name}' is already stopped (hijacked); "
            f"use sase agent recover {name} -a dismiss",
            file=sys.stderr,
        )
        sys.exit(2)
    result = kill_named_agent(name)

    if result.success:
        print(result.message)
        sys.exit(0)

    print(result.message, file=sys.stderr)
    sys.exit(2)
