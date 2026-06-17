"""Handler for ``sase chat`` subcommands."""

from __future__ import annotations

import argparse
import sys


def handle_chat_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate chat sub-handler."""
    sub = getattr(args, "chat_subcommand", None)

    if sub == "list":
        from sase.chat.cli_list import handle_chat_list

        handle_chat_list(args)
        sys.exit(0)

    if sub == "show":
        from sase.chat.cli_show import handle_chat_show

        handle_chat_show(args)
        sys.exit(0)

    print("Usage: sase chat {list,show}")
    sys.exit(1)
