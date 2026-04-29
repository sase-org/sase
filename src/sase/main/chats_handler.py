"""Handler for ``sase chats`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_chats_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate chats sub-handler."""
    sub = getattr(args, "chats_subcommand", None)

    if sub == "list":
        from sase.chats.cli_list import handle_chats_list

        handle_chats_list(args)
        sys.exit(0)

    if sub == "show":
        from sase.chats.cli_show import handle_chats_show

        handle_chats_show(args)
        sys.exit(0)

    print("Usage: sase chats {list,show}")
    sys.exit(1)
