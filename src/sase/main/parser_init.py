"""Argument parser definitions for project/skill initialization CLI subcommands."""

import argparse


def register_init_skills_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'init-skills' subcommand parser."""
    init_skills_parser = subparsers.add_parser(
        "init-skills",
        help="Generate and deploy agent skill files from xprompt sources",
    )
    init_skills_parser.add_argument(
        "-A",
        "--no-apply",
        action="store_true",
        help="With use_chezmoi: skip running 'chezmoi apply' after pushing",
    )
    init_skills_parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="With use_chezmoi: skip the entire git commit/push/apply sequence",
    )
    init_skills_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite existing files without confirmation",
    )
    init_skills_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing",
    )
    init_skills_parser.add_argument(
        "-P",
        "--no-push",
        action="store_true",
        help="With use_chezmoi: commit but skip 'git pull --rebase && git push' and 'chezmoi apply'",
    )
    init_skills_parser.add_argument(
        "-p",
        "--provider",
        choices=["claude", "gemini", "codex"],
        help="Only deploy for a specific provider (default: all)",
    )


def register_init_git_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'init-git' subcommand parser."""
    init_git_parser = subparsers.add_parser(
        "init-git",
        help="Initialize a new bare-repo-backed git project",
    )
    init_git_parser.add_argument(
        "project_name",
        help="Name of the project to initialize",
    )
    # Options for 'init-git' (keep sorted alphabetically by long option name)
    init_git_parser.add_argument(
        "-b",
        "--bare-dir",
        default=None,
        help="Override bare repo path (default: ~/.sase/repos/<name>.git)",
    )
    init_git_parser.add_argument(
        "-c",
        "--clone-dir",
        default=None,
        help="Override clone path (default: ~/projects/git/<name>/)",
    )
    init_git_parser.add_argument(
        "-e",
        "--existing",
        default=None,
        help="Path to an existing bare repo to register instead of creating new",
    )
