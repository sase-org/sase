"""Argument parser definitions for initialization command groups."""

import argparse


def add_enable_project_memory_argument(parser: argparse.ArgumentParser) -> None:
    """Add the compatibility flag that marks a repository as SASE-managed."""
    parser.add_argument(
        "-M",
        "--enable-project-memory",
        action="store_true",
        help=(
            "Create or update sase/sase.yml with is_sase_managed: true, enabling "
            "managed project memory (cannot be combined with --check)"
        ),
    )


def add_skills_init_arguments(parser: argparse.ArgumentParser) -> None:
    """Add flags shared by ``sase skill init`` and its ``sase init skills`` alias."""
    parser.add_argument(
        "-D",
        "--allow-dirty",
        action="store_true",
        help=(
            "Allow a chezmoi deploy from dirty or unmerged skill sources "
            "(dangerous: can revert other agents' deployments)"
        ),
    )
    parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Report generated skill-file drift without writing files",
    )
    parser.add_argument(
        "-d",
        "--diff",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Show full generated skill-file diffs without writing files",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help=(
            "Overwrite existing files without confirmation, and deploy even when "
            "the recorded provenance manifest names a different source commit "
            "(dangerous: can revert other agents' deployments)"
        ),
    )
    parser.add_argument(
        "-A",
        "--no-apply",
        action="store_true",
        help="With use_chezmoi: skip running 'chezmoi apply' after pushing",
    )
    parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="With use_chezmoi: skip the entire git commit/push/apply sequence",
    )
    parser.add_argument(
        "-P",
        "--no-push",
        action="store_true",
        help="With use_chezmoi: commit but skip 'git pull --rebase && git push' and 'chezmoi apply'",
    )
    parser.add_argument(
        "-p",
        "--provider",
        metavar="PROVIDER",
        help="Only deploy for a registered provider (default: all)",
    )


def register_init_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'init' command group."""
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize SASE-managed resources",
        description=(
            "Check and initialize SASE-managed resources. With no subcommand, "
            "runs the onboarding coordinator for config, memory, repositories, "
            "and skills."
        ),
        epilog=(
            "Advanced deploy controls live on explicit subcommands; for example, "
            "use `sase init memory --no-commit` or `sase skill init --no-push`."
        ),
    )
    project_scope_group = init_parser.add_mutually_exclusive_group()
    project_scope_group.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Attempt every known enabled main SASE project",
    )
    mode_group = init_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Report initialization drift without writing files or running initializers",
    )
    init_parser.add_argument(
        "-d",
        "--diff",
        action="store_true",
        help="Show full file diffs for planned changes",
    )
    add_enable_project_memory_argument(project_scope_group)
    mode_group.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=(
            "Run every needed initializer without generic prompts; cannot "
            "authorize creation of a missing provider sidecar repository"
        ),
    )
    init_subparsers = init_parser.add_subparsers(
        dest="init_subcommand",
        help="Initialization subcommands",
        required=False,
    )

    config_parser = init_subparsers.add_parser(
        "config",
        help="Alias for `sase config init`",
        description=(
            "Compatibility alias for `sase config init`, which interactively "
            "creates, selects, or migrates the explicit SASE owner identity."
        ),
    )
    config_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Report whether owner identity initialization or migration is needed",
    )

    memory_parser = init_subparsers.add_parser(
        "memory",
        help="Alias for `sase memory init`",
        description=(
            "Compatibility alias for `sase memory init`, which creates or "
            "refreshes SASE memory files, managed AGENTS.md, and provider "
            "instruction shims."
        ),
    )
    memory_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Report memory initialization drift without writing files",
    )
    memory_parser.add_argument(
        "-d",
        "--diff",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Show full file diffs for planned memory changes",
    )
    add_enable_project_memory_argument(memory_parser)
    memory_parser.add_argument(
        "-m",
        "--message",
        metavar="MESSAGE",
        help=(
            "Commit subject for folding eligible memory and generated-change source edits; a "
            "`docs(memory):` tag is added if omitted"
        ),
    )
    memory_parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="Skip the project git commit/push sequence",
    )

    repo_parser = init_subparsers.add_parser(
        "repo",
        help="Alias for `sase repo init`",
        description=(
            "Alias for `sase repo init`, which initializes configured sidecars, "
            "declares the plans sidecar, and maintains the project ignore rule. "
            "Creating a missing provider repository always requires an "
            "interactive, default-no y/yes confirmation."
        ),
    )
    repo_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Report sidecar, config, and ignore-rule work without writing files",
    )
    repo_parser.add_argument(
        "-d",
        "--diff",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Show full file diffs for planned repository changes",
    )
    repo_parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="Write project config and ignore rules without committing or pushing",
    )

    skills_parser = init_subparsers.add_parser(
        "skills",
        help="Alias for `sase skill init`",
        description=(
            "Compatibility alias for `sase skill init`, which generates and "
            "deploys agent skill files from canonical skill sources."
        ),
    )
    add_skills_init_arguments(skills_parser)
