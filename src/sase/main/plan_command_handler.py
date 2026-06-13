"""Handlers for the ``sase plan`` CLI command group."""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from sase.main.plan_list_handler import handle_plan_list_command
from sase.main.plan_propose_handler import handle_plan_propose_command


def handle_plan_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch ``sase plan`` subcommands."""
    subcommand = getattr(args, "plan_subcommand", "list")
    if subcommand == "propose":
        handle_plan_propose_command(args.plan_file)
    if subcommand == "list":
        handle_plan_list_command(args)
        sys.exit(0)
    if subcommand == "approve":
        print("Error: 'sase plan approve' is not implemented yet.", file=sys.stderr)
        sys.exit(2)

    print(f"Error: unknown plan subcommand: {subcommand}", file=sys.stderr)
    sys.exit(2)
