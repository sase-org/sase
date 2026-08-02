"""Argument parser definition for the 'prompt' CLI subcommand."""

import argparse


def _nonnegative_int(value: str) -> int:
    """Argparse type for a non-negative integer (``0`` means unlimited)."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _add_prefix_option(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-P/--prefix`` VCS-tag replacement option."""
    parser.add_argument(
        "-P",
        "--prefix",
        default=None,
        metavar="VCS_PREFIX",
        help=(
            "Replace embedded VCS workflow tags with VCS_PREFIX before replay,"
            " e.g. reuse a '#gh:sase' prompt under '#gh:bob-cli'"
        ),
    )


def register_prompt_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'prompt' subcommand parser and its subcommands."""
    prompt_parser = subparsers.add_parser(
        "prompt",
        help="Inspect, search, and reuse previously submitted agent prompts",
    )
    prompt_sub = prompt_parser.add_subparsers(
        dest="prompt_subcommand", help="Prompt subcommands"
    )

    # sase prompt copy
    copy_parser = prompt_sub.add_parser(
        "copy",
        help="Copy a prompt's exact text to the system clipboard",
    )
    copy_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )

    # sase prompt delete
    delete_parser = prompt_sub.add_parser(
        "delete",
        help="Delete one stored prompt by selector (confirms unless --yes)",
    )
    delete_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )
    delete_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt and delete immediately",
    )

    # sase prompt doctor
    doctor_parser = prompt_sub.add_parser(
        "doctor",
        help="Diagnose the prompt-history store (read-only, JSON with -j)",
    )
    doctor_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object (stable schema)",
    )

    # sase prompt edit
    edit_parser = prompt_sub.add_parser(
        "edit",
        help="Open a prompt in the editor, then launch the edited text",
    )
    edit_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )
    _add_prefix_option(edit_parser)

    # sase prompt export
    export_parser = prompt_sub.add_parser(
        "export",
        help="Export a local-history prompt to stdout or a file",
    )
    export_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )
    export_parser.add_argument(
        "-F",
        "--force",
        action="store_true",
        help="Overwrite the destination file if it already exists",
    )
    export_parser.add_argument(
        "-m",
        "--metadata",
        action="store_true",
        help="Wrap output in frontmatter (id, hash, timestamps, status, source)",
    )
    export_parser.add_argument(
        "-o",
        "--out",
        default=None,
        metavar="PATH",
        help="Write to PATH instead of stdout (fails if it exists without --force)",
    )
    export_parser.add_argument(
        "-s",
        "--sdd",
        action="store_true",
        help=(
            "Retired compatibility option; use --out for files or `sase agent"
            " prompts` for canonical archived prompts"
        ),
    )

    # sase prompt list
    list_parser = prompt_sub.add_parser(
        "list",
        help="List recent prompts (pretty table by default, JSON with -j)",
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include cancelled prompts alongside launched prompts",
    )
    list_parser.add_argument(
        "-c",
        "--cancelled",
        action="store_true",
        help="Show only cancelled prompts (takes precedence over --all)",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array (stable schema)",
    )
    list_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=20,
        help="Maximum number of prompts to return (default: 20)",
    )
    list_parser.add_argument(
        "-q",
        "--query",
        default=None,
        help="Case-insensitive substring filter over exact prompt text",
    )

    # sase prompt prune
    prune_parser = prompt_sub.add_parser(
        "prune",
        help="Remove prompts by objective criteria (confirms unless --yes)",
    )
    prune_parser.add_argument(
        "-b",
        "--before",
        default=None,
        metavar="DATE",
        help=("Remove prompts older than DATE (YYYY-MM-DD, YYmmdd, or YYmmdd_HHMMSS)"),
    )
    prune_parser.add_argument(
        "-c",
        "--cancelled",
        action="store_true",
        help="Limit removal to cancelled prompts",
    )
    prune_parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Show what would be removed without mutating the store",
    )
    prune_parser.add_argument(
        "-k",
        "--keep",
        type=int,
        default=None,
        metavar="LIMIT",
        help="Keep the newest LIMIT prompts; older ones become removable",
    )
    prune_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt and prune immediately",
    )

    # sase prompt run
    run_parser = prompt_sub.add_parser(
        "run",
        help="Launch a stored prompt by selector",
    )
    run_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )
    run_parser.add_argument(
        "-e",
        "--edit",
        action="store_true",
        help="Open the prompt in the editor before launching",
    )
    _add_prefix_option(run_parser)

    # sase prompt save
    save_parser = prompt_sub.add_parser(
        "save",
        help="Save a prompt as a reusable xprompt markdown file",
    )
    save_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )
    save_parser.add_argument(
        "-D",
        "--description",
        default=None,
        metavar="TEXT",
        help="Override the auto-generated xprompt description",
    )
    save_parser.add_argument(
        "-F",
        "--force",
        action="store_true",
        help="Overwrite the xprompt file if it already exists",
    )
    save_parser.add_argument(
        "-g",
        "--global",
        dest="global_",
        action="store_true",
        help="Save to ~/sase/xprompts/ instead of the project sase/xprompts/",
    )
    save_parser.add_argument(
        "-n",
        "--name",
        default=None,
        help="xprompt name (defaults to a slug derived from the prompt)",
    )
    save_parser.add_argument(
        "-p",
        "--project",
        default=None,
        metavar="PROJECT",
        help="Save to ~/sase/xprompts/PROJECT/ for a project namespace",
    )
    save_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=None,
        metavar="TAG",
        help="Tag recorded in xprompt frontmatter (repeatable)",
    )

    # sase prompt search
    search_parser = prompt_sub.add_parser(
        "search",
        help="Search canonical archived prompts and local history",
        description=(
            "Find prompts whose text or metadata contains a literal query,"
            " across the canonical agents-sidecar archive and machine-wide"
            " local prompt history. Archived prompts rank first."
        ),
        epilog=(
            "Examples:\n"
            "  sase prompt search auth\n"
            "  sase prompt search tui --source archive\n"
            "  sase prompt search review --after 30d --tag review\n"
            "  sase prompt search deploy --format json --limit 0"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    search_parser.add_argument(
        "query",
        help="Literal, non-empty text to search for (case-insensitive)",
    )
    search_parser.add_argument(
        "-a",
        "--after",
        default=None,
        metavar="DATE",
        help=(
            "Keep prompts dated on/after DATE: 2026-01-01, 202601 (YYYYMM),"
            " 260101 (YYmmdd), 260101_143000, or a relative 30d/2w/6m/1y"
        ),
    )
    search_parser.add_argument(
        "-b",
        "--before",
        default=None,
        metavar="DATE",
        help="Keep prompts dated on/before DATE (same forms as --after)",
    )
    search_parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    search_parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "json", "full"],
        default="compact",
        help="Output format: compact, json, or full (default: compact)",
    )
    search_parser.add_argument(
        "-n",
        "--limit",
        type=_nonnegative_int,
        default=20,
        help="Maximum results to show after ranking; 0 means unlimited (default: 20)",
    )
    search_parser.add_argument(
        "-s",
        "--source",
        choices=["archive", "local", "all", "sdd"],
        default="all",
        help=(
            "Which store to search: archive, local, or all (default: all);"
            " sdd is a deprecated alias for archive"
        ),
    )
    search_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=None,
        metavar="TAG",
        help="Keep prompts carrying TAG (repeatable; repeats OR together)",
    )
    search_parser.add_argument(
        "-x",
        "--cancelled",
        action="store_true",
        help="Restrict local results to cancelled prompts (no effect on archive)",
    )

    # sase prompt select
    select_parser = prompt_sub.add_parser(
        "select",
        help="Pick a prompt with an fzf picker, then launch it",
    )
    select_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include cancelled prompts alongside launched prompts",
    )
    select_parser.add_argument(
        "-c",
        "--cancelled",
        action="store_true",
        help="Show only cancelled prompts (takes precedence over --all)",
    )
    select_parser.add_argument(
        "-e",
        "--edit",
        action="store_true",
        help="Open the selected prompt in the editor before launching",
    )
    _add_prefix_option(select_parser)
    select_parser.add_argument(
        "-q",
        "--query",
        default=None,
        help="Case-insensitive substring filter over candidates before fzf",
    )

    # sase prompt show
    show_parser = prompt_sub.add_parser(
        "show",
        help="Print a prompt by ID, hash prefix, or sha256:<hash>",
    )
    show_parser.add_argument(
        "id",
        help="Prompt selector: ph_<prefix>, a bare hash prefix, or sha256:<hash>",
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=("raw", "markdown", "json"),
        default="raw",
        help=(
            "Output format: 'raw' (default) prints exact prompt text,"
            " 'markdown' prints a metadata header plus the body,"
            " 'json' prints metadata plus full text"
        ),
    )

    # sase prompt stats
    stats_parser = prompt_sub.add_parser(
        "stats",
        help="Summarize the prompt-history store (pretty by default, JSON with -j)",
    )
    stats_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object (stable schema)",
    )
