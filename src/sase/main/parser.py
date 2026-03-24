"""Argument parser creation for the SASE CLI tool."""

import argparse

from sase.main.parser_ace import register_ace_parser, register_axe_parser
from sase.main.parser_bead import register_bead_parser
from sase.main.parser_commands import (
    register_comments_parser,
    register_commit_parser,
    register_config_parser,
    register_init_git_parser,
    register_logs_parser,
    register_notify_parser,
    register_path_parser,
    register_plan_parser,
    register_questions_parser,
    register_restore_parser,
    register_revert_parser,
    register_run_parser,
    register_search_parser,
    register_xprompt_parser,
)


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="SASE - Structured Agentic Software Engineering", prog="sase"
    )

    # Top-level subparsers
    top_level_subparsers = parser.add_subparsers(
        dest="command", help="Available commands", required=True
    )

    # =========================================================================
    # TOP-LEVEL SUBCOMMANDS (keep sorted alphabetically)
    # =========================================================================
    register_ace_parser(top_level_subparsers)
    register_axe_parser(top_level_subparsers)
    register_bead_parser(top_level_subparsers)
    register_comments_parser(top_level_subparsers)
    register_commit_parser(top_level_subparsers)
    register_config_parser(top_level_subparsers)
    register_init_git_parser(top_level_subparsers)
    register_logs_parser(top_level_subparsers)
    register_notify_parser(top_level_subparsers)
    register_path_parser(top_level_subparsers)
    register_plan_parser(top_level_subparsers)
    register_questions_parser(top_level_subparsers)
    register_restore_parser(top_level_subparsers)
    register_revert_parser(top_level_subparsers)
    register_run_parser(top_level_subparsers)
    register_search_parser(top_level_subparsers)
    register_xprompt_parser(top_level_subparsers)

    return parser
