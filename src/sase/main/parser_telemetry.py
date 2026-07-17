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
        "-r",
        "--range",
        choices=["15m", "1h", "6h", "24h", "7d"],
        default="1h",
        help="Time range to display (default: 1h)",
    )
    dashboard_parser.add_argument(
        "-s",
        "--subsystem",
        choices=[
            "agents",
            "axe",
            "beads",
            "hooks",
            "llm",
            "memory",
            "notifications",
            "workspace",
        ],
        default="agents",
        help="Chart set to display (default: agents)",
    )

    # sase telemetry export-config
    export_config_parser = tel_subparsers.add_parser(
        "export-config",
        help="Export bundled monitoring config (Prometheus + Grafana + Docker Compose)",
    )
    export_config_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite the target directory if it already exists",
    )
    export_config_parser.add_argument(
        "-o",
        "--output-dir",
        default="./sase-monitoring",
        help="Target directory (default: ./sase-monitoring/)",
    )

    # sase telemetry graph
    graph_parser = tel_subparsers.add_parser(
        "graph", help="Render one metric as a pipeable chart"
    )
    graph_parser.add_argument(
        "metric",
        help="Metric wire name or catalog attribute (for example AGENT_RUNS)",
    )
    graph_parser.add_argument(
        "-a",
        "--aggregation",
        help="Aggregation: sum, rate, avg, min, max, count, quantile, or pNN",
    )
    graph_parser.add_argument(
        "-g",
        "--group-by",
        help="Comma-separated metric labels to render as separate series",
    )
    graph_parser.add_argument(
        "-n",
        "--no-color",
        action="store_true",
        help="Disable ANSI color even when stdout is a terminal",
    )
    graph_parser.add_argument(
        "-r",
        "--range",
        choices=["15m", "1h", "6h", "24h", "7d"],
        default="1h",
        help="Time range to display (default: 1h)",
    )
    graph_parser.add_argument(
        "-w",
        "--width",
        type=int,
        default=80,
        help="Chart width in terminal cells (default: 80)",
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
