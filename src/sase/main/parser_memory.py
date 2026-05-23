"""Argument parser definition for the ``sase memory`` command group."""

import argparse


def register_memory_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``memory`` command group."""
    memory_parser = subparsers.add_parser(
        "memory",
        help="Inspect and initialize SASE memory context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect SASE memory context. With no subcommand, defaults to "
            "`sase memory list`."
        ),
        epilog=(
            "examples:\n"
            "  sase memory read long/generated_skills.md --reason "
            '"Need generated skill context"\n'
            '  sase memory write --title "Generated skills" --slug '
            "generated_skills --evidence sdd/research/skills.md --body "
            '"Durable memory body"\n'
            "  sase memory log\n"
            "  sase memory log --path long/generated_skills.md\n"
            "  sase memory log --id <read-id>"
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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Read a memory/long markdown file, strip leading YAML frontmatter, "
            "and append an attributable audit log row."
        ),
        epilog=(
            "example:\n"
            "  sase memory read long/generated_skills.md --reason "
            '"Need generated skill context"'
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

    write_parser = memory_subparsers.add_parser(
        "write",
        help="Propose a long-term memory file for user review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create an attributable, reviewable long-term memory proposal. "
            "This command writes only proposal state under ~/.sase/projects; "
            "it never modifies canonical memory/long files."
        ),
        epilog=(
            "examples:\n"
            '  sase memory write --title "Generated skills" --slug '
            "generated_skills --evidence sdd/research/skills.md --body "
            '"Durable memory body"\n'
            '  cat draft.md | sase memory write --title "Generated skills" '
            "--target long/generated_skills.md --evidence chat:abc123"
        ),
    )
    write_parser.add_argument(
        "--title",
        required=True,
        help="Human-readable title for the memory proposal",
    )
    write_parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        metavar="EVIDENCE",
        help=(
            "Evidence for the proposal; repeatable. Supports paths, chat:<id>, "
            "url:<url>, http(s) URLs, and supplemental note:<text>."
        ),
    )
    write_parser.add_argument(
        "--from-chat",
        action="append",
        default=[],
        metavar="CHAT_ID",
        help="Add chat:<id> evidence for the proposal; repeatable",
    )
    target_group = write_parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--target",
        metavar="long/<slug>.md",
        help="One-level canonical long-memory target path",
    )
    target_group.add_argument(
        "--slug",
        metavar="SLUG",
        help="Slug used to derive the target path long/<slug>.md",
    )
    write_parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        metavar="KEYWORD",
        help="Keyword frontmatter candidate for future approval; repeatable",
    )
    body_group = write_parser.add_mutually_exclusive_group()
    body_group.add_argument(
        "--file",
        metavar="PATH",
        help="Read the proposed memory body from a UTF-8 file",
    )
    body_group.add_argument(
        "--body",
        help="Inline proposed memory body",
    )
    write_parser.add_argument(
        "--allow-large",
        action="store_true",
        help="Suppress the 16 KiB large-body warning",
    )
    write_parser.add_argument(
        "--manual-author",
        metavar="NAME",
        help="Explicit proposal author for tests and demos when no agent identity exists",
    )
    write_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )

    log_parser = memory_subparsers.add_parser(
        "log",
        help="Summarize or inspect auditable long-term memory reads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Summarize auditable long-term memory reads recorded by "
            "`sase memory read`, or inspect matching read events with "
            "--path, --agent, or --id."
        ),
        epilog=(
            "examples:\n"
            "  sase memory log\n"
            "  sase memory log --path long/generated_skills.md\n"
            "  sase memory log --id <read-id>"
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
