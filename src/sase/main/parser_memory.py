"""Argument parser definition for the ``sase memory`` command group."""

import argparse


def register_memory_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``memory`` command group."""
    memory_parser = subparsers.add_parser(
        "memory",
        help="Inspect and initialize SASE memory context",
        description=(
            "Inspect SASE memory context. With no subcommand, defaults to "
            "`sase memory list`."
        ),
    )
    memory_subparsers = memory_parser.add_subparsers(
        dest="memory_subcommand",
        help="Memory subcommands",
        required=False,
    )

    init_parser = memory_subparsers.add_parser(
        "init",
        help="Create or refresh memory files and provider instruction shims",
        description=(
            "Create or refresh SASE memory files and provider instruction "
            "shims. `sase init memory` is a compatibility alias for this "
            "command."
        ),
    )
    init_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Report memory initialization drift without writing files",
    )
    init_parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="Skip the project git commit/push sequence",
    )

    memory_subparsers.add_parser(
        "list",
        help="Show loaded, referenced, available, and missing memory files",
        description=(
            "Show the memory files visible from the current launch context, "
            "including loaded @ references, referenced-only plain memory paths, "
            "available files, and missing references."
        ),
    )

    read_parser = memory_subparsers.add_parser(
        "read",
        help="Read and audit a long-term memory file",
        description=(
            "Read a memory/long markdown file, strip leading YAML frontmatter, "
            "and append an attributable audit log row."
        ),
    )
    read_parser.add_argument(
        "memory_path",
        metavar="memory-relative-path",
        help="Path relative to memory/, for example long/generated_skills.md",
    )
    read_parser.add_argument(
        "--reason",
        required=True,
        help="Non-empty reason for the audited memory read",
    )

    log_parser = memory_subparsers.add_parser(
        "log",
        help="Summarize or inspect auditable long-term memory reads",
        description=(
            "Summarize auditable long-term memory reads recorded by "
            "`sase memory read`, or inspect matching read events with "
            "--path, --agent, or --id."
        ),
    )
    log_parser.add_argument(
        "--path",
        metavar="MEMORY_PATH",
        help="Only include reads for the given memory-relative path",
    )
    log_parser.add_argument(
        "--agent",
        metavar="AGENT_NAME",
        help="Only include reads by the given agent",
    )
    log_parser.add_argument(
        "--id",
        metavar="READ_ID",
        help="Show one memory read event by id or unambiguous id prefix",
    )
    log_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )
