"""Argument parser definition for the 'xprompt' CLI subcommand."""

import argparse
import textwrap


def register_xprompt_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'xprompt' subcommand parser."""
    xprompt_parser = subparsers.add_parser(
        "xprompt",
        help="Expand and visualize xprompt workflows",
    )
    xprompt_subparsers = xprompt_parser.add_subparsers(dest="xprompt_subcommand")

    # xprompt catalog
    catalog_parser = xprompt_subparsers.add_parser(
        "catalog",
        help="Render every visible xprompt to a beautifully-formatted PDF",
    )
    catalog_parser.add_argument(
        "-o",
        "--out",
        dest="out_dir",
        default=None,
        help="Directory to write the PDF (defaults to a tempdir).",
    )

    # xprompt expand
    expand_parser = xprompt_subparsers.add_parser(
        "expand",
        help="Expand sase references (snippets, file refs) in a prompt",
    )
    expand_parser.add_argument(
        "prompt",
        nargs="?",
        help="Prompt text to expand. If not provided, reads from STDIN.",
    )
    expand_parser.add_argument(
        "-t",
        "--trace",
        action="store_true",
        help="Print expansion trace to stderr showing each resolved reference.",
    )

    # xprompt explain
    explain_parser = xprompt_subparsers.add_parser(
        "explain",
        help="Dry-run: show execution plan without running anything",
    )
    explain_parser.add_argument(
        "workflow_name",
        help="Workflow name to explain.",
    )
    explain_parser.add_argument(
        "args",
        nargs="*",
        help="Positional arguments for the workflow.",
    )
    explain_parser.add_argument(
        "-a",
        "--arg",
        action="append",
        dest="named_args",
        metavar="KEY=VALUE",
        help="Named argument (can be repeated).",
    )

    # xprompt graph
    graph_parser = xprompt_subparsers.add_parser(
        "graph",
        help="Generate a DAG visualization of a workflow",
    )
    graph_parser.add_argument(
        "workflow_name",
        nargs="?",
        help="Workflow name to graph. If not provided, lists all workflows.",
    )
    graph_parser.add_argument(
        "-f",
        "--format",
        choices=["mermaid", "text"],
        default="mermaid",
        help="Output format (default: mermaid)",
    )

    # xprompt list
    xprompt_subparsers.add_parser(
        "list",
        help="List all available xprompts and workflows as JSON",
    )

    # xprompt show
    show_parser = xprompt_subparsers.add_parser(
        "show",
        help="Show one xprompt definition with syntax highlighting",
        description=(
            "Show one xprompt or workflow definition: its declared properties, "
            "typed inputs, local helper xprompts, highlighted body, provenance, "
            "and the references it makes. The NAME argument accepts a bare name "
            "or a copied reference (#name, #!name, /name); arguments such as "
            "#name(a, b) are ignored with a note. --format json emits a "
            "versioned record and --format raw emits the exact definition "
            "source bytes."
        ),
        epilog=textwrap.dedent(
            """\
            examples:
              sase xprompt show sase/reads
              sase xprompt show '#!sync'
              sase xprompt show plan --format json | jq .inputs
              sase xprompt show coder --format raw > coder.md
              sase xprompt show t --color always | less -R
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    show_parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color mode for rendered output (default: auto).",
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=["full", "json", "raw"],
        default="full",
        help="Output format (default: full).",
    )
    show_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Resolve within a specific project namespace.",
    )
    show_parser.add_argument(
        "name",
        metavar="NAME",
        help="XPrompt or workflow name, with optional copied reference marker.",
    )
