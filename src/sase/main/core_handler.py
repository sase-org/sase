"""Handler for ``sase core`` subcommands."""

from __future__ import annotations

import argparse
import json
import sys

from sase.core.health import HEALTH_OK, BackendHealthReport, check_backend_health

EXIT_OK = 0
EXIT_ERROR = 1


def _format_human(report: BackendHealthReport) -> str:
    """Render the report as a short, line-oriented human-readable block."""
    lines = [
        f"status: {report.status}",
        f"rust extension module: {report.rust_extension_module}",
        f"rust extension loaded: {'yes' if report.rust_extension_loaded else 'no'}",
    ]
    if report.rust_extension_path:
        lines.append(f"rust extension path: {report.rust_extension_path}")
    if report.rust_extension_version:
        lines.append(f"rust extension version: {report.rust_extension_version}")
    lines.append(
        f"probe: parse_query({report.probe_query!r}) -> "
        f"{'ok' if report.probe_ok else 'skipped/failed'}"
    )
    lines.append(f"python: {report.python_version}")
    lines.append(f"platform: {report.platform}")
    if report.error:
        lines.append(f"error: {report.error}")
    return "\n".join(lines)


def _handle_core_health(args: argparse.Namespace) -> None:
    """Implement ``sase core health``.

    Exits 0 on a healthy report and non-zero on error so release smokes and
    user scripts can branch on the exit code without parsing output.
    """
    report = check_backend_health()
    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(_format_human(report))
    sys.exit(EXIT_OK if report.status == HEALTH_OK else EXIT_ERROR)


def handle_core_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase core`` sub-handler."""
    sub = getattr(args, "core_subcommand", None)
    if sub == "health":
        _handle_core_health(args)
        return
    print("Usage: sase core {health}", file=sys.stderr)
    sys.exit(1)
