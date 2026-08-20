"""Argument parser definition for the ``sase final`` command group."""

from __future__ import annotations

import argparse


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
            "  sase final submit -"
        ),
    )
    final_subparsers = final_parser.add_subparsers(
        dest="final_subcommand",
        help="Finalizer subcommands",
        metavar="<subcommand>",
        title="subcommands",
    )

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

    doctor_parser = final_subparsers.add_parser(
        "doctor",
        help="Diagnose finalizer configuration and providers",
    )
    _add_format_argument(doctor_parser)

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
