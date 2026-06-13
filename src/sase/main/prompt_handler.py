"""Handler for ``sase prompt`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_prompt_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate prompt sub-handler."""
    sub = getattr(args, "prompt_subcommand", None)

    if sub == "list":
        from sase.prompt.cli_list import handle_prompt_list

        handle_prompt_list(args)
        sys.exit(0)

    if sub == "show":
        from sase.prompt.cli_show import handle_prompt_show

        handle_prompt_show(args)
        sys.exit(0)

    if sub == "stats":
        from sase.prompt.cli_stats import handle_prompt_stats

        handle_prompt_stats(args)
        sys.exit(0)

    print("Usage: sase prompt {list,show,stats}")
    sys.exit(1)
