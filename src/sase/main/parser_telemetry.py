"""Argument parser definition for the 'telemetry' CLI subcommand."""

import argparse


def register_telemetry_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'telemetry' subcommand parser."""
    telemetry_parser = subparsers.add_parser(
        "telemetry",
        help="Inspect locally persisted telemetry (defaults to list)",
        description=(
            "Inspect locally persisted telemetry. Running 'sase telemetry' "
            "without a subcommand delegates to 'sase telemetry list'."
        ),
    )
    tel_subparsers = telemetry_parser.add_subparsers(
        dest="telemetry_subcommand", help="Telemetry subcommands"
    )

    # sase telemetry health
    health_parser = tel_subparsers.add_parser(
        "health", help="Traffic-light health assessment"
    )
    health_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Machine-readable JSON output",
    )
    # sase telemetry list
    list_parser = tel_subparsers.add_parser(
        "list", help="Show the metric catalog from internal definitions"
    )
    list_parser.add_argument(
        "-s",
        "--subsystem",
        help="Filter to a specific subsystem (e.g., 'Agent Lifecycle')",
    )
    list_parser.add_argument(
        "-t",
        "--type",
        choices=["counter", "gauge", "histogram"],
        help="Filter by metric type",
    )

    # sase telemetry snapshot
    snapshot_parser = tel_subparsers.add_parser(
        "snapshot", help="Display current values from the local store"
    )
    snapshot_parser.add_argument(
        "-f",
        "--format",
        choices=["json", "rich"],
        default="rich",
        help="Output format (default: rich)",
    )
    snapshot_parser.add_argument(
        "-s",
        "--subsystem",
        help="Filter by subsystem",
    )

    # sase telemetry status
    tel_subparsers.add_parser("status", help="Quick health check and config display")
