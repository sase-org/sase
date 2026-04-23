"""Handler for ``sase agents`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_agents_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate agents sub-handler."""
    sub = getattr(args, "agents_subcommand", None) or "status"

    if sub == "status":
        from sase.agents.cli_status import handle_agents_status

        handle_agents_status(args)
        sys.exit(0)

    if sub == "kill":
        from sase.agents.cli_kill import handle_agents_kill

        handle_agents_kill(args)
        # handle_agents_kill calls sys.exit() itself with the appropriate code
        return

    if sub == "show":
        from sase.agents.cli_show import handle_agents_show

        handle_agents_show(args)
        sys.exit(0)

    print("Usage: sase agents {status,kill,show}")
    sys.exit(1)
