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

    if sub == "tag":
        from sase.agents.cli_tag import handle_agents_tag

        handle_agents_tag(args)
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

        print("Usage: sase agents artifacts {layout}")
        sys.exit(1)

    if sub == "index":
        from sase.agents.cli_index import handle_agents_index

        handle_agents_index(args)
        sys.exit(0)

    if sub == "names":
        from sase.agents.cli_names import handle_agents_names

        handle_agents_names(args)
        sys.exit(0)

    print("Usage: sase agents {archive,artifacts,index,kill,names,show,status,tag}")
    sys.exit(1)
