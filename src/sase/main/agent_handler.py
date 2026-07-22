"""Handler for ``sase agent`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_agent_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate agent sub-handler."""
    sub = getattr(args, "agent_subcommand", None) or "list"

    if sub == "list":
        from sase.agents.cli_list import handle_agents_list

        handle_agents_list(args)
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

    if sub == "sync":
        from sase.agents.cli_sync import handle_agents_sync

        sys.exit(handle_agents_sync(args))

    if sub == "tribe":
        from sase.agents.cli_tribe import handle_agents_tribe

        handle_agents_tribe(args)
        sys.exit(0)

    if sub == "archive":
        from sase.agents.cli_archive import handle_agents_archive

        handle_agents_archive(args)
        return

    if sub == "artifacts":
        if getattr(args, "artifacts_subcommand", None) == "layout":
            from sase.agents.cli_artifacts_layout import handle_agents_artifacts_layout

            handle_agents_artifacts_layout(args)
            sys.exit(0)

        print("Usage: sase agent artifacts {layout}")
        sys.exit(1)

    if sub == "index":
        from sase.agents.cli_index import handle_agents_index

        handle_agents_index(args)
        sys.exit(0)

    if sub == "names":
        from sase.agents.cli_names import handle_agents_names

        handle_agents_names(args)
        sys.exit(0)

    print("Usage: sase agent {archive,artifacts,index,kill,list,names,show,sync,tribe}")
    sys.exit(1)
