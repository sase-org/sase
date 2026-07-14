"""Argument parser definition for the ``sase memory`` command group."""

import argparse

from sase.main.parser_init import add_enable_project_memory_argument


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
            "  sase memory read generated_skills.md --reason "
            '"Need generated skill context"\n'
            '  sase memory write --title "Generated skills" --slug '
            'generated_skills --evidence "$(sase repo path research)/skills.md" --body '
            '"Durable memory body"\n'
            "  sase memory review --list\n"
            "  sase memory review mem-20260523-142233-a1b2c3d4 --edit\n"
            "  sase memory log\n"
            "  sase memory log --include proposals\n"
            "  sase memory log --path generated_skills.md\n"
            "  sase memory log --id <read-id>"
        ),
    )
    memory_subparsers = memory_parser.add_subparsers(
        dest="memory_subcommand",
        help="Memory subcommands",
        required=False,
    )

    agent_docs_parser = memory_subparsers.add_parser(
        "agent-docs",
        help="Inspect AGENTS.md files and provider instruction shims",
        description=(
            "Inspect agent instruction documents. With no subcommand, defaults "
            "to `sase memory agent-docs list`."
        ),
    )
    agent_docs_subparsers = agent_docs_parser.add_subparsers(
        dest="agent_docs_subcommand",
        help="Agent-document subcommands",
        required=False,
    )
    agent_docs_subparsers.add_parser(
        "list",
        help="Show AGENTS.md files, provider shims, and memory reference status",
        description=(
            "Show discovered AGENTS.md files across the project, its "
            "subdirectories, home, and chezmoi source, including each H1 title, "
            "managed/custom state, memory reference counts, and provider "
            "instruction shim status. This command never writes files."
        ),
    )

    init_parser = memory_subparsers.add_parser(
        "init",
        help="Create or refresh memory files, AGENTS.md, and provider shims",
        description=(
            "Create or refresh SASE memory files, managed AGENTS.md, and "
            "provider instruction shims. `sase init memory` is a compatibility "
            "alias for this command."
        ),
    )
    init_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Report memory initialization drift without writing files",
    )
    init_parser.add_argument(
        "-d",
        "--diff",
        action="store_true",
        help="Show full file diffs for planned memory changes",
    )
    add_enable_project_memory_argument(init_parser)
    init_parser.add_argument(
        "-m",
        "--message",
        metavar="MESSAGE",
        help=(
            "Commit subject for folding eligible memory and generated-change source edits; a "
            "`docs(memory):` tag is added if omitted"
        ),
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
            "Read a long-term memory markdown file from project memory/, "
            "falling back to ~/memory/ when the project file is absent. "
            "Pass a flat note name such as generated_skills.md. Leading YAML "
            "frontmatter is stripped before printing, child notes are listed "
            "when present, and each read appends an attributable "
            "audit log row."
        ),
        epilog=(
            "example:\n"
            "  sase memory read generated_skills.md --reason "
            '"Need generated skill context"'
        ),
    )
    read_parser.add_argument(
        "memory_path",
        metavar="memory-relative-path",
        help=(
            "Path relative to project memory/ or ~/memory/, for example "
            "generated_skills.md"
        ),
    )
    read_parser.add_argument(
        "-r",
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
            "it never modifies canonical memory files."
        ),
        epilog=(
            "examples:\n"
            '  sase memory write --title "Generated skills" --slug '
            'generated_skills --evidence "$(sase repo path research)/skills.md" --body '
            '"Durable memory body"\n'
            '  sase memory write --title "Generated skills" --slug '
            "generated_skills --evidence chat:abc123 --body "
            '"Durable memory body" --notify\n'
            '  cat draft.md | sase memory write --title "Generated skills" '
            "--target generated_skills.md --evidence chat:abc123"
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
        metavar="<slug>.md",
        help="One-level canonical long-memory target filename",
    )
    target_group.add_argument(
        "--slug",
        metavar="SLUG",
        help="Slug used to derive the target filename <slug>.md",
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
    write_parser.add_argument(
        "--notify",
        action="store_true",
        help="Best-effort append a memory.proposed notification after creation",
    )

    review_parser = memory_subparsers.add_parser(
        "review",
        help="Review pending long-term memory proposals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List, inspect, approve, edit, or reject pending long-term memory "
            "proposals. On a TTY, a bare command launches the interactive "
            "review app; otherwise it prints the pending proposal list."
        ),
        epilog=(
            "examples:\n"
            "  sase memory review --list\n"
            "  sase memory review mem-20260523-142233-a1b2c3d4 --show\n"
            "  sase memory review mem-20260523-142233-a1b2c3d4 --approve\n"
            "  sase memory review mem-20260523-142233-a1b2c3d4 --edit\n"
            "  sase memory review mem-20260523-142233-a1b2c3d4 --reject "
            '--reason "Too speculative"'
        ),
    )
    review_parser.add_argument(
        "proposal_id",
        nargs="?",
        help="Proposal id or unambiguous id prefix",
    )
    review_action_group = review_parser.add_mutually_exclusive_group()
    review_action_group.add_argument(
        "--list",
        action="store_true",
        help="List pending proposals, or all proposals with --all",
    )
    review_action_group.add_argument(
        "--show",
        action="store_true",
        help="Show full proposal detail",
    )
    review_action_group.add_argument(
        "--approve",
        action="store_true",
        help="Approve the proposal and write its canonical memory file",
    )
    review_action_group.add_argument(
        "--edit",
        action="store_true",
        help="Open $VISUAL/$EDITOR on reviewed.md, then approve the result",
    )
    review_action_group.add_argument(
        "--reject",
        action="store_true",
        help="Reject the proposal; requires --reason",
    )
    review_parser.add_argument(
        "--all",
        action="store_true",
        help="Include approved and rejected proposals with --list",
    )
    review_parser.add_argument(
        "--target",
        metavar="<slug>.md",
        help="Override the canonical approval target",
    )
    review_parser.add_argument(
        "--edited-file",
        metavar="PATH",
        help="Approve using edited body content from PATH",
    )
    review_parser.add_argument(
        "--reason",
        help="Non-empty rejection reason",
    )
    review_parser.add_argument(
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
            "  sase memory log --include proposals\n"
            "  sase memory log --path generated_skills.md\n"
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
        "--include",
        action="append",
        choices=("proposals",),
        default=[],
        metavar="KIND",
        help="Include additional audit events; currently only 'proposals'",
    )
    log_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )
