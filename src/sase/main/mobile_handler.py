"""Handler for ``sase mobile`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_mobile_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate mobile sub-handler."""
    sub = getattr(args, "mobile_subcommand", None)
    gateway_sub = getattr(args, "mobile_gateway_subcommand", None)

    if sub == "agent-bridge":
        from sase.integrations.mobile_agents import handle_mobile_agent_bridge

        sys.exit(handle_mobile_agent_bridge(args))

    if sub == "gateway" and gateway_sub == "start":
        from sase.integrations.mobile_gateway import handle_mobile_gateway_start

        handle_mobile_gateway_start(args)
        return

    print("Usage: sase mobile {gateway,agent-bridge}", file=sys.stderr)
    sys.exit(1)
