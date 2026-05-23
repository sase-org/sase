"""Argument parser definitions for git and skill initialization command groups."""

import argparse

from sase.main.parser_sdd import add_sdd_path_arg


def register_git_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'git' command group."""
    git_parser = subparsers.add_parser(
        "git",
        help="Manage bare-repo-backed git projects",
    )
    git_subparsers = git_parser.add_subparsers(
        dest="git_subcommand",
        help="Git subcommands",
        required=True,
    )

    init_parser = git_subparsers.add_parser(
        "init",
        help="Initialize a new bare-repo-backed git project",
    )
    init_parser.add_argument(
        "project_name",
        help="Name of the project to initialize",
    )
    # Options for 'sase git init' (keep sorted alphabetically by long option name)
    init_parser.add_argument(
        "-b",
        "--bare-dir",
        default=None,
        help="Override bare repo path (default: ~/.sase/repos/<name>.git)",
    )
    init_parser.add_argument(
        "-c",
        "--clone-dir",
        default=None,
        help="Override clone path (default: ~/projects/git/<name>/)",
    )
    init_parser.add_argument(
        "-e",
        "--existing",
        default=None,
        help="Path to an existing bare repo to register instead of creating new",
    )


def register_init_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'init' command group."""
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize SASE-managed resources",
    )
    init_parser.add_argument(
        "--check",
        action="store_true",
        help="Report initialization drift without writing files",
    )
    init_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Run every needed initializer without prompting",
    )
    init_subparsers = init_parser.add_subparsers(
        dest="init_subcommand",
        help="Initialization subcommands",
        required=False,
    )

    memory_parser = init_subparsers.add_parser(
        "memory",
        help="Alias for `sase memory init`",
        description=(
            "Compatibility alias for `sase memory init`, which creates or "
            "refreshes SASE memory files and provider instruction shims."
        ),
    )
    memory_parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="Skip the project git commit/push sequence",
    )

    sdd_parser = init_subparsers.add_parser(
        "sdd",
        help="Create or refresh SDD README files and directory map assets",
    )
    add_sdd_path_arg(sdd_parser)

    skills_parser = init_subparsers.add_parser(
        "skills",
        help="Generate and deploy agent skill files from xprompt sources",
    )
    skills_parser.add_argument(
        "-A",
        "--no-apply",
        action="store_true",
        help="With use_chezmoi: skip running 'chezmoi apply' after pushing",
    )
    skills_parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="With use_chezmoi: skip the entire git commit/push/apply sequence",
    )
    skills_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite existing files without confirmation",
    )
    skills_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing",
    )
    skills_parser.add_argument(
        "-P",
        "--no-push",
        action="store_true",
        help="With use_chezmoi: commit but skip 'git pull --rebase && git push' and 'chezmoi apply'",
    )
    skills_parser.add_argument(
        "-p",
        "--provider",
        choices=["claude", "gemini", "codex", "opencode", "qwen"],
        help="Only deploy for a specific provider (default: all)",
    )
