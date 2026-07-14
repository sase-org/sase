"""Handlers for the ``sase plan`` CLI command group."""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from sase.main.plan_approve_handler import handle_plan_approve_command
from sase.main.plan_list_handler import handle_plan_list_command
from sase.main.plan_links_handler import handle_plan_links_command
from sase.main.plan_propose_handler import handle_plan_propose_command
from sase.main.plan_reject_handler import handle_plan_reject_command
from sase.main.plan_search_handler import handle_plan_search_command


def handle_plan_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch ``sase plan`` subcommands."""
    subcommand = getattr(args, "plan_subcommand", "list")
    if subcommand == "propose":
        handle_plan_propose_command(args.plan_file)
    if subcommand == "list":
        handle_plan_list_command(args)
        sys.exit(0)
    if subcommand == "links":
        handle_plan_links_command(args)
    if subcommand == "approve":
        handle_plan_approve_command(args)
    if subcommand == "reject":
        handle_plan_reject_command(args)
    if subcommand == "search":
        handle_plan_search_command(args)
        sys.exit(0)

    print(f"Error: unknown plan subcommand: {subcommand}", file=sys.stderr)
    sys.exit(2)
