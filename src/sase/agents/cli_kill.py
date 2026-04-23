"""``sase agents kill`` — terminate a running agent by name."""

from __future__ import annotations

import argparse
import sys

from sase.agent.running import kill_named_agent


def handle_agents_kill(args: argparse.Namespace) -> None:
    """SIGTERM the named agent, echoing the outcome."""
    name: str = args.name
    result = kill_named_agent(name)

    if result.success:
        print(result.message)
        sys.exit(0)

    print(result.message, file=sys.stderr)
    sys.exit(2)
