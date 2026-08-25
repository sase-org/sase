"""Argument parser definition for the ``sase memory`` command group."""

import argparse

from sase.main.parser_bead_common import nonnegative_int
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
            '  sase memory read glossary:stitch -r "Need the stitch vocabulary"\n'
            "  sase memory show generated_skills.md\n"
            "  sase memory web list\n"
            "  sase memory web show glossary\n"
            '  sase memory write --title "Generated skills" --slug '
            'generated_skills --evidence "$(sase repo path research)/skills.md" --body '
            '"Durable memory body"\n'
            "  sase memory review --list\n"
            "  sase memory review mem-20260523-142233-a1b2c3d4 --edit\n"
            "  sase memory log\n"
            "  sase memory log --include proposals\n"
            "  sase memory log --include glossary\n"
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
        help="Read and audit one or more memory selectors",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resolve one or more memory selectors from project sase/memory/, "
            "falling back to ~/sase/memory/ when the project file is absent. "
            "A selector is a flat note name (generated_skills.md), a bare "
            "memory-web name (glossary, every strand), or a web:keyword "
            "strand reference (glossary:stitch). The whole batch is resolved "
            "before anything is printed or logged, so one unknown selector "
            "fails the entire request. Leading YAML frontmatter is stripped "
            "from notes, child notes are listed when present, and each read "
            "appends one attributable audit log row. Identical to "
            "`sase memory show` except that it requires a reason and records "
            "an audited read before printing."
        ),
        epilog=(
            "examples:\n"
            "  sase memory read generated_skills.md --reason "
            '"Need generated skill context"\n'
            '  sase memory read glossary:stitch -r "Need the stitch/patch vocabulary"\n'
            '  sase memory read glossary cli_rules.md -r "Need everything"'
        ),
    )
    _add_memory_view_arguments(read_parser, require_reason=True)

    show_parser = memory_subparsers.add_parser(
        "show",
        help="Print one or more memory selectors without recording a read",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resolve one or more memory selectors exactly like "
            "`sase memory read` — project sase/memory/ first, then "
            "~/sase/memory/ — strip leading YAML frontmatter from notes, and "
            "append the `## Children` section when children exist. Unlike "
            "`read`, this command records no audit event, so agents "
            "consulting memory to do work must use `sase memory read` "
            "instead."
        ),
        epilog=(
            "examples:\n"
            "  sase memory show generated_skills.md\n"
            "  sase memory show sase_beads.md -f rich\n"
            "  sase memory show glossary:stitch -f json\n"
            "  sase memory show glossary -d 0"
        ),
    )
    _add_memory_view_arguments(show_parser)

    _register_memory_web_parser(memory_subparsers)

    write_parser = memory_subparsers.add_parser(
        "write",
        help="Propose a reference memory file for user review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create an attributable, reviewable reference memory proposal. "
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
        help="One-level canonical reference-memory target filename",
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
        help="Review pending reference memory proposals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List, inspect, approve, edit, or reject pending reference memory "
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
        help="Summarize or inspect auditable reference memory reads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Summarize auditable reference memory reads recorded by "
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
        choices=("glossary", "proposals"),
        default=[],
        metavar="KIND",
        help=(
            "Include additional audit events: 'proposals' or 'glossary' "
            "(folds in the legacy sase glossary read audit log)"
        ),
    )
    log_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )


def _add_memory_view_arguments(
    parser: argparse.ArgumentParser, *, require_reason: bool = False
) -> None:
    parser.add_argument(
        "selectors",
        metavar="selector",
        nargs="+",
        help=(
            "One or more selectors: a flat note name (generated_skills.md), "
            "a bare memory-web name (glossary), or a web:keyword strand "
            "reference (glossary:stitch)"
        ),
    )
    parser.add_argument(
        "-d",
        "--depth",
        type=nonnegative_int,
        default=None,
        metavar="N",
        help=(
            "Cap strand mention-closure recursion depth (default: unlimited); "
            "-d 0 prints only the requested strands"
        ),
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("json", "markdown", "rich"),
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "-p",
        "--project",
        metavar="REF",
        default=None,
        help="Project to resolve memory from (default: infer from current directory)",
    )
    if require_reason:
        parser.add_argument(
            "-r",
            "--reason",
            required=True,
            help="Non-empty reason for the audited memory read",
        )


def _register_memory_web_parser(
    memory_subparsers: argparse._SubParsersAction,
) -> None:
    """Register the ``memory web`` command group."""
    web_parser = memory_subparsers.add_parser(
        "web",
        help="List and inspect memory webs and their strands",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect memory webs — keyed strand collections addressed with "
            "`sase memory read <web>:<keyword>`. Running `sase memory web` "
            "defaults to `sase memory web list`."
        ),
        epilog=(
            "examples:\n"
            "  sase memory web list\n"
            "  sase memory web migrate glossary -n\n"
            "  sase memory web show glossary\n"
            "  sase memory web show glossary stitch -b"
        ),
    )
    web_subparsers = web_parser.add_subparsers(
        dest="memory_web_subcommand",
        help="Memory web subcommands",
    )

    list_parser = web_subparsers.add_parser(
        "list",
        help="List memory webs for a project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List discovered memory webs: name, rendering (core/reference), "
            "scope, and strand count."
        ),
        epilog=("examples:\n  sase memory web list\n  sase memory web list -f json"),
    )
    list_parser.add_argument(
        "-f",
        "--format",
        choices=("json", "names", "table"),
        default="table",
        help="Output format (default: table)",
    )
    _add_web_project_option(list_parser)

    migrate_parser = web_subparsers.add_parser(
        "migrate",
        help="Migrate a config-backed memory web into strand files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Migrate a supported config-backed memory web into a descriptor "
            "and strand files. In this release, only `glossary` is accepted."
        ),
        epilog=(
            "examples:\n"
            "  sase memory web migrate glossary\n"
            "  sase memory web migrate glossary -n\n"
            "  sase memory web migrate glossary -p sase"
        ),
    )
    migrate_parser.add_argument(
        "web",
        metavar="WEB",
        help="Memory web to migrate; only 'glossary' is supported",
    )
    migrate_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print the migration report without writing files",
    )
    _add_web_project_option(migrate_parser)

    show_parser = web_subparsers.add_parser(
        "show",
        help="Show one web's filterable strand index",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Print one web's strand index: keyword, slug, aliases, "
            "mention-reference count, and summary, optionally filtered by "
            "PATTERN. This is the index, the memory-web analogue of "
            "`sase glossary list`; `sase memory show <web>:<keyword>` is the "
            "content read."
        ),
        epilog=(
            "examples:\n"
            "  sase memory web show glossary\n"
            "  sase memory web show glossary stitch\n"
            "  sase memory web show glossary -b -f json"
        ),
    )
    show_parser.add_argument(
        "web",
        metavar="WEB",
        help="Memory web slug to inspect",
    )
    show_parser.add_argument(
        "pattern",
        metavar="PATTERN",
        nargs="?",
        default=None,
        help="Case-insensitive substring filter over keywords and aliases",
    )
    show_parser.add_argument(
        "-b",
        "--bodies",
        action="store_true",
        help="Extend PATTERN matching into strand bodies",
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=("json", "names", "table"),
        default="table",
        help="Output format (default: table)",
    )
    _add_web_project_option(show_parser)


def _add_web_project_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--project",
        metavar="REF",
        default=None,
        help="Project to resolve memory webs from (default: infer from current directory)",
    )
