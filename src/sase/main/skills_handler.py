"""Handler for ``sase skill`` subcommands."""

from __future__ import annotations

import argparse
import sys


def _handle_skills_list_command(args: argparse.Namespace) -> None:
    """Handle the ``sase skill list`` dashboard."""
    from sase.skills.cli_list import handle_skills_list_command

    handle_skills_list_command(args)


def _handle_skills_log_command(args: argparse.Namespace) -> None:
    """Handle the ``sase skill log`` dashboard."""
    from sase.skills.cli_log import handle_skills_log_command

    handle_skills_log_command(args)


def _handle_skills_use_command(args: argparse.Namespace) -> None:
    """Handle ``sase skill use``."""
    from sase.skills.cli_use import handle_skills_use_command

    handle_skills_use_command(args)


def handle_skills_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase skill`` sub-handler."""
    sub = getattr(args, "skill_subcommand", None) or "list"

    if sub == "init":
        from .init_skills_handler import run_init_skills

        sys.exit(run_init_skills(args))

    if sub == "list":
        _handle_skills_list_command(args)
        sys.exit(0)

    if sub == "log":
        _handle_skills_log_command(args)
        sys.exit(0)

    if sub == "use":
        _handle_skills_use_command(args)
        sys.exit(0)

    print("Usage: sase skill {init,list,log,use}", file=sys.stderr)
    sys.exit(1)
