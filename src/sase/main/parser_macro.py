"""Argument parser definition for the 'macro' CLI subcommand."""

import argparse
import textwrap


def register_macro_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the canonical 'macro' subcommand parser."""
    macro_parser = subparsers.add_parser(
        "macro",
        help="Expand and visualize macro workflows",
    )
    macro_subparsers = macro_parser.add_subparsers(dest="macro_subcommand")

    # macro catalog
    catalog_parser = macro_subparsers.add_parser(
        "catalog",
        help="Render every visible macro to a beautifully-formatted PDF",
    )
    catalog_parser.add_argument(
        "-o",
        "--out",
        dest="out_dir",
        default=None,
        help="Directory to write the PDF (defaults to a tempdir).",
    )

    # macro expand
    expand_parser = macro_subparsers.add_parser(
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

    # macro explain
    explain_parser = macro_subparsers.add_parser(
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

    # macro graph
    graph_parser = macro_subparsers.add_parser(
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

    # macro list
    macro_subparsers.add_parser(
        "list",
        help="List all available macros and workflows as JSON",
    )

    # macro types
    types_parser = macro_subparsers.add_parser(
        "types",
        help="List macro input types, including plugin-shared enums",
        description=(
            "List macro input types: scalar keywords, builtin domain types, "
            "and plugin-shared enums. With NAME, show one type's detail card."
        ),
    )
    types_parser.add_argument(
        "type_name",
        nargs="?",
        metavar="NAME",
        help="Type name, alias, or plugin-qualified name (e.g. effort, sase-research-artifacts@audio_edition).",
    )
    types_parser.add_argument(
        "-j",
        "--json",
        dest="json",
        action="store_true",
        help="Print the Rust catalog projection as JSON.",
    )

    # macro show
    show_parser = macro_subparsers.add_parser(
        "show",
        help="Show one macro definition with syntax highlighting",
        description=(
            "Show one macro or workflow definition: its declared properties, "
            "typed inputs, local helper macros, highlighted body, provenance, "
            "and the references it makes. The NAME argument accepts a bare name "
            "or a copied reference (#name, #!name, /name); arguments such as "
            "#name(a, b) are ignored with a note. --format json emits a "
            "versioned record and --format raw emits the exact definition "
            "source bytes."
        ),
        epilog=textwrap.dedent(
            """\
            examples:
              sase macro show sase/reads
              sase macro show '#!sync'
              sase macro show plan --format json | jq .inputs
              sase macro show coder --format raw > coder.md
              sase macro show t --color always | less -R
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
        help="Macro or workflow name, with optional copied reference marker.",
    )
