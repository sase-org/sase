"""Argument parser definition for the 'telemetry' CLI subcommand."""

import argparse


def register_telemetry_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'telemetry' subcommand parser."""
    telemetry_parser = subparsers.add_parser(
        "telemetry",
        help="Inspect and monitor Prometheus telemetry metrics",
    )
    tel_subparsers = telemetry_parser.add_subparsers(
        dest="telemetry_subcommand", help="Telemetry subcommands"
    )

    # sase telemetry dashboard
    dashboard_parser = tel_subparsers.add_parser(
        "dashboard", help="Live auto-refreshing TUI dashboard"
    )
    dashboard_parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=5,
        help="Refresh interval in seconds (default: 5)",
    )
    dashboard_parser.add_argument(
        "-S",
        "--source",
        choices=["auto", "pushgateway", "exposition"],
        default="auto",
        help="Data source (default: auto)",
    )
    dashboard_parser.add_argument(
        "-c",
        "--charts",
        action="store_true",
        help="Enable charts mode with historical data from Prometheus",
    )
    dashboard_parser.add_argument(
        "-r",
        "--range",
        choices=["1h", "6h", "24h", "7d"],
        default="1h",
        help="Time range for charts mode (default: 1h)",
    )
    dashboard_parser.add_argument(
        "-s",
        "--subsystem",
        help="Focus on a single subsystem (larger charts, more detail)",
    )

    # sase telemetry export-config
    export_config_parser = tel_subparsers.add_parser(
        "export-config",
        help="Export bundled monitoring config (Prometheus + Grafana + Docker Compose)",
    )
    export_config_parser.add_argument(
        "-o",
        "--output-dir",
        default="./sase-monitoring",
        help="Target directory (default: ./sase-monitoring/)",
    )
    export_config_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite the target directory if it already exists",
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
    health_parser.add_argument(
        "-S",
        "--source",
        choices=["auto", "pushgateway", "exposition"],
        default="auto",
        help="Data source (default: auto)",
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
        "snapshot", help="Fetch and display current metric values"
    )
    snapshot_parser.add_argument(
        "-S",
        "--source",
        choices=["auto", "pushgateway", "exposition"],
        default="auto",
        help="Where to fetch metrics from (default: auto)",
    )
    snapshot_parser.add_argument(
        "-f",
        "--format",
        choices=["rich", "json", "prometheus"],
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
