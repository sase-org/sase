"""Argument parser definition for the ``sase final`` command group."""

from __future__ import annotations

import argparse

from sase.core.finalizer_wire import FINALIZER_DEFERRAL_REASONS


def register_final_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase final`` command group."""

    final_parser = subparsers.add_parser(
        "final",
        help="Inspect configured finalizers and declarations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect host-owned finalizer instances, provider provenance, and "
            "the current turn's declaration obligations. With no subcommand, "
            "`sase final` defaults to `sase final list`."
        ),
        epilog=(
            "examples:\n"
            "  sase final list\n"
            "  sase final show commit\n"
            "  sase final context -f json\n"
            "  sase final submit final-manifest.json\n"
            "  sase final submit -\n"
            "  sase final defer repo-a protected_paths"
        ),
    )
    final_subparsers = final_parser.add_subparsers(
        dest="final_subcommand",
        help="Finalizer subcommands",
        metavar="<subcommand>",
        title="subcommands",
    )

    context_parser = final_subparsers.add_parser(
        "context",
        help="Publish and show the current turn's finalizer context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Recompute selected finalizers, triggers, and opaque repository "
            "obligations for the active turn, validate the context through "
            "the shared protocol, publish final_context.json, and print it."
        ),
        epilog=("examples:\n  sase final context\n  sase final context -f json"),
    )
    _add_format_argument(context_parser)

    defer_parser = final_subparsers.add_parser(
        "defer",
        help="Declare a rare, host-adjudicated deferral for one dirty repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Defer one repository obligation instead of committing it. "
            "Deferral is rare: prefer an authored commit message through "
            "`sase final submit`. The host adjudicates every deferral against "
            "this run's own evidence before accepting it, so an unfounded "
            "deferral is rejected as a repairable error instead of failing "
            "the run. An accepted deferral leaves the repository's tree "
            "dirty by design and completes the run instead of failing it. "
            "Only supports a turn with exactly one finalizer instance and "
            "one repository requiring a decision; use `sase final context "
            "-f json` and `sase final submit` for anything wider."
        ),
        epilog=(
            "examples:\n"
            "  sase final defer repo-a protected_paths\n"
            "  sase final defer repo-a unsafe_content -p src/secret.env"
        ),
    )
    defer_parser.add_argument(
        "repo_id",
        metavar="<repo-id>",
        help="Repository obligation ID, from `sase final context`",
    )
    defer_parser.add_argument(
        "reason",
        metavar="<reason>",
        choices=FINALIZER_DEFERRAL_REASONS,
        help="Typed deferral reason: " + ", ".join(FINALIZER_DEFERRAL_REASONS),
    )
    defer_parser.add_argument(
        "-p",
        "--paths",
        action="append",
        metavar="<path>",
        help="Path within the repository to defer (repeatable); defaults to "
        "every dirty path in the repository",
    )

    doctor_parser = final_subparsers.add_parser(
        "doctor",
        help="Diagnose finalizer configuration and providers",
    )
    _add_format_argument(doctor_parser)

    list_parser = final_subparsers.add_parser(
        "list",
        help="List effective finalizer instances",
    )
    _add_format_argument(list_parser)

    show_parser = final_subparsers.add_parser(
        "show",
        help="Show one finalizer instance",
    )
    show_parser.add_argument("instance", help="Finalizer instance ID")
    _add_format_argument(show_parser)

    submit_parser = final_subparsers.add_parser(
        "submit",
        help="Validate and save one finalizer declaration manifest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Read exactly one JSON manifest from a file or stdin, validate it "
            "against the latest finalizer context, append a bounded diagnostic "
            "attempt record, and replace final_submission.json only on success."
        ),
        epilog=(
            "examples:\n"
            "  sase final submit final-manifest.json\n"
            "  sase final context -f json | jq '.manifest_template' | "
            "sase final submit -"
        ),
    )
    submit_parser.add_argument(
        "manifest",
        metavar="<manifest-file|->",
        help="JSON declaration manifest path, or '-' to read stdin",
    )


def _add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-f",
        "--format",
        choices=("pretty", "json"),
        default="pretty",
        help="Output format",
    )


__all__ = ["register_final_parser"]
