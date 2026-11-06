"""``sase agent kill`` — terminate a running agent by name."""

from __future__ import annotations

import argparse
import sys

from sase.agent.hijack.custody import held_record_for_agent
from sase.agent.running import kill_named_agent


def handle_agents_kill(args: argparse.Namespace) -> None:
    """SIGTERM the named agent, echoing the outcome."""
    name: str = args.name
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
